# Invoice Extractor

A multi-provider AI vision benchmarking tool that extracts structured purchase invoice data from PDFs and images into ERPNext-ready JSON. Compare extraction quality, speed, and cost across Anthropic, OpenAI, and Google models — no OCR setup needed.

---

## What It Does

1. **Reads** invoice files (PDF, PNG, JPG, WebP) from an `input/` folder
2. **Sends** each page as an image to an AI vision model with a structured extraction prompt
3. **Parses** the AI response into a validated Pydantic model (ERPNext Purchase Invoice schema)
4. **Validates** the extraction against 14 quality checks catching common AI hallucinations
5. **Writes** ERPNext-ready JSON to `output/`
6. **Logs** benchmark metrics (latency, tokens, cost, quality score) to `logs/benchmark.csv`
7. **Prints** a run summary with aggregated stats

---

## Prerequisites

- Python 3.10+
- An API key from at least one supported provider

---

## Supported Providers & Models

| Provider  | Recommended                              | Also Supported                                              | Get API Key                                                                  |
| --------- | ---------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6`   | `claude-haiku-4-5`                                          | [console.anthropic.com](https://console.anthropic.com/settings/keys)         |
| OpenAI    | `gpt-5.4`, `gpt-5`                      | `gpt-5.2`, `gpt-4o`, `gpt-4.1`, `gpt-4.1-mini`            | [platform.openai.com](https://platform.openai.com/api-keys)                 |
| Google    | `gemini-3-flash-preview`, `gemini-3.1-pro-preview` | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash` | [aistudio.google.com](https://aistudio.google.com/apikey)                   |

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

---

## Setup

```bash
# 1. Navigate to the project
cd "Claude Trails/invoice-extractor"

# 2. Activate the shared virtual environment
source ../.venv/bin/activate

# 3. Install core dependencies
pip install PyMuPDF pydantic python-dotenv

# 4. Install the SDK for your provider
pip install anthropic          # For Anthropic
pip install openai             # For OpenAI
pip install google-genai       # For Google

# 5. Create your .env file
cp .env.example .env
```

Edit `.env` to configure your provider and API key:

```env
# Choose provider: anthropic | openai | google
AI_PROVIDER=anthropic

# Choose model
AI_MODEL=claude-sonnet-4-6

# Set the API key for your provider
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
OPENAI_API_KEY=
GOOGLE_API_KEY=
```

---

## Usage

### 1. Add your invoices

Place invoice files into the `input/` folder.

**Supported formats:** PDF, PNG, JPG, JPEG, WebP

### 2. Run the extractor

```bash
cd "Claude Trails/invoice-extractor"
source ../.venv/bin/activate
python -m src.main
```

### 3. Collect your JSON

Each invoice produces a corresponding JSON file in `output/`:

```
input/invoice-001.pdf  ->  output/invoice-001.json
input/receipt.png      ->  output/receipt.json
```

### Custom input/output folders

```bash
python -m src.main /path/to/invoices /path/to/output
```

### Sample output

```
Provider: anthropic | Model: claude-sonnet-4-6
Found 3 file(s) in input

[1/3] Processing: invoice-001.pdf... OK -> invoice-001.json (2.34s, 1847 tokens, $0.0082, quality 92%)
    ~ total matches sum of line items: got 4500.0, expected 4520.00 (diff 0.4%)
[2/3] Processing: receipt.png... OK -> receipt.json (1.89s, 1203 tokens, $0.0054, quality 100%)
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
Log: logs/benchmark.csv
============================================================
```

---

## Output JSON Schema

Each JSON file follows the **ERPNext v15+ Purchase Invoice** schema:

```json
{
  "doctype": "Purchase Invoice",
  "naming_series": "ACC-PINV-.YYYY.-",
  "supplier": "ABC Suppliers Ltd",
  "supplier_name": "ABC Suppliers",
  "posting_date": "2026-03-10",
  "due_date": "2026-04-10",
  "bill_no": "INV-2026-0042",
  "bill_date": "2026-03-08",
  "currency": "INR",
  "items": [
    {
      "item_name": "Widget A",
      "description": "Standard Widget Type A",
      "qty": 10,
      "uom": "Nos",
      "rate": 250.00,
      "amount": 2250.00,
      "discount_percentage": 10.0,
      "discount_amount": 250.00
    }
  ],
  "taxes": [
    {
      "charge_type": "On Net Total",
      "description": "CGST 9%",
      "rate": 9.0,
      "tax_amount": 202.50
    },
    {
      "charge_type": "On Net Total",
      "description": "SGST 9%",
      "rate": 9.0,
      "tax_amount": 202.50
    }
  ],
  "total": 2250.00,
  "discount_amount": 250.00,
  "grand_total": 2655.00,
  "remarks": "Payment terms: Net 30",
  "docstatus": 0
}
```

**Note:** All invoices are created as **Draft** (`docstatus: 0`). Review them before submitting in ERPNext.

### Schema Fields

| Field               | Type       | Required | Description                                    |
| ------------------- | ---------- | -------- | ---------------------------------------------- |
| `supplier`          | string     | Yes      | Official supplier/company name                 |
| `supplier_name`     | string     | No       | Display name if different                      |
| `posting_date`      | string     | Yes      | Invoice date (YYYY-MM-DD)                      |
| `due_date`          | string     | No       | Payment due date                               |
| `bill_no`           | string     | No       | Supplier's invoice number                      |
| `bill_date`         | string     | No       | Supplier's invoice date                        |
| `currency`          | string     | No       | ISO 4217 code (INR, USD, EUR). Default: INR    |
| `items`             | array      | Yes      | Line items (see below)                         |
| `taxes`             | array      | No       | Tax/charge entries                             |
| `total`             | number     | No       | Net total before tax                           |
| `discount_amount`   | number     | No       | Invoice-level discount                         |
| `grand_total`       | number     | No       | Final amount including tax                     |

**Line Item Fields:** `item_name` (required), `description`, `qty` (required), `uom`, `rate` (required), `amount`, `discount_percentage`, `discount_amount`

**Tax Fields:** `description` (required), `charge_type`, `rate`, `tax_amount`, `account_head`

---

## Benchmark & Metrics

Every run appends metrics to `logs/benchmark.csv`. Use this to compare models side-by-side.

### Metrics Collected

| Metric                | Description                                      |
| --------------------- | ------------------------------------------------ |
| `timestamp`           | UTC ISO timestamp of extraction                  |
| `file_name`           | Input file name                                  |
| `provider`            | `anthropic`, `openai`, or `google`               |
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
```

All results append to the same `logs/benchmark.csv` for easy comparison in a spreadsheet or pandas.

---

## Validation Engine

The validation module (`src/validation.py`) runs **14 quality checks** on every extraction, catching common AI vision failures:

### Checks Performed

| # | Check                          | What It Catches                                             | Type    |
|---|--------------------------------|-------------------------------------------------------------|---------|
| 1 | Required fields present        | Missing supplier, posting_date, or items                    | Error   |
| 2 | Date format (YYYY-MM-DD)       | Malformed dates, wrong separators                           | Error   |
| 3 | Date calendar validity         | Impossible dates like Feb 30, month 13                      | Error   |
| 4 | Date logical order             | due_date before posting_date                                | Error   |
| 5 | Currency code validation       | Symbols (₹, $, €) instead of ISO codes (INR, USD, EUR)     | Error   |
| 6 | Supplier name sanity           | Watermark text (DRAFT/COPY/SAMPLE) leaking into supplier    | Warning |
| 7 | Line item math                 | `amount != qty * rate - discount` beyond 2% tolerance       | Warning |
| 8 | Discount consistency           | Discount % out of 0-100 range, discount > gross amount      | Error   |
| 9 | Duplicate item detection       | Same (name, qty, rate) appearing multiple times              | Warning |
| 10 | Identical amounts              | All 3+ items having the exact same amount (hallucination)   | Warning |
| 11 | Total vs items sum             | `total` doesn't match sum of line item amounts              | Warning |
| 12 | Grand total vs total + taxes   | `grand_total != total - discount + taxes`                   | Error   |
| 13 | Magnitude sanity               | Grand total is 10x/100x off from items sum (digit misread)  | Warning |
| 14 | Decimal precision              | >2 decimal places (European separator misparse)             | Warning |

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

## Prompt Engineering

The system prompt (`src/extractor.py`) is heavily engineered for financial document accuracy:

### Key Prompt Sections

| Section                    | Purpose                                                      |
| -------------------------- | ------------------------------------------------------------ |
| Objective                  | Define the task: extract structured invoice data for ERP     |
| Strict Output Rules        | JSON only, no markdown/comments, null for unknown fields     |
| Data Normalization         | Date format (YYYY-MM-DD), currency stripping, number parsing |
| Currency Separator Rules   | Indian/US (commas) vs European (dots) format detection       |
| Field Extraction Guide     | Per-field instructions for supplier, items, taxes, totals    |
| Discount Handling          | Rate = original price, amount = after discount               |
| Anti-Hallucination Rules   | Never fabricate, round, transpose, paraphrase, merge/split   |
| Document Structure Rules   | Ignore watermarks, handle multi-page, preserve item order    |
| Date Disambiguation        | DD/MM/YYYY for INR/EUR/GBP, MM/DD/YYYY for USD              |
| Numeric Consistency        | Self-check: items sum ~ total, total + tax ~ grand_total     |

### Structured Output Enforcement

Each provider uses its native JSON schema enforcement:

| Provider  | Method                                            |
| --------- | ------------------------------------------------- |
| Anthropic | `output_config.format.json_schema` with schema    |
| OpenAI    | `text.format.json_schema` with schema             |
| Google    | `response_mime_type="application/json"` + schema  |

All providers use the same `schema.json` file, ensuring consistent output structure regardless of the model.

### Robust JSON Parsing

The `_parse_json_robust()` function handles malformed AI responses:

1. Strips markdown code fences (```json ... ```)
2. Tries direct `json.loads()`
3. Extracts JSON object from surrounding text (`{...}`)
4. Fixes trailing commas (`,}` or `,]`)
5. Raises with raw text for debugging if all else fails

---

## Configuration

All configuration is via the `.env` file:

| Variable           | Default              | Description                              |
| ------------------ | -------------------- | ---------------------------------------- |
| `AI_PROVIDER`      | `anthropic`          | `anthropic`, `openai`, or `google`       |
| `AI_MODEL`         | `claude-sonnet-4-6`  | Any vision model from your provider      |
| `ANTHROPIC_API_KEY` | —                   | API key for Anthropic                    |
| `OPENAI_API_KEY`   | —                    | API key for OpenAI                       |
| `GOOGLE_API_KEY`   | —                    | API key for Google                       |
| `SCHEMA_PATH`      | `schema.json`        | Path to custom JSON schema (optional)    |

To switch providers, update `.env` — no code changes needed.

---

## Troubleshooting

| Problem                          | Solution                                                    |
| -------------------------------- | ----------------------------------------------------------- |
| `ModuleNotFoundError: anthropic` | `pip install anthropic`                                     |
| `ModuleNotFoundError: openai`    | `pip install openai`                                        |
| `ModuleNotFoundError: fitz`      | `pip install PyMuPDF`                                       |
| `No API key set for provider`    | Check `.env` has the correct key for your `AI_PROVIDER`     |
| `No supported files found`       | Ensure files are in `input/` with supported extensions      |
| `Schema file not found`          | Ensure `schema.json` exists in project root                 |
| Poor extraction quality          | Try a stronger model (`claude-opus-4-6`, `gpt-5.4`)        |
| Rate limit errors                | Built-in 0.5s delay between files; reduce batch size        |
| `Failed to parse JSON`           | Model returned non-JSON; try a different model              |
| Low validation score             | Check `validation_errors` in CSV for specific failures      |

---

## Project Structure

```
Claude Trails/                           <- Shared root
|-- .venv/                               <- Shared Python virtual environment
|-- .gitignore
|
|-- invoice-extractor/                   <- This project
|   |-- .env                             <- Provider config & API keys (git-ignored)
|   |-- .env.example                     <- Template for .env
|   |-- schema.json                      <- ERPNext Purchase Invoice JSON schema
|   |-- pyproject.toml                   <- Python package config & dependencies
|   |-- README.md                        <- This file
|   |
|   |-- input/                           <- Drop invoice files here
|   |-- output/                          <- JSON output files (git-ignored)
|   |-- logs/                            <- Benchmark CSV logs (git-ignored)
|   |
|   |-- src/
|   |   |-- __init__.py
|   |   |-- config.py                    <- .env loading, provider/model/key resolution
|   |   |-- models.py                    <- Pydantic models (PurchaseInvoice schema)
|   |   |-- extractor.py                 <- AI vision extraction + system prompt
|   |   |-- validation.py                <- 14-check quality validation engine
|   |   |-- benchmark.py                 <- Metrics dataclass + CSV logger
|   |   |-- main.py                      <- CLI entry point, orchestration loop
```

### How the Modules Connect

```
main.py
  |-- config.py          -> reads .env, resolves provider/model/api_key
  |-- extractor.py       -> sends images to AI API, gets structured JSON
  |   |-- config.py      -> loads schema.json
  |   |-- models.py      -> validates JSON into PurchaseInvoice Pydantic model
  |-- validation.py      -> runs 14 quality checks on the PurchaseInvoice
  |-- benchmark.py       -> collects metrics, writes CSV, prints summary
