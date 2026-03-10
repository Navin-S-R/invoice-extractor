"""Main entry point — scan input folder, extract invoices, write JSON to output."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import BenchmarkLogger, ExtractionMetrics, estimate_cost
from .config import AI_PROVIDER, get_api_key, get_model
from .extractor import extract_invoice
from .validation import validate_invoice

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


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


def main():
    base_dir = Path(__file__).resolve().parent.parent
    input_dir = base_dir / "input"
    output_dir = base_dir / "output"

    # Allow overriding via CLI args
    if len(sys.argv) >= 2:
        input_dir = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])

    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    files = get_files(input_dir)
    if not files:
        print(f"No supported files found in {input_dir}")
        print(f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
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

            # Write JSON output
            output_file = output_dir / f"{file_path.stem}.json"
            output_file.write_text(
                json.dumps(invoice.model_dump(exclude_none=True), indent=2, ensure_ascii=False)
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

            print(
                f"OK -> {output_file.name} "
                f"({metrics.latency_seconds}s, {metrics.total_tokens} tokens, "
                f"${metrics.estimated_cost_usd:.4f}, quality {vr.score_pct}%)"
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

        logger.log(metrics)
        all_metrics.append(metrics)

        # Small delay to stay within rate limits
        if i < len(files):
            time.sleep(0.5)

    logger.print_summary(all_metrics)


if __name__ == "__main__":
    main()
