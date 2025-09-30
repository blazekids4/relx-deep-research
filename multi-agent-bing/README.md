# Multi-Agent Product Analysis Pipeline

This folder contains a small pipeline that runs a multi-agent Bing-based retrieval stage and a product analysis (report generation) stage. The three main scripts work together to produce per-product reports (JSON + Markdown) and a summary index:

- `run_product_analysis_pipeline.py` — Orchestrator that runs the full pipeline: multi-agent search, then the Product Attributes Analyst; supports dry-run and skipping the search stage.
- `agents_multi_w_bing.py` — Multi-agent Bing retrieval stage. Creates role-specific agents (all_attributes, ingredients, nutrition, reviews), runs searches, and saves per-role outputs in a `multi_agent_with_bing_results_*` directory.
- `agent_product_attributes_analyst.py` — Consumes the combined agent outputs and calls a Foundry model (model router) to generate consolidated product reports. Produces per-product JSON & Markdown reports and a `summary_report.md`.

This README explains how the pieces fit together, required environment variables, common run patterns, and troubleshooting tips.

## Contract (Inputs / Outputs / Success Criteria)

Inputs:

- A set of product search inputs located at `data/pet_food_search.json` (used by `agents_multi_w_bing.py`).
- Environment variables configured via a `.env` file (see `.env.example`).

Outputs:

- A `multi_agent_with_bing_results_<TIMESTAMP>/` directory containing per-role JSON/MD outputs and a `combined_agent_results.json` file.
- A `product_analysis_<TIMESTAMP>/product_analysis_reports_<TIMESTAMP>/` directory (or supplied `--output-dir`) with per-product reports and a `summary_report.md`.
- `pipeline_summary.json` under the pipeline `--output-base` directory describing durations and phase statuses.

Success criteria:

- Multi-agent stage completes and writes `combined_agent_results.json`.
- Product Attributes Analyst produces one Markdown+JSON report per product and a summary index.

## Required environment variables

Copy `.env.example` to `.env` and fill in your values. Key variables used across the flow include:

- `PROJECT_ENDPOINT_MULTI_AGENT_EXPERIMENTS` — Foundry project endpoint used by the agents stage
- `MODEL_DEPLOYMENT_NAME` — model deployment used by agents (for agent creation / chat)
- `MODEL_ROUTER_ENDPOINT` — Foundry endpoint used by the Product Attributes Analyst
- `MODEL_ROUTER_DEPLOYMENT` — model/router deployment name used by the analyst
- `APPLICATIONINSIGHTS_CONNECTION_STRING` — optional; used for telemetry if present
- `BING_GROUNDED_CONNECTION_NAME` — connection name for the regular Bing Grounding tool
- Role-specific Bing connection variables (preferred):
  - `BING_INGREDIENTS_CONNECTION_NAME`, `BING_INGREDIENTS_INSTANCE_NAME`
  - `BING_NUTRITION_CONNECTION_NAME`, `BING_NUTRITION_INSTANCE_NAME`
  - `BING_REVIEWS_CONNECTION_NAME`, `BING_REVIEWS_INSTANCE_NAME` (optional)
- `BING_CUSTOM_CONNECTION_NAME`, `BING_CUSTOM_INSTANCE_NAME` — default fallback for custom Bing searches
- `BATCH_TIMEOUT_SECONDS` — optional, default `120`

The repository includes a `.env.example` in this folder (or at the root) you can use as a template.

## Typical workflows / examples (PowerShell)

1. Dry run to verify what would run (no network calls):

```powershell
# From this folder
python run_product_analysis_pipeline.py --dry-run
```

1. Run full pipeline (search + analysis):

```powershell
python run_product_analysis_pipeline.py --output-base "product_analysis_$(Get-Date -Format yyyyMMdd_HHmmss)"
```

1. Run only the Product Attributes Analyst using an existing search results directory (skip search):

```powershell
# Provide the search results folder created by the multi-agent stage
python run_product_analysis_pipeline.py --search-dir "multi_agent_with_bing_results_20250917_092638" --output-base "product_analysis_$(Get-Date -Format yyyyMMdd_HHmmss)"
```

