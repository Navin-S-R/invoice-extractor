# Invoice Extractor

A multi-provider AI vision benchmarking tool that extracts structured purchase invoice data from PDFs and images into ERPNext-ready JSON with per-field confidence scores. Compare extraction quality, speed, and cost across Anthropic, OpenAI, Google, and Ollama (local) models — no OCR setup needed.

---

## What It Does

1. **Reads** invoice files (PDF, PNG, JPG, WebP) from an `input/` folder
2. **Sends** each page as an image to an AI vision model with a structured extraction prompt
3. **Parses** the AI response into a validated Pydantic model (ERPNext Purchase Invoice schema)
4. **Scores** every extracted field with a confidence score (0-100) based on visual clarity
5. **Validates** the extraction against quality checks catching common AI hallucinations
6. **Writes** JSON to `output/` with per-field `{"value": X, "confidence_score": Y}` format
7. **Logs** benchmark metrics (latency, tokens, cost, quality, confidence) to `logs/benchmark.csv`
8. **Prints** a run summary with per-file breakdown table

---

## Quick Start

### Prerequisites

- Python 3.10+
- An API key from at least one cloud provider ([Anthropic](https://console.anthropic.com/settings/keys) | [OpenAI](https://platform.openai.com/api-keys) | [Google](https://aistudio.google.com/apikey)), **or** a running [Ollama](https://ollama.com/) instance with a vision model

### 1. Clone & setup environment

```bash
cd "Claude Trails/invoice-extractor"

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows
```

### 2. Install dependencies

```bash
# Core + all cloud provider SDKs
pip install ".[all]"
```

Or install only what you need:

```bash
pip install .                    # Core only (Ollama needs no extra SDK)
pip install ".[anthropic]"       # Anthropic only
pip install ".[openai]"          # OpenAI only
pip install ".[google]"          # Google only
```

This installs everything defined in `pyproject.toml` — PyMuPDF, Pydantic, Pillow, python-dotenv, and your chosen provider SDK. Ollama uses HTTP directly (`httpx`), so `pip install .` is enough.

### 3. Configure your provider

```bash
cp .env.example .env
```

Edit `.env` for your preferred provider:

```env
# --- Cloud provider (pick one) ---
AI_PROVIDER=anthropic
AI_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx

# --- OR local Ollama (free, no API key needed) ---
AI_PROVIDER=ollama
AI_MODEL=qwen3-vl:32b
OLLAMA_BASE_URL=http://localhost:11434
```

### 4. Run

```bash
# Drop invoices into input/ folder, then:
python -m src.main
```

That's it. JSON output appears in `output/`, metrics in `logs/benchmark.csv`.

---

## Supported Providers & Models

| Provider  | Recommended                              | Also Supported                                              |
| --------- | ---------------------------------------- | ----------------------------------------------------------- |
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6`   | `claude-haiku-4-5`                                          |
| OpenAI    | `gpt-5.4`, `gpt-5`                      | `gpt-5.2`, `gpt-4o`, `gpt-4.1`, `gpt-4.1-mini`            |
| Google    | `gemini-3-flash-preview`, `gemini-3.1-pro-preview` | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash` |
| Ollama    | `qwen3-vl:32b`, `gemma3:27b`             | `qwen2.5vl:32b`, `qwen2.5vl:7b`, any vision-capable model  |

### Cost Estimates (per 1M tokens)

| Model                    | Input  | Output  |
| ------------------------ | ------ | ------- |
| `claude-sonnet-4-6`      | $3.00  | $15.00  |
| `claude-opus-4-6`        | $5.00  | $25.00  |
| `claude-haiku-4-5`       | $1.00  | $5.00   |
| `gpt-5.4`                | $2.50  | $20.00  |
| `gpt-5`                  | $0.625 | $5.00   |
| `gpt-4o`                 | $2.50  | $10.00  |
| `gemini-3-flash-preview` | $0.50  | $3.00   |
| `gemini-2.5-pro`         | $1.25  | $10.00  |
| `gemini-2.5-flash`       | $0.15  | $0.60   |
| Ollama models            | Free   | Free    |

---

## Usage

### Add invoices & run

```bash
# Place files in input/
cp ~/invoices/*.pdf input/

# Run with default provider from .env
python -m src.main

# Or override provider/model inline
AI_PROVIDER=openai AI_MODEL=gpt-5.4 python -m src.main

# Run with local Ollama
AI_PROVIDER=ollama AI_MODEL=qwen3-vl:32b python -m src.main

# Custom input/output folders
python -m src.main /path/to/invoices /path/to/output
```

**Supported formats:** PDF, PNG, JPG, JPEG, WebP

### Sample terminal output

```
Provider: anthropic | Model: claude-sonnet-4-6
Found 3 file(s) in input

[1/3] Processing: invoice-001.pdf... OK -> invoice-001.json (2.3s, 4821 tokens, $0.0082, quality 92%, confidence 94%)
    ~ total matches sum of line items: got 4500.0, expected 4520.00 (diff 0.4%)
[2/3] Processing: receipt.png... OK -> receipt.json (1.9s, 3203 tokens, $0.0054, quality 100%, confidence 97%)
[3/3] Processing: invoice-002.pdf... FAILED: No API key set for provider 'anthropic'

============================================================
BENCHMARK SUMMARY
============================================================
Provider: anthropic | Model: claude-sonnet-4-6
Files: 2 succeeded, 1 failed
Total time: 4.7s | Avg latency: 2.1s
Tokens: 2,541 input + 509 output = 3,050 total
Estimated cost: $0.0136
Avg items extracted: 3.5
Avg field fill rate: 82% (9/11)
Avg validation score: 96%
Avg confidence score: 95%

File                           Status   Time    Tokens     Cost  Quality  Conf
--------------------------------------------------------------------------------
invoice-001.pdf                OK        2.3s    4,821  $ 0.0082    92%   94%
receipt.png                    OK        1.9s    3,203  $ 0.0054   100%   97%
invoice-002.pdf                FAIL        -        -        -       -     -
  -> No API key set for provider 'anthropic'

Log: logs/benchmark.csv
============================================================
```

---

## Output Format

Every field in the output JSON includes a confidence score based on visual clarity of the text on the invoice:

```json
{
  "supplier": {"value": "ABC Suppliers Ltd", "confidence_score": 98},
  "posting_date": {"value": "2026-03-10", "confidence_score": 95},
  "currency": {"value": "INR", "confidence_score": 97},
  "items": [
    {
      "item_name": {"value": "Widget A", "confidence_score": 96},
      "qty": {"value": 10, "confidence_score": 98},
      "rate": {"value": 250.00, "confidence_score": 95},
      "amount": {"value": 2500.00, "confidence_score": 94},
      "discount_percentage": {"value": 10.0, "confidence_score": 90},
      "discount_amount": {"value": 250.00, "confidence_score": 90},
      "net_amount": {"value": 2250.00, "confidence_score": 88},
      "tax_rate": {"value": 18.0, "confidence_score": 92},
      "tax_amount": {"value": 405.00, "confidence_score": 91},
      "batch_no": {"value": "LOT-2026-001", "confidence_score": 85},
      "hsn_sac": {"value": "8479", "confidence_score": 93}
    }
  ],
  "taxes": [
    {
      "description": {"value": "CGST 9%", "confidence_score": 97},
      "rate": {"value": 9.0, "confidence_score": 96},
      "tax_amount": {"value": 202.50, "confidence_score": 94}
    }
  ],
  "total": {"value": 2250.00, "confidence_score": 96},
  "grand_total": {"value": 2655.00, "confidence_score": 97},
  "supplier_address": {
    "address_line1": {"value": "123 Industrial Area", "confidence_score": 92},
    "city": {"value": "Mumbai", "confidence_score": 98},
    "state": {"value": "Maharashtra", "confidence_score": 95},
    "country": {"value": "India", "confidence_score": 99}
  }
}
```

### Confidence Score Scale

| Score   | Meaning                                                              |
| ------- | -------------------------------------------------------------------- |
| 95-100  | Crystal clear, high resolution, unambiguous                          |
| 80-94   | Readable but minor issues (slight blur, small font)                  |
| 60-79   | Partially obscured, low contrast, ambiguous characters (0/O, 1/l)   |
| 40-59   | Significantly blurred, cut off, requires inference                   |
| 1-39    | Barely legible, heavily occluded, mostly guessed                     |
| 0       | Field not found in the document                                      |

Scores are based on **visual clarity** of the source text, not logical correctness.

### Schema Fields

| Field                 | Type       | Required | Description                                    |
| --------------------- | ---------- | -------- | ---------------------------------------------- |
| `supplier`            | string     | Yes      | Official supplier/company name                 |
| `supplier_name`       | string     | No       | Display name if different                      |
| `supplier_tax_ids`    | object     | No       | GSTIN, PAN, VAT ID, generic tax ID             |
| `supplier_address`    | object     | No       | Structured address (line1, city, state, etc.)  |
| `supplier_bank`       | object     | No       | Bank details (account, IFSC, SWIFT, IBAN)      |
| `company`             | string     | No       | Buyer/our company name                         |
| `company_tax_ids`     | object     | No       | Buyer's tax identifiers                        |
| `billing_address`     | object     | No       | Bill To address                                |
| `shipping_address`    | object     | No       | Ship To address                                |
| `posting_date`        | string     | Yes      | Invoice date (YYYY-MM-DD)                      |
| `due_date`            | string     | No       | Payment due date                               |
| `bill_no`             | string     | No       | Supplier's invoice number                      |
| `bill_date`           | string     | No       | Supplier's invoice date                        |
| `currency`            | string     | No       | ISO 4217 code (INR, USD, EUR). Default: INR    |
| `items`               | array      | Yes      | Line items (see below)                         |
| `taxes`               | array      | No       | Tax/charge entries                             |
| `total`               | number     | No       | Net total before tax                           |
| `discount_amount`     | number     | No       | Invoice-level discount                         |
| `grand_total`         | number     | No       | Final amount including tax                     |

**Line Item Fields:**

| Field                 | Required | Description                                       |
| --------------------- | -------- | ------------------------------------------------- |
| `item_name`           | Yes      | Name of the item                                  |
| `description`         | No       | Item description                                  |
| `qty`                 | Yes      | Quantity                                          |
| `uom`                 | No       | Unit of measure (default: Nos)                    |
| `rate`                | Yes      | Unit price before discount                        |
| `amount`              | No       | Gross amount (qty * rate)                         |
| `discount_percentage` | No       | Discount % on this item                           |
| `discount_amount`     | No       | Discount amount on this item                      |
| `net_amount`          | No       | Amount after discount (before tax)                |
| `tax_rate`            | No       | Tax % applicable to this item                     |
| `tax_amount`          | No       | Tax amount on this item                           |
| `batch_no`            | No       | Batch or lot number                               |
| `serial_no`           | No       | Serial number                                     |
| `hsn_sac`             | No       | HSN/SAC or commodity code                         |

**Tax Fields:** `description` (required), `charge_type`, `rate`, `tax_amount`, `account_head`

---

## Benchmark & Metrics

Every run appends metrics to `logs/benchmark.csv`. Use this to compare models side-by-side.

### Metrics Collected

| Metric                | Description                                      |
| --------------------- | ------------------------------------------------ |
| `timestamp`           | UTC ISO timestamp of extraction                  |
| `file_name`           | Input file name                                  |
| `provider`            | `anthropic`, `openai`, `google`, or `ollama`     |
| `model`               | Model ID used                                    |
| `status`              | `success` or `error`                             |
| `latency_seconds`     | Wall-clock time for the API call                 |
| `input_tokens`        | Tokens consumed (input)                          |
| `output_tokens`       | Tokens consumed (output)                         |
| `total_tokens`        | Sum of input + output tokens                     |
| `estimated_cost_usd`  | Cost estimate based on published pricing         |
| `items_count`         | Number of line items extracted                   |
| `taxes_count`         | Number of tax entries extracted                  |
| `has_grand_total`     | Whether grand_total was extracted                |
| `has_supplier`        | Whether supplier name was extracted              |
| `fields_populated`    | Count of non-null fields in output               |
| `fields_total`        | Total possible fields                            |
| `validation_score`    | Quality score (0-100%) from validation checks    |
| `validation_passed`   | Number of checks passed                          |
| `validation_total`    | Total number of checks run                       |
| `validation_warnings` | Count of quality warnings (soft issues)          |
| `validation_errors`   | Semicolon-separated list of errors + warnings    |
| `avg_confidence`      | Average confidence score across all fields (0-100) |
| `stop_reason`         | API stop reason (`end_turn`, `max_tokens`, etc.) |
| `error_message`       | Error details if extraction failed               |

### Benchmarking Workflow

Run the same invoice set against multiple models to compare:

```bash
# Run 1: Anthropic Sonnet
AI_PROVIDER=anthropic AI_MODEL=claude-sonnet-4-6 python -m src.main

# Run 2: OpenAI GPT-5.4
AI_PROVIDER=openai AI_MODEL=gpt-5.4 python -m src.main

# Run 3: Google Gemini Flash
AI_PROVIDER=google AI_MODEL=gemini-3-flash-preview python -m src.main

# Run 4: Ollama (local, free)
AI_PROVIDER=ollama AI_MODEL=qwen3-vl:32b python -m src.main
```

All results append to the same `logs/benchmark.csv` for easy comparison in a spreadsheet or pandas.

---

## Validation Engine

The validation module runs quality checks on every extraction, catching common AI vision failures:

### Checks Performed

| # | Check                          | What It Catches                                             | Type    |
|---|--------------------------------|-------------------------------------------------------------|---------|
| 1 | Required fields present        | Missing supplier, posting_date, or items                    | Error   |
| 2 | Date format (YYYY-MM-DD)       | Malformed dates, wrong separators                           | Error   |
| 3 | Date calendar validity         | Impossible dates like Feb 30, month 13                      | Error   |
| 4 | Date logical order             | due_date before posting_date                                | Error   |
| 5 | Currency code validation       | Symbols (₹, $, €) instead of ISO codes (INR, USD, EUR)     | Error   |
| 6 | Tax ID format validation       | GSTIN, PAN, EU VAT, SWIFT, IBAN format checks               | Error   |
| 7 | Supplier name sanity           | Watermark text (DRAFT/COPY/SAMPLE) leaking into supplier    | Warning |
| 8 | Line item math                 | `amount != qty * rate - discount` beyond 2% tolerance       | Warning |
| 9 | Net amount consistency         | `net_amount != amount - discount`                           | Warning |
| 10 | Item tax validation           | `tax_amount != taxable * tax_rate`, tax_rate out of range   | Error   |
| 11 | Discount consistency           | Discount % out of 0-100 range, discount > gross amount      | Error   |
| 12 | Total vs items sum             | `total` doesn't match sum of line item amounts              | Warning |
| 13 | Grand total vs total + taxes   | `grand_total != total - discount + taxes`                   | Error   |
| 14 | Magnitude sanity               | Grand total is 10x/100x off from items sum (digit misread)  | Warning |
| 15 | Decimal precision              | >2 decimal places (European separator misparse)             | Warning |

### Additional Heuristic Warnings

- Control characters in text fields (OCR garbage)
- Purely numeric item names (column misalignment)
- Bill number >50 characters (field misalignment)
- Negative totals (unusual for purchase invoices)
- Unknown currency codes not in common ISO 4217 list

### Validation Scoring

- **Errors** = hard failures that reduce the quality score
- **Warnings** = soft issues logged but don't reduce the score
- **Score** = `checks_passed / checks_total * 100`
- A perfect invoice scores **100%**

---

## Configuration

All configuration is via the `.env` file:

| Variable           | Default                      | Description                                      |
| ------------------ | ---------------------------- | ------------------------------------------------ |
| `AI_PROVIDER`      | `anthropic`                  | `anthropic`, `openai`, `google`, or `ollama`     |
| `AI_MODEL`         | `claude-sonnet-4-6`          | Any vision model from your provider              |
| `ANTHROPIC_API_KEY` | —                           | API key for Anthropic                            |
| `OPENAI_API_KEY`   | —                            | API key for OpenAI                               |
| `GOOGLE_API_KEY`   | —                            | API key for Google                               |
| `OLLAMA_BASE_URL`  | `http://192.168.1.9:11434`   | Ollama server URL (no API key needed)            |
| `SCHEMA_PATH`      | `schema.json`                | Path to custom JSON schema (optional)            |
| `PROMPT_PATH`      | `prompt.txt`                 | Path to custom system prompt (optional)          |

To switch providers, update `.env` — no code changes needed.

### Ollama Setup

1. [Install Ollama](https://ollama.com/download) on your machine (or a remote server)
2. Pull a vision-capable model:
   ```bash
   ollama pull qwen3-vl:32b     # Best quality, 128K context (~37GB VRAM)
   ollama pull gemma3:27b        # Good alternative, 128K context (~32GB VRAM)
   ollama pull qwen2.5vl:32b    # Older Qwen, 32K context (~29GB VRAM)
   ollama pull qwen2.5vl:7b     # Lighter option, 32K context (~9GB VRAM)
   ```
3. Set `OLLAMA_BASE_URL` in `.env` to point to your Ollama instance
4. **Tip:** Only keep one large model loaded at a time. The extractor uses `keep_alive: 10m` so models auto-unload after 10 minutes of inactivity, freeing VRAM for other models.

---

## Error Handling & Resilience

| Feature                  | Details                                                      |
| ------------------------ | ------------------------------------------------------------ |
| Rate limit retry         | Auto-retries on 429 errors with 15s / 30s / 60s backoff (up to 3 retries) |
| Inter-file delay         | 3-second delay between files to avoid hitting rate limits    |
| Image size limits        | Auto-resizes images >5MB using Pillow before sending to API  |
| JSON truncation          | Uses 16,384 max output tokens to handle large invoices       |
| Robust JSON parsing      | Handles markdown fences, trailing commas, surrounding text   |
| Ollama timeout           | 600-second timeout for local models (large invoices can be slow) |
| Ollama VRAM management   | `keep_alive: 10m` auto-unloads models after inactivity       |

---

## Troubleshooting

| Problem                          | Solution                                                    |
| -------------------------------- | ----------------------------------------------------------- |
| `ModuleNotFoundError: anthropic` | `pip install ".[anthropic]"`                                |
| `ModuleNotFoundError: openai`    | `pip install ".[openai]"`                                   |
| `ModuleNotFoundError: fitz`      | `pip install ".[all]"` (includes PyMuPDF)                   |
| `No API key set for provider`    | Check `.env` has the correct key for your `AI_PROVIDER`     |
| `No supported files found`       | Ensure files are in `input/` with supported extensions      |
| `Schema file not found`          | Ensure `schema.json` exists in project root                 |
| Poor extraction quality          | Try a stronger model (`claude-opus-4-6`, `gpt-5.4`)        |
| Rate limit errors (429)          | Built-in retry with backoff handles this automatically      |
| `Failed to parse JSON`           | Model returned non-JSON; try a different model              |
| Low validation score             | Check `validation_errors` in CSV for specific failures      |
| Image too large error            | Auto-resize handles this; ensure Pillow is installed        |
| Ollama 500 / model crash         | VRAM contention — unload other models: `curl -X POST http://host:11434/api/generate -d '{"model":"other_model","keep_alive":0}'` |
| Ollama connection refused        | Check `OLLAMA_BASE_URL` in `.env` and that Ollama is running |
| Ollama slow response             | Normal for large models; 600s timeout is set automatically  |

---

## Project Structure

```
invoice-extractor/
|-- .env                             <- Provider config & API keys (git-ignored)
|-- .env.example                     <- Template for .env
|-- schema.json                      <- ERPNext Purchase Invoice JSON schema
|-- prompt.txt                       <- System prompt for extraction rules
|-- pyproject.toml                   <- Python package config & dependencies
|-- README.md                        <- This file
|
|-- input/                           <- Drop invoice files here (git-ignored)
|-- output/                          <- JSON output files (git-ignored)
|-- logs/                            <- Benchmark CSV logs (git-ignored)
|
|-- src/
|   |-- __init__.py
|   |-- config.py                    <- .env loading, provider/model/key resolution
|   |-- models.py                    <- Pydantic models (PurchaseInvoice schema)
|   |-- extractor.py                 <- AI vision extraction (Anthropic/OpenAI/Google/Ollama)
|   |-- validation.py                <- Quality validation engine
|   |-- benchmark.py                 <- Metrics dataclass + CSV logger
|   |-- main.py                      <- CLI entry point, orchestration loop
```

### How the Modules Connect

```
main.py
  |-- config.py          -> reads .env, resolves provider/model/api_key
  |-- extractor.py       -> sends images to AI API, gets structured JSON
  |   |-- config.py      -> loads schema.json
  |   |-- models.py      -> validates JSON into PurchaseInvoice Pydantic model
  |-- validation.py      -> runs quality checks on the PurchaseInvoice
  |-- benchmark.py       -> collects metrics, writes CSV, prints summary
```

---

## Architecture Decisions

| Decision                       | Rationale                                                        |
| ------------------------------ | ---------------------------------------------------------------- |
| Multi-provider support         | Compare cloud and local models fairly; avoid vendor lock-in      |
| Image-based extraction         | Works with scanned PDFs, photos, digital PDFs — universal input  |
| PyMuPDF for PDF rendering      | Fast, no external dependencies (Poppler/Tesseract not needed)    |
| 200 DPI rendering              | Balance between quality and token cost                           |
| Pillow for image resize        | Auto-downscale large images to stay within API size limits       |
| Pydantic v2 models             | Runtime validation, type safety, easy JSON serialization         |
| Shared JSON schema             | Same schema.json across all providers for fair comparison        |
| Provider-native JSON mode      | Each provider's structured output for best results               |
| Per-field confidence scores    | Know which extracted values to trust vs review manually          |
| Robust JSON parser             | Handles markdown fences, trailing commas, surrounding text       |
| Rate-limit retry with backoff  | Handles 429 errors automatically (15s/30s/60s)                   |
| CSV benchmark logging          | Append-only, easy to analyze in spreadsheet or pandas            |
| .env configuration             | Switch providers without code changes                            |
