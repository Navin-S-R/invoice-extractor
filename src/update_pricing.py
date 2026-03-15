"""Fetch latest AI model pricing from litellm and cache locally.

Runs at most once per day. Subsequent calls on the same day are skipped
unless --force is passed.

Usage:
    python -m src.update_pricing          # fetch if not updated today
    python -m src.update_pricing --force  # always fetch
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

PRICING_FILE = Path(__file__).resolve().parent.parent / "pricing.json"

# Models we care about — maps our short name to the litellm key.
# Ollama / local models are always free and don't need external pricing.
_MODEL_MAP: dict[str, str] = {
	# Anthropic
	"claude-sonnet-4-6": "claude-sonnet-4-6",
	"claude-opus-4-6": "claude-opus-4-6",
	"claude-haiku-4-5": "claude-haiku-4-5",
	# OpenAI
	"gpt-5.4": "gpt-5.4",
	"gpt-5": "gpt-5",
	"gpt-5.2": "gpt-5.2",
	"gpt-4o": "gpt-4o",
	"gpt-4o-mini": "gpt-4o-mini",
	"gpt-4.1": "gpt-4.1",
	"gpt-4.1-mini": "gpt-4.1-mini",
	"gpt-4.1-nano": "gpt-4.1-nano",
	# Google
	"gemini-3-flash-preview": "gemini-3-flash-preview",
	"gemini-3-pro-preview": "gemini-3-pro-preview",
	"gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
	"gemini-2.5-pro": "gemini-2.5-pro",
	"gemini-2.5-flash": "gemini-2.5-flash",
	"gemini-2.0-flash": "gemini-2.0-flash",
}

# Ollama / local models — always free, never fetched.
_LOCAL_MODELS: dict[str, tuple[float, float]] = {
	"qwen2.5vl:7b": (0.0, 0.0),
	"qwen2.5vl:32b": (0.0, 0.0),
	"gemma3:27b": (0.0, 0.0),
	"qwen3:8b": (0.0, 0.0),
	"qwen3-vl:32b": (0.0, 0.0),
}


def _should_update(force: bool = False) -> bool:
	"""Return True if pricing.json is missing or was not updated today."""
	if force:
		return True
	if not PRICING_FILE.exists():
		return True
	try:
		data = json.loads(PRICING_FILE.read_text())
		last = data.get("_updated")
		if not last:
			return True
		return last != datetime.now(timezone.utc).strftime("%Y-%m-%d")
	except (json.JSONDecodeError, KeyError):
		return True


def update_pricing(force: bool = False) -> dict[str, tuple[float, float]]:
	"""Fetch pricing from litellm and write pricing.json.

	Returns the pricing dict: {model: (input_per_1M, output_per_1M)}.
	Skips the fetch if already updated today (unless force=True).
	"""
	if not _should_update(force):
		data = json.loads(PRICING_FILE.read_text())
		print(f"[pricing] Already up-to-date ({data['_updated']}), skipping fetch.")
		# Reconstruct dict without metadata keys
		return {k: (v[0], v[1]) for k, v in data.items() if not k.startswith("_")}

	print("[pricing] Fetching latest pricing from litellm...")
	try:
		resp = httpx.get(LITELLM_URL, timeout=30.0)
		resp.raise_for_status()
		litellm_data = resp.json()
	except (httpx.HTTPError, json.JSONDecodeError) as e:
		print(f"[pricing] Fetch failed: {e}")
		if PRICING_FILE.exists():
			print("[pricing] Using cached pricing.json as fallback.")
			data = json.loads(PRICING_FILE.read_text())
			return {k: (v[0], v[1]) for k, v in data.items() if not k.startswith("_")}
		print("[pricing] No cached pricing available. Using empty pricing.")
		return {}

	# Extract pricing for our models.
	# litellm stores cost per-token; we convert to per-1M-tokens.
	pricing: dict[str, tuple[float, float]] = {}
	for our_name, litellm_key in _MODEL_MAP.items():
		entry = litellm_data.get(litellm_key)
		if entry and isinstance(entry, dict):
			input_per_token = entry.get("input_cost_per_token", 0)
			output_per_token = entry.get("output_cost_per_token", 0)
			pricing[our_name] = (
				round(input_per_token * 1_000_000, 4),
				round(output_per_token * 1_000_000, 4),
			)
		else:
			print(f"[pricing] Model '{our_name}' not found in litellm data, skipping.")

	# Add local models (always free).
	pricing.update(_LOCAL_MODELS)

	# Write to pricing.json with metadata.
	output = {"_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
	output.update({k: list(v) for k, v in sorted(pricing.items())})
	PRICING_FILE.write_text(json.dumps(output, indent=2) + "\n")

	print(f"[pricing] Updated {len(pricing)} models → {PRICING_FILE.name}")
	return pricing


if __name__ == "__main__":
	force = "--force" in sys.argv
	result = update_pricing(force=force)
	if result:
		print(f"\n{'Model':<30} {'Input/1M':>10} {'Output/1M':>10}")
		print("-" * 52)
		for model, (inp, out) in sorted(result.items()):
			print(f"{model:<30} ${inp:>8.4f}  ${out:>8.4f}")
