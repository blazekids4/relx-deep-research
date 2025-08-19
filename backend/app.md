# Deep Research Assistant

## Overview

`app.py` is a command-line research assistant that leverages Azure AI Projects and Azure Agents to help you explore scientific and technical topics. It uses a custom DeepResearchTool powered by Bing grounding and OpenAI models, and integrates Azure Monitor with OpenTelemetry for tracing and telemetry.

## Features

- Interactive chat interface for research queries
- Automatic polling and display of AI agent responses
- Auto-save research summaries as Markdown files with metadata and references
- Manual save command to persist the last response
- Comprehensive tracing with Azure Monitor, OpenAI, and AI Agents instrumentation

## Prerequisites

- Python 3.8 or later
- An Azure subscription with the following resources:
  - Azure AI Projects resource
  - Azure AI agent endpoint (PROJECT_ENDPOINT)
  - Azure Cognitive Search or Bing grounding resource (BING_RESOURCE_NAME)
  - Model deployments for chat (MODEL_DEPLOYMENT_NAME) and DeepResearch (DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME)
  - Application Insights resource (optional for telemetry)

## Installation

1. Clone this repository:

   ```powershell
   git clone https://github.com/blazekids4/relx-deep-research.git
   cd relx-deep-research
   ```

2. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

## Configuration

Create a `.env` file in the project root with the following variables:

```ini
PROJECT_ENDPOINT="<your-ai-project-endpoint>"
BING_RESOURCE_NAME="<your-bing-connection-name>"
MODEL_DEPLOYMENT_NAME="<your-chat-model-deployment>"
DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME="<your-deep-research-model-deployment>"
APPLICATIONINSIGHTS_CONNECTION_STRING="<optional-connection-string>"
```

## Usage

Run the application:

```powershell
python app.py
```

When prompted, type your research questions. Commands:

- `exit`, `quit`, or `bye` to end the session
- `save` to manually save the last agent response as a Markdown summary

All AI responses are auto-saved to files named `research_<timestamp>.md` by default.

## Output

- **Console**: Real-time agent responses and status messages
- **Markdown files**: Research summaries with metadata, content, and references

## Troubleshooting

- Ensure all required environment variables are set in `.env`
- Verify Azure resources are deployed and accessible
- Check Application Insights for telemetry logs

## License

This project is licensed under the MIT License.
