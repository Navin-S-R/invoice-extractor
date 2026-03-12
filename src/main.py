"""Main entry point — scan input folder, extract invoices, write JSON to output."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import BenchmarkLogger, ExtractionMetrics, estimate_cost
from .config import AI_PROVIDER, get_api_key, get_model
from .extractor import extract_invoice
from .validation import validate_invoice

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

# Delay between files (seconds). Only applied after rate-limit errors;
# otherwise no artificial delay is imposed.
_RATE_LIMIT_COOLDOWN = 5


def get_files(input_dir: Path) -> list[Path]:
    """Get all supported files from the input directory."""
    files = []
    for f in sorted(input_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(f)
    return files


def _count_populated_fields(invoice) -> tuple[int, int]:
    """Count how many fields are populated vs total fields."""
    data = invoice.model_dump()
    total = 0
    populated = 0
    for key, value in data.items():
        if key in ("doctype", "naming_series", "docstatus"):
            continue  # Skip defaults
        total += 1
        if value is not None and value != [] and value != "":
            populated += 1
    return populated, total


def _avg_confidence(scores: dict | list | None) -> int | None:
    """Compute average confidence score from a nested confidence_scores structure."""
    if scores is None:
        return None
    values: list[int] = []

    def _collect(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                _collect(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)
        elif isinstance(obj, (int, float)):
            values.append(int(obj))

    _collect(scores)
    return round(sum(values) / len(values)) if values else None


def _merge_with_confidence(data: dict, scores: dict | None) -> dict:
    """Merge invoice data and confidence scores into per-field format.

    Transforms:
      data:   {"total": 100, "supplier": "Acme"}
      scores: {"total": 97,  "supplier": 98}
    Into:
      {"total": {"value": 100, "confidence_score": 97},
       "supplier": {"value": "Acme", "confidence_score": 98}}

    Handles nested dicts, arrays of dicts, and leaf values.
    Falls back to confidence_score=0 when scores are missing.
    """
    if scores is None:
        scores = {}

    def _merge(d, s):
        if isinstance(d, dict) and isinstance(s, dict):
            result = {}
            for key, val in d.items():
                score_val = s.get(key)
                if isinstance(val, dict) and isinstance(score_val, dict):
                    # Nested object (address, tax_ids, bank) — recurse
                    result[key] = _merge(val, score_val)
                elif isinstance(val, list):
                    # Array (items, taxes) — merge element-wise
                    score_list = score_val if isinstance(score_val, list) else []
                    merged_list = []
                    for idx, item in enumerate(val):
                        item_score = score_list[idx] if idx < len(score_list) else {}
                        if isinstance(item, dict) and isinstance(item_score, dict):
                            merged_list.append(_merge(item, item_score))
                        else:
                            merged_list.append({
                                "value": item,
                                "confidence_score": item_score if isinstance(item_score, (int, float)) else 0,
                            })
                    result[key] = merged_list
                else:
                    # Leaf value
                    result[key] = {
                        "value": val,
                        "confidence_score": score_val if isinstance(score_val, (int, float)) else 0,
                    }
            return result
        # Fallback: data without matching scores
        return {"value": d, "confidence_score": s if isinstance(s, (int, float)) else 0}

    return _merge(data, scores)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract structured invoice data from PDFs and images using AI Vision APIs."
    )
    base_dir = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "input_dir", nargs="?", default=str(base_dir / "input"),
        help="Directory containing invoice files (default: ./input)",
    )
    parser.add_argument(
        "output_dir", nargs="?", default=str(base_dir / "output"),
        help="Directory for JSON output (default: ./output)",
    )
    parser.add_argument(
        "--file", "-f", dest="single_file", default=None,
        help="Process a single file instead of the entire input directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be processed without extracting",
    )
    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    # Single-file mode
    if args.single_file:
        single = Path(args.single_file)
        if not single.exists():
            print(f"File not found: {single}")
            return
        if single.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(f"Unsupported file type: {single.suffix}")
            return
        files = [single]
    else:
        files = get_files(input_dir)

    if not files:
        print(f"No supported files found in {input_dir}")
        print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
        return

    # Dry-run: just list files and exit
    if args.dry_run:
        print(f"Would process {len(files)} file(s):")
        for f in files:
            print(f"  - {f.name}")
        return

    provider = AI_PROVIDER
    model = get_model()
    api_key = get_api_key()

    # Set up benchmark logging
    log_path = base_dir / "logs" / "benchmark.csv"
    logger = BenchmarkLogger(log_path)

    print(f"Provider: {provider} | Model: {model}")
    print(f"Found {len(files)} file(s) in {input_dir}\n")

    all_metrics: list[ExtractionMetrics] = []
    was_rate_limited = False

    for i, file_path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] Processing: {file_path.name}...", end=" ", flush=True)

        metrics = ExtractionMetrics(
            file_name=file_path.name,
            provider=provider,
            model=model,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            invoice, result = extract_invoice(file_path, provider, model, api_key)

            # Write JSON output with per-field confidence scores
            invoice_data = invoice.model_dump(exclude_none=True)
            output_data = _merge_with_confidence(invoice_data, result.confidence_scores)

            output_file = output_dir / f"{file_path.stem}.json"
            output_file.write_text(
                json.dumps(output_data, indent=2, ensure_ascii=False)
            )

            # Fill metrics from API response
            metrics.status = "success"
            metrics.latency_seconds = round(result.latency_seconds, 2)
            metrics.input_tokens = result.input_tokens
            metrics.output_tokens = result.output_tokens
            metrics.total_tokens = result.input_tokens + result.output_tokens
            metrics.stop_reason = result.stop_reason
            metrics.estimated_cost_usd = round(
                estimate_cost(model, result.input_tokens, result.output_tokens), 6
            )

            # Quality indicators
            metrics.items_count = len(invoice.items)
            metrics.taxes_count = len(invoice.taxes) if invoice.taxes else 0
            metrics.has_grand_total = invoice.grand_total is not None
            metrics.has_supplier = bool(invoice.supplier)
            metrics.fields_populated, metrics.fields_total = _count_populated_fields(invoice)

            # Validation checks
            vr = validate_invoice(invoice)
            metrics.validation_score = vr.score_pct
            metrics.validation_passed = vr.checks_passed
            metrics.validation_total = vr.checks_total
            metrics.validation_warnings = len(vr.warnings)
            metrics.validation_errors = "; ".join(vr.errors + vr.warnings) if (vr.errors or vr.warnings) else ""

            # Compute average confidence from scores
            avg_confidence = _avg_confidence(result.confidence_scores) if result.confidence_scores else None
            if avg_confidence is not None:
                metrics.avg_confidence = avg_confidence
            conf_str = f", confidence {avg_confidence}%" if avg_confidence is not None else ""

            print(
                f"OK -> {output_file.name} "
                f"({metrics.latency_seconds}s, {metrics.total_tokens} tokens, "
                f"${metrics.estimated_cost_usd:.4f}, quality {vr.score_pct}%{conf_str})"
            )
            if vr.errors:
                for err in vr.errors:
                    print(f"    ! {err}")
            if vr.warnings:
                for warn in vr.warnings:
                    print(f"    ~ {warn}")

        except Exception as e:
            metrics.status = "error"
            metrics.error_message = str(e)
            print(f"FAILED: {e}")
            # Cool down after errors that may indicate rate limiting
            err_lower = str(e).lower()
            if "429" in err_lower or "rate" in err_lower or "overloaded" in err_lower:
                was_rate_limited = True

        logger.log(metrics)
        all_metrics.append(metrics)

        # Only delay after rate-limit errors to avoid unnecessary waits
        if i < len(files) and was_rate_limited:
            time.sleep(_RATE_LIMIT_COOLDOWN)
            was_rate_limited = False

    logger.print_summary(all_metrics)


if __name__ == "__main__":
    main()
