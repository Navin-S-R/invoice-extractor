"""Extract invoice data from PDF/PNG files using AI Vision APIs."""

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .config import get_schema
from .models import PurchaseInvoice


@dataclass
class ExtractionResult:
    """Raw extraction output with API response metadata."""
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    latency_seconds: float = 0.0

SYSTEM_PROMPT = """
You are a highly accurate financial document parser specialized in extracting structured invoice data for ERP systems.

Your task is to analyze the provided invoice image or document and extract all identifiable information into a JSON object that strictly follows the provided ERPNext Purchase Invoice schema.

OBJECTIVE
Extract structured invoice data including supplier details, invoice metadata, line items, taxes, and totals.

STRICT OUTPUT RULES
- Return ONLY a valid JSON object.
- Do NOT include markdown, comments, explanations, or additional text.
- The output must strictly conform to the provided JSON schema.
- If a field cannot be determined from the document, return null.
- Do not invent values.

DATA NORMALIZATION RULES
- Dates must follow YYYY-MM-DD format.
- Monetary values must be pure numbers — strip ALL currency symbols (₹, $, €, £, ¥, Rs., etc.) and thousand separators.
- CRITICAL — Currency separator handling:
  - Indian/US format: commas for thousands, dot for decimals → "1,23,456.78" or "12,345.67" means 123456.78 or 12345.67
  - European format: dots for thousands, comma for decimals → "12.345,67" means 12345.67
  - Detect the format from context (currency, locale cues on the invoice) and convert correctly.
  - The final numeric value must use dot as decimal separator with NO thousand separators.
- Quantities and rates must be numbers.
- If amount is missing but qty and rate are present, calculate: amount = qty * rate.
- Trim whitespace from all text fields.

FIELD EXTRACTION GUIDELINES

Supplier Information (seller/vendor)
- supplier: official supplier/company name on the invoice
- supplier_name: display name if different from supplier
- supplier_tax_ids: structured object for ALL tax registration numbers found:
  - gstin: 15-character Indian GSTIN (e.g. "29AABCU9603R1ZM"). Labels: "GSTIN", "GST No", "GST IN"
  - pan: 10-character Indian PAN (e.g. "AABCU9603R"). Labels: "PAN", "PAN No"
  - vat_id: VAT registration number for EU/UK/Gulf (e.g. "GB123456789", "DE123456789", "FR12345678901"). Labels: "VAT ID", "VAT No", "VAT Reg", "USt-IdNr", "TVA", "BTW", "TRN"
  - tax_id: any other tax/registration ID — US EIN, AU ABN, SG UEN, SA CRN, etc.
  - tax_id_type: label describing tax_id (e.g. "EIN", "ABN", "UEN", "CRN", "TIN", "Tax Reg No")
  - Populate whichever fields match the invoice's jurisdiction. Leave others as "".
- supplier_address: structured object:
  - address_line1: street / building / door number
  - address_line2: area / locality / landmark
  - city: city or town
  - state: state / province / region / canton / emirate
  - pincode: PIN / ZIP / postal code (any format)
  - country: country name (detect from address or currency context)
  - state_code: state/region code if present (Indian GST code, US state abbrev, etc.)
  - phone: phone number if printed near the address
  - email: email if printed near the address
- supplier_bank: structured object for payment/bank details:
  - bank_name: bank name
  - branch: branch name if shown
  - account_number: bank account number
  - ifsc_code: IFSC code (Indian banks only, e.g. "HDFC0002047")
  - swift_code: SWIFT/BIC code (e.g. "HDFCINBB")
  - iban: IBAN (EU/UK/Gulf/international, e.g. "DE89370400440532013000")
  - routing_number: ABA routing number (US) or sort code (UK)
  - account_type: "Current" / "Savings" / "Checking" if mentioned

Buyer/Company Information (our company — the purchaser)
- company: buyer/company name (labels: "Bill To", "Buyer", "Sold To", "Invoice To", "Customer")
- company_tax_ids: structured object (same keys as supplier_tax_ids) for the buyer
- billing_address: structured object (same keys as supplier_address) from "Bill To" section
- shipping_address: structured object (same keys as supplier_address) from "Ship To" / "Deliver To" section. If no separate shipping address, leave all fields as empty strings.
- place_of_supply: tax jurisdiction for supply — Indian GST state, EU member state, or country name

Invoice Metadata
- bill_no: invoice number
- bill_date: invoice issue date
- posting_date: invoice date or document date
- due_date: payment due date if available
- currency: 3-letter ISO 4217 code (e.g. INR, USD, EUR, GBP). Do NOT return currency symbols like ₹, $, €. Detect from symbol/context on the invoice.

Line Items
For each product/service row extract:
- item_name
- description
- qty
- uom
- rate
- amount (after discount if applicable)
- discount_percentage (if a percentage discount is shown on the line)
- discount_amount (if a fixed discount amount is shown on the line)
- hsn_sac: HSN/SAC code (India), HS code, commodity code, or tariff code if shown

If a line item has a discount:
- rate should be the ORIGINAL unit price before discount
- amount should be the FINAL amount after discount: (qty * rate) - discount
- If only discounted price is shown, use that as rate and leave discount fields null

If UOM is not present use:
- "Nos" for goods and services

Taxes
Extract ALL taxes, duties, or charges including:
- description: e.g. "CGST @ 9%", "SGST @ 9%", "IGST @ 18%", "VAT 20%", "Sales Tax 8.875%", "WHT 10%", "Service Tax", "Customs Duty"
- rate (percentage if visible)
- tax_amount
- charge_type (On Net Total, Actual, etc.)
- Country-specific tax handling:
  - India: extract CGST, SGST, IGST, cess as separate entries
  - EU/UK: extract VAT (may be multiple rates like 0%, 5%, 20%)
  - US: extract Sales Tax, Use Tax (may vary by state/city)
  - Gulf (UAE/SA/etc.): extract VAT (usually 5% or 15%)
  - Any country: extract withholding tax (WHT/TDS) if shown
- If only a combined tax amount is shown, extract it as a single entry

Totals
Extract:
- total (subtotal before tax, after all discounts)
- discount_amount (total invoice-level discount if shown separately)
- grand_total (final invoice amount including taxes)

Additional Fields
- remarks: notes, references, or comments
- doctype: always "Purchase Invoice"
- docstatus: always 0 unless clearly marked as submitted

ANTI-HALLUCINATION RULES (CRITICAL)
- NEVER fabricate or guess values. If you cannot clearly read a value, return null.
- NEVER round numbers. Extract the exact value shown on the invoice.
- NEVER transpose digits. Double-check each number matches the document exactly.
- NEVER paraphrase item names or descriptions. Copy the EXACT text as printed.
- NEVER merge or split line items. Each row in the invoice table = one item in the output.
- Do NOT skip any line items, even if they have missing fields. Extract what is visible.
- Do NOT confuse similar-looking characters: 0 vs O, 1 vs l vs I, 5 vs S, 8 vs B.
- Verify your math: sum of line item amounts should equal the total.

DOCUMENT STRUCTURE RULES
- Ignore watermarks, stamps, logos, letterheads, and decorative elements.
- Do NOT extract text from watermarks or background images as supplier/item data.
- If multiple invoices appear in one document, extract ONLY the primary/first invoice.
- For multi-page documents, ensure line items from ALL pages are captured.
- Preserve the exact order of line items as shown on the invoice.

DATE DISAMBIGUATION
- If the date format is ambiguous (e.g., "01/02/2024"), use these rules:
  - Check for other dates on the invoice to determine the format pattern.
  - If the day value > 12, the format is clear (e.g., "25/01/2024" = 2024-01-25).
  - Detect from country/locale context:
    - DD/MM/YYYY: India (INR), EU (EUR), UK (GBP), Australia (AUD), Gulf (AED/SAR), most of Asia/Africa
    - MM/DD/YYYY: United States (USD), Philippines (PHP)
    - YYYY/MM/DD: Japan (JPY), China (CNY), Korea (KRW), ISO standard
  - Look for month names (Jan, Feb, März, janvier) as disambiguation clues.
  - Always output in YYYY-MM-DD format regardless of input format.

NUMERIC CONSISTENCY
- Ensure: sum of item amounts ≈ total (before tax).
- Ensure: total + taxes ≈ grand_total.
- If extracted numbers don't add up, re-read the document carefully before submitting.
- If a value looks suspiciously round (e.g., exactly 1000.00 when items suggest 987.50), verify it.
"""

