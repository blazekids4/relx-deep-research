import os, time
from typing import Optional
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from dotenv import load_dotenv
from datetime import datetime
from opentelemetry import trace

# Import telemetry module
from telemetry import tracer, configure_tracing

# Load environment variables from .env file
load_dotenv()


@tracer.start_as_current_span("fetch_agent_response")

def fetch_and_print_new_agent_response(
    thread_id: str,
    agents_client: AgentsClient,
    last_message_id: Optional[str] = None,
) -> Optional[str]:
    """Fetch and display new agent responses with tracing."""
    span = trace.get_current_span()
    span.set_attribute("thread.id", thread_id)
    span.set_attribute("last_message.id", last_message_id or "none")
    span.set_attribute("gen_ai.operation.name", "agent_response_fetch")
    
    response = agents_client.messages.get_last_message_by_role(
        thread_id=thread_id,
        role=MessageRole.AGENT,
    )
    if not response or response.id == last_message_id:
        span.set_attribute("response.new_content", False)
        return last_message_id  # No new content

    span.set_attribute("response.new_content", True)
    span.set_attribute("response.id", response.id)
    span.set_attribute("response.text_count", len(response.text_messages))
    span.set_attribute("response.citation_count", len(response.url_citation_annotations))
    span.set_attribute("gen_ai.response.model", "deep-research")
    
    # Add event for new response
    span.add_event("gen_ai.new_response", {
        "message_id": response.id,
        "text_count": len(response.text_messages),
        "citation_count": len(response.url_citation_annotations)
    })

    print("\nAgent response:")
    print("\n".join(t.text.value for t in response.text_messages))

    for ann in response.url_citation_annotations:
        print(f"URL Citation: [{ann.url_citation.title}]({ann.url_citation.url})")

    return response.id


@tracer.start_as_current_span("create_research_summary")

def create_research_summary(
        message: ThreadMessage,
        user_query: str = "",
        filepath: str = "research_summary.md"
) -> None:
    """Create a formatted markdown research summary with metadata."""
    span = trace.get_current_span()
    
    if not message:
        print("No message content provided, cannot create research summary.")
        span.set_status(trace.Status(trace.StatusCode.ERROR, "No message content"))
        return

    span.set_attribute("file.path", filepath)
    span.set_attribute("message.id", message.id)
    span.set_attribute("user.query", user_query)
    
    try:
        with open(filepath, "w", encoding="utf-8") as fp:
            # Write metadata header
            fp.write("# Research Summary\n\n")
            fp.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if user_query:
                fp.write(f"**Query:** {user_query}\n")
            fp.write(f"**Thread ID:** {message.thread_id}\n")
            fp.write(f"**Message ID:** {message.id}\n\n")
            fp.write("---\n\n")
            
            # Write text summary
            text_summary = "\n\n".join([t.text.value.strip() for t in message.text_messages])
            fp.write(text_summary)

            # Write unique URL citations, if present
            if message.url_citation_annotations:
                fp.write("\n\n## References\n\n")
                seen_urls = set()
                citation_count = 0
                for ann in message.url_citation_annotations:
                    url = ann.url_citation.url
                    title = ann.url_citation.title or url
                    if url not in seen_urls:
                        fp.write(f"{citation_count + 1}. [{title}]({url})\n")
                        seen_urls.add(url)
                        citation_count += 1
                
                span.set_attribute("citations.unique_count", citation_count)

        print(f"Research summary written to '{filepath}'.")
        span.set_status(trace.Status(trace.StatusCode.OK))
        span.add_event("summary_created", {
            "file_path": filepath,
            "citations_count": citation_count if message.url_citation_annotations else 0
        })
        
    except Exception as e:
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        print(f"Error creating research summary: {str(e)}")


@tracer.start_as_current_span("process_user_message")

def process_user_message(
    user_input: str,
    thread_id: str,
    agent_id: str,
    agents_client: AgentsClient,
    auto_save: bool = True
) -> ThreadMessage:
    """Process a single user message and return the agent's response."""
    span = trace.get_current_span()
    span.set_attribute("gen_ai.request.model", os.environ.get("MODEL_DEPLOYMENT_NAME", "unknown"))
    span.set_attribute("gen_ai.operation.name", "process_message")
    span.set_attribute("user.input", user_input)
    span.set_attribute("thread.id", thread_id)
    span.set_attribute("agent.id", agent_id)
    span.set_attribute("auto_save.enabled", auto_save)
    
    # Add event for user input
    span.add_event("gen_ai.prompt", {
        "gen_ai.prompt.user": user_input
    })
    
    # Create message to thread
    message = agents_client.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_input,
    )
    print(f"Created message, ID: {message.id}")
    span.set_attribute("message.id", message.id)

    print(f"Processing your request... this may take a few minutes. Please be patient!")
    
    # Record the start time for tracking
    start_time = time.time()
    
    # Poll the run as long as run status is queued or in progress
    run = agents_client.runs.create(thread_id=thread_id, agent_id=agent_id)
    span.set_attribute("run.id", run.id)
    
    last_message_id = None
    poll_count = 0
    
    while run.status in ("queued", "in_progress"):
        time.sleep(1)
        poll_count += 1
        run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)

        last_message_id = fetch_and_print_new_agent_response(
            thread_id=thread_id,
            agents_client=agents_client,
            last_message_id=last_message_id,
        )
        
        # Update status every 10 polls
        if poll_count % 10 == 0:
            print(f"Run status: {run.status} (polling for {poll_count} seconds...)")

    # Calculate processing time
    processing_time = time.time() - start_time
    span.set_attribute("gen_ai.usage.latency_ms", processing_time * 1000)
    span.set_attribute("processing.duration_seconds", processing_time)
    span.set_attribute("processing.poll_count", poll_count)
    span.set_attribute("run.final_status", run.status)
    
    print(f"Run finished with status: {run.status}")
    print(f"Processing time: {processing_time:.2f} seconds")

    if run.status == "failed":
        error_msg = f"Run failed: {run.last_error}"
        print(error_msg)
        span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
        span.add_event("run_failed", {"error": str(run.last_error)})
        return None

    # Fetch the final message from the agent
    final_message = agents_client.messages.get_last_message_by_role(
        thread_id=thread_id, role=MessageRole.AGENT
    )
    
    if final_message:
        # Add completion event
        span.add_event("gen_ai.completion", {
            "gen_ai.completion.id": final_message.id,
            "gen_ai.response.model": "deep-research"
        })
        
        if auto_save:
            # Auto-save the response
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"research_{timestamp}.md"
            create_research_summary(final_message, user_query=user_input, filepath=filename)
            span.add_event("auto_saved", {"filename": filename})
    
    span.set_status(trace.Status(trace.StatusCode.OK))
    return final_message


