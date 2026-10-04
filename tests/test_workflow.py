"""Tests for ingest / export / revoke / purge / webhook / persistence."""

import pytest
from fastapi.testclient import TestClient

from app.io import IngestError, parse_invoices_csv, ledger_to_csv, findings_to_csv
from app.main import app
from app.models import Finding, LedgerEntry
from app.store import BahiStore

client = TestClient(app)

GOOD_CSV = (
    "id,vendor,invoice_no,date,taxable_value,gst_rate,gst_amount,category\n"
    "A-1,Acme Traders,AC-1,2026-05-01,1000.00,18,180.00,goods\n"
    "A-2,Acme Traders,AC-2,2026-05-02,2000.00,18,300.00,goods\n"  # GST math wrong
)


# --------------------------------------------------------------------- ingest
def test_parse_valid_csv():
    rows = parse_invoices_csv(GOOD_CSV)
    assert len(rows) == 2
    assert rows[0].vendor == "Acme Traders"
    assert rows[0].total == 1180.0


def test_parse_csv_tolerates_currency_symbols():
    csv_ = ("id,vendor,invoice_no,date,taxable_value,gst_rate,gst_amount,category\n"
            "A-1,Acme,AC-1,2026-05-01,\"Rs 1,000.00\",18,180.0,goods\n")
    assert parse_invoices_csv(csv_)[0].taxable_value == 1000.0


def test_parse_csv_reports_the_bad_row():
    bad = ("id,vendor,invoice_no,date,taxable_value,gst_rate,gst_amount,category\n"
           "A-1,Acme,AC-1,2026-05-01,notanumber,18,180.0,goods\n")
    with pytest.raises(IngestError, match="row 2"):
        parse_invoices_csv(bad)


def test_parse_csv_missing_columns():
    with pytest.raises(IngestError, match="missing required columns"):
        parse_invoices_csv("foo,bar\n1,2\n")


def test_ingest_endpoint_rejects_bad_csv():
    resp = client.post("/api/ingest", files={
        "file": ("broken.csv", "id,vendor,invoice_no,date\n", "text/csv")})
    assert resp.status_code == 422
    assert "missing required columns" in resp.json()["detail"]


def test_ingest_endpoint_accepts_good_csv_and_runs():
    resp = client.post("/api/ingest", files={
        "file": ("mine.csv", GOOD_CSV, "text/csv")})
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["summary"]["invoices"] == 2
    assert any(f["invoice_id"] == "A-2" for f in snap["findings"])


# -------------------------------------------------------------------- exports
def test_template_downloads():
    resp = client.get("/api/template.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "taxable_value" in resp.text


def test_ledger_and_findings_export():
    client.post("/api/load-sample")
    client.post("/api/reconcile")
    ledger = client.get("/api/export/ledger.csv")
    findings = client.get("/api/export/findings.csv")
    assert ledger.status_code == findings.status_code == 200
    assert ledger.text.splitlines()[0] == "date,vendor,amount,reference"
    assert findings.text.splitlines()[0].startswith("id,rule_id,severity")
    assert "attachment" in ledger.headers["content-disposition"]


def test_export_empty_ledger_is_a_clear_400():
    client.post("/api/purge")
    assert client.get("/api/export/ledger.csv").status_code == 400


# --------------------------------------------------------------------- revoke
def test_revoke_rolls_the_ledger_back():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    target = next(f for f in snap["findings"] if f["rule_id"] == "R2.2")
    ledger_id = target["proposed_action"]["ledger_id"]

    before = next(e["amount"] for e in snap["ledger"] if e["id"] == ledger_id)

    approved = client.post(f"/api/findings/{target['id']}/approve").json()
    changed = next(e["amount"] for e in approved["ledger"] if e["id"] == ledger_id)
    assert changed != before

    reverted = client.post(f"/api/findings/{target['id']}/revoke").json()
    restored = next(e["amount"] for e in reverted["ledger"] if e["id"] == ledger_id)
    assert restored == before
    assert any(a["action"] == "finding_revoked" for a in reverted["audit"])


def test_revoke_a_reject_returns_finding_to_open():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    target = snap["findings"][0]
    rejected = client.post(f"/api/findings/{target['id']}/reject").json()
    assert next(f for f in rejected["findings"] if f["id"] == target["id"])["status"] == "rejected"
    reverted = client.post(f"/api/findings/{target['id']}/revoke").json()
    assert next(f for f in reverted["findings"] if f["id"] == target["id"])["status"] == "open"


def test_revoke_open_finding_is_a_400():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    assert client.post(f"/api/findings/{snap['findings'][0]['id']}/revoke").status_code == 400


def test_revoke_unknown_finding_is_a_404():
    assert client.post("/api/findings/nope/revoke").status_code == 404


# ------------------------------------------------------------------ ownership
def test_purge_deletes_everything():
    client.post("/api/load-sample")
    client.post("/api/reconcile")
    after = client.post("/api/purge").json()
    assert after["summary"]["invoices"] == 0
    assert after["findings"] == []
    assert any(a["action"] == "purge" for a in after["audit"])


# ------------------------------------------------------------------- webhook
def test_n8n_webhook_adds_invoice_and_flags_it():
    client.post("/api/load-sample")
    resp = client.post("/api/webhook/invoice", json={
        "vendor": "Brand New Supplier", "invoice_no": "BNS-1",
        "date": "2026-07-01", "taxable_value": 1000.0,
        "gst_rate": 17.0, "gst_amount": 170.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    rules = {f["rule_id"] for f in body["findings"]}
    assert "R1.1" in rules   # invalid GST slab
    assert "R4.1" in rules   # unknown vendor


def test_webhook_validates_payload():
    assert client.post("/api/webhook/invoice",
                       json={"vendor": "x", "invoice_no": "y",
                             "date": "01-07-2026", "taxable_value": 1,
                             "gst_rate": 1, "gst_amount": 1}).status_code == 422


# -------------------------------------------------------------- persistence
def test_state_roundtrip_across_instances():
    a = BahiStore()
    a.load_sample()
    a.run(use_agent=False)
    a.decide(a.findings[0].id, "approve")
    ledger_len = len(a.ledger)

    b = BahiStore()
    assert b.load_state() is True
    assert len(b.invoices) == 8
    assert len(b.ledger) == ledger_len
    assert any(f.status == "approved" for f in b.findings)


def test_csv_helpers_are_lossless():
    ledger = [LedgerEntry(id="L1", date="2026-05-01", vendor="Acme",
                          amount=1180.0, reference="AC-1")]
    lines = ledger_to_csv(ledger).splitlines()
    assert lines[0] == "date,vendor,amount,reference"
    assert lines[1] == "2026-05-01,Acme,1180.00,AC-1"
    out = findings_to_csv([Finding(id="R1.1:x", rule_id="R1.1",
                                   severity="error", title="t")])
    assert "rule_id" in out
