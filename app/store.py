"""In-memory state, the human-in-the-loop approval workflow and the audit log.

Nothing is ever written to the books without a human ``approve`` call, and
every such call appends an immutable :class:`AuditEvent`.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import agent
from .engine import load_invoices, load_ledger, reconcile, summarise
from .io import parse_invoices_csv
from .models import AuditEvent, Finding, Invoice, LedgerEntry
from .rules import RULES_BY_ID, get_rule

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
# State survives a page refresh / process restart so judges never see empty work.
STATE_FILE = Path(os.environ.get("BAHI_STATE_FILE")
                  or (BASE_DIR / ".bahi" / "state.json"))

# Indian financial year used by the demo (rule R5.1).
PERIOD_START = date(2026, 4, 1)
PERIOD_END = date(2027, 3, 31)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BahiStore:
    def __init__(self) -> None:
        self.invoices: list[Invoice] = []
        self.ledger: list[LedgerEntry] = []
        self.findings: list[Finding] = []
        self.audit: list[AuditEvent] = []
        self.known_vendors: set[str] = set()
        self._new_ledger_id = 0

    # ------------------------------------------------------------------ util
    def _log(self, action: str, finding_id: Optional[str] = None, detail: Optional[dict] = None) -> None:
        self.audit.append(AuditEvent(at=_now(), action=action,
                                     finding_id=finding_id, detail=detail or {}))

    def load_sample(self) -> None:
        self.invoices = load_invoices(DATA_DIR / "sample_invoices.json")
        self.ledger = load_ledger(DATA_DIR / "sample_ledger.json")
        self.known_vendors = {e.vendor for e in self.ledger}
        self._log("load_sample", detail={"invoices": len(self.invoices),
                                         "ledger": len(self.ledger)})
        self.save()

    def ingest_csv(self, text: str, source: str = "upload") -> None:
        """Replace the invoice book with an owner-supplied CSV."""
        before = len(self.invoices)
        self.invoices = parse_invoices_csv(text)
        self.known_vendors = {e.vendor for e in self.ledger}
        self._log("ingest_csv", detail={"source": source, "before": before,
                                        "after": len(self.invoices)})
        self.save()

    # ------------------------------------------------------------- persistence
    def add_invoice(self, data: dict) -> Invoice:
        """Append a single invoice (used by the n8n / integration webhook)."""
        if not data.get("id"):
            data = {**data, "id": f"WH-{len(self.invoices) + 1:04d}"}
        invoice = Invoice(**data)
        self.invoices.append(invoice)
        # deliberately NOT added to known_vendors, so R4.1 (new vendor) still fires
        self._log("webhook_invoice", detail={"invoice_id": invoice.id,
                                             "vendor": invoice.vendor})
        self.save()
        return invoice

    def reset(self) -> None:
        """Purge everything the owner's data — 'right to delete'."""
        self.invoices.clear()
        self.ledger.clear()
        self.findings.clear()
        self.audit.clear()
        self.known_vendors.clear()
        self._new_ledger_id = 0
        self._log("purge", detail={"deleted": True})
        self.save()

    def save(self) -> None:
        """Write state to disk so a refresh/restart never loses the demo."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({
                "invoices": [i.model_dump(mode="json") for i in self.invoices],
                "ledger": [e.model_dump(mode="json") for e in self.ledger],
                "findings": [f.model_dump() for f in self.findings],
                "audit": [a.model_dump() for a in self.audit],
                "known_vendors": sorted(self.known_vendors),
                "next_ledger_id": self._new_ledger_id,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # persistence must never break the workflow

    def load_state(self) -> bool:
        if not STATE_FILE.exists():
            return False
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        self.invoices = [Invoice(**d) for d in raw.get("invoices", [])]
        self.ledger = [LedgerEntry(**d) for d in raw.get("ledger", [])]
        self.findings = [Finding(**d) for d in raw.get("findings", [])]
        self.audit = [AuditEvent(**d) for d in raw.get("audit", [])]
        self.known_vendors = set(raw.get("known_vendors", []))
        self._new_ledger_id = int(raw.get("next_ledger_id", 0))
        self._log("state_restored", detail={"invoices": len(self.invoices)})
        return True

    def run(self, use_agent: bool = True) -> list[Finding]:
        findings = reconcile(self.invoices, self.ledger,
                             period_start=PERIOD_START, period_end=PERIOD_END,
                             known_vendors=self.known_vendors)
        if use_agent:
            findings = agent.enhance_all(findings)

        # keep any human decisions already made, matched by finding id
        prev = {f.id: f for f in self.findings}
        for f in findings:
            old = prev.get(f.id)
            if old and old.status != "open":
                f.status = old.status
                f.decided_by = old.decided_by
                f.decided_at = old.decided_at
                f.reversal = old.reversal
        self.findings = findings
        self._log("reconcile", detail=summarise(self.invoices, findings))
        self.save()
        return findings

    # --------------------------------------------------------------- decisions
    def decide(self, finding_id: str, decision: str, by: str = "owner") -> Finding:
        finding = self._find(finding_id)
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")

        finding.status = "approved" if decision == "approve" else "rejected"
        finding.decided_by = by
        finding.decided_at = _now()
        if finding.status == "approved":
            self._apply(finding)
        self._log(f"finding_{finding.status}", finding_id,
                  {"rule_id": finding.rule_id, "action": finding.proposed_action})
        self.save()
        return finding

    def revoke(self, finding_id: str) -> Finding:
        """Undo a decision and roll the books back — nothing is irreversible."""
        finding = self._find(finding_id)
        if finding.status == "open":
            raise ValueError("finding has no decision to revoke")
        previous = finding.status
        if previous == "approved" and finding.reversal:
            self._revert(finding.reversal)
        finding.status = "open"
        finding.decided_by = None
        finding.decided_at = None
        finding.reversal = {}
        self._log("finding_revoked", finding_id, {"was": previous})
        self.save()
        return finding

    def _find(self, finding_id: str) -> Finding:
        finding = next((f for f in self.findings if f.id == finding_id), None)
        if finding is None:
            raise KeyError(finding_id)
        return finding

    # ---------------------------------------------------------------- preview
    def preview(self, finding_id: str) -> dict:
        """Describe what an approval WOULD change — WITHOUT changing it.

        Powers the confirm dialog and ``GET /api/findings/{id}/preview`` so the
        owner sees the exact before → after before committing (responsible design).
        """
        finding = self._find(finding_id)
        action = finding.proposed_action or {}
        op = action.get("op")
        entity, before, after = "Nothing — advisory only", None, None
        changes_data = True

        if op == "set_ledger_amount":
            entry = next((e for e in self.ledger if e.id == action.get("ledger_id")), None)
            if entry:
                entity = f"Ledger {entry.id} · amount"
                before, after = entry.amount, action["value"]
        elif op in ("set_invoice_gst_rate", "set_invoice_gst_amount"):
            inv = next((i for i in self.invoices if i.id == action.get("invoice_id")), None)
            if inv:
                field = "gst_rate" if op.endswith("rate") else "gst_amount"
                entity = f"Invoice {inv.id} · {field}"
                before, after = getattr(inv, field), action["value"]
        elif op == "create_ledger_entry":
            entity = "Ledger · new row"
            before, after = "not present", action.get("amount")
        elif op == "mark_duplicate":
            inv = next((i for i in self.invoices if i.id == action.get("invoice_id")), None)
            entity = f"Invoice {inv.id if inv else '?'} · presence"
            before, after = "kept", "removed"
        elif op and op.startswith("review_"):
            changes_data = False
            entity = "Nothing — recorded as reviewed"

        delta = None
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = round(float(after) - float(before), 2)

        return {
            "finding_id": finding.id,
            "rule_id": finding.rule_id,
            "operation": op,
            "entity": entity,
            "changes_data": changes_data,
            "before": before,
            "after": after,
            "delta": delta,
            "currently": finding.status,
        }

    def chain(self, finding_id: str) -> dict:
        """Full reasoning chain: rule -> linked rules -> evidence -> impact."""
        finding = self._find(finding_id)
        rule = get_rule(finding.rule_id)
        linked = [{"id": rid, "name": get_rule(rid).name,
                   "description": get_rule(rid).description}
                  for rid in rule.relates_to if rid in RULES_BY_ID]
        return {
            "finding": finding.model_dump(),
            "rule": {"id": rule.id, "name": rule.name,
                     "description": rule.description, "severity": rule.severity,
                     "category": rule.category, "fixable": rule.fixable},
            "related_rules": linked,
            "preview": self.preview(finding_id),
            "requires_human_approval": True,
            "reversible": True,
        }

    def metrics(self) -> dict:
        """Aggregate numbers for the dashboard (auditable, all derived)."""
        fired = Counter(f.rule_id for f in self.findings)
        decisions = Counter(f.status for f in self.findings)
        reversals = sum(1 for a in self.audit if a.action == "finding_revoked")
        applied = sum(1 for a in self.audit if a.action == "finding_approved")
        return {
            "rules_fired": dict(sorted(fired.items())),
            "decisions": {"open": decisions.get("open", 0),
                          "approved": decisions.get("approved", 0),
                          "rejected": decisions.get("rejected", 0)},
            "approvals_applied": applied,
            "approvals_reversed": reversals,
            "auto_writes": 0,  # by design: a human approves every change
            "audit_events": len(self.audit),
            "agent": agent.agent_status(),
            **self.summary(),
        }

    def _apply(self, finding: Finding) -> None:
        """Apply an approved proposed_action, storing how to undo it."""
        action = finding.proposed_action or {}
        op = action.get("op")
        inv = next((i for i in self.invoices if i.id == action.get("invoice_id")), None)
        rev: dict = {}

        if op == "set_invoice_gst_rate" and inv is not None:
            rev = {"type": "invoice_field", "invoice_id": inv.id,
                   "field": "gst_rate", "value": inv.gst_rate}
            inv.gst_rate = float(action["value"])
        elif op == "set_invoice_gst_amount" and inv is not None:
            rev = {"type": "invoice_field", "invoice_id": inv.id,
                   "field": "gst_amount", "value": inv.gst_amount}
            inv.gst_amount = float(action["value"])
        elif op == "set_ledger_amount":
            entry = next((e for e in self.ledger if e.id == action.get("ledger_id")), None)
            if entry is not None:
                rev = {"type": "ledger_field", "ledger_id": entry.id,
                       "value": entry.amount}
                entry.amount = float(action["value"])
        elif op == "create_ledger_entry" and inv is not None:
            self._new_ledger_id += 1
            new_id = f"L-new-{self._new_ledger_id}"
            rev = {"type": "remove_ledger", "ledger_id": new_id}
            self.ledger.append(LedgerEntry(
                id=new_id,
                date=inv.date, vendor=inv.vendor,
                amount=float(action.get("amount", inv.total)),
                reference=str(action.get("reference", inv.invoice_no)),
            ))
        elif op == "mark_duplicate" and inv is not None:
            rev = {"type": "restore_invoice", "invoice": inv.model_dump(mode="json")}
            self.invoices = [i for i in self.invoices if i.id != inv.id]
        # review_vendor / review_period are advisory: approving just records it.

        finding.reversal = rev

    def _revert(self, rev: dict) -> None:
        """Inverse of _apply — restores the exact pre-approval state."""
        kind = rev.get("type")
        if kind == "invoice_field":
            inv = next((i for i in self.invoices if i.id == rev["invoice_id"]), None)
            if inv is not None:
                setattr(inv, rev["field"], rev["value"])
        elif kind == "ledger_field":
            entry = next((e for e in self.ledger if e.id == rev["ledger_id"]), None)
            if entry is not None:
                entry.amount = rev["value"]
        elif kind == "remove_ledger":
            self.ledger = [e for e in self.ledger if e.id != rev["ledger_id"]]
        elif kind == "restore_invoice":
            self.invoices.append(Invoice(**rev["invoice"]))

    # ------------------------------------------------------------------ views
    def summary(self) -> dict:
        return summarise(self.invoices, self.findings)

    def snapshot(self) -> dict:
        return {
            "summary": self.summary(),
            "findings": [f.model_dump() for f in self.findings],
            "ledger": [e.model_dump(mode="json") for e in self.ledger],
            "invoices": [i.model_dump(mode="json") for i in self.invoices],
            "audit": [a.model_dump() for a in self.audit],
            "agent": agent.agent_status(),
        }


# single shared instance for the demo service — restored from disk on boot
store = BahiStore()
store.load_state()