1. Run the multi-agent component by itself (useful for development):

```powershell
python agents_multi_w_bing.py
```

1. Run the analyst by itself (consumes an existing combined results dir):

```powershell
python agent_product_attributes_analyst.py --input-dir "multi_agent_with_bing_results_20250917_092638" --output-dir "product_analysis_reports"
```

## Testing & quick checks

- Use `test_agents_connection.py` (located in the repository root `multi-agent` folder) to verify:
  - Foundry/OpenAI model connectivity
  - Bing Grounding and custom search connections
  - Basic agent creation and message exchange

- For smoke testing the analyst locally, create a small `combined_agent_results.json` with one product entry and point `--input-dir` at the containing folder.

## Telemetry and tracing

- If `APPLICATIONINSIGHTS_CONNECTION_STRING` is available and the `telemetry` helper is used, the code configures OpenTelemetry instrumentation for the Azure AI SDK and the OpenAI instrumentation. The multi-agent scripts also read `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (or `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED`) to enable message content capture for traces.

## Implementation notes / how the pieces interact

1. `run_product_analysis_pipeline.py` performs orchestration:
   - Validates environment and that dependent scripts/files exist.
   - Runs `agents_multi_w_bing.py` (unless `--skip-search` or `--search-dir` provided).
   - Detects the created `multi_agent_with_bing_results_*` directory (parses stdout or finds the most recent directory).
   - Runs `agent_product_attributes_analyst.py` with the `--input-dir` set to the search results directory and an `--output-dir` for reports.
   - Writes a `pipeline_summary.json` with metrics.

2. `agents_multi_w_bing.py`:
   - Creates per-role agents (or reuses existing via role config files), calls / runs each agent for each product in the `data/*.json` input, captures responses, extracts attributes and citations, and writes per-role JSON/MD plus a `combined_agent_results.json` for later analysis.

3. `agent_product_attributes_analyst.py`:
   - Loads `combined_agent_results.json`, builds an analysis prompt for each product that includes all role responses, calls the model router (Foundry) and saves a JSON & Markdown report per product and a `summary_report.md` for the run.

## Common problems & troubleshooting

- Missing environment variables:
  - Error messages will indicate required variables (e.g., `MODEL_ROUTER_ENDPOINT environment variable is required`). Ensure `.env` is present and loaded.

- Authentication issues with `DefaultAzureCredential()`:
  - Locally, `az login` usually helps. In CI or VM, ensure a service principal or managed identity is configured.

- Cannot find the search results directory after the agents run:
  - Check the stdout of `agents_multi_w_bing.py` for the `Results saved in` message. If that message format changed, `run_product_analysis_pipeline.py` also falls back to finding the most recent `multi_agent_with_bing_product_analysis_*` (or `multi_agent_with_bing_results_*`) directory.

- Model errors or throttling:
  - Inspect exception trace printed by the analyst or agent scripts. Reduce concurrency, add retries, or check your Azure subscription quotas.

## Development tips

- Keep a local `.env` out of source control. Commit `.env.example` only.
- When iterating on prompts, test the analyst with a single product to reduce cost and speed up feedback loop.
- Add retries and exponential backoff around Azure API calls when scaling to larger datasets.

## Files in this folder

- `run_product_analysis_pipeline.py` — orchestrator for the two-stage flow
- `agents_multi_w_bing.py` — multi-agent search stage (Bing)
- `agent_product_attributes_analyst.py` — foundry/analysis stage
- `.env.example` — example environment config (use to create `.env`)
- `data/` — input test data (e.g., `pet_food_search.json`)

## Next steps / suggestions

- Add a small `examples/combined_agent_results_sample.json` for the analyst to make testing onboarding even easier.
- Optionally add unit tests for prompt generation and attribute extraction helpers.

---

If you'd like, I can also:

- Add a minimal `combined_agent_results.json` sample into `examples/`.
- Create a top-level `README.md` that references this module and the other folders in the repository.
