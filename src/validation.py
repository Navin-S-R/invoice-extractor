"""Validate extraction quality for benchmarking.

Covers common AI vision extraction failures:
- Numerical hallucinations and value fabrication
- Currency symbol/separator misparses
- Digit transposition and character substitution
- Duplicate/skipped line items
- Date format ambiguity
- Watermark text leaking into data
- Calculation mismatches (items vs totals)
- Decimal precision errors
- Discount consistency
- Tax ID format validation (GSTIN, VAT, EIN, etc.)
"""

import re
from dataclasses import dataclass, field

from .models import PurchaseInvoice, TaxIdentifiers

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ── Configurable thresholds ──────────────────────────────────────────
_TOLERANCE = 0.02  # 2% tolerance for numeric comparisons
_MAGNITUDE_HIGH = 3.0  # grand_total / items_sum ratio above this warns
_MAGNITUDE_LOW = 0.5  # grand_total / items_sum ratio below this warns
_MAX_TAX_RATE = 100  # max plausible tax rate percentage
_MAX_DISCOUNT_PCT = 100  # max plausible discount percentage
_MAX_BILL_NO_LEN = 50  # bill_no longer than this warns of field leak
_MAX_TAX_ID_LEN = 30  # generic tax_id longer than this warns
_MIN_SUPPLIER_LEN = 2  # supplier name shorter than this warns
_YEAR_RANGE = (1900, 2100)  # valid year range for dates

# Indian formats
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][A-Z\d]$")
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

# International formats
_EU_VAT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,13}$")  # EU VAT: 2-letter country + alphanumeric
_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{4,30}$")
_SWIFT_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")

# Currency symbols that should NOT appear in currency code field
_CURRENCY_SYMBOLS = re.compile(r"[₹$€£¥]|Rs\.?")

# Characters that suggest OCR/vision confusion in text fields
_SUSPICIOUS_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Common watermark/stamp text patterns
_WATERMARK_PATTERNS = re.compile(r"(?i)\b(draft|copy|duplicate|sample|specimen|cancelled|void|confidential|original)\b")

# Valid ISO 4217 currency codes (common ones)
_VALID_CURRENCIES = {
	"INR",
	"USD",
	"EUR",
	"GBP",
	"JPY",
	"AUD",
	"CAD",
	"CHF",
	"CNY",
	"HKD",
	"SGD",
	"AED",
	"SAR",
	"BDT",
	"LKR",
	"NPR",
	"PKR",
	"MYR",
	"THB",
	"IDR",
	"PHP",
	"VND",
	"KRW",
	"TWD",
	"NZD",
	"ZAR",
	"BRL",
	"MXN",
	"RUB",
	"TRY",
	"SEK",
	"NOK",
	"DKK",
	"PLN",
	"CZK",
	"HUF",
	"ILS",
	"EGP",
	"KWD",
	"QAR",
	"BHD",
	"OMR",
	"JOD",
}


@dataclass
class ValidationResult:
	"""Quality checks on an extracted invoice."""

	checks_passed: int = 0
	checks_total: int = 0
	warnings: list[str] = field(default_factory=list)
	errors: list[str] = field(default_factory=list)

	@property
	def score(self) -> float:
		"""Quality score from 0.0 to 1.0."""
		return self.checks_passed / self.checks_total if self.checks_total else 0.0

	@property
	def score_pct(self) -> int:
		"""Quality score as integer percentage."""
		return round(self.score * 100)


def _is_indian_invoice(invoice: PurchaseInvoice) -> bool:
	"""Detect if this is an Indian invoice based on currency, GSTIN, or country."""
	if invoice.currency == "INR":
		return True
	if invoice.supplier_tax_ids and invoice.supplier_tax_ids.gstin:
		return True
	if invoice.company_tax_ids and invoice.company_tax_ids.gstin:
		return True
	return bool(invoice.supplier_address and invoice.supplier_address.country.lower().strip() in ("india", "in"))


