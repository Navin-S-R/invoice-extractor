"""Extract invoice data from PDF/PNG files using AI Vision APIs."""

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .config import OLLAMA_BASE_URL, get_schema, get_system_prompt
from .models import PurchaseInvoice


@dataclass
class ExtractionResult:
    """Raw extraction output with API response metadata."""

    data: dict
    confidence_scores: dict | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    latency_seconds: float = 0.0


USER_PROMPT = """
Extract all invoice data from the provided document image.

Return a JSON object with two keys:
1. "data": the extracted invoice data conforming to the provided schema.
2. "confidence_scores": a parallel structure where each leaf value is an integer 0-100 representing visual clarity confidence.

Ensure the output contains only valid JSON.
"""


def _parse_json_robust(raw_text: str) -> dict:
    """Parse JSON from model output, handling common malformed responses.

    Models sometimes return:
    - Markdown-wrapped JSON (```json ... ```)
    - Leading/trailing text around JSON
    - Trailing commas
    - Single quotes instead of double quotes
    """
    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1 :]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract JSON object from surrounding text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Try fixing trailing commas: ,} or ,]
        import re

        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    # Nothing worked — raise with the original text for debugging
    raise ValueError(f"Failed to parse JSON from model output. Raw text (first 500 chars): {raw_text[:500]}")


_MAX_IMAGE_BYTES = 4_800_000  # stay under Anthropic's 5MB limit