@tracer.start_as_current_span("deep_research_session")

def main():
    """Main conversation loop with comprehensive tracing."""
    span = trace.get_current_span()
    
    # Set service name for better identification in Application Insights
    span.set_attribute("service.name", "deep-research-agent")
    span.set_attribute("service.version", "1.0.0")
    
    try:
        project_client = AIProjectClient(
            endpoint=os.environ["PROJECT_ENDPOINT"],
            credential=DefaultAzureCredential(),
        )
        
        # Configure tracing with the project client
        configure_tracing(project_client)

        conn_id = project_client.connections.get(name=os.environ["BING_CONNECTED_RESOURCE_NAME"]).id
        span.set_attribute("bing.connection_id", conn_id)

        # Initialize a Deep Research tool with Bing Connection ID and Deep Research model deployment name
        deep_research_tool = DeepResearchTool(
            bing_grounding_connection_id=conn_id,
            deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
        )

        # Create Agent with the Deep Research tool and process Agent run
        with project_client:
            with project_client.agents as agents_client:
                # Create a new agent that has the Deep Research tool attached.
                with tracer.start_as_current_span("create_agent") as agent_span:
                    agent = agents_client.create_agent(
                        model=os.environ["MODEL_DEPLOYMENT_NAME"],
                        name="my-agent-relx",
                        instructions="You are a helpful Agent that assists in researching scientific topics.",
                        tools=deep_research_tool.definitions,
                    )
                    print(f"Created agent, ID: {agent.id}")
                    agent_span.set_attribute("agent.id", agent.id)
                    agent_span.set_attribute("agent.name", "my-agent-relx")
                    agent_span.set_attribute("agent.model", os.environ["MODEL_DEPLOYMENT_NAME"])
                    agent_span.set_attribute("gen_ai.system.message", "You are a helpful Agent that assists in researching scientific topics.")

                # Create thread for communication
                with tracer.start_as_current_span("create_thread") as thread_span:
                    thread = agents_client.threads.create()
                    print(f"Created thread, ID: {thread.id}")
                    thread_span.set_attribute("thread.id", thread.id)

                print("\n=== Deep Research Assistant ===")
                print("Type your research questions below. Type 'exit', 'quit', or 'bye' to end the conversation.")
                print("Type 'save' to save the last response to a file.")
                print("Auto-save is enabled - all responses will be saved automatically.")
                print("================================\n")

                last_agent_message = None
                conversation_count = 0
                session_start = time.time()
                
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
                                create_research_summary(last_agent_message, filepath=filename)
                            else:
                                print("No agent response to save yet.")
                            continue
                        
                        # Skip empty input
                        if not user_input:
                            continue
                        
                        conversation_count += 1
                        
                        # Process the user's message
                        with tracer.start_as_current_span("conversation_turn") as turn_span:
                            turn_span.set_attribute("conversation.turn_number", conversation_count)
                            turn_span.set_attribute("user.input_length", len(user_input))
                            turn_span.set_attribute("gen_ai.operation.name", "conversation_turn")
                            
                            last_agent_message = process_user_message(
                                user_input=user_input,
                                thread_id=thread.id,
                                agent_id=agent.id,
                                agents_client=agents_client,
                                auto_save=True  # Enable auto-save
                            )
                            
                            if last_agent_message:
                                turn_span.set_attribute("response.success", True)
                            else:
                                turn_span.set_attribute("response.success", False)
                        
                        print("\n" + "-" * 50)  # Separator for readability

                except KeyboardInterrupt:
                    print("\n\nConversation interrupted by user.")
                
                finally:
                    session_duration = time.time() - session_start
                    span.set_attribute("session.duration_seconds", session_duration)
                    span.set_attribute("session.conversation_count", conversation_count)
                    
                    # Clean-up and delete the agent once the conversation is finished.
                    with tracer.start_as_current_span("cleanup") as cleanup_span:
                        agents_client.delete_agent(agent.id)
                        print("\nCleaned up resources. Agent deleted.")
                        cleanup_span.set_attribute("agent.deleted", True)
                    
                    span.add_event("session_ended", {
                        "duration_seconds": session_duration,
                        "conversation_count": conversation_count
                    })

    except Exception as e:
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        print(f"Error in main: {str(e)}")
        raise


if __name__ == "__main__":
    main()