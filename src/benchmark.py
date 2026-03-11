"""Benchmark metrics collection and CSV logging."""

import csv
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class ExtractionMetrics:
    file_name: str = ""
    provider: str = ""
    model: str = ""
    status: str = ""  # "success" or "error"
    error_message: str = ""

    # Timing
    latency_seconds: float = 0.0

    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Cost estimate (USD)
    estimated_cost_usd: float = 0.0

    # Extraction quality indicators
    items_count: int = 0
    taxes_count: int = 0
    has_grand_total: bool = False
    has_supplier: bool = False
    fields_populated: int = 0
    fields_total: int = 0

    # Validation quality score
    validation_score: int = 0  # 0-100%
    validation_passed: int = 0
    validation_total: int = 0
    validation_warnings: int = 0
    validation_errors: str = ""

    # Confidence score (avg across all fields, 0-100)
    avg_confidence: int = 0

    # Raw stop reason from the API
    stop_reason: str = ""

    timestamp: str = ""


# Approximate pricing per 1M tokens (USD) as of 2026-03
_PRICING = {
    # (input_per_1M, output_per_1M)
    # Anthropic
    "claude-sonnet-4-6":        (3.00, 15.00),
    "claude-opus-4-6":          (5.00, 25.00),
    "claude-haiku-4-5":         (1.00, 5.00),
    # OpenAI — current
    "gpt-5.4":                  (2.50, 20.00),
    "gpt-5":                    (0.625, 5.00),
    "gpt-5.2":                  (1.75, 14.00),
    # OpenAI — legacy
    "gpt-4o":                   (2.50, 10.00),
    "gpt-4o-mini":              (0.15, 0.60),
    "gpt-4.1":                  (2.00, 8.00),
    "gpt-4.1-mini":             (0.40, 1.60),
    "gpt-4.1-nano":             (0.10, 0.40),
    # Google — current
    "gemini-3-flash-preview":   (0.50, 3.00),
    "gemini-3-pro-preview":     (2.00, 12.00),
    "gemini-3.1-pro-preview":   (2.00, 12.00),
    # Google — legacy
    "gemini-2.5-pro":           (1.25, 10.00),
    "gemini-2.5-flash":         (0.15, 0.60),
    "gemini-2.0-flash":         (0.10, 0.40),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD based on token usage."""
    pricing = _PRICING.get(model)
    if not pricing:
        return 0.0
    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


class BenchmarkLogger:
    """Append extraction metrics to a CSV log file."""

    CSV_FIELDS = [
        "timestamp", "file_name", "provider", "model", "status",
        "latency_seconds", "input_tokens", "output_tokens", "total_tokens",
        "estimated_cost_usd", "items_count", "taxes_count",
        "has_grand_total", "has_supplier", "fields_populated", "fields_total",
        "validation_score", "validation_passed", "validation_total",
        "validation_warnings", "validation_errors",
        "avg_confidence",
        "stop_reason", "error_message",
    ]

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self._ensure_header()

    def _ensure_header(self):
        """Write CSV header if file doesn't exist or is empty."""
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                writer.writeheader()

    def log(self, metrics: ExtractionMetrics):
        """Append a single metrics row to the CSV."""
        row = asdict(metrics)
        with open(self.log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            writer.writerow({k: row[k] for k in self.CSV_FIELDS})

    def print_summary(self, all_metrics: list[ExtractionMetrics]):
        """Print a run summary to stdout."""
        if not all_metrics:
            return

        succeeded = [m for m in all_metrics if m.status == "success"]
        failed = [m for m in all_metrics if m.status == "error"]

        total_time = sum(m.latency_seconds for m in all_metrics)
        total_input = sum(m.input_tokens for m in succeeded)
        total_output = sum(m.output_tokens for m in succeeded)
        total_cost = sum(m.estimated_cost_usd for m in succeeded)
        avg_latency = total_time / len(all_metrics) if all_metrics else 0

        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        print(f"Provider: {all_metrics[0].provider} | Model: {all_metrics[0].model}")
        print(f"Files: {len(succeeded)} succeeded, {len(failed)} failed")
        print(f"Total time: {total_time:.1f}s | Avg latency: {avg_latency:.1f}s")
        print(f"Tokens: {total_input:,} input + {total_output:,} output = {total_input + total_output:,} total")
        print(f"Estimated cost: ${total_cost:.4f}")

        if succeeded:
            avg_items = sum(m.items_count for m in succeeded) / len(succeeded)
            avg_fields = sum(m.fields_populated for m in succeeded) / len(succeeded)
            avg_total_fields = sum(m.fields_total for m in succeeded) / len(succeeded)
            fill_rate = (avg_fields / avg_total_fields * 100) if avg_total_fields else 0
            avg_validation = sum(m.validation_score for m in succeeded) / len(succeeded)
            total_warnings = sum(m.validation_warnings for m in succeeded)
            conf_scores = [m.avg_confidence for m in succeeded if m.avg_confidence > 0]
            avg_conf = sum(conf_scores) / len(conf_scores) if conf_scores else 0

            print(f"Avg items extracted: {avg_items:.1f}")
            print(f"Avg field fill rate: {fill_rate:.0f}% ({avg_fields:.0f}/{avg_total_fields:.0f})")
            print(f"Avg validation score: {avg_validation:.0f}%")
            if avg_conf > 0:
                print(f"Avg confidence score: {avg_conf:.0f}%")
            if total_warnings > 0:
                print(f"Total warnings: {total_warnings} (check logs for details)")

        # Per-file breakdown table
        print(f"\n{'File':<30} {'Status':<8} {'Time':>6} {'Tokens':>8} {'Cost':>8} {'Quality':>7} {'Conf':>5}")
        print("-" * 80)
        for m in all_metrics:
            if m.status == "success":
                print(
                    f"{m.file_name:<30} {'OK':<8} {m.latency_seconds:>5.1f}s "
                    f"{m.total_tokens:>8,} ${m.estimated_cost_usd:>7.4f} "
                    f"{m.validation_score:>5}%  {m.avg_confidence or '-':>4}%"
                )
            else:
                err_short = m.error_message[:40] if m.error_message else "unknown"
                print(f"{m.file_name:<30} {'FAIL':<8} {'-':>6} {'-':>8} {'-':>8} {'-':>7} {'-':>5}")
                print(f"  -> {err_short}")

        if failed:
            print(f"\nFailed files ({len(failed)}):")
            for m in failed:
                print(f"  - {m.file_name}: {m.error_message}")

        print(f"\nLog: {self.log_path}")
        print("=" * 60)