def validate_invoice(invoice: PurchaseInvoice) -> ValidationResult:
	"""Run all quality checks against an extracted invoice."""
	v = ValidationResult()
	is_indian = _is_indian_invoice(invoice)

	# ── 1. Required fields ──────────────────────────────────────────
	_check(v, bool(invoice.supplier), "supplier is present", "supplier is empty")
	_check(v, bool(invoice.posting_date), "posting_date is present", "posting_date is empty")
	_check(v, len(invoice.items) > 0, "has at least 1 line item", "no line items extracted")

	# ── 2. Date format & validity ───────────────────────────────────
	for date_field in ("posting_date", "due_date", "bill_date"):
		val = getattr(invoice, date_field)
		if val:
			_check(v, bool(_DATE_RE.match(val)), f"{date_field} is YYYY-MM-DD", f"{date_field} bad format: {val}")
			if _DATE_RE.match(val):
				_check_date_valid(v, val, date_field)

	# Check date logical order: bill_date <= posting_date <= due_date
	if (
		invoice.posting_date
		and invoice.due_date
		and _DATE_RE.match(invoice.posting_date)
		and _DATE_RE.match(invoice.due_date)
	):
		_check(
			v,
			invoice.due_date >= invoice.posting_date,
			"due_date >= posting_date",
			f"due_date ({invoice.due_date}) is before posting_date ({invoice.posting_date})",
		)

	# ── 3. Currency validation ──────────────────────────────────────
	if invoice.currency:
		has_symbol = bool(_CURRENCY_SYMBOLS.search(invoice.currency))
		_check(
			v,
			not has_symbol,
			"currency has no symbols",
			f"currency contains symbol: '{invoice.currency}' — expected ISO code like INR, USD",
		)
		_check(
			v,
			len(invoice.currency) == 3 and invoice.currency.isalpha(),
			"currency is 3-letter code",
			f"currency bad format: '{invoice.currency}'",
		)
		if len(invoice.currency) == 3 and invoice.currency.isalpha():
			is_known = invoice.currency.upper() in _VALID_CURRENCIES
			if not is_known:
				v.warnings.append(f"currency '{invoice.currency}' not in common ISO 4217 list")

	# ── 4. Tax ID validation (jurisdiction-aware) ───────────────────
	_validate_tax_ids(v, invoice.supplier_tax_ids, "supplier", is_indian)
	_validate_tax_ids(v, invoice.company_tax_ids, "company", is_indian)

	# Cross-check: supplier GSTIN should contain supplier PAN
	if invoice.supplier_tax_ids:
		ids = invoice.supplier_tax_ids
		if ids.gstin and ids.pan and _GSTIN_RE.match(ids.gstin.strip().upper()):
			_check(
				v,
				ids.gstin.strip().upper()[2:12] == ids.pan.strip().upper(),
				"supplier GSTIN contains matching PAN",
				f"supplier PAN ({ids.pan}) doesn't match GSTIN chars 3-12 ({ids.gstin[2:12]})",
			)

	# ── 5. Bank details validation ──────────────────────────────────
	if invoice.supplier_bank:
		bank = invoice.supplier_bank
		if bank.ifsc_code:
			_check(
				v,
				bool(_IFSC_RE.match(bank.ifsc_code.strip().upper())),
				"supplier_bank.ifsc_code is valid format",
				f"supplier_bank.ifsc_code invalid: '{bank.ifsc_code}' (expected like HDFC0001234)",
			)
		if bank.swift_code:
			swift = bank.swift_code.replace(" ", "").strip().upper()
			_check(
				v,
				bool(_SWIFT_RE.match(swift)),
				"supplier_bank.swift_code is valid format",
				f"supplier_bank.swift_code invalid: '{bank.swift_code}' (expected 8 or 11 chars like HDFCINBB)",
			)
		if bank.iban:
			iban = bank.iban.replace(" ", "").upper()
			_check(
				v,
				bool(_IBAN_RE.match(iban)) and len(iban) >= 15,
				"supplier_bank.iban is valid format",
				f"supplier_bank.iban invalid: '{bank.iban}' (expected like DE89370400440532013000)",
			)

	# ── 6. Supplier name sanity ─────────────────────────────────────
	if invoice.supplier:
		if _WATERMARK_PATTERNS.search(invoice.supplier):
			v.warnings.append(
				f"supplier '{invoice.supplier}' contains watermark-like text "
				f"(DRAFT/COPY/SAMPLE/etc.) — may be extracted from background"
			)
		if _SUSPICIOUS_CHARS.search(invoice.supplier):
			v.warnings.append("supplier contains control characters — possible OCR error")
		if len(invoice.supplier.strip()) < _MIN_SUPPLIER_LEN:
			v.warnings.append(f"supplier name too short: '{invoice.supplier}'")

	# ── 7. Line item checks ─────────────────────────────────────────
	for i, item in enumerate(invoice.items, 1):
		prefix = f"item[{i}]"
		_check(v, bool(item.item_name), f"{prefix} has item_name", f"{prefix} missing item_name")
		_check(v, item.qty > 0, f"{prefix} qty > 0", f"{prefix} qty is {item.qty}")
		_check(v, item.rate >= 0, f"{prefix} rate >= 0", f"{prefix} rate is {item.rate}")

		# amount = qty * rate consistency (accounting for discounts)
		if item.amount is not None:
			expected = item.qty * item.rate
			if item.discount_percentage is not None and item.discount_percentage > 0:
				discount = expected * item.discount_percentage / 100
				expected_after_disc = expected - discount
				_check_numeric(v, item.amount, expected_after_disc, f"{prefix} amount matches qty*rate - discount%")
			elif item.discount_amount is not None and item.discount_amount > 0:
				expected_after_disc = expected - item.discount_amount
				_check_numeric(
					v, item.amount, expected_after_disc, f"{prefix} amount matches qty*rate - discount_amount"
				)
			else:
				_check_numeric(v, item.amount, expected, f"{prefix} amount matches qty*rate")

		# net_amount = amount - discount consistency
		if item.net_amount is not None and item.amount is not None:
			if item.discount_amount is not None and item.discount_amount > 0:
				expected_net = item.amount - item.discount_amount
				_check_numeric(
					v, item.net_amount, expected_net, f"{prefix} net_amount matches amount - discount_amount"
				)
			elif item.discount_percentage is not None and item.discount_percentage > 0:
				discount = item.amount * item.discount_percentage / 100
				expected_net = item.amount - discount
				_check_numeric(v, item.net_amount, expected_net, f"{prefix} net_amount matches amount - discount%")

		# Item-level tax validation
		if item.tax_rate is not None:
			_check(
				v,
				0 < item.tax_rate <= _MAX_TAX_RATE,
				f"{prefix} tax_rate in valid range",
				f"{prefix} tax_rate looks wrong: {item.tax_rate}%",
			)
		if item.tax_amount is not None:
			_check_decimal_precision(v, item.tax_amount, f"{prefix} tax_amount")
			if item.tax_rate is not None and item.tax_rate > 0:
				taxable = (
					item.net_amount
					if item.net_amount is not None
					else (item.amount if item.amount is not None else item.qty * item.rate)
				)
				expected_tax = taxable * item.tax_rate / 100
				_check_numeric(v, item.tax_amount, expected_tax, f"{prefix} tax_amount matches taxable * tax_rate")

		# Discount consistency
		if item.discount_percentage is not None:
			_check(
				v,
				0 <= item.discount_percentage <= _MAX_DISCOUNT_PCT,
				f"{prefix} discount_percentage in 0-100",
				f"{prefix} discount_percentage out of range: {item.discount_percentage}",
			)
		if item.discount_amount is not None and item.discount_amount > 0:
			gross = item.qty * item.rate
			_check(
				v,
				item.discount_amount <= gross,
				f"{prefix} discount_amount <= gross",
				f"{prefix} discount_amount ({item.discount_amount}) > gross ({gross})",
			)

		# Check item_name for control chars or pure numeric (likely misparse)
		if item.item_name:
			if _SUSPICIOUS_CHARS.search(item.item_name):
				v.warnings.append(f"{prefix} item_name contains control characters")
			if item.item_name.replace(".", "").replace(",", "").strip().isdigit():
				v.warnings.append(
					f"{prefix} item_name is purely numeric: '{item.item_name}' — possible column misalignment"
				)

	# ── 8. Total vs line items ───────────────────────────────────────
	items_sum = sum((item.amount if item.amount is not None else item.qty * item.rate) for item in invoice.items)
	if invoice.total is not None:
		_check_numeric(v, invoice.total, items_sum, "total matches sum of line items")

	# ── 10. Invoice-level discount ──────────────────────────────────
	if invoice.discount_amount is not None and invoice.discount_amount > 0 and invoice.total is not None:
		_check(
			v,
			invoice.discount_amount <= invoice.total,
			"discount_amount <= total",
			f"discount_amount ({invoice.discount_amount}) > total ({invoice.total})",
		)

	# ── 11. Grand total vs total + taxes ────────────────────────────
	if invoice.grand_total is not None and invoice.total is not None:
		tax_sum = 0.0
		if invoice.taxes:
			for tax in invoice.taxes:
				if tax.tax_amount is not None:
					tax_sum += tax.tax_amount
				elif tax.rate is not None and invoice.total:
					tax_sum += invoice.total * tax.rate / 100

		discount = invoice.discount_amount or 0.0
		if tax_sum > 0:
			expected_grand = invoice.total - discount + tax_sum
			_check_numeric(v, invoice.grand_total, expected_grand, "grand_total matches total - discount + taxes")
		elif discount > 0:
			_check(
				v,
				invoice.grand_total <= invoice.total,
				"grand_total <= total (discount applied)",
				f"grand_total ({invoice.grand_total}) > total ({invoice.total}) despite discount",
			)
		else:
			_check(
				v,
				invoice.grand_total >= invoice.total,
				"grand_total >= total",
				f"grand_total ({invoice.grand_total}) < total ({invoice.total})",
			)

	# ── 12. Magnitude sanity — catch 10x/100x misreads ──────────────
	if invoice.grand_total is not None and items_sum > 0:
		ratio = invoice.grand_total / items_sum
		if ratio > _MAGNITUDE_HIGH or ratio < _MAGNITUDE_LOW:
			v.warnings.append(
				f"grand_total ({invoice.grand_total}) is {ratio:.1f}x of items sum "
				f"({items_sum:.2f}) — possible magnitude error (10x/100x misread)"
			)

	# ── 13. Decimal precision (separator misparse detection) ─────────
	_check_decimal_precision(v, invoice.total, "total")
	_check_decimal_precision(v, invoice.grand_total, "grand_total")
	for i, item in enumerate(invoice.items, 1):
		_check_decimal_precision(v, item.rate, f"item[{i}] rate")
		_check_decimal_precision(v, item.amount, f"item[{i}] amount")

	# ── 14. Tax checks ──────────────────────────────────────────────
	if invoice.taxes:
		for i, tax in enumerate(invoice.taxes, 1):
			prefix = f"tax[{i}]"
			_check(v, bool(tax.description), f"{prefix} has description", f"{prefix} missing description")
			if tax.rate is not None:
				_check(
					v,
					0 < tax.rate <= _MAX_TAX_RATE,
					f"{prefix} rate in valid range",
					f"{prefix} rate looks wrong: {tax.rate}%",
				)
			if tax.tax_amount is not None:
				_check_decimal_precision(v, tax.tax_amount, f"{prefix} tax_amount")
				if invoice.grand_total and tax.tax_amount > invoice.grand_total:
					v.warnings.append(
						f"{prefix} tax_amount ({tax.tax_amount}) exceeds grand_total ({invoice.grand_total})"
					)

	# ── 15. Bill number sanity ──────────────────────────────────────
	if invoice.bill_no:
		if len(invoice.bill_no) > _MAX_BILL_NO_LEN:
			v.warnings.append(f"bill_no is unusually long ({len(invoice.bill_no)} chars) — possible field misalignment")
		if _SUSPICIOUS_CHARS.search(invoice.bill_no):
			v.warnings.append("bill_no contains control characters")

	# ── 16. Negative values detection ───────────────────────────────
	if invoice.total is not None and invoice.total < 0:
		v.warnings.append(f"total is negative ({invoice.total}) — unusual for purchase invoice")
	if invoice.grand_total is not None and invoice.grand_total < 0:
		v.warnings.append(f"grand_total is negative ({invoice.grand_total}) — unusual for purchase invoice")

	return v


