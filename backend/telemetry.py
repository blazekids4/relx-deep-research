import os
import warnings
from typing import Optional
from azure.ai.projects import AIProjectClient
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# Suppress deprecation warnings
warnings.filterwarnings("ignore", message="LogRecord init with.*is deprecated", category=UserWarning)

# Enable content recording for tracing (contains chat messages)
os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"

# Get the tracer
tracer = trace.get_tracer(__name__)


def configure_tracing(project_client: AIProjectClient):
    """Configure Azure Monitor and instrumentation using project client."""
    try:
        # Get connection string from the project's Application Insights
        connection_string = project_client.telemetry.get_application_insights_connection_string()
        
        # Configure Azure Monitor with the connection string
        configure_azure_monitor(
            connection_string=connection_string,
            disable_logging=True  # This will suppress the deprecated logging warnings
        )
        
        print("Azure Monitor configured successfully")
        
    except Exception as e:
        print(f"Warning: Could not get Application Insights connection string from project: {e}")
        # Fall back to environment variable
        connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if connection_string:
            configure_azure_monitor(
                connection_string=connection_string,
                disable_logging=True
            )
            print("Azure Monitor configured using environment variable")
        else:
            print("Warning: No Application Insights connection string available. Tracing disabled.")
    
    # Instrument OpenAI and AI Agents after Azure Monitor is configured
    OpenAIInstrumentor().instrument()
    AIAgentsInstrumentor().instrument()
    print("OpenAI and AI Agents instrumentation enabled")
