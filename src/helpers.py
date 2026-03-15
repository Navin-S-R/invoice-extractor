"""Shared helpers used by both the CLI (main.py) and the API (api.py)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def count_populated_fields(invoice) -> tuple[int, int]:
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


def avg_confidence(scores: dict | list | None) -> int | None:
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
        elif isinstance(obj, int | float):
            values.append(int(obj))

    _collect(scores)
    return round(sum(values) / len(values)) if values else None


def merge_with_confidence(data: dict, scores: dict | None) -> dict:
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
                            merged_list.append(
                                {
                                    "value": item,
                                    "confidence_score": item_score if isinstance(item_score, int | float) else 0,
                                }
                            )
                    result[key] = merged_list
                else:
                    # Leaf value
                    result[key] = {
                        "value": val,
                        "confidence_score": score_val if isinstance(score_val, int | float) else 0,
                    }
            return result
        # Fallback: data without matching scores
        return {"value": d, "confidence_score": s if isinstance(s, int | float) else 0}

    return _merge(data, scores)


@dataclass
class PipelineResult:
    """Result of running the extraction + validation + metrics pipeline."""

    merged: dict  # Invoice data merged with confidence scores
    invoice_raw: dict  # Plain invoice data (no confidence)
    validation: dict  # {score_pct, checks_passed, checks_total, warnings, errors}
    metrics_summary: dict  # {provider, model, latency, tokens, cost, confidence}
    avg_conf: int | None  # Average confidence score


def run_extraction_pipeline(
    file_path: Path,
    provider: str,
    model: str,
    api_key: str,
    metrics: object,
) -> PipelineResult:
    """Shared extraction pipeline used by both CLI and API.

    Calls extract_invoice → merge → validate → fill metrics.
    The caller must create the ExtractionMetrics object and handle errors.
    """
    from .benchmark import estimate_cost
    from .extractor import extract_invoice
    from .validation import validate_invoice

    invoice, result = extract_invoice(file_path, provider, model, api_key)

    invoice_data = invoice.model_dump(exclude_none=True)
    merged = merge_with_confidence(invoice_data, result.confidence_scores)

    # Fill metrics
    metrics.status = "success"
    metrics.latency_seconds = round(result.latency_seconds, 2)
    metrics.input_tokens = result.input_tokens
    metrics.output_tokens = result.output_tokens
    metrics.total_tokens = result.input_tokens + result.output_tokens
    metrics.stop_reason = result.stop_reason
    metrics.estimated_cost_usd = round(estimate_cost(model, result.input_tokens, result.output_tokens), 6)

    metrics.items_count = len(invoice.items)
    metrics.taxes_count = len(invoice.taxes) if invoice.taxes else 0
    metrics.has_grand_total = invoice.grand_total is not None
    metrics.has_supplier = bool(invoice.supplier)
    metrics.fields_populated, metrics.fields_total = count_populated_fields(invoice)

    vr = validate_invoice(invoice)
    metrics.validation_score = vr.score_pct
    metrics.validation_passed = vr.checks_passed
    metrics.validation_total = vr.checks_total
    metrics.validation_warnings = len(vr.warnings)
    metrics.validation_errors = "; ".join(vr.errors + vr.warnings) if (vr.errors or vr.warnings) else ""

    avg_conf = avg_confidence(result.confidence_scores) if result.confidence_scores else None
    if avg_conf is not None:
        metrics.avg_confidence = avg_conf

    validation_summary = {
        "score_pct": vr.score_pct,
        "checks_passed": vr.checks_passed,
        "checks_total": vr.checks_total,
        "warnings": vr.warnings,
        "errors": vr.errors,
    }
    metrics_summary = {
        "provider": provider,
        "model": model,
        "latency_seconds": metrics.latency_seconds,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": metrics.total_tokens,
        "estimated_cost_usd": metrics.estimated_cost_usd,
        "avg_confidence": avg_conf,
    }

    return PipelineResult(
        merged=merged,
        invoice_raw=invoice_data,
        validation=validation_summary,
        metrics_summary=metrics_summary,
        avg_conf=avg_conf,
    )
