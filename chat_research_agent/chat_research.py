import os
import csv
import json
import time
import re
import argparse
from datetime import datetime
from typing import Dict, List, Optional
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from opentelemetry import trace
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()

def validate_environment():
    """Validate required environment variables are set."""
    required_vars = [
        "PROJECT_ENDPOINT_RELX_LEGAL",
        "BING_CONNECTED_RESOURCE_NAME",
        "DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME",
        "MODEL_DEPLOYMENT_NAME"
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Validate optional timeout values
    try:
        int(os.getenv("BATCH_TIMEOUT_SECONDS", "300"))
        int(os.getenv("INTERACTIVE_SESSION_TIMEOUT", "1800"))
        int(os.getenv("INTERACTIVE_QUESTION_TIMEOUT", "300"))
    except ValueError:
        raise ValueError("Timeout environment variables must be valid integers")

def read_questions(file_path: str) -> List[str]:
    """Read questions from JSON or CSV file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")
    
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

def load_progress(output_dir: str) -> List[str]:
    """Load already processed questions from output directory."""
    processed_questions = []
    
    # Check for existing results file
    results_file = f"{output_dir}/batch_results.json"
    if os.path.exists(results_file):
        with open(results_file, 'r', encoding='utf-8') as f:
            results = json.load(f)
            processed_questions = [r['question'] for r in results]
    
    return processed_questions

def is_clarification_needed(response_text: str) -> bool:
    """Better detection of when agent needs clarification."""
    clarification_patterns = [
        r'\?$',  # Ends with question mark
        r'could you (please )?clarify',
        r'could you (please )?specify',
        r'which .* do you mean',
        r'what (specific|particular) .* are you (interested|looking)',
        r'please provide (more|additional) (information|details|context)',
        r'to better assist you',
        r'would you like me to focus on',
        r'are you (asking|looking for|interested in)',
        r'did you mean',
    ]
    
    text_lower = response_text.lower()
    
    for pattern in clarification_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False

def process_batch_research(
    questions: List[str],
    agents_client: AgentsClient,
    agent_id: str,
    output_base_path: str,
    resume_progress: List[str] = None
) -> List[Dict]:
    """Process a batch of research questions and track metrics."""
    results = []
    
    # Load existing results if resuming
    if resume_progress:
        results_file = f"{output_base_path}/batch_results.json"
        if os.path.exists(results_file):
            with open(results_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
    
    # Summary statistics tracking
    total_start_time = time.time()
    successful_queries = sum(1 for r in results if r.get('status') == 'completed')
    failed_queries = sum(1 for r in results if r.get('status') != 'completed')
    
    # Filter out already processed questions
    if resume_progress:
        questions = [q for q in questions if q not in resume_progress]
        if resume_progress:
            print(f"\nResuming: Skipping {len(resume_progress)} already processed questions")
    
    for i, question in enumerate(questions, 1):
        print(f"\n{'='*60}")
        print(f"Processing question {i}/{len(questions)} ({(i + len(results))/(len(questions) + len(resume_progress or []))*100:.1f}% complete)")
        print(f"Successful: {successful_queries}, Failed: {failed_queries}")
        elapsed = time.time() - total_start_time
        avg_time = elapsed / (i + len(results)) if (i + len(results)) > 0 else 0
        estimated_remaining = avg_time * (len(questions) - i)
        print(f"Elapsed: {elapsed:.1f}s, Est. remaining: {estimated_remaining:.1f}s")
        print(f"{'='*60}")
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
                        if citations:
                            print("\nReferences:")
                            for j, citation in enumerate(citations, 1):
                                print(f"{j}. {citation['title']}: {citation['url']}")
            
            # Calculate metrics
            total_time = time.time() - start_time
            
            # Get token usage (if available from run)
            tokens_in = getattr(run.usage, 'prompt_tokens', 0) if hasattr(run, 'usage') else 0
            tokens_out = getattr(run.usage, 'completion_tokens', 0) if hasattr(run, 'usage') else 0
            total_tokens = tokens_in + tokens_out
            
            # Save individual result with metrics
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
            
            # Update success/failure counts
            if result['status'] == 'completed':
                successful_queries += 1
            else:
                failed_queries += 1
            
            # Save individual markdown file
            save_markdown_result(result, output_base_path, i + len(resume_progress) if resume_progress else i)
            
            # Save progress after each question
            save_json_results(results, output_base_path)
            
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
            failed_queries += 1
            
            # Save progress even on error
            save_json_results(results, output_base_path)
    
    # Save final consolidated results
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
        f.write(f"- Total Time: {metrics['total_time']} seconds\n")
        f.write(f"- Tokens In: {metrics['tokens_in']}\n")
        f.write(f"- Tokens Out: {metrics['tokens_out']}\n")
        f.write(f"- Total Tokens: {metrics['total_tokens']}\n\n")
        
        f.write("## Response\n")
        f.write(metrics['response_text'])
        
        if metrics['citations']:
            f.write("\n\n## References\n")
            for i, citation in enumerate(metrics['citations'], 1):
                f.write(f"{i}. [{citation['title']}]({citation['url']})\n")

def save_json_results(results: List[Dict], base_path: str):
    """Save consolidated results as JSON."""
    filename = f"{base_path}/batch_results.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

def save_consolidated_markdown(results: List[Dict], base_path: str):
    """Save consolidated results as markdown."""
    filename = f"{base_path}/batch_results.md"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("# Batch Research Results\n\n")
        f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total Questions Processed:** {len(results)}\n\n")
        
        # Summary statistics
        total_time = sum(r['metrics']['total_time'] or 0 for r in results)
        total_tokens = sum(r['metrics']['total_tokens'] or 0 for r in results)
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
            f.write(f"- Total Time: {metrics['total_time']} seconds\n")
            f.write(f"- Tokens: {metrics['tokens_in']} in, {metrics['tokens_out']} out, {metrics['total_tokens']} total\n")
            f.write("\n---\n\n")

def interactive_research_session(
    agents_client: AgentsClient,
    agent_id: str,
    initial_question: str,
    output_base_path: str
) -> Dict:
    """Conduct an interactive research session with multi-turn conversation."""
    print(f"\n=== Starting Interactive Research Session ===")
    print(f"Initial Question: {initial_question}")
    
    # Create a new thread for the conversation
    thread = agents_client.threads.create()
    thread_id = thread.id
    print(f"Created thread ID: {thread_id}")
    
    conversation_history = []
    all_citations = []  # Initialize citations list
    
    # Initialize metrics
    session_start = time.time()
    time_to_first_token = None
    total_tokens_in = 0
    total_tokens_out = 0
    
    # Add timeout for interactive sessions
    session_timeout = int(os.getenv("INTERACTIVE_SESSION_TIMEOUT", "1800"))  # 30 minutes default
    
    # Send initial question
    message = agents_client.messages.create(
        thread_id=thread_id,
        role="user",
        content=initial_question,
    )
    conversation_history.append({"role": "user", "content": initial_question})
    
    while True:
        # Check session timeout
        if time.time() - session_start > session_timeout:
            print(f"\n[Session timeout after {session_timeout} seconds]")
            break
            
        try:
            # Create and monitor run with timeout
            run = agents_client.runs.create(thread_id=thread_id, agent_id=agent_id)
            run_id = run.id
            
            # Add per-question timeout for interactive mode
            question_timeout = int(os.getenv("INTERACTIVE_QUESTION_TIMEOUT", "300"))
            question_start = time.time()
            
            # Poll for completion with visual feedback
            print("\nProcessing", end="", flush=True)
            while run.status in ("queued", "in_progress"):
                time.sleep(1)
                print(".", end="", flush=True)
                
                # Check question timeout
                if time.time() - question_start > question_timeout:
                    print(f"\n[Question timeout after {question_timeout} seconds]")
                    try:
                        agents_client.runs.cancel(thread_id=thread_id, run_id=run_id)
                    except:
                        pass
                    break
                    
                run = agents_client.runs.get(thread_id=thread_id, run_id=run_id)
            print()  # New line after dots
            
            # Update token metrics
            if hasattr(run, 'usage'):
                total_tokens_in += getattr(run.usage, 'prompt_tokens', 0)
                total_tokens_out += getattr(run.usage, 'completion_tokens', 0)
            
            # Handle run status
            if run.status == "failed":
                print(f"[Run failed: {run.last_error}]")
                user_input = input("\nWould you like to retry or exit? (retry/exit): ").strip().lower()
                if user_input == 'exit':
                    break
                else:
                    continue
            
            # Get agent's response
            response = agents_client.messages.get_last_message_by_role(
                thread_id=thread_id,
                role=MessageRole.AGENT,
            )
            
            agent_response = ""
            if response and response.text_messages:
                if time_to_first_token is None:
                    time_to_first_token = time.time() - session_start
                    
                agent_response = "\n".join(t.text.value for t in response.text_messages)
                
                # Display agent's response
                print("\n--- Agent Response ---")
                print(agent_response)
                print("--- End Response ---\n")
                
                conversation_history.append({"role": "agent", "content": agent_response})
                
                # Collect citations if any
                if response.url_citation_annotations:
                    citations = [
                        {"title": ann.url_citation.title, "url": ann.url_citation.url}
                        for ann in response.url_citation_annotations
                    ]
                    if citations:
                        print("\nReferences:")
                        for i, citation in enumerate(citations, 1):
                            print(f"{i}. {citation['title']}: {citation['url']}")
                        all_citations.extend(citations)
            
            # Check if agent is asking for clarification using improved detection
            if agent_response and is_clarification_needed(agent_response):
                # Agent is asking for clarification
                print("\n[The agent appears to be asking for clarification]")
                user_input = input("\nYour response (or 'exit' to end session): ").strip()
                
                if user_input.lower() == 'exit':
                    print("Ending interactive session...")
                    break
                
                # Validate user input
                if not user_input:
                    print("Empty response not allowed. Please provide a response.")
                    continue
                
                # Send user's clarification
                message = agents_client.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_input,
                )
                conversation_history.append({"role": "user", "content": user_input})
            else:
                # Research appears complete, ask if user needs more
                user_input = input("\nDo you need further clarification or have follow-up questions? (yes/no/exit): ").strip().lower()
                
                if user_input in ['no', 'exit']:
                    print("Research session complete.")
                    break
                elif user_input == 'yes':
                    follow_up = input("Please enter your follow-up question: ").strip()
                    if not follow_up:
                        print("Empty question not allowed. Please provide a question.")
                        continue
                    
                    message = agents_client.messages.create(
                        thread_id=thread_id,
                        role="user",
                        content=follow_up,
                    )
                    conversation_history.append({"role": "user", "content": follow_up})
            
                
        except Exception as e:
            print(f"Error during conversation: {str(e)}")
            user_input = input("\nWould you like to continue or exit? (continue/exit): ").strip().lower()
            if user_input == 'exit':
                break
    
    
    # Compile final response text
    response_text = "\n\n".join(
        f"**{turn['role'].upper()}**: {turn['content']}" 
        for turn in conversation_history
    )
    
    # Calculate final metrics
    total_time = time.time() - session_start
    total_tokens = total_tokens_in + total_tokens_out
    
    # Save interactive session results
    result = {
        "question": initial_question,
        "conversation_history": conversation_history,
        "status": "completed",
        "error": None,
        "metrics": {
            "time_to_first_token": time_to_first_token,
            "total_time": total_time,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "total_tokens": total_tokens,
            "citations": all_citations
        }
    }
    
    # Save results
    save_interactive_session(result, output_base_path)
    
    return result

def save_interactive_session(result: Dict, base_path: str):
    """Save interactive session results as markdown and JSON."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save as markdown
    md_filename = f"{base_path}/interactive_session_{timestamp}.md"
    with open(md_filename, "w", encoding="utf-8") as f:
        f.write("# Interactive Research Session\n\n")
        f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Initial Question:** {result['question']}\n\n")
        
        f.write("## Conversation History\n\n")
        for turn in result['conversation_history']:
            role = turn['role'].upper()
            f.write(f"### {role}\n{turn['content']}\n\n")
        
        f.write("## Metrics\n")
        metrics = result['metrics']
        f.write(f"- Time to First Token: {metrics['time_to_first_token']} seconds\n")
        f.write(f"- Total Time: {metrics['total_time']} seconds\n")
        f.write(f"- Tokens In: {metrics['tokens_in']}\n")
        f.write(f"- Tokens Out: {metrics['tokens_out']}\n")
        f.write(f"- Total Tokens: {metrics['total_tokens']}\n\n")
        
        if metrics['citations']:
            f.write("## References\n")
            for i, citation in enumerate(metrics['citations'], 1):
                f.write(f"{i}. [{citation['title']}]({citation['url']})\n")
    
    # Save as JSON
    json_filename = f"{base_path}/interactive_session_{timestamp}.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nSession saved to:\n- {md_filename}\n- {json_filename}")

