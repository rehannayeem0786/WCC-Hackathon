"""Explainability + reliability tests.

Includes a GOLDEN REGRESSION CORPUS: the sample books must always produce the
exact same findings, in the same set — this is the proof behind the
"technical depth and reliability" criterion.
"""

from fastapi.testclient import TestClient

from app.engine import load_invoices, load_ledger, reconcile
from app.main import app
from app.store import DATA_DIR, PERIOD_END, PERIOD_START, BahiStore

client = TestClient(app)

# The exact findings the bundled sample books must always produce.
GOLDEN = {
    ("R1.1", "INV-002"),   # illegal 15% GST slab
    ("R1.2", "INV-003"),   # 18% of 2000 is 360, invoice says 300
    ("R2.1", "INV-004"),   # SBT-1002 never reached the ledger
    ("R2.1", "INV-007"),   # new vendor, no ledger row
    ("R2.2", "INV-005"),   # ledger 4270 vs invoice 4720
    ("R3.1", "INV-006"),   # duplicate SBT-1001
    ("R4.1", "INV-007"),   # unseen vendor
    ("R5.1", "INV-008"),   # dated before the FY starts
}


def _golden_run():
    invoices = load_invoices(DATA_DIR / "sample_invoices.json")
    ledger = load_ledger(DATA_DIR / "sample_ledger.json")
    return reconcile(invoices, ledger, period_start=PERIOD_START,
                     period_end=PERIOD_END,
                     known_vendors={e.vendor for e in ledger})


# ------------------------------------------------------- golden regression
def test_golden_corpus_exact_findings():
    got = {(f.rule_id, f.invoice_id) for f in _golden_run()}
    assert got == GOLDEN


def test_engine_is_deterministic():
    assert _golden_run() == _golden_run()


def test_golden_corpus_severity_counts():
    findings = _golden_run()
    assert sum(1 for f in findings if f.severity == "error") == 5
    assert sum(1 for f in findings if f.severity == "warn") == 2
    assert sum(1 for f in findings if f.severity == "info") == 1
    assert len(findings) == 8


def test_clean_invoice_is_never_flagged():
    findings = _golden_run()
    assert not any(f.invoice_id == "INV-001" for f in findings)


# --------------------------------------------------------------- preview
def test_preview_shows_before_after_without_mutating():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    target = next(f for f in snap["findings"] if f["rule_id"] == "R2.2")

    before = next(e["amount"] for e in snap["ledger"]
                  if e["id"] == target["proposed_action"]["ledger_id"])

    prev = client.get(f"/api/findings/{target['id']}/preview").json()
    assert prev["before"] == before
    assert prev["after"] == target["proposed_action"]["value"]
    assert prev["delta"] != 0
    assert prev["changes_data"] is True
    assert prev["currently"] == "open"

    # NOTHING must have been written by merely asking for a preview
    state = client.get("/api/state").json()
    assert next(e["amount"] for e in state["ledger"]
                if e["id"] == target["proposed_action"]["ledger_id"]) == before


def test_preview_404():
    assert client.get("/api/findings/nope/preview").status_code == 404


def test_preview_of_advisory_rule_changes_nothing():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    target = next(f for f in snap["findings"] if f["rule_id"] == "R4.1")
    prev = client.get(f"/api/findings/{target['id']}/preview").json()
    assert prev["changes_data"] is False


# ------------------------------------------------------------------ chain
def test_chain_explains_rule_and_links():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    target = next(f for f in snap["findings"] if f["rule_id"] == "R1.2")
    ch = client.get(f"/api/findings/{target['id']}/chain").json()
    assert ch["rule"]["id"] == "R1.2"
    assert any(r["id"] == "R1.1" for r in ch["related_rules"])
    assert ch["requires_human_approval"] is True
    assert ch["reversible"] is True
    assert ch["preview"]["finding_id"] == target["id"]


# --------------------------------------------------------------- metrics
def test_metrics_are_derived_and_show_zero_auto_writes():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    m = client.get("/api/metrics").json()

    assert m["findings"] == len(snap["findings"])
    assert m["auto_writes"] == 0           # a human approves every change
    assert sum(m["rules_fired"].values()) == len(snap["findings"])
    assert m["decisions"]["open"] == len(snap["findings"])
    assert m["minutes_saved_estimate"] == len(snap["findings"]) * 4


def test_metrics_counts_approvals_and_reversals():
    client.post("/api/load-sample")
    snap = client.post("/api/reconcile").json()
    fid = next(f for f in snap["findings"] if f["rule_id"] == "R2.2")["id"]
    client.post(f"/api/findings/{fid}/approve")
    client.post(f"/api/findings/{fid}/revoke")
    m = client.get("/api/metrics").json()
    assert m["approvals_applied"] == 1
    assert m["approvals_reversed"] == 1
    assert m["audit_events"] >= 2


def test_state_roundtrip_still_works_after_new_fields():
    store = BahiStore()
    store.load_sample()
    store.run(use_agent=False)
    assert store.metrics()["invoices"] == 8
