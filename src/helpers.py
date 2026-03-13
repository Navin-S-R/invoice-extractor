"""Shared helpers used by both the CLI (main.py) and the API (api.py)."""

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
        elif isinstance(obj, (int, float)):
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
