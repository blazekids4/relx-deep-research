import logging
import os
from typing import Optional
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress Azure SDK HTTP logging
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)
logging.getLogger('azure.monitor.opentelemetry.exporter.export._base').setLevel(logging.WARNING)
logging.getLogger('azure').setLevel(logging.WARNING)

# Create tracer provider
tracer_provider = TracerProvider()

# Remove console exporter for cleaner output
# tracer_provider.add_span_processor(
#     BatchSpanProcessor(ConsoleSpanExporter())
# )

# Set as global tracer provider
trace.set_tracer_provider(tracer_provider)

# Create a tracer
tracer = trace.get_tracer("deep-research-tracer")

def configure_tracing(client=None):
    """Configure tracing for the application."""
    try:
        # Check if Application Insights connection string is available
        connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        
        if connection_string:
            # Configure Azure Monitor (Application Insights)
            configure_azure_monitor(
                connection_string=connection_string,
                enable_diagnostics=True,
                log_level=logging.WARNING,  # Changed from INFO to WARNING
            )
            logger.info("Azure Monitor telemetry configured successfully")
        else:
            logger.warning("No Application Insights connection string found, using local tracing only")
            
        # If a client is provided, attach the OpenTelemetry span policy to its HTTP pipeline
        if client:
            try:
                from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpanPolicy
                # Many Azure SDK clients wrap an inner _client with pipeline
                inner = getattr(client, '_client', None)
                if inner and hasattr(inner, '_pipeline'):
                    # Insert the tracing policy at the start of pipeline policies
                    inner._pipeline._impl_policies.insert(0, OpenTelemetrySpanPolicy())
                    logger.info(f"Attached OpenTelemetrySpanPolicy to {type(client).__name__} pipeline")
                else:
                    logger.warning(f"Unable to attach tracing policy to {type(client).__name__}, inner client pipeline not found")
            except Exception as e:
                logger.error(f"Failed to attach tracing policy to client: {str(e)}")
            
    except Exception as e:
        logger.error(f"Failed to configure telemetry: {str(e)}")