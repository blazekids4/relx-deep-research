# RELX Deep Research

A comprehensive Python-based toolkit for conducting in-depth research using Azure AI services. This project provides tools for both batch processing of research questions and interactive research sessions, leveraging Azure's advanced AI and Deep Research capabilities.

## Project Overview

This toolkit is designed to help researchers, analysts, and knowledge workers efficiently find accurate answers to complex questions using the power of Azure's AI services with web grounding. The system leverages Large Language Models (LLMs) enhanced with citation capabilities to provide well-researched answers with proper references.

## Key Components

The repository contains three main components:

### 1. Batch Research Agent

Located in the `batch_research-agents` directory, this component processes multiple research questions in batch mode from a file. It's ideal for:

- Processing large sets of research questions
- Gathering metrics across multiple research queries
- Running automated research without user interaction
- Creating comprehensive research reports

[Learn more about Batch Research](batch_research-agents/batch/README.md)

### 2. Chat Research Agent

Located in the `chat_research_agent` directory, this component provides an interactive research experience with multi-turn conversations. It's designed for:

- In-depth exploration of complex topics
- Clarification and follow-up questions
- Real-time research with human guidance
- Interactive learning and discovery

[Learn more about Chat Research](chat_research_agent/README.md)

### 3. Multi-Agent Bing Integration

Located in the `multi-agent-bing` directory, this component demonstrates how multiple specialized agents can work together with Bing search integration. It's particularly useful for:

- Coordinated multi-agent research workflows
- Product analysis and attribute extraction
- Search-enhanced knowledge retrieval
- Pipeline-based processing of complex research tasks

## Features Common to Both Components

- **Azure AI Integration**: Utilizes Azure AI Agents and Deep Research capabilities
- **Citation Tracking**: Automatically collects and formats reference citations
- **Metrics Collection**: Tracks processing time, token usage, and success rates
- **Markdown Output**: Generates well-formatted research reports
- **JSON Data**: Stores structured data for further analysis

## Prerequisites

- Python 3.8+
- Azure subscription with access to:
  - Azure AI Projects (formerly Azure OpenAI Service)
  - Azure AI Studio with Deep Research capabilities
  - Bing Search configured as a connection

## Getting Started

1. Clone this repository:

   ```bash
   git clone https://github.com/blazekids4/relx-deep-research.git
   cd relx-deep-research
   ```

1. Install required packages:

   ```bash
   pip install -r requirements.txt
   ```

1. Configure your environment:
   - Create a `.env` file based on the template in each component's README
   - Set up your Azure credentials and endpoints

1. Choose your research mode:
   - For batch processing, see [Batch Research README](batch_research-agents/batch/README.md)
   - For interactive sessions, see [Chat Research README](chat_research_agent/README.md)

## Sample Data

The `data` directory contains sample question sets in various formats:

- JSON files with sample research questions
- CSV files with sample research questions
- Excel files with additional metadata

These can be used to test the system or as templates for your own research questions.

## Advanced Usage

### OpenTelemetry Integration

Both components have versions with OpenTelemetry tracing in their respective `scripts-with-tracing` directories. These versions provide:

- Distributed tracing capabilities
- Performance monitoring
- Integration with observability platforms

### Customization Options

The toolkit offers several customization options:

- Custom timeout settings for different research phases
- Adjustable clarification detection patterns
- Configurable output formats and paths
- Error handling strategies

## Project Structure

```plaintext
relx-deep-research/
├── batch_research-agents/          # Batch processing module
│   ├── batch/                      # Main batch implementation
│   │   ├── batch_research.py       # Core batch processing script
│   │   └── README.md               # Batch module documentation
│   ├── scripts-with-tracing/       # Version with telemetry
│   │   ├── batch_research_with_tracing.py
│   │   └── telemetry.py            # Telemetry implementation
│   └── test_batch_research.py      # Tests for batch module
│
├── chat_research_agent/            # Interactive research module
│   ├── aoai_deep_research.py       # Azure OpenAI implementation
│   ├── chat_research.py            # Core interactive script
│   ├── README.md                   # Chat module documentation
│   ├── scripts-with-tracing/       # Version with telemetry
│   │   ├── aoai_deep_research_with_tracing.py
│   │   ├── chat_research_with_tracing.py
│   │   └── telemetry.py            # Telemetry implementation
│   └── __pycache__/                # Python cache files
│
├── multi-agent-bing/               # Multi-agent with Bing integration
│   ├── agent_product_attributes_analyst.py  # Product analysis agent
│   ├── agents_multi_w_bing.py      # Multi-agent coordination
│   ├── README.md                   # Multi-agent documentation
│   └── run_product_analysis_pipeline.py     # Pipeline execution script
│
├── data/                           # Sample data files
│   ├── Sample Questions - Deep Research.csv
│   ├── Sample Questions - Deep Research.json
│   ├── Sample Questions - Deep Research.xlsx
│   ├── SampleQuestionsDeepResearch_1.json
│   └── SampleQuestionsDeepResearch_2.json
│
└── README.md                       # This file
```

## Troubleshooting

### Common Issues

- **Azure Authentication**: Ensure your credentials are correctly configured
- **Missing Dependencies**: Verify all required packages are installed
- **Configuration Errors**: Check your `.env` file for missing variables
- **Access Rights**: Verify your Azure account has the necessary permissions

### Getting Help

If you encounter issues:

1. Check the README in the specific component directory
2. Examine the error output for specific error messages
3. Verify your Azure resource configurations
4. Check for timeout settings if queries are complex

## Contributing

Contributions are welcome! To contribute:

1. Fork the repository
2. Create a feature branch
3. Add your changes
4. Submit a pull request

Please include tests and update documentation as needed.

## License

[MIT License](LICENSE)

## Acknowledgements

- This project uses Azure AI Services and the Azure Deep Research capabilities
- Built with Python and the Azure SDK for AI
