# Automated B2B Lead Generation Pipeline (Google GenAI)

A modular, production-ready Python pipeline for automated B2B lead discovery and enrichment powered by **Google GenAI SDK (`google-genai`)** with `gemini-1.5-flash` structured outputs.

## Features

- **Automated Website Discovery**: DuckDuckGo search integration with smart domain filters (skipping directory aggregators like LinkedIn, Wikipedia, Crunchbase, etc.).
- **Async Web Scraping**: High-performance `httpx` async fetcher with user-agent headers, HTML sanitization, and fallback 1-hop crawling to `/contact` / `/about` pages.
- **Heuristic Email Extraction**: Discovers `mailto:` links and email regex patterns in DOM before passing high-signal context to the LLM.
- **Google GenAI Structured Output**: Uses `google-genai` with `client.models.generate_content` and strict Pydantic schema validation (`CompanyExtractionResult`) to return 1-sentence company summaries and verified contact emails.
- **State Checkpointing & Resume**: Maintains `.checkpoint.json` so large batch runs can be resumed immediately without re-processing.
- **Rich CLI**: Beautiful terminal UI with progress bars, status badges, and summary tables.

## Quick Start

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file or export your API key:

```bash
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY
```

### 3. Run Pipeline

Run the pipeline against the included sample CSV:

```bash
python main.py run --input data/sample_companies.csv --output data/output/enriched_leads.csv
```

### 4. CLI Options

```bash
python main.py run --help

Options:
  -i, --input PATH         Path to input CSV file [default: data/sample_companies.csv]
  -o, --output PATH        Path to output CSV [default: data/output/enriched_leads.csv]
  -m, --model TEXT         Gemini model name [default: gemini-1.5-flash]
  -c, --concurrency INT    Max concurrent scraping and API workers [default: 3]
  -n, --limit INT          Limit number of records to process
  --no-checkpoint          Disable caching/checkpointing
  --api-key TEXT           Pass Gemini API key directly
```
