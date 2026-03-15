"""Main entry point — scan input folder, extract invoices, write JSON to output."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import BenchmarkLogger, ExtractionMetrics
from .config import AI_PROVIDER, get_api_key, get_model
from .helpers import SUPPORTED_EXTENSIONS, run_extraction_pipeline

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
            result = run_extraction_pipeline(file_path, provider, model, api_key, metrics)

            # Write JSON output
            output_file = output_dir / f"{file_path.stem}.json"
            output_file.write_text(
                json.dumps(result.merged, indent=2, ensure_ascii=False)
            )

            conf_str = f", confidence {result.avg_conf}%" if result.avg_conf is not None else ""
            vr = result.validation
            print(
                f"OK -> {output_file.name} "
                f"({metrics.latency_seconds}s, {metrics.total_tokens} tokens, "
                f"${metrics.estimated_cost_usd:.4f}, quality {vr['score_pct']}%{conf_str})"
            )
            if vr["errors"]:
                for err in vr["errors"]:
                    print(f"    ! {err}")
            if vr["warnings"]:
                for warn in vr["warnings"]:
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
