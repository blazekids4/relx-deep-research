import os
import csv
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()


def read_questions(file_path: str) -> List[str]:
    """Read questions from JSON or CSV file."""
    questions = []
    if file_path.endswith('.json'):
        with open(file_path, 'r', encoding='utf-8') as f:
            questions = json.load(f)
    else:
        # Fallback to CSV reading
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row:  # Skip empty rows
                    questions.append(row[0])
    return questions

def process_batch_research(
    questions: List[str],
    agents_client: AgentsClient,
    agent_id: str,
    output_base_path: str
) -> List[Dict]:
    """Process a batch of research questions and track metrics."""
    results = []
    
    for i, question in enumerate(questions, 1):
        print(f"\nProcessing question {i}/{len(questions)}:")
        print(f"Question: {question}")
        
        # Create a new thread for each question to avoid conflicts
        thread = agents_client.threads.create()
        thread_id = thread.id
        print(f"Created new thread for question {i}, ID: {thread_id}")
        
        # Initialize metrics
        start_time = time.time()
        time_to_first_token = None
        response_text = ""
        citations = []
        
        try:
            # Create message
            message = agents_client.messages.create(
                thread_id=thread_id,
                role="user",
                content=question,
            )
            
            # Create and monitor run
            run = agents_client.runs.create(thread_id=thread_id, agent_id=agent_id)
            run_id = run.id
            # Add timeout and heartbeat settings for polling
            timeout = int(os.getenv("BATCH_TIMEOUT_SECONDS", "300"))  # max seconds to wait per question
            heartbeat_interval = 10  # seconds between progress logs
            loop_seconds = 0
    
            # Poll for completion
            while run.status in ("queued", "in_progress"):
                time.sleep(1)
                loop_seconds += 1
                if loop_seconds % heartbeat_interval == 0:
                    print(f"Still processing question {i}, elapsed {loop_seconds}s")
                if loop_seconds >= timeout:
                    print(f"Timeout after {timeout}s for question {i}, aborting run.")
                    # Cancel the run that timed out
                    try:
                        agents_client.runs.cancel(thread_id=thread_id, run_id=run_id)
                        print(f"Run {run_id} canceled")
                    except Exception as cancel_error:
                        print(f"Error canceling run: {str(cancel_error)}")
                    break
                # update run status
                run = agents_client.runs.get(thread_id=thread_id, run_id=run_id)
            
            # Get response after completion
            if run.status == "completed":
                # Get latest response
                response = agents_client.messages.get_last_message_by_role(
                    thread_id=thread_id,
                    role=MessageRole.AGENT,
                )
                
                if response and response.text_messages:
                    if time_to_first_token is None:
                        time_to_first_token = time.time() - start_time
                    response_text = "\n".join(t.text.value for t in response.text_messages)
                    
                    # Collect citations
                    if response.url_citation_annotations:
                        citations = [
                            {"title": ann.url_citation.title, "url": ann.url_citation.url}
                            for ann in response.url_citation_annotations
                        ]
            
            # Calculate metrics
            total_time = time.time() - start_time
            
            # Get token usage (if available from run)
            tokens_in = getattr(run.usage, 'prompt_tokens', 0) if hasattr(run, 'usage') else 0
            tokens_out = getattr(run.usage, 'completion_tokens', 0) if hasattr(run, 'usage') else 0
            total_tokens = tokens_in + tokens_out
            
            # Save result with metrics
            result = {
                "question": question,
                "status": run.status,
                "error": str(run.last_error) if run.status == "failed" else None,
                "metrics": {
                    "time_to_first_token": time_to_first_token,
                    "total_time": total_time,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "total_tokens": total_tokens,
                    "response_text": response_text,
                    "citations": citations
                }
            }
            results.append(result)
            
            # Save individual markdown file
            save_markdown_result(result, output_base_path, i)
            
        except Exception as e:
            print(f"Error processing question {i}: {str(e)}")
            total_time = time.time() - start_time
            results.append({
                "question": question,
                "status": "error",
                "error": str(e),
                "metrics": {
                    "time_to_first_token": None,
                    "total_time": total_time,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "total_tokens": 0,
                    "response_text": "",
                    "citations": []
                }
            })
    
    save_consolidated_markdown(results, output_base_path)
    
    return results

