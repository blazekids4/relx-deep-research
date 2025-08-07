import os, time
from typing import Optional
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def fetch_and_print_new_agent_response(
    thread_id: str,
    agents_client: AgentsClient,
    last_message_id: Optional[str] = None,
) -> Optional[str]:
    response = agents_client.messages.get_last_message_by_role(
        thread_id=thread_id,
        role=MessageRole.AGENT,
    )
    if not response or response.id == last_message_id:
        return last_message_id  # No new content

    print("\nAgent response:")
    print("\n".join(t.text.value for t in response.text_messages))

    for ann in response.url_citation_annotations:
        print(f"URL Citation: [{ann.url_citation.title}]({ann.url_citation.url})")

    return response.id


def create_research_summary(
        message : ThreadMessage,
        filepath: str = "research_summary.md"
) -> None:
    if not message:
        print("No message content provided, cannot create research summary.")
        return

    with open(filepath, "w", encoding="utf-8") as fp:
        # Write text summary
        text_summary = "\n\n".join([t.text.value.strip() for t in message.text_messages])
        fp.write(text_summary)

        # Write unique URL citations, if present
        if message.url_citation_annotations:
            fp.write("\n\n## References\n")
            seen_urls = set()
            for ann in message.url_citation_annotations:
                url = ann.url_citation.url
                title = ann.url_citation.title or url
                if url not in seen_urls:
                    fp.write(f"- [{title}]({url})\n")
                    seen_urls.add(url)

    print(f"Research summary written to '{filepath}'.")


def process_user_message(
    user_input: str,
    thread_id: str,
    agent_id: str,
    agents_client: AgentsClient
) -> ThreadMessage:
    """Process a single user message and return the agent's response."""
    # Create message to thread
    message = agents_client.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_input,
    )
    print(f"Created message, ID: {message.id}")

    print(f"Processing your request... this may take a few minutes. Please be patient!")
    
    # Poll the run as long as run status is queued or in progress
    run = agents_client.runs.create(thread_id=thread_id, agent_id=agent_id)
    last_message_id = None
    
    while run.status in ("queued", "in_progress"):
        time.sleep(1)
        run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)

        last_message_id = fetch_and_print_new_agent_response(
            thread_id=thread_id,
            agents_client=agents_client,
            last_message_id=last_message_id,
        )
        print(f"Run status: {run.status}")

    print(f"Run finished with status: {run.status}")

    if run.status == "failed":
        print(f"Run failed: {run.last_error}")
        return None

    # Fetch the final message from the agent
    final_message = agents_client.messages.get_last_message_by_role(
        thread_id=thread_id, role=MessageRole.AGENT
    )
    
    return final_message


def main():
    """Main conversation loop."""
    project_client = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )

    conn_id = project_client.connections.get(name=os.environ["BING_RESOURCE_NAME"]).id

    # Initialize a Deep Research tool with Bing Connection ID and Deep Research model deployment name
    deep_research_tool = DeepResearchTool(
        bing_grounding_connection_id=conn_id,
        deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
    )

    # Create Agent with the Deep Research tool and process Agent run
    with project_client:
        with project_client.agents as agents_client:
            # Create a new agent that has the Deep Research tool attached.
            agent = agents_client.create_agent(
                model=os.environ["MODEL_DEPLOYMENT_NAME"],
                name="my-agent-relx",
                instructions="You are a helpful Agent that assists in researching scientific topics.",
                tools=deep_research_tool.definitions,
            )
            print(f"Created agent, ID: {agent.id}")

            # Create thread for communication
            thread = agents_client.threads.create()
            print(f"Created thread, ID: {thread.id}")

            print("\n=== Deep Research Assistant ===")
            print("Type your research questions below. Type 'exit', 'quit', or 'bye' to end the conversation.")
            print("Type 'save' to save the last response to a file.")
            print("================================\n")

            last_agent_message = None
            
            try:
                while True:
                    # Get user input
                    user_input = input("\nYou: ").strip()
                    
                    # Check for exit commands
                    if user_input.lower() in ['exit', 'quit', 'bye']:
                        print("\nGoodbye! Thanks for using the Deep Research Assistant.")
                        break
                    
                    # Check for save command
                    if user_input.lower() == 'save':
                        if last_agent_message:
                            timestamp = time.strftime("%Y%m%d_%H%M%S")
                            filename = f"research_summary_{timestamp}.md"
                            create_research_summary(last_agent_message, filename)
                        else:
                            print("No agent response to save yet.")
                        continue
                    
                    # Skip empty input
                    if not user_input:
                        continue
                    
                    # Process the user's message
                    last_agent_message = process_user_message(
                        user_input=user_input,
                        thread_id=thread.id,
                        agent_id=agent.id,
                        agents_client=agents_client
                    )
                    
                    print("\n" + "-" * 50)  # Separator for readability

            except KeyboardInterrupt:
                print("\n\nConversation interrupted by user.")
            
            finally:
                # Clean-up and delete the agent once the conversation is finished.
                agents_client.delete_agent(agent.id)
                print("\nCleaned up resources. Agent deleted.")


if __name__ == "__main__":
    main()