USER_PROMPT = """
Extract all invoice data from the provided document image.

Return the result as a JSON object that strictly follows the provided ERPNext Purchase Invoice schema.
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
        text = text[first_newline + 1:]
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
        candidate = text[start:end + 1]
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
    raise ValueError(
        f"Failed to parse JSON from model output. "
        f"Raw text (first 500 chars): {raw_text[:500]}"
    )


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
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
    content.append({"type": "text", "text": USER_PROMPT})

    # Anthropic's output_config structured output has strict schema limits.
    # Use prompt-based JSON extraction with robust parsing instead.
    schema_text = json.dumps(schema, indent=2)
    system_with_schema = (
        SYSTEM_PROMPT
        + f"\n\nJSON SCHEMA (your output MUST conform to this):\n```json\n{schema_text}\n```"
    )

    start = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
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
        image_inputs.append({
            "type": "input_image",
            "image_url": f"data:{media_type};base64,{b64}",
        })

    start = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
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

    start = time.perf_counter()
    response = client.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=schema,
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


_PROVIDERS = {
    "anthropic": _extract_anthropic,
    "openai": _extract_openai,
    "google": _extract_google,
}


def extract_invoice(
    file_path: Path,
    provider: str,
    model: str,
    api_key: str,
) -> tuple[PurchaseInvoice, ExtractionResult]:
    """Extract invoice data from a single PDF or image file.

    Returns (invoice, extraction_result) where extraction_result contains
    API response metrics (tokens, latency, stop reason).
    """
    extract_fn = _PROVIDERS.get(provider)
    if not extract_fn:
        raise ValueError(f"Unsupported provider: '{provider}'. Choose from: {', '.join(_PROVIDERS)}")

    schema = get_schema()
    result = extract_fn(file_path, model, api_key, schema)
    _coerce_nulls(result.data, schema)
    invoice = PurchaseInvoice(**result.data)
    return invoice, result


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
        elif prop_type == "array" and isinstance(data[key], list):
            item_schema = prop.get("items", {})
            if item_schema.get("type") == "object":
                for item_data in data[key]:
                    if isinstance(item_data, dict):
                        _coerce_nulls(item_data, item_schema)
        # Nullable array — same but check for list type
        elif isinstance(prop_type, list) and "array" in prop_type and isinstance(data[key], list):
            item_schema = prop.get("items", {})
            if item_schema.get("type") == "object":
                for item_data in data[key]:
                    if isinstance(item_data, dict):
                        _coerce_nulls(item_data, item_schema)