def save_markdown_result(result: Dict, base_path: str, index: int):
    """Save individual research result as markdown."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{base_path}/research_{index:03d}_{timestamp}.md"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("# Research Result\n\n")
        f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Question:** {result['question']}\n")
        f.write(f"**Status:** {result['status']}\n\n")
        
        if result['error']:
            f.write(f"**Error:** {result['error']}\n\n")
        
        f.write("## Metrics\n")
        metrics = result['metrics']
        f.write(f"- Time to First Token: {metrics['time_to_first_token']} seconds\n")
        f.write(f"- Total Time: {metrics['total_time']:.2f} seconds\n")
        f.write(f"- Tokens In: {metrics['tokens_in']}\n")
        f.write(f"- Tokens Out: {metrics['tokens_out']}\n")
        f.write(f"- Total Tokens: {metrics['total_tokens']}\n\n")
        
        if metrics['response_text']:
            f.write("## Response\n")
            f.write(metrics['response_text'])
        
        if metrics['citations']:
            f.write("\n\n## References\n")
            for i, citation in enumerate(metrics['citations'], 1):
                f.write(f"{i}. [{citation['title']}]({citation['url']})\n")

def save_consolidated_markdown(results: List[Dict], base_path: str):
    """Save consolidated results as markdown."""
    filename = f"{base_path}/batch_results.md"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("# Batch Research Results\n\n")
        f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total Questions Processed:** {len(results)}\n\n")
        
        # Summary statistics
        total_time = sum(r['metrics']['total_time'] for r in results if r['metrics']['total_time'] is not None)
        total_tokens = sum(r['metrics']['total_tokens'] for r in results if r['metrics']['total_tokens'] is not None)
        success_count = sum(1 for r in results if r['status'] == 'completed')
        
        f.write("## Summary Statistics\n")
        f.write(f"- Total Processing Time: {total_time:.2f} seconds\n")
        f.write(f"- Total Tokens Used: {total_tokens}\n")
        f.write(f"- Success Rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)\n\n")
        
        f.write("## Individual Results\n\n")
        for i, result in enumerate(results, 1):
            f.write(f"### {i}. {result['question'][:100]}...\n")
            f.write(f"**Status:** {result['status']}\n")
            if result['error']:
                f.write(f"**Error:** {result['error']}\n")
            
            metrics = result['metrics']
            f.write("**Metrics:**\n")
            f.write(f"- Time to First Token: {metrics['time_to_first_token']} seconds\n")
            f.write(f"- Total Time: {metrics['total_time']:.2f} seconds\n")
            f.write(f"- Tokens: {metrics['tokens_in']} in, {metrics['tokens_out']} out, {metrics['total_tokens']} total\n")
            f.write("\n---\n\n")

def main():
    """Main function to process batch research questions."""
    try:
        # Initialize Azure clients
        project_client = AIProjectClient(
            endpoint=os.environ["PROJECT_ENDPOINT_RELX_LEGAL"],
            credential=DefaultAzureCredential(),
        )
        
        # Get Bing connection
        conn_id = project_client.connections.get(name=os.environ["BING_CONNECTED_RESOURCE_NAME"]).id
        
        # Initialize Deep Research tool
        deep_research_tool = DeepResearchTool(
            bing_grounding_connection_id=conn_id,
            deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
        )
        
        # Create output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"research_results_{timestamp}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Read questions from JSON file
        questions = read_questions("data/SampleQuestionsDeepResearch_2.json")
        print(f"Loaded {len(questions)} questions from JSON")
        
        with project_client:
            with project_client.agents as agents_client:
                # Create agent
                agent = agents_client.create_agent(
                    model=os.environ["MODEL_DEPLOYMENT_NAME"],
                    name="batch-research-agent",
                    instructions="You are a helpful Agent that assists in researching topics.  You will be provided a question to answer that you must do your best to answer without asking for clarity.  Just answer it.",
                    tools=deep_research_tool.definitions,
                )
                print(f"Created agent, ID: {agent.id}")
                
                try:
                    # Process questions
                    results = process_batch_research(
                        questions=questions,
                        agents_client=agents_client,
                        agent_id=agent.id,
                        output_base_path=output_dir
                    )
                    
                    print(f"\nProcessing complete. Results saved in {output_dir}/")
                    
                finally:
                    # Cleanup
                    agents_client.delete_agent(agent.id)
                    print("Agent cleaned up")
        
    except Exception as e:
        print(f"Error in main: {str(e)}")
        raise

if __name__ == "__main__":
    main()