def main():
    """Main function to process batch research questions or run interactive mode."""
    try:
        # Validate environment first
        validate_environment()
        
        parser = argparse.ArgumentParser(description="Research Assistant - Batch or Interactive Mode")
        parser.add_argument("--mode", choices=["batch", "interactive"], default="batch",
                          help="Run in batch mode (default) or interactive mode")
        parser.add_argument("--question", type=str, help="Initial question for interactive mode")
        parser.add_argument("--file", type=str, default="data/SampleQuestionsDeepResearch_2.json",
                          help="Input file for batch mode")
        parser.add_argument("--resume", action="store_true", 
                           help="Resume from previous batch run if interrupted")
        
        args = parser.parse_args()
        
        # Initialize Azure clients - Use the correct environment variable
        project_client = AIProjectClient(
            endpoint=os.environ["PROJECT_ENDPOINT_RELX_LEGAL"],
            credential=DefaultAzureCredential(),
        )
        
        # Get Bing connection with better error handling
        try:
            bing_connection_name = os.environ["BING_CONNECTED_RESOURCE_NAME"]
            print(f"Attempting to get Bing connection: {bing_connection_name}")
            
            # List available connections for debugging
            try:
                connections = project_client.connections.list()
                print("Available connections:")
                for conn in connections:
                    print(f"  - {conn.name} (Type: {conn.properties.get('category', 'Unknown')})")
            except Exception as list_error:
                print(f"Could not list connections: {list_error}")
            
            conn_id = project_client.connections.get(name=bing_connection_name).id
            print(f"Successfully retrieved connection ID: {conn_id}")
            
        except KeyError:
            raise ValueError("BING_CONNECTED_RESOURCE_NAME environment variable is not set")
        except Exception as e:
            print(f"Error getting Bing connection '{bing_connection_name}': {str(e)}")
            print("\nPossible solutions:")
            print("1. Verify the connection name matches exactly in Azure AI Studio")
            print("2. Check if the connection exists in your Azure AI Project")
            print("3. Ensure your credentials have access to the connection")
            print("4. Try using the connection ID directly if you have it")
            raise
        
        # Initialize Deep Research tool
        deep_research_tool = DeepResearchTool(
            bing_grounding_connection_id=conn_id,
            deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
        )
        
        # Create output directory
        if args.mode == "batch" and args.resume:
            # Find the most recent research results directory
            import glob
            existing_dirs = glob.glob("research_results_*")
            if existing_dirs:
                existing_dirs.sort()
                output_dir = existing_dirs[-1]
                print(f"Resuming with existing directory: {output_dir}")
            else:
                print("No existing results directory found to resume from.")
                args.resume = False
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = f"research_results_{timestamp}"
                os.makedirs(output_dir, exist_ok=True)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = f"research_results_{timestamp}"
            os.makedirs(output_dir, exist_ok=True)
        
        with project_client:
            with project_client.agents as agents_client:
                # Create agent with updated instructions for interactive mode
                instructions = (
                    "You are a helpful research assistant that conducts thorough research on topics. "
                    "When you need clarification to provide better results, ask specific questions. "
                    "Be clear about what additional information would help improve your research."
                    if args.mode == "interactive"
                    else "You are a helpful Agent that assists in researching topics. You will be provided a question to answer that you must do your best to answer without asking for clarity. Just answer it."
                )
                
                agent = agents_client.create_agent(
                    model=os.environ["MODEL_DEPLOYMENT_NAME"],
                    name=f"{args.mode}-research-agent",
                    instructions=instructions,
                    tools=deep_research_tool.definitions,
                )
                print(f"Created agent, ID: {agent.id}")
                
                try:
                    if args.mode == "interactive":
                        # Interactive mode
                        if not args.question:
                            initial_question = input("Please enter your research question: ").strip()
                            if not initial_question:
                                print("No question provided. Exiting.")
                                return
                        else:
                            initial_question = args.question
                        
                        result = interactive_research_session(
                            agents_client=agents_client,
                            agent_id=agent.id,
                            initial_question=initial_question,
                            output_base_path=output_dir
                        )
                    else:
                        # Batch mode
                        questions = read_questions(args.file)
                        print(f"Loaded {len(questions)} questions from {args.file}")
                        
                        # Check for resume
                        resume_progress = []
                        if args.resume:
                            resume_progress = load_progress(output_dir)
                            if resume_progress:
                                print(f"Found {len(resume_progress)} already processed questions")
                        
                        results = process_batch_research(
                            questions=questions,
                            agents_client=agents_client,
                            agent_id=agent.id,
                            output_base_path=output_dir,
                            resume_progress=resume_progress
                        )
                    
                    print(f"\nProcessing complete. Results saved in {output_dir}/")
                    
                finally:
                    # Cleanup
                    agents_client.delete_agent(agent.id)
                    print("Agent cleaned up")
        
    except FileNotFoundError as e:
        print(f"File error: {str(e)}")
    except ValueError as e:
        print(f"Configuration error: {str(e)}")
    except Exception as e:
        print(f"Error in main: {str(e)}")
        raise

if __name__ == "__main__":
    main()