```

---

## Architecture Decisions

| Decision                       | Rationale                                                        |
| ------------------------------ | ---------------------------------------------------------------- |
| Multi-provider support         | Compare models fairly; avoid vendor lock-in                      |
| Image-based extraction         | Works with scanned PDFs, photos, digital PDFs — universal input  |
| PyMuPDF for PDF rendering      | Fast, no external dependencies (Poppler/Tesseract not needed)    |
| 200 DPI rendering              | Balance between quality and token cost                           |
| Pydantic v2 models             | Runtime validation, type safety, easy JSON serialization         |
| Shared JSON schema             | Same schema.json across all providers for fair comparison        |
| Provider-native JSON mode      | Each provider's structured output for best results               |
| Robust JSON parser             | Handles markdown fences, trailing commas, surrounding text       |
| 14-check validation            | Catches hallucinations, math errors, separator misparses         |
| CSV benchmark logging          | Append-only, easy to analyze in spreadsheet or pandas            |
| .env configuration             | Switch providers without code changes                            |
| 0.5s inter-file delay          | Simple rate limiting without complexity                          |

---

## AI Prompt for Recreating This Project

Use the following prompt with any AI coding assistant to build a similar invoice extraction + benchmarking tool:

---

> **Project: AI Vision Invoice Extractor with Multi-Provider Benchmarking**
>
> Build a Python CLI tool that extracts structured purchase invoice data from PDF and image files using AI vision APIs, validates the results, and benchmarks performance across multiple AI providers.
>
> ### Core Requirements
>
> 1. **Multi-provider support**: Support at least 3 AI vision providers (e.g., Anthropic Claude, OpenAI GPT, Google Gemini). Each provider should use its native structured output / JSON schema enforcement. Provider selection via environment variable — no code changes to switch.
>
> 2. **Input handling**: Accept PDF and image files (PNG, JPG, WebP). For PDFs, render each page to a PNG image at 200 DPI using PyMuPDF. Send all pages as a multi-image request to the AI API.
>
> 3. **Output schema**: Define a Pydantic v2 model for a Purchase Invoice with these fields:
>    - Supplier info: `supplier`, `supplier_name`
>    - Dates: `posting_date`, `due_date`, `bill_no`, `bill_date` (all YYYY-MM-DD)
>    - Currency: ISO 4217 3-letter code (INR, USD, EUR — not symbols like ₹/$)
>    - Line items array: `item_name`, `description`, `qty`, `uom`, `rate`, `amount`, `discount_percentage`, `discount_amount`
>    - Taxes array: `description`, `charge_type`, `rate`, `tax_amount`
>    - Totals: `total` (before tax), `discount_amount`, `grand_total` (after tax)
>    - Also export as a JSON schema file that all providers can reference
>
> 4. **System prompt engineering**: Write a detailed extraction prompt covering:
>    - Strict JSON-only output rules
>    - Data normalization: dates to YYYY-MM-DD, strip currency symbols from numbers, handle Indian/US comma separators vs European dot separators
>    - Discount handling: rate = original price, amount = after discount
>    - Anti-hallucination rules: never fabricate values, never round numbers, never transpose digits, never paraphrase item names, never merge/split line items, verify math
>    - Document structure: ignore watermarks/stamps, handle multi-page, preserve item order
>    - Date disambiguation: DD/MM/YYYY default for INR/EUR/GBP, MM/DD/YYYY for USD
>    - Numeric self-checks: sum of items ~ total, total + taxes ~ grand_total
>
> 5. **Robust JSON parsing**: Handle common AI response issues:
>    - Markdown code fence wrapping (```json...```)
>    - Leading/trailing non-JSON text
>    - Trailing commas in objects/arrays
>    - Raise clear errors with raw text snippet for debugging
>
> 6. **Validation engine** (14 checks): After extraction, validate against these common AI vision failures:
>    - Required fields present (supplier, date, items)
>    - Date format YYYY-MM-DD + real calendar date (catch Feb 30, month 13)
>    - Date logical order (due_date >= posting_date)
>    - Currency is ISO code not symbol (₹ → error, INR → pass)
>    - Supplier name not contaminated with watermark text (DRAFT/COPY/SAMPLE)
>    - Line item math: amount = qty * rate - discount (within 2% tolerance)
>    - Discount ranges valid (0-100% for percentage, not exceeding gross)
>    - Duplicate item detection (same name+qty+rate repeated = possible hallucination)
>    - All items having identical amounts (3+ items = suspicious)
>    - Total matches sum of line items
>    - Grand total = total - discount + taxes
>    - Magnitude sanity (grand_total not 10x/100x off from items — digit misread)
>    - Decimal precision (>2 decimals = currency separator misparse)
>    - Additional warnings: control characters (OCR garbage), numeric item names (column misalignment), very long bill numbers (field leak), negative totals
>    - Score = checks_passed / checks_total as percentage
>
> 7. **Benchmark metrics**: For every extraction, log to a CSV file:
>    - Timestamp, file name, provider, model, status (success/error)
>    - Latency (seconds), input/output/total tokens, estimated cost (USD)
>    - Quality: items count, taxes count, has_grand_total, has_supplier, fields_populated/total
>    - Validation: score %, checks passed/total, warning count, error details
>    - Stop reason, error message
>    - Include a pricing table for cost estimation per model
>    - Print a run summary with aggregated stats at the end
>
> 8. **CLI entry point**:
>    - Scan `input/` folder for supported files
>    - Process each file sequentially with progress output
>    - Write JSON to `output/` folder (one JSON per input file)
>    - Append metrics to `logs/benchmark.csv`
>    - Print per-file status with validation errors/warnings
>    - 0.5s delay between files for rate limiting
>    - Support custom input/output paths via CLI args
>
> 9. **Configuration**: All config via `.env` file — provider, model, API keys, schema path. Include `.env.example` template.
>
> 10. **Dependencies**: PyMuPDF (PDF rendering), Pydantic v2 (schema validation), python-dotenv (config). Provider SDKs as optional dependencies.
>
> ### Tech Stack
> - Python 3.10+, Pydantic v2, PyMuPDF, python-dotenv
> - Provider SDKs: anthropic, openai, google-genai
> - No OCR libraries needed — pure AI vision extraction

---
