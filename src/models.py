"""Pydantic models matching ERPNext v15+ Purchase Invoice schema."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PurchaseInvoiceItem(BaseModel):
    item_code: Optional[str] = Field(None, description="Item code from ERPNext")
    item_name: str = Field(..., description="Name of the item")
    description: Optional[str] = Field(None, description="Item description")
    qty: float = Field(..., description="Quantity")
    uom: str = Field(default="Nos", description="Unit of measure")
    rate: float = Field(..., description="Rate per unit")
    amount: Optional[float] = Field(None, description="qty * rate, auto-calculated if omitted")
    discount_percentage: Optional[float] = Field(None, description="Discount percentage on this item")
    discount_amount: Optional[float] = Field(None, description="Discount amount on this item")


class PurchaseTax(BaseModel):
    charge_type: str = Field(default="On Net Total", description="Actual | On Net Total | On Previous Row Amount | On Previous Row Total")
    account_head: Optional[str] = Field(None, description="Tax account in ERPNext")
    description: str = Field(..., description="Tax description e.g. VAT 15%")
    rate: Optional[float] = Field(None, description="Tax rate percentage")
    tax_amount: Optional[float] = Field(None, description="Fixed tax amount (for Actual type)")


class PurchaseInvoice(BaseModel):
    doctype: Literal["Purchase Invoice"] = "Purchase Invoice"
    naming_series: str = Field(default="ACC-PINV-.YYYY.-")
    supplier: str = Field(..., description="Supplier name")
    supplier_name: Optional[str] = Field(None, description="Supplier display name")
    company: Optional[str] = Field(None, description="Company name in ERPNext")
    posting_date: str = Field(..., description="Invoice date YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="Payment due date YYYY-MM-DD")
    bill_no: Optional[str] = Field(None, description="Supplier's invoice number")
    bill_date: Optional[str] = Field(None, description="Supplier's invoice date")
    currency: Optional[str] = Field(default="INR", description="Invoice currency")
    items: list[PurchaseInvoiceItem] = Field(..., description="Line items")
    taxes: Optional[list[PurchaseTax]] = Field(default=None, description="Taxes and charges")
    total: Optional[float] = Field(None, description="Net total before tax")
    discount_amount: Optional[float] = Field(None, description="Total discount amount on invoice")
    grand_total: Optional[float] = Field(None, description="Total including tax")
    remarks: Optional[str] = Field(None, description="Any additional notes")
    docstatus: int = Field(default=0, description="0=Draft, 1=Submitted")