# ── Helper functions ─────────────────────────────────────────────────


def _validate_tax_ids(v: ValidationResult, ids: TaxIdentifiers | None, party: str, is_indian: bool):
	"""Validate tax identifiers based on jurisdiction."""
	if ids is None:
		return

	# Indian GSTIN
	if ids.gstin:
		gstin = ids.gstin.strip().upper()
		_check(
			v,
			bool(_GSTIN_RE.match(gstin)),
			f"{party} GSTIN is valid format",
			f"{party} GSTIN invalid: '{ids.gstin}' (expected 15-char like 29AABCU9603R1ZM)",
		)

	# Indian PAN
	if ids.pan:
		_check(
			v,
			bool(_PAN_RE.match(ids.pan.strip().upper())),
			f"{party} PAN is valid format",
			f"{party} PAN invalid: '{ids.pan}' (expected 10-char like AABCU9603R)",
		)

	# EU/UK VAT ID
	if ids.vat_id:
		vat = ids.vat_id.replace(" ", "").replace(".", "").replace("-", "").upper()
		_check(
			v,
			bool(_EU_VAT_RE.match(vat)) and len(vat) >= 4,
			f"{party} VAT ID is valid format",
			f"{party} VAT ID invalid: '{ids.vat_id}' (expected like GB123456789 or DE123456789)",
		)

	# Generic tax_id — just check it's not suspiciously long or has control chars
	if ids.tax_id:
		if len(ids.tax_id) > _MAX_TAX_ID_LEN:
			v.warnings.append(f"{party} tax_id is very long ({len(ids.tax_id)} chars) — possible field leak")
		if _SUSPICIOUS_CHARS.search(ids.tax_id):
			v.warnings.append(f"{party} tax_id contains control characters")


