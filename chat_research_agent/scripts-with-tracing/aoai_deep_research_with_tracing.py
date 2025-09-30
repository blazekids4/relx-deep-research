import os
import json
import time
import random
import uuid
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
import asyncio
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from opentelemetry import trace
from dotenv import load_dotenv

# Import telemetry module
from telemetry import tracer, configure_tracing

# Load environment variables from .env file
load_dotenv()

class ResearchMetrics:
    def __init__(self):
        self.start_time = None
        self.first_token_time = None
        self.completion_time = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.total_tokens = 0
        self.time_to_first_token = None
        self.total_time = None
        self.response_text = ""
        self.citations = []

    def start(self):
        self.start_time = time.time()

    def mark_first_token(self):
        if not self.first_token_time:
            self.first_token_time = time.time()
            self.time_to_first_token = self.first_token_time - self.start_time

    def complete(self):
        self.completion_time = time.time()
        self.total_time = self.completion_time - self.start_time

    def to_dict(self) -> Dict:
        return {
            "time_to_first_token": round(self.time_to_first_token, 2) if self.time_to_first_token else None,
            "total_time": round(self.total_time, 2) if self.total_time else None,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "response_text": self.response_text,
            "citations": self.citations
        }


class DeepResearchChatAgent:
    def __init__(self):
        # Initialize Azure clients
        self.project_client = AIProjectClient(
            endpoint=os.environ["PROJECT_ENDPOINT_RELX_LEGAL"],
            credential=DefaultAzureCredential(),
        )
        
        configure_tracing(self.project_client)
        
        # Initialize Deep Research tool
        self.conn_id = self.project_client.connections.get(
            name=os.environ["BING_CONNECTED_RESOURCE_NAME"]
        ).id
        
        self.deep_research_tool = DeepResearchTool(
            bing_grounding_connection_id=self.conn_id,
            deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
        )
        
        # Configure persistence directories
        self.config_dir = os.path.join(os.getcwd(), "agent_config")
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Thread cache to maintain conversation state - format: {session_id: thread_id}
        # Try to load from disk if available
        self.thread_cache = self._load_thread_cache() or {}
        
        # Initialize agents client
        self.project_client.__enter__()
        self.agents_client = self.project_client.agents.__enter__()
        
        # Try to load existing agent ID
        self.agent = self._load_or_create_agent()
        
        # Set up periodic thread cache saving (every 10 minutes)
        self.keep_saving = True
        self.save_interval = 600  # 10 minutes
        self.save_thread = threading.Thread(target=self._periodic_save_thread_cache, daemon=True)
        self.save_thread.start()
        
        print(f"Initialized Deep Research Chat Agent, ID: {self.agent.id}")
        
    def _load_or_create_agent(self):
        """Load existing agent or create a new one if needed"""
        agent_config_file = os.path.join(self.config_dir, "agent_config.json")
        agent = None
        
        try:
            # Check if config file exists
            if os.path.exists(agent_config_file):
                with open(agent_config_file, 'r') as f:
                    agent_config = json.load(f)
                    
                agent_id = agent_config.get('agent_id')
                if agent_id:
                    try:
                        # Try to fetch the existing agent
                        agent = self.agents_client.get_agent(agent_id)
                        print(f"Loaded existing agent, ID: {agent_id}")
                        return agent
                    except Exception as e:
                        print(f"Failed to load existing agent: {str(e)}")
        except Exception as e:
            print(f"Error loading agent config: {str(e)}")
        

        # Create a new agent if we couldn't load an existing one
        agent = self.agents_client.create_agent(
            model=os.environ["MODEL_DEPLOYMENT_NAME"],
            name="deep-research-chat-agent",
            instructions="""You are a helpful research agent that assists in researching topics comprehensively. 
            
Your responses should:
1. Provide detailed, thorough analysis of the topic
2. Include specific facts, data, and statistics where relevant
3. Always cite your sources with proper references
4. Structure your response with clear sections when appropriate
5. Be comprehensive rather than brief - depth and accuracy are more important than brevity

You will be provided a question to answer that you must do your best to answer without asking for clarity. Provide a complete, well-researched response.""",
            tools=self.deep_research_tool.definitions,
        )        
        # Save the agent ID for future use
        try:
            with open(agent_config_file, 'w') as f:
                json.dump({
                    'agent_id': agent.id,
                    'name': "deep-research-chat-agent",
                    'model': os.environ["MODEL_DEPLOYMENT_NAME"],
                    'created_at': datetime.now().isoformat()
                }, f, indent=2)
                print(f"Saved agent configuration, ID: {agent.id}")
        except Exception as e:
            print(f"Failed to save agent configuration: {str(e)}")
            
        return agent

    def _load_thread_cache(self):
        """Load thread cache from file"""
        thread_cache_file = os.path.join(self.config_dir, "thread_cache.json")
        thread_cache = None
        
        try:
            if os.path.exists(thread_cache_file):
                with open(thread_cache_file, 'r') as f:
                    thread_cache = json.load(f)
                print(f"Loaded thread cache with {len(thread_cache)} sessions")
        except json.JSONDecodeError as e:
            print(f"Corrupted thread cache file: {str(e)}")
            thread_cache = self._repair_thread_cache(thread_cache_file)
        except Exception as e:
            print(f"Error loading thread cache: {str(e)}")
            
        return thread_cache or {}
        
    def _repair_thread_cache(self, cache_file):
        """Attempt to repair corrupted thread cache file"""
        print("Attempting to repair thread cache...")
        
        # Check for backups first
        backup_dir = os.path.join(self.config_dir, "backups")
        if os.path.exists(backup_dir):
            backup_files = [f for f in os.listdir(backup_dir) if f.startswith("thread_cache_")]
            if backup_files:
                # Sort by timestamp (newest first)
                backup_files.sort(reverse=True)
                for backup_file in backup_files:
                    try:
                        with open(os.path.join(backup_dir, backup_file), 'r') as f:
                            thread_cache = json.load(f)
                        print(f"Successfully loaded thread cache from backup: {backup_file}")
                        # Save this as the main thread cache
                        with open(cache_file, 'w') as f:
                            json.dump(thread_cache, f, indent=2)
                        return thread_cache
                    except Exception:
                        continue  # Try next backup
        
        # If no valid backups found, create empty cache
        empty_cache = {}
        try:
            with open(cache_file, 'w') as f:
                json.dump(empty_cache, f, indent=2)
            print("Created new empty thread cache")
        except Exception as e:
            print(f"Failed to create new thread cache: {str(e)}")
            
        return empty_cache
    
    def _save_thread_cache(self):
        """Save thread cache to file"""
        thread_cache_file = os.path.join(self.config_dir, "thread_cache.json")
        try:
            # Create a timestamped backup of the thread cache periodically
            if os.path.exists(thread_cache_file) and random.random() < 0.2:  # 20% chance to create backup
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = os.path.join(self.config_dir, "backups")
                os.makedirs(backup_dir, exist_ok=True)
                
                # Clean up old backups if there are more than 10
                try:
                    backup_files = [f for f in os.listdir(backup_dir) if f.startswith("thread_cache_")]
                    if len(backup_files) > 10:
                        backup_files.sort()  # Sort by timestamp (oldest first)
                        for old_file in backup_files[:-10]:  # Remove all but the 10 newest
                            try:
                                os.remove(os.path.join(backup_dir, old_file))
                            except Exception:
                                pass
                except Exception:
                    pass  # Silently ignore cleanup errors
                
                # Create the backup
                backup_file = os.path.join(backup_dir, f"thread_cache_{timestamp}.json")
                try:
                    import shutil
                    shutil.copy2(thread_cache_file, backup_file)
                    print(f"Created thread cache backup: {backup_file}")
                except Exception as backup_error:
                    print(f"Failed to create backup: {str(backup_error)}")
                
            # Save the current thread cache
            with open(thread_cache_file, 'w') as f:
                json.dump(self.thread_cache, f, indent=2)
            
            # Write a special "last_saved" timestamp file
            try:
                with open(os.path.join(self.config_dir, "thread_cache_last_saved.txt"), 'w') as f:
                    f.write(datetime.now().isoformat())
            except Exception:
                pass  # Silently ignore timestamp file errors
                
        except Exception as e:
            print(f"Error saving thread cache: {str(e)}")
    
    async def create_session(self, session_id: str) -> str:
        """Create a new conversation session with a unique thread"""
        if session_id in self.thread_cache:
            # Verify the thread still exists
            thread_id = self.thread_cache[session_id]
            try:
                # Try to list messages - if the thread doesn't exist, this will fail
                self.agents_client.messages.list(thread_id=thread_id)
                print(f"Using existing thread for session {session_id}, ID: {thread_id}")
                return thread_id
            except Exception as e:
                print(f"Thread {thread_id} no longer exists or cannot be accessed: {str(e)}")
                print(f"Error type: {type(e).__name__}")
                # Continue below to create a new thread
        
        try:
            # Create a new thread
            thread = self.agents_client.threads.create()
            thread_id = thread.id
            self.thread_cache[session_id] = thread_id
            print(f"Created new thread for session {session_id}, ID: {thread_id}")
            
            # Save updated thread cache
            self._save_thread_cache()
            
            return thread_id
        except Exception as e:
            # If there's an error creating a thread, log it and raise to caller
            print(f"Failed to create thread for session {session_id}: {str(e)}")
            print(f"Error type: {type(e).__name__}")
            raise

    async def send_message(self, session_id: str, message: str, timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Send a message to the agent and get a response
        
        Args:
            session_id: The session ID for the conversation
            message: The user's message to the agent
            timeout_seconds: Optional custom timeout in seconds. If not specified, uses CHAT_TIMEOUT_SECONDS env var or 600 seconds by default
        """
        # Set up retry mechanism for thread operations
        max_retries = 2
        retry_count = 0
        last_error = None
        
        while retry_count <= max_retries:
            try:
                # Ensure session exists
                thread_id = await self.create_session(session_id)
                break  # Success, exit retry loop
            except Exception as e:
                last_error = e
                retry_count += 1
                print(f"Attempt {retry_count}/{max_retries}: Error accessing thread for session {session_id}: {str(e)}")
                
                # If we still have retries left, recreate the thread
                if retry_count <= max_retries:
                    print(f"Creating a new thread for retry {retry_count}...")
                    if session_id in self.thread_cache:
                        del self.thread_cache[session_id]
                    # Wait a short time before retry
                    await asyncio.sleep(0.5)
                else:
                    # Max retries reached, raise error
                    raise Exception(f"Failed to create or access thread after {max_retries} attempts: {str(last_error)}")
        
        metrics = ResearchMetrics()
        metrics.start()
        
        try:
            # Create message
            self.agents_client.messages.create(
                thread_id=thread_id,
                role="user",
                content=message,
            )
            
            # Create and monitor run
            run = self.agents_client.runs.create(thread_id=thread_id, agent_id=self.agent.id)
            run_id = run.id
            
            # Add timeout and heartbeat settings for polling
            timeout = timeout_seconds or int(os.getenv("CHAT_TIMEOUT_SECONDS", "600"))  # increased default timeout to 600 seconds
            heartbeat_interval = 5  # seconds between progress logs
            loop_seconds = 0
            
            response_text = ""
            citations = []
            
            # Poll for completion
            while run.status in ("queued", "in_progress"):
                await asyncio.sleep(1)  # Use asyncio.sleep for async waiting
                loop_seconds += 1
                
                if loop_seconds % heartbeat_interval == 0:
                    print(f"Still processing message in session {session_id}, elapsed {loop_seconds}s")
                
                if loop_seconds >= timeout:
                    print(f"Timeout after {timeout}s for message ('{message[:50]}...'), aborting run.")
                    try:
                        self.agents_client.runs.cancel(thread_id=thread_id, run_id=run_id)
                        print(f"Run {run_id} canceled")
                        
                        # Add warning to response text about timeout
                        if not response_text:
                            response_text = f"⚠️ Your research query timed out after {timeout} seconds. Please try a more specific question or increase the timeout value."
                        else:
                            response_text += f"\n\n⚠️ Note: This response may be incomplete as the research process timed out after {timeout} seconds."
                    except Exception as cancel_error:
                        print(f"Error canceling run: {str(cancel_error)}")
                    break
                
                # Update run status
                run = self.agents_client.runs.get(thread_id=thread_id, run_id=run_id)
                
                # Get latest response
                response = self.agents_client.messages.get_last_message_by_role(
                    thread_id=thread_id,
                    role=MessageRole.AGENT,
                )
                
                if response and response.text_messages:
                    metrics.mark_first_token()
                    response_text = "\n".join(t.text.value for t in response.text_messages)
                    
                    # Collect citations
                    if response.url_citation_annotations:
                        citations = [
                            {
                                "id": str(i+1),
                                "title": ann.url_citation.title,
                                "url": ann.url_citation.url,
                                "source": ann.url_citation.url,
                                "type": "web",
                                "snippet": ann.url_citation.text if hasattr(ann.url_citation, 'text') else ""
                            }
                            for i, ann in enumerate(response.url_citation_annotations)
                        ]
            
            metrics.complete()
            metrics.response_text = response_text
            metrics.citations = citations
            
            # Get token usage from run
            if hasattr(run, 'usage'):
                metrics.tokens_in = getattr(run.usage, 'prompt_tokens', 0)
                metrics.tokens_out = getattr(run.usage, 'completion_tokens', 0)
                metrics.total_tokens = getattr(run.usage, 'total_tokens', 0)
            
            # Generate formatted markdown for the response
            formatted_markdown = self._format_research_markdown(message, response_text, citations, metrics, run.status)
            
            # Return formatted response
            return {
                "answer": response_text,
                "markdown": formatted_markdown,
                "citations": citations,
                "metrics": metrics.to_dict(),
                "status": run.status,
                "error": str(run.last_error) if run.status == "failed" else None
            }
            
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            metrics.complete()
            return {
                "answer": f"I apologize, but I encountered an error while processing your request. Please try again.",
                "citations": [],
                "metrics": metrics.to_dict(),
                "status": "error",
                "error": str(e)
            }

    async def reset_session(self, session_id: str) -> bool:
        """Reset a conversation session by creating a new thread"""
        if session_id in self.thread_cache:
            # We don't need to explicitly delete the thread, just remove from cache
            del self.thread_cache[session_id]
            # Save the updated cache
            self._save_thread_cache()
        
        # Create a new thread
        await self.create_session(session_id)
        return True
    
    async def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Get the conversation history for a session"""
        if session_id not in self.thread_cache:
            print(f"No thread found for session {session_id} in cache")
            return []
        
        thread_id = self.thread_cache[session_id]
        
        # Set up retry mechanism for history retrieval
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # Try to get messages from the thread
                messages = self.agents_client.messages.list(thread_id=thread_id)
                history = []
                
                for msg in messages:
                    if not msg.text_messages:
                        continue
                    
                    role = "user" if msg.role == MessageRole.USER else "assistant"
                    content = "\n".join(t.text.value for t in msg.text_messages)
                    
                    # Get citations if available
                    citations = []
                    if role == "assistant" and msg.url_citation_annotations:
                        citations = [
                            {
                                "id": str(i+1),
                                "title": ann.url_citation.title,
                                "url": ann.url_citation.url,
                                "source": ann.url_citation.url,
                                "type": "web", 
                                "snippet": ann.url_citation.text if hasattr(ann.url_citation, 'text') else ""
                            }
                            for i, ann in enumerate(msg.url_citation_annotations)
                        ]
                    
                    history.append({
                        "role": role,
                        "content": content,
                        "citations": citations,
                        "timestamp": msg.created_at.isoformat() if hasattr(msg, 'created_at') else datetime.now().isoformat()
                    })
                
                history.sort(key=lambda x: x.get("timestamp", ""))
                return history
                
            except Exception as e:
                retry_count += 1
                print(f"Attempt {retry_count}/{max_retries}: Error retrieving conversation history: {str(e)}")
                
                # Check if it's a "thread not found" type of error
                if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                    # Thread might have been deleted or expired, remove from cache
                    if session_id in self.thread_cache:
                        del self.thread_cache[session_id]
                        self._save_thread_cache()
                        print(f"Thread for session {session_id} not found, removed from cache")
                    
                    # If we still have retries left, create a new thread and try again
                    if retry_count <= max_retries:
                        try:
                            print(f"Creating a new thread for session {session_id}")
                            await self.create_session(session_id)
                            thread_id = self.thread_cache[session_id]
                            # For a new thread, history will be empty
                            if retry_count == max_retries:
                                return []
                        except Exception as create_error:
                            print(f"Failed to create new thread: {str(create_error)}")
                            return []
                    else:
                        return []
                else:
                    # For non-thread-not-found errors, wait a bit before retrying
                    if retry_count < max_retries:
                        await asyncio.sleep(0.5)
                    else:
                        return []
                        
        return []

    def _periodic_save_thread_cache(self):
        """Periodically save thread cache in background thread"""
        while self.keep_saving:
            time.sleep(self.save_interval)
            try:
                if hasattr(self, 'thread_cache'):
                    self._save_thread_cache()
                    print(f"Periodic thread cache backup completed at {datetime.now().isoformat()}")
            except Exception as e:
                print(f"Error in periodic thread cache save: {str(e)}")
    
    def _format_research_markdown(self, question: str, response_text: str, citations: List[Dict], metrics: ResearchMetrics, status: str) -> str:
        """Format research response as markdown, similar to batch research output"""
        markdown = []
        
        # Header
        markdown.append("# Research Result\n")
        markdown.append(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        markdown.append(f"**Question:** {question}\n")
        markdown.append(f"**Status:** {status}\n\n")
        
        # Metrics section
        markdown.append("## Metrics\n")
        markdown.append(f"- Time to First Token: {metrics.time_to_first_token:.2f} seconds\n" if metrics.time_to_first_token else "- Time to First Token: N/A\n")
        markdown.append(f"- Total Time: {metrics.total_time:.2f} seconds\n" if metrics.total_time else "- Total Time: N/A\n")
        markdown.append(f"- Tokens In: {metrics.tokens_in}\n")
        markdown.append(f"- Tokens Out: {metrics.tokens_out}\n")
        markdown.append(f"- Total Tokens: {metrics.total_tokens}\n\n")
        
        # Response section
        markdown.append("## Response\n")
        markdown.append(response_text)
        
        # Citations section
        if citations:
            markdown.append("\n\n## References\n")
            for i, citation in enumerate(citations, 1):
                markdown.append(f"{i}. [{citation['title']}]({citation['url']})\n")
        
        return "".join(markdown)
                
    def cleanup(self):
        """Clean up resources - no longer deletes the agent"""
        try:
            # Stop the periodic save thread
            if hasattr(self, 'keep_saving'):
                self.keep_saving = False
                if hasattr(self, 'save_thread'):
                    self.save_thread.join(timeout=2.0)  # Give it 2 seconds to finish
                
            # Save thread cache before shutting down
            if hasattr(self, 'thread_cache'):
                self._save_thread_cache()
                print("Thread cache saved during cleanup")
                
            # Note: We no longer delete the agent since we want to reuse it
            # We just clean up the clients
            if hasattr(self, 'agents_client'):
                self.project_client.agents.__exit__(None, None, None)
                
            if hasattr(self, 'project_client'):
                self.project_client.__exit__(None, None, None)
                
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.cleanup()
        except Exception as e:
            # Silently ignore errors during destruction
            pass


# Singleton instance
deep_research_agent = DeepResearchChatAgent()

# Async function to run a chat session
def save_response_locally(prompt: str, result: Dict[str, Any], session_id: str) -> str:
    """Save the response to a local file for review"""
    try:
        # Create a responses directory if it doesn't exist
        responses_dir = os.path.join(os.getcwd(), "responses")
        os.makedirs(responses_dir, exist_ok=True)
        
        # Create a timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"response_{session_id}_{timestamp}.json"
        filepath = os.path.join(responses_dir, filename)
        
        # Create the response object with metadata
        response_data = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "prompt": prompt,
            "response": result
        }
        
        # Write the response to a JSON file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
            
        print(f"Response saved locally: {filepath}")
        return filepath
    except Exception as e:
        print(f"Error saving response locally: {str(e)}")
        return ""

async def run_chat(prompt: str, session_id: Optional[str] = None, timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
    """Run a chat session with the Deep Research Agent
    
    Args:
        prompt: The user's message/question
        session_id: Optional session ID (defaults to "default")
        timeout_seconds: Optional timeout in seconds. For complex research, consider 300-600 seconds
    """
    try:
        # Use a default session ID if none is provided
        if not session_id:
            session_id = "default"
            
        result = await deep_research_agent.send_message(session_id, prompt, timeout_seconds)
        
        # Save the response locally for review
        save_response_locally(prompt, result, session_id)
        
        return result
    except Exception as e:
        print(f"Error in run_chat: {str(e)}")
        # Return a structured error response
        error_markdown = "# Research Result\n\n"
        error_markdown += f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        error_markdown += f"**Question:** {prompt}\n"
        error_markdown += "**Status:** error\n\n"
        error_markdown += f"**Error:** {str(e)}\n\n"
        error_markdown += "## Response\n"
        error_markdown += "I apologize, but I encountered an error processing your request. Please try again."
        
        error_response = {
            "answer": "I apologize, but I encountered an error processing your request. Please try again.",
            "markdown": error_markdown,
            "citations": [],
            "status": "error",
            "error": str(e),
            "metrics": {
                "total_time": 0,
                "time_to_first_token": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0
            }
        }
        
        # Save the error response locally as well
        save_response_locally(prompt, error_response, session_id or "default")
        
        return error_response

# Async function to get conversation history
async def get_history(session_id: Optional[str] = None) -> List[Dict]:
    """Get conversation history for a session"""
    try:
        if not session_id:
            session_id = "default"
            
        return await deep_research_agent.get_conversation_history(session_id)
    except Exception as e:
        print(f"Error in get_history: {str(e)}")
        return []

# Async function to reset a session
async def reset_session(session_id: Optional[str] = None) -> bool:
    """Reset a conversation session"""
    try:
        if not session_id:
            session_id = "default"
            
        return await deep_research_agent.reset_session(session_id)
    except Exception as e:
        print(f"Error in reset_session: {str(e)}")
        return False
        
# Function to list saved responses
def list_saved_responses(session_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """List saved responses, optionally filtered by session_id"""
    try:
        responses_dir = os.path.join(os.getcwd(), "responses")
        if not os.path.exists(responses_dir):
            return []
            
        # Get all response files
        response_files = [f for f in os.listdir(responses_dir) if f.startswith("response_") and f.endswith(".json")]
        
        # Filter by session_id if provided
        if session_id:
            response_files = [f for f in response_files if f"_{session_id}_" in f]
            
        # Sort by timestamp (newest first)
        response_files.sort(reverse=True)
        
        # Limit the number of responses
        response_files = response_files[:limit]
        
        # Load each response file
        responses = []
        for filename in response_files:
            try:
                filepath = os.path.join(responses_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    response_data = json.load(f)
                    # Add the filename for reference
                    response_data["filepath"] = filepath
                    responses.append(response_data)
            except Exception as e:
                print(f"Error loading response file {filename}: {str(e)}")
                
        return responses
    except Exception as e:
        print(f"Error listing saved responses: {str(e)}")
        return []

# Function to get a specific saved response by filename
def get_saved_response(filename: str) -> Optional[Dict[str, Any]]:
    """Get a specific saved response by filename"""
    try:
        responses_dir = os.path.join(os.getcwd(), "responses")
        filepath = os.path.join(responses_dir, filename)
        
        if not os.path.exists(filepath):
            return None
            
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error getting saved response {filename}: {str(e)}")
        return None

# Add a health check function to verify the agent is working properly
async def check_health() -> Dict[str, Any]:
    """Check if the deep research agent is healthy and can access Azure services"""
    try:
        # Check if we can access the agent
        if deep_research_agent and deep_research_agent.agent:
            # Try to create a test thread to verify Azure connectivity
            test_thread = deep_research_agent.agents_client.threads.create()
            
            # If we got here, we can access Azure services
            # Delete the test thread - we don't need it
            deep_research_agent.agents_client.threads.delete(test_thread.id)
            
            return {
                "status": "healthy",
                "agent_id": deep_research_agent.agent.id,
                "thread_cache_size": len(deep_research_agent.thread_cache),
                "azure_services_accessible": True
            }
        else:
            return {
                "status": "degraded",
                "error": "Deep research agent not initialized properly",
                "azure_services_accessible": False
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "azure_services_accessible": False
        }
