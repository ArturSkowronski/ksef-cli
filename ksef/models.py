"""Pydantic models for invoice fields and API responses."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class SellerData(BaseModel):
    nip: str
    name: str
    address: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "PL"


class BuyerData(BaseModel):
    nip: Optional[str] = None
    name: str
    address: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "PL"


class LineItem(BaseModel):
    name: str
    unit: str = "szt."
    quantity: Decimal = Decimal("1")
    unit_price_net: Decimal
    vat_rate: str = "23"  # "23", "8", "5", "0", "zw", "np"
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal


class InvoiceData(BaseModel):
    invoice_number: str
    issue_date: date
    sale_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_link: Optional[str] = None           # FA(3) LinkDoPlatnosci
    payment_deadline_days: Optional[int] = None  # FA(3) alternative to due_date

    seller: SellerData
    buyer: BuyerData

    items: List[LineItem] = Field(default_factory=list)

    total_net: Decimal = Decimal("0")
    total_vat: Decimal = Decimal("0")
    total_gross: Decimal = Decimal("0")

    currency: str = "PLN"
    notes: str = ""

    # Extraction metadata — not serialised to XML
    extraction_confidence: float = 1.0
    raw_text: str = ""


class InvoiceStatusResponse(BaseModel):
    processing_code: int
    processing_description: str
    reference_number: Optional[str] = None
    ksef_reference_number: Optional[str] = None
    invoice_hash: Optional[str] = None
    acquisition_timestamp: Optional[datetime] = None