def _check(v: ValidationResult, condition: bool, pass_msg: str, fail_msg: str):
	"""Record a pass/fail check."""
	v.checks_total += 1
	if condition:
		v.checks_passed += 1
	else:
		v.errors.append(fail_msg)


def _check_numeric(v: ValidationResult, actual: float, expected: float, label: str):
	"""Check numeric value within tolerance."""
	v.checks_total += 1
	if expected == 0:
		if abs(actual) < 0.01:
			v.checks_passed += 1
		else:
			v.errors.append(f"{label}: got {actual}, expected ~0")
		return

	diff_pct = abs(actual - expected) / abs(expected)
	if diff_pct <= _TOLERANCE:
		v.checks_passed += 1
	else:
		v.warnings.append(f"{label}: got {actual}, expected {expected:.2f} (diff {diff_pct:.1%})")


def _check_date_valid(v: ValidationResult, date_str: str, field_name: str):
	"""Check that a YYYY-MM-DD date is a real calendar date."""
	try:
		year, month, day = map(int, date_str.split("-"))
		if not (_YEAR_RANGE[0] <= year <= _YEAR_RANGE[1]):
			v.warnings.append(f"{field_name} year {year} looks unusual")
		if not (1 <= month <= 12):
			v.errors.append(f"{field_name} invalid month: {month}")
			return
		if not (1 <= day <= 31):
			v.errors.append(f"{field_name} invalid day: {day}")
			return
		from datetime import date

		date(year, month, day)
	except (ValueError, TypeError):
		v.errors.append(f"{field_name} is not a valid date: {date_str}")


def _check_decimal_precision(v: ValidationResult, value: float | None, label: str):
	"""Warn if a monetary value has more than 2 decimal places.

	This catches currency separator misparses like:
	- "12.345" from European "12,345" (should be 12345)
	- "1.500" from European "1.500" (should be 1500)
	"""
	if value is None:
		return
	rounded = round(value, 2)
	if abs(value - rounded) > 1e-9:
		v.warnings.append(f"{label} has >2 decimal places: {value} (expected {rounded})")
