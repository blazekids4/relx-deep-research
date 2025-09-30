# Batch Research Module Documentation

## Overview

The Batch Research module is a Python script designed to process multiple research questions in batch using Azure AI Services. It leverages Azure's Deep Research capabilities to find comprehensive answers to a set of questions, while tracking performance metrics and saving results in both individual and consolidated formats.

## Features

- **Batch Processing**: Process multiple research questions sequentially
- **Timeout Handling**: Configurable timeout for each question
- **Progress Monitoring**: Regular heartbeat messages during processing
- **Metrics Collection**: Track execution time, token usage, and success rates
- **Markdown Output**: Generate individual and consolidated markdown reports
- **Error Handling**: Graceful handling of failures during processing

## Dependencies

- `azure.ai.projects`: For interfacing with Azure AI Project services
- `azure.identity`: For Azure authentication
- `azure.ai.agents`: For creating and managing AI agents
- `dotenv`: For loading environment variables

## Environment Variables

The script requires the following environment variables to be set (typically in a `.env` file):

- `PROJECT_ENDPOINT_RELX_LEGAL`: Endpoint URL for the AI Project
- `BING_CONNECTED_RESOURCE_NAME`: Name of the Bing resource connection
- `DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME`: Name of the Deep Research model deployment
- `MODEL_DEPLOYMENT_NAME`: Name of the base model deployment
- `BATCH_TIMEOUT_SECONDS` (optional): Maximum time in seconds to wait for each question (default: 300)

## Functions

### `read_questions(file_path: str) -> List[str]`

Reads research questions from a JSON or CSV file.

- **Parameters**:
  - `file_path`: Path to the input file (JSON or CSV)
- **Returns**: List of question strings

### `process_batch_research(questions, agents_client, agent_id, output_base_path) -> List[Dict]`

Processes a batch of research questions and tracks metrics.

- **Parameters**:
  - `questions`: List of question strings
  - `agents_client`: Azure Agents client
  - `agent_id`: ID of the created agent
  - `output_base_path`: Directory where results will be saved
- **Returns**: List of result dictionaries containing question, status, metrics, etc.

### `save_markdown_result(result, base_path, index)`

Saves an individual research result as a markdown file.

- **Parameters**:
  - `result`: Result dictionary containing question, status, metrics, etc.
  - `base_path`: Directory where the file will be saved
  - `index`: Question index for file naming

### `save_consolidated_markdown(results, base_path)`

Saves consolidated results as a single markdown file.

- **Parameters**:
  - `results`: List of result dictionaries
  - `base_path`: Directory where the file will be saved

### `main()`

Main function that initializes the Azure clients, creates the agent, processes the questions, and handles cleanup.

## Output Format

### Individual Result Files (`research_XXX_YYYYMMDD_HHMMSS.md`)

Each individual result file includes:

- Generation timestamp
- Original question
- Processing status
- Error message (if any)
- Metrics (time to first token, total time, token usage)
- Agent's response
- References/citations (if any)

### Consolidated Results (`batch_results.md`)

The consolidated file includes:

- Generation timestamp
- Total questions processed
- Summary statistics (total time, total tokens, success rate)
- Brief summary of each individual result

## Usage

1. Set up the required environment variables in a `.env` file
2. Prepare a JSON or CSV file with questions
3. Run the script: `python batch_research.py`

## Performance Considerations

- Each question is processed in a new thread to avoid conflicts
- Questions have a configurable timeout (default: 300 seconds)
- Progress updates are logged every 10 seconds
- Token usage is tracked if available from the run object

## Error Handling

- Exceptions during question processing are caught and logged
- The script continues processing the next question after an error
- Failed questions are included in the results with error information
- Timeouts are handled by canceling the run and moving to the next question

## Data Flow

1. Load questions from input file
2. Initialize Azure clients and create agent
3. For each question:
   - Create a thread
   - Send question message
   - Start and monitor run
   - Collect response and metrics
   - Save individual result
4. Save consolidated results
5. Clean up resources (delete agent)
