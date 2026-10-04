"""CSV ingest + export. Bahi is only useful if you can feed it your own books
and take a clean ledger back out — this is the real-world usability layer.
"""

from __future__ import annotations

import csv
import io
from typing import Iterable

from .models import Finding, Invoice, LedgerEntry

INVOICE_FIELDS = ["id", "vendor", "invoice_no", "date",
                  "taxable_value", "gst_rate", "gst_amount", "category"]

LEDGER_FIELDS = ["date", "vendor", "amount", "reference"]

FINDING_FIELDS = ["id", "rule_id", "severity", "status", "invoice_id",
                  "title", "why", "suggestion"]

TEMPLATE_CSV = (
    ",".join(INVOICE_FIELDS) + "\n"
    'INV-001,Sri Balaji Traders,SBT-1001,2026-04-12,1000.00,18,180.00,goods\n'
    'INV-002,Metro Stationers,MS-2201,2026-04-15,500.00,15,75.00,supplies\n'
)


class IngestError(ValueError):
    """Raised with a human-readable row number when a CSV is malformed."""


def _num(row: dict, key: str, line: int) -> float:
    raw = (row.get(key) or "").strip()
    if not raw:
        raise IngestError(f"row {line}: '{key}' is empty")
    try:
        # tolerate 1,234.56 and ₹1,234.56
        return float(raw.replace(",", "").replace("₹", "").replace("Rs", "").strip())
    except ValueError:
        raise IngestError(f"row {line}: '{key}' must be a number, got {raw!r}") from None


def parse_invoices_csv(text: str) -> list[Invoice]:
    """Parse an uploaded invoices CSV into Invoice models.

    Raises :class:`IngestError` naming the offending row, so the UI can show
    the user exactly what to fix instead of failing silently.
    """
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("the file has no header row")

    header = {(f or "").strip().lower() for f in reader.fieldnames}
    missing = set(INVOICE_FIELDS) - header - {"category"}
    if missing:
        raise IngestError("missing required columns: " + ", ".join(sorted(missing)))

    invoices: list[Invoice] = []
    for line, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # skip blank lines
        data = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            invoices.append(Invoice(
                id=data.get("id") or f"INV-{line:03d}",
                vendor=data.get("vendor", ""),
                invoice_no=data.get("invoice_no", ""),
                date=data["date"],
                taxable_value=_num(data, "taxable_value", line),
                gst_rate=_num(data, "gst_rate", line),
                gst_amount=_num(data, "gst_amount", line),
                category=data.get("category") or "general",
            ))
        except (KeyError, ValueError) as exc:
            raise IngestError(f"row {line}: {exc}") from None
    if not invoices:
        raise IngestError("no invoice rows found")
    return invoices


def ledger_to_csv(ledger: Iterable[LedgerEntry]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LEDGER_FIELDS)
    for e in ledger:
        writer.writerow([e.date.isoformat(), e.vendor, f"{e.amount:.2f}", e.reference])
    return buf.getvalue()


def findings_to_csv(findings: Iterable[Finding]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(FINDING_FIELDS)
    for f in findings:
        writer.writerow([f.id, f.rule_id, f.severity, f.status, f.invoice_id or "",
                         f.title, f.why, f.suggestion])
    return buf.getvalue()
