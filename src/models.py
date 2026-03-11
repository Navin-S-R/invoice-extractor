"""Pydantic models matching ERPNext v15+ Purchase Invoice schema."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Address(BaseModel):
    """Structured address with key-wise segregation."""
    address_line1: str = Field(default="", description="Street / building / door number")
    address_line2: str = Field(default="", description="Area / locality / landmark")
    city: str = Field(default="", description="City or town")
    state: str = Field(default="", description="State or province or region")
    pincode: str = Field(default="", description="PIN / ZIP / postal code")
    country: str = Field(default="", description="Country name")
    state_code: str = Field(default="", description="State/region code (e.g. GST state code 29, US state CA)")
    phone: str = Field(default="", description="Phone number if printed")
    email: str = Field(default="", description="Email if printed")


class BankDetails(BaseModel):
    """Structured bank details for payment."""
    bank_name: str = Field(default="", description="Bank name")
    branch: str = Field(default="", description="Branch name")
    account_number: str = Field(default="", description="Bank account number")
    ifsc_code: str = Field(default="", description="IFSC code (Indian banks)")
    swift_code: str = Field(default="", description="SWIFT/BIC code")
    iban: str = Field(default="", description="IBAN (international bank account number)")
    routing_number: str = Field(default="", description="Routing/sort code (US/UK banks)")
    account_type: str = Field(default="", description="Current / Savings / Checking")


class TaxIdentifiers(BaseModel):
    """Tax registration identifiers — works across jurisdictions."""
    gstin: str = Field(default="", description="GSTIN (India, 15-char)")
    pan: str = Field(default="", description="PAN (India, 10-char)")
    vat_id: str = Field(default="", description="VAT ID (EU/UK/Gulf, e.g. GB123456789)")
    tax_id: str = Field(default="", description="Generic Tax ID / TIN / EIN / ABN / UEN")
    tax_id_type: str = Field(default="", description="Type label: GSTIN, VAT, EIN, TIN, ABN, UEN, CRN, etc.")


class PurchaseInvoiceItem(BaseModel):
    item_code: str = Field(default="", description="Item code from ERPNext")
    item_name: str = Field(..., description="Name of the item")
    description: str = Field(default="", description="Item description")
    qty: float = Field(..., description="Quantity")
    uom: str = Field(default="Nos", description="Unit of measure")
    rate: float = Field(..., description="Rate per unit")
    amount: Optional[float] = Field(None, description="qty * rate (gross amount before discount)")
    discount_percentage: Optional[float] = Field(None, description="Discount percentage on this item")
    discount_amount: Optional[float] = Field(None, description="Discount amount on this item")
    net_amount: Optional[float] = Field(None, description="Amount after discount (amount - discount_amount)")
    tax_rate: Optional[float] = Field(None, description="Tax rate percentage applicable to this item")
    tax_amount: Optional[float] = Field(None, description="Tax amount on this item")
    batch_no: str = Field(default="", description="Batch or lot number")
    serial_no: str = Field(default="", description="Serial number")
    hsn_sac: str = Field(default="", description="HSN/SAC code (India) or commodity code")


class PurchaseTax(BaseModel):
    charge_type: str = Field(default="On Net Total", description="Actual | On Net Total | On Previous Row Amount | On Previous Row Total")
    account_head: str = Field(default="", description="Tax account in ERPNext")
    description: str = Field(..., description="Tax description e.g. CGST 9%, VAT 20%, Sales Tax 8.875%")
    rate: Optional[float] = Field(None, description="Tax rate percentage")
    tax_amount: Optional[float] = Field(None, description="Fixed tax amount (for Actual type)")


class PurchaseInvoice(BaseModel):
    doctype: Literal["Purchase Invoice"] = "Purchase Invoice"
    naming_series: str = Field(default="ACC-PINV-.YYYY.-")

    # Supplier details
    supplier: str = Field(..., description="Supplier / vendor company name")
    supplier_name: str = Field(default="", description="Supplier display name if different")
    supplier_tax_ids: TaxIdentifiers = Field(default_factory=TaxIdentifiers, description="Supplier's tax identifiers")
    supplier_address: Address = Field(default_factory=Address, description="Supplier's registered address")
    supplier_bank: BankDetails = Field(default_factory=BankDetails, description="Supplier's bank details for payment")

    # Buyer / our company details
    company: str = Field(default="", description="Buyer / our company name")
    company_tax_ids: TaxIdentifiers = Field(default_factory=TaxIdentifiers, description="Buyer's tax identifiers")
    billing_address: Address = Field(default_factory=Address, description="Bill To address on the invoice")
    shipping_address: Address = Field(default_factory=Address, description="Ship To address (if different from billing)")
    place_of_supply: str = Field(default="", description="Place of supply (GST state / VAT country / tax jurisdiction)")

    # Invoice metadata
    posting_date: str = Field(..., description="Invoice date YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="Payment due date YYYY-MM-DD")
    bill_no: Optional[str] = Field(None, description="Supplier's invoice number")
    bill_date: Optional[str] = Field(None, description="Supplier's invoice date")
    currency: str = Field(default="INR", description="Invoice currency ISO 4217")

    # Line items, taxes, totals
    items: list[PurchaseInvoiceItem] = Field(..., description="Line items")
    taxes: Optional[list[PurchaseTax]] = Field(default=None, description="Taxes and charges")
    total: Optional[float] = Field(None, description="Net total before tax")
    discount_amount: Optional[float] = Field(None, description="Total discount amount on invoice")
    grand_total: Optional[float] = Field(None, description="Total including tax")
    remarks: str = Field(default="", description="Any additional notes")
    docstatus: int = Field(default=0, description="0=Draft, 1=Submitted")
