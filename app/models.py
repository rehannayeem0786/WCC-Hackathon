"""Domain models for Bahi (pydantic v2)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Valid Indian GST slabs (percent). Used by rule R1.1.
GST_SLABS: tuple[float, ...] = (0.0, 5.0, 12.0, 18.0, 28.0)

# Rupee tolerance for "does the math line up" checks.
AMOUNT_TOLERANCE = 1.0


class Invoice(BaseModel):
    """A purchase invoice / bill as the owner would upload it."""

    id: str
    vendor: str
    invoice_no: str
    date: date
    taxable_value: float = Field(description="value before GST, in rupees")
    gst_rate: float = Field(description="GST rate in percent, e.g. 18")
    gst_amount: float = Field(description="GST actually charged, in rupees")
    category: str = "general"

    @property
    def total(self) -> float:
        return round(self.taxable_value + self.gst_amount, 2)

    def expected_gst(self) -> float:
        return round(self.taxable_value * self.gst_rate / 100.0, 2)


class LedgerEntry(BaseModel):
    """A line already recorded in the owner's ledger / bank statement."""

    id: str
    date: date
    vendor: str
    amount: float
    reference: str = ""


Severity = Literal["info", "warn", "error"]
FindingStatus = Literal["open", "approved", "rejected"]


class Finding(BaseModel):
    """One thing the engine noticed, ready for a human to act on.

    A finding is deliberately *explainable*: it carries the rule id, a
    plain-language ``why``, the raw ``evidence`` it was derived from, and the
    exact ``proposed_action`` that will be applied if a human approves it.
    """

    id: str
    rule_id: str
    severity: Severity
    title: str
    invoice_id: Optional[str] = None
    why: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggestion: str = ""
    proposed_action: dict[str, Any] = Field(default_factory=dict)
    status: FindingStatus = "open"
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    # snapshot of the pre-approval values, so an approval can be REVOKED
    # (responsible design: every change must be reversible)
    reversal: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """Immutable trail entry. Nothing is written without one of these."""

    at: str
    action: str
    finding_id: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)