def _resize_if_needed(img_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Shrink image if it exceeds the API size limit. Returns JPEG to save space."""
    if len(img_bytes) <= _MAX_IMAGE_BYTES:
        return img_bytes, media_type
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(img_bytes))
    # Progressively reduce until under limit
    for quality in (85, 70, 55, 40):
        for scale in (1.0, 0.75, 0.5):
            w, h = int(img.width * scale), int(img.height * scale)
            resized = img.resize((w, h), Image.LANCZOS) if scale < 1.0 else img
            buf = BytesIO()
            resized.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= _MAX_IMAGE_BYTES:
                return buf.getvalue(), "image/jpeg"
    # Last resort: force smallest
    buf = BytesIO()
    img.resize((img.width // 2, img.height // 2), Image.LANCZOS).save(buf, format="JPEG", quality=30)
    return buf.getvalue(), "image/jpeg"


def pdf_to_images(pdf_path: Path) -> list[tuple[bytes, str]]:
    """Convert each PDF page to an image. Returns list of (image_bytes, media_type)."""
    images = []
    doc = fitz.open(str(pdf_path))
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        img_bytes, media_type = _resize_if_needed(img_bytes, "image/png")
        images.append((img_bytes, media_type))
    doc.close()
    return images


def load_image(image_path: Path) -> tuple[bytes, str]:
    """Load a PNG/JPG image file. Returns (image_bytes, media_type)."""
    suffix = image_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_types.get(suffix, "image/png")
    img_bytes = image_path.read_bytes()
    return _resize_if_needed(img_bytes, media_type)


def get_file_images(file_path: Path) -> list[tuple[bytes, str]]:
    """Get images from a PDF or image file."""
    if file_path.suffix.lower() == ".pdf":
        return pdf_to_images(file_path)
    return [load_image(file_path)]


# --- Provider-specific extraction ---


def _prepare_anthropic_schema(schema: dict) -> dict:
    """Make a schema compatible with Anthropic's structured output API.

    Anthropic requires:
    - 'additionalProperties': false on every object
    - No array-style nullable types like {"type": ["string", "null"]}
      — must use {"anyOf": [{"type": "string"}, {"type": "null"}]}
    """
    import copy

    schema = copy.deepcopy(schema)

    def _patch(node: dict):
        if not isinstance(node, dict):
            return
        # Convert {"type": ["X", "null"]} to {"anyOf": [...]}
        t = node.get("type")
        if isinstance(t, list):
            node.pop("type")
            branches = []
            for x in t:
                branch = {"type": x}
                # Move type-specific keys into the correct branch
                if x == "array" and "items" in node:
                    branch["items"] = node.pop("items")
                if x == "object" and "properties" in node:
                    branch["properties"] = node.pop("properties")
                    branch["additionalProperties"] = False
                    if "required" in node:
                        branch["required"] = node.pop("required")
                branches.append(branch)
            node["anyOf"] = branches
        # Add additionalProperties: false for objects
        if node.get("type") == "object":
            node["additionalProperties"] = False
        # Also handle anyOf containing objects
        if "anyOf" in node:
            for option in node["anyOf"]:
                _patch(option)
        # Recurse into all nested dicts/lists
        for key, value in list(node.items()):
            if key == "anyOf":
                continue  # already handled above
            if isinstance(value, dict):
                _patch(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _patch(item)

    _patch(schema)
    return schema


def _extract_anthropic(file_path: Path, model: str, api_key: str, schema: dict) -> ExtractionResult:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    images = get_file_images(file_path)

    content: list[dict] = []
    for img_bytes, media_type in images:
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        )
    content.append({"type": "text", "text": USER_PROMPT})

    # Anthropic's output_config structured output has strict schema limits.
    # Use prompt-based JSON extraction with robust parsing instead.
    schema_text = json.dumps(schema, indent=2)
    system_prompt = get_system_prompt()
    system_with_schema = (
        system_prompt + f"\n\nJSON SCHEMA (your output MUST conform to this):\n```json\n{schema_text}\n```"
    )

    start = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=16384,
        system=system_with_schema,
        messages=[{"role": "user", "content": content}],
    )
    latency = time.perf_counter() - start

    raw_text = next(b.text for b in response.content if b.type == "text")
    return ExtractionResult(
        data=_parse_json_robust(raw_text),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason or "",
        latency_seconds=latency,
    )


def _extract_openai(file_path: Path, model: str, api_key: str, schema: dict) -> ExtractionResult:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    images = get_file_images(file_path)

    # Build image input blocks
    image_inputs = []
    for img_bytes, media_type in images:
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        image_inputs.append(
            {
                "type": "input_image",
                "image_url": f"data:{media_type};base64,{b64}",
            }
        )

    system_prompt = get_system_prompt()
    start = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=[
            *image_inputs,
            {"type": "input_text", "text": USER_PROMPT},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "purchase_invoice",
                "schema": schema,
                "strict": False,
            }
        },
    )
    latency = time.perf_counter() - start

    usage = response.usage
    raw_text = response.output_text
    return ExtractionResult(
        data=_parse_json_robust(raw_text),
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        stop_reason=response.status or "",
        latency_seconds=latency,
    )


def _prepare_google_schema(schema: dict) -> dict:
    """Make a schema compatible with Google's Gemini API.

    Gemini requires a single type string, not array-style nullable types.
    Converts {"type": ["string", "null"]} to {"type": "STRING", "nullable": true}.
    """
    import copy

    schema = copy.deepcopy(schema)

    def _patch(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            node["type"] = non_null[0] if non_null else "string"
            if "null" in t:
                node["nullable"] = True
        for _key, value in list(node.items()):
            if isinstance(value, dict):
                _patch(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _patch(item)

    _patch(schema)
    return schema


def _extract_google(file_path: Path, model: str, api_key: str, schema: dict) -> ExtractionResult:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    images = get_file_images(file_path)

    # Build multimodal parts
    parts = []
    for img_bytes, media_type in images:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=media_type))
    parts.append(types.Part.from_text(text=USER_PROMPT))

    system_prompt = get_system_prompt()
    schema_text = json.dumps(schema, indent=2)
    system_with_schema = (
        system_prompt + f"\n\nJSON SCHEMA (your output MUST conform to this):\n```json\n{schema_text}\n```"
    )
    start = time.perf_counter()
    response = client.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=system_with_schema,
            response_mime_type="application/json",
        ),
    )
    latency = time.perf_counter() - start

    # Usage metadata from new SDK
    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count if usage else 0
    output_tokens = usage.candidates_token_count if usage else 0
    stop_reason = ""
    if response.candidates:
        stop_reason = str(response.candidates[0].finish_reason)

    return ExtractionResult(
        data=_parse_json_robust(response.text),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
        latency_seconds=latency,
    )


# Per-model context window sizes for Ollama.
# Sized for a 64GB RAM machine — balances context capacity vs KV cache memory.
_OLLAMA_NUM_CTX = {
    "qwen3-vl:32b": 65536,  # 128K native, ~16GB KV cache
    "qwen2.5vl:32b": 32768,  # 32K native,  ~8GB KV cache
    "qwen2.5vl:7b": 32768,  # 32K native,  ~4GB KV cache
    "gemma3:27b": 65536,  # 128K native, ~14GB KV cache
}
_OLLAMA_NUM_CTX_DEFAULT = 32768


def _extract_ollama(file_path: Path, model: str, api_key: str, schema: dict) -> ExtractionResult:
    """Extract using a local Ollama model via its native /api/chat endpoint.

    Uses Ollama's native API (not the OpenAI compat layer) because the native
    endpoint handles vision/image payloads more reliably across model families.
    """
    import httpx

    images = get_file_images(file_path)

    system_prompt = get_system_prompt()
    schema_text = json.dumps(schema, indent=2)
    system_with_schema = (
        system_prompt + f"\n\nJSON SCHEMA (your output MUST conform to this):\n```json\n{schema_text}\n```"
    )

    # Ollama native format: images are raw base64 strings (no data-uri prefix)
    image_b64_list = [base64.standard_b64encode(img_bytes).decode("utf-8") for img_bytes, _ in images]

    num_ctx = _OLLAMA_NUM_CTX.get(model, _OLLAMA_NUM_CTX_DEFAULT)

    # Disable thinking mode for qwen3 models — it generates thousands of
    # internal reasoning tokens before the JSON, causing timeouts.
    # /no_think makes it output the answer directly.
    user_content = USER_PROMPT
    if "qwen3" in model.lower():
        user_content = "/no_think " + USER_PROMPT

    payload = {
        "model": model,
        "keep_alive": "10m",
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
        "messages": [
            {"role": "system", "content": system_with_schema},
            {
                "role": "user",
                "content": user_content,
                "images": image_b64_list,
            },
        ],
    }

    # Large models (32B+ with 64K ctx) can take several minutes to load
    # into VRAM and generate output.  Use generous per-phase timeouts:
    #   connect  = 120s  (model loading / cold start)
    #   read     = 1800s (token generation — qwen3 models can be slow)
    #   write    = 120s  (sending large base64 image payloads)
    #   pool     = 60s
    timeout = httpx.Timeout(connect=120.0, read=1800.0, write=120.0, pool=60.0)

    start = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
    latency = time.perf_counter() - start

    data = resp.json()
    raw_text = data.get("message", {}).get("content", "")
    input_tokens = data.get("prompt_eval_count", 0)
    output_tokens = data.get("eval_count", 0)
    stop_reason = data.get("done_reason", "")

    return ExtractionResult(
        data=_parse_json_robust(raw_text),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
        latency_seconds=latency,
    )


_PROVIDERS = {
    "anthropic": _extract_anthropic,
    "openai": _extract_openai,
    "google": _extract_google,
    "ollama": _extract_ollama,
}


_MAX_RETRIES = 3
_RETRY_BACKOFF = [15, 30, 60]  # seconds to wait on rate-limit (429) errors


def extract_invoice(
    file_path: Path,
    provider: str,
    model: str,
    api_key: str,
) -> tuple[PurchaseInvoice, ExtractionResult]:
    """Extract invoice data from a single PDF or image file.

    Returns (invoice, extraction_result) where extraction_result contains
    API response metrics (tokens, latency, stop reason).
    Retries automatically on rate-limit (429) errors with exponential backoff.
    """
    extract_fn = _PROVIDERS.get(provider)
    if not extract_fn:
        raise ValueError(f"Unsupported provider: '{provider}'. Choose from: {', '.join(_PROVIDERS)}")

    schema = get_schema()

    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = extract_fn(file_path, model, api_key, schema)

            # Split envelope: model returns {"data": {...}, "confidence_scores": {...}}
            raw = result.data
            if "data" in raw and isinstance(raw["data"], dict):
                result.data = raw["data"]
                result.confidence_scores = raw.get("confidence_scores")
            # Fallback: model returned flat invoice data (no envelope)

            _coerce_nulls(result.data, schema)
            invoice = PurchaseInvoice(**result.data)
            return invoice, result
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate" in err_str or "overloaded" in err_str
            if is_rate_limit and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF[attempt]
                print(
                    f"\n    Rate limited, retrying in {wait}s (attempt {attempt + 2}/{_MAX_RETRIES + 1})...",
                    end=" ",
                    flush=True,
                )
                time.sleep(wait)
                last_err = e
            else:
                raise
    raise last_err  # type: ignore[misc]


def _coerce_nulls(data: dict, schema: dict):
    """Convert null values to "" for non-nullable string fields.

    Models may return null for fields the schema defines as plain strings.
    This prevents Pydantic validation errors.
    """
    props = schema.get("properties", {})
    for key, prop in props.items():
        if key not in data:
            continue
        prop_type = prop.get("type")
        # Plain string field but got None -> coerce to ""
        if prop_type == "string" and data[key] is None:
            data[key] = ""
        # Plain integer field but got None -> coerce to 0
        elif prop_type == "integer" and data[key] is None:
            data[key] = 0
        # Nested object — recurse and coerce nulls within
        elif prop_type == "object" and isinstance(data[key], dict):
            _coerce_nulls(data[key], prop)
        elif prop_type == "object" and data[key] is None:
            data[key] = {}
        # Array of objects — recurse into each item
        elif (
            prop_type == "array"
            and isinstance(data[key], list)
            or isinstance(prop_type, list)
            and "array" in prop_type
            and isinstance(data[key], list)
        ):
            item_schema = prop.get("items", {})
            if item_schema.get("type") == "object":
                for item_data in data[key]:
                    if isinstance(item_data, dict):
                        _coerce_nulls(item_data, item_schema)
