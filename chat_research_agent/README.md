# Deep Research Agent

A Python-based agent for conducting deep research on complex questions using Azure AI Services. Supports both batch processing and interactive research sessions.

## Features

- **Dual Mode Operation**: Run in batch or interactive mode to suit your research needs
- **Azure AI Integration**: Leverages Azure AI Agents and Deep Research capabilities
- **Advanced Research**: Uses Azure's LLM capabilities with web grounding for accurate research
- **Comprehensive Metrics**: Tracks time, token usage, and success rates
- **Resume Capability**: Continue interrupted batch sessions from where they left off
- **Citation Tracking**: Automatically collects and formats reference citations
- **Progress Reporting**: Real-time progress updates with time estimates
- **Interactive Dialogue**: Multi-turn conversations with clarification handling

## Prerequisites

- Python 3.8+
- Azure subscription with access to:
  - Azure AI Projects (formerly Azure OpenAI Service)
  - Azure AI Studio with Deep Research capabilities
  - Bing Search configured as a connection

## Setup

1. Clone this repository:

```bash
git clone https://github.com/blazekids4/relx-deep-research.git
cd relx-deep-research
```

2. Install required packages:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with the following variables:

```plaintext
PROJECT_ENDPOINT_RELX_LEGAL=<Your Azure AI Project Endpoint>
BING_CONNECTED_RESOURCE_NAME=<Name of your Bing Search connected resource>
DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME=<Name of your Deep Research model deployment>
MODEL_DEPLOYMENT_NAME=<Name of your base model deployment>

# Optional timeout settings (in seconds)
BATCH_TIMEOUT_SECONDS=300
INTERACTIVE_SESSION_TIMEOUT=1800
INTERACTIVE_QUESTION_TIMEOUT=300
```

## Usage

### Batch Mode

Process multiple research questions from a file:

```bash
python chat_research_agent/chat_research.py --mode batch --file data/your_questions.json
```

To resume an interrupted batch process:

```bash
python chat_research_agent/chat_research.py --mode batch --file data/your_questions.json --resume
```

### Interactive Mode

Start an interactive research session with a question:

```bash
python chat_research_agent/chat_research.py --mode interactive --question "Your research question here"
```

Or start without a predefined question (you'll be prompted):

```bash
python chat_research_agent/chat_research.py --mode interactive
```

## Input File Formats

The script accepts questions in either JSON or CSV format:

### JSON Format

```json
[
  "What are the latest advances in quantum computing?",
  "How does climate change affect global food security?",
  "What is the current state of AI regulation worldwide?"
]
```

### CSV Format

```csv
What are the latest advances in quantum computing?
How does climate change affect global food security?
What is the current state of AI regulation worldwide?
```

## Output

Results are saved in a timestamped directory (`research_results_YYYYMMDD_HHMMSS/`):

### Batch Mode Outputs

- Individual markdown files for each question (`research_001_YYYYMMDD_HHMMSS.md`)
- Consolidated results in markdown (`batch_results.md`)
- JSON results file for resuming interrupted sessions (`batch_results.json`)

### Interactive Mode Outputs

- Conversation transcript in markdown (`interactive_session_YYYYMMDD_HHMMSS.md`)
- JSON record of the conversation (`interactive_session_YYYYMMDD_HHMMSS.json`)

## Metrics Collected

For each question/session, the following metrics are tracked:

- Time to first token (responsiveness)
- Total processing time
- Token usage (input, output, total)
- Success/failure status
- Citations and references

## Advanced Features

### Clarification Detection

In interactive mode, the agent detects when it needs more information using pattern matching. You can customize detection patterns in the `is_clarification_needed()` function.

### Token Usage Tracking

The script captures and reports token usage metrics when available from the AI service, helping you monitor usage and costs.

### Error Handling

Comprehensive error handling with descriptive messages for:

- Environment validation
- File loading issues
- API connection problems
- Session timeouts

## Project Structure

```plaintext
relx-deep-research/
├── batch_research-agents/      # Batch processing scripts
├── chat_research_agent/        # Interactive research scripts
│   ├── chat_research.py        # Main script for this README
│   └── scripts-with-tracing/   # Versions with OpenTelemetry tracing
├── data/                       # Sample question files
└── README.md                   # This file
```

## Troubleshooting

- **Connection issues**: Ensure your Azure credentials are valid and have access to the required resources
- **Timeout errors**: Adjust timeout settings in `.env` file for complex questions
- **File not found**: Check file paths and ensure input files exist
- **Missing environment variables**: Verify all required variables are set in `.env`

## License

[MIT License](LICENSE)

## Acknowledgements

This project uses Azure AI Services and the Azure Deep Research capabilities to provide enhanced research capabilities.
