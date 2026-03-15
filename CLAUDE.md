# CLAUDE.md — Invoice Extractor Project Context

<!-- IMPORTANT: Update this file whenever you make structural changes to the codebase
     (new files, renamed modules, changed APIs, new dependencies, modified workflows).
     This file is read by Claude Code to understand the project context. -->

## What this project does

Multi-provider AI Vision tool that extracts structured purchase invoice data from PDFs/images
into ERPNext-ready JSON. Supports Anthropic, OpenAI, Google Gemini, and local Ollama models.

## Architecture

Two interfaces share the same extraction pipeline:

- **CLI** (`python -m src.main`) — Batch processing from `input/` folder, writes JSON to `output/`
- **FastAPI API** (`python -m src.api`) — REST service on port 8000 with async background extraction

### Module Map

```
src/
├── config.py        — Loads .env (provider, model, keys, Ollama URL)
├── models.py        — Pydantic v2 models matching ERPNext Purchase Invoice schema
├── extractor.py     — AI extraction logic for all 4 providers + PDF→image + JSON parsing
├── helpers.py       — Shared pipeline: run_extraction_pipeline(), merge_with_confidence(), etc.
├── validation.py    — 16 categories of anti-hallucination quality checks
├── benchmark.py     — ExtractionMetrics dataclass, CSV logging, cost estimation
├── main.py          — CLI entry point (batch file processing)
└── api.py           — FastAPI service (upload → async extract → poll/webhook)
```

### Dependency Flow

```
main.py ──┐
           ├──→ helpers.py (run_extraction_pipeline) ──→ extractor.py ──→ config.py
api.py  ──┘                                          ──→ models.py
                                                     ──→ validation.py
                                                     ──→ benchmark.py
```

### Key Design Decisions

- **Shared pipeline**: `run_extraction_pipeline()` in `helpers.py` is the single source of truth
  for extract → merge → validate → metrics. Both CLI and API call this function.
- **Per-field confidence**: Output JSON uses `{"value": X, "confidence_score": Y}` format per field.
- **Duplicate detection (API)**: SHA-256 hash of uploaded file content prevents re-extraction.
  Failed extractions are automatically retried on re-upload.
- **Ollama per-model context**: `_OLLAMA_NUM_CTX` dict in `extractor.py` sizes context windows
  per model based on 64GB VRAM budget (model weights + KV cache).

## Directory Layout

```
input/       — Source invoice PDFs/images (gitignored)
output/      — Extracted JSON results (gitignored)
uploads/     — Temporary API uploads, cleaned after extraction (gitignored)
logs/        — benchmark.csv with extraction metrics (gitignored)
prompt.txt   — System prompt sent to AI models
```

## How to Run

```bash
# Install
pip install -e ".[all]"

# CLI — single file
python -m src.main -f "input/Invoice.pdf"

# CLI — entire folder
python -m src.main

# API server
python -m src.api
# Then: curl -X POST http://localhost:8000/extract -F "file=@input/Invoice.pdf"
```

## Configuration

All config is in `.env` (see `.env.example`). Key variables:

| Variable | Purpose |
|----------|---------|
| `AI_PROVIDER` | `ollama`, `anthropic`, `openai`, or `google` |
| `AI_MODEL` | Model name (e.g., `qwen3-vl:32b`, `gemini-3-flash-preview`) |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google Gemini API key |

You can override provider/model per-run with env vars:
```bash
AI_PROVIDER=google AI_MODEL=gemini-3-flash-preview python -m src.main -f "input/test.pdf"
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/extract` | Upload invoice, returns `txn_id` immediately |
| GET | `/status/{txn_id}` | Poll extraction status |
| GET | `/result/{txn_id}` | Get full extraction result (when completed) |
| GET | `/transactions` | List all transactions |
| GET | `/docs` | Swagger UI |

## Git Workflow

- **`develop`** — Base branch, pull from here
- **`navin-dev`** — Working branch, push changes here
- Always: `git pull origin develop` then push to `navin-dev`

## Supported Providers & Models

| Provider | Models | Notes |
|----------|--------|-------|
| Ollama | `qwen3-vl:32b`, `qwen2.5vl:32b`, `qwen2.5vl:7b`, `gemma3:27b` | Free, local, 64GB RAM server |
| Google | `gemini-3-flash-preview`, `gemini-2.5-pro` | Fast, cheap |
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6` | High quality |
| OpenAI | `gpt-5.4`, `gpt-5`, `gpt-4o` | |

## Coding Conventions

- Python 3.10+, Pydantic v2
- Type hints on all function signatures
- Provider-specific SDK imports are lazy (inside functions) to avoid requiring all SDKs
- `httpx` for Ollama native API calls (not openai-compat)
- Timeouts: `httpx.Timeout(connect=120, read=900, write=120, pool=60)` for large Ollama models
- Validation warnings use `~` prefix, errors use `!` prefix in CLI output
- Cost estimation uses `_PRICING` dict in `benchmark.py` — update when adding new models
