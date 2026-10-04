"""End-to-end smoke test of the HTTP workflow (no network, no API keys)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_rule_graph():
    assert client.get("/api/health").json()["ok"] is True
    graph = client.get("/api/rule-graph").json()
    assert len(graph["nodes"]) == 7
    assert graph["edges"], "rules must be linked into a graph"


def test_index_page_is_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "Bahi" in res.text


def test_full_human_in_the_loop_journey():
    # 1. load the books
    snap = client.post("/api/load-sample").json()
    assert snap["summary"]["invoices"] == 8

    # 2. reconcile -> findings queue
    snap = client.post("/api/reconcile").json()
    findings = snap["findings"]
    assert len(findings) >= 7

    # 3. approve the ledger-mismatch fix -> books change + audit entry
    target = next(f for f in findings if f["rule_id"] == "R2.2")
    before = next(e["amount"] for e in snap["ledger"] if e["id"] == target["proposed_action"]["ledger_id"])

    after = client.post(f"/api/findings/{target['id']}/approve").json()
    changed = next(e["amount"] for e in after["ledger"] if e["id"] == target["proposed_action"]["ledger_id"])
    assert changed != before
    assert any(a["action"] == "finding_approved" for a in after["audit"])

    # 4. reject a finding -> no change
    open_finding = next(f for f in after["findings"] if f["status"] == "open")
    rejected = client.post(f"/api/findings/{open_finding['id']}/reject").json()
    assert any(f["id"] == open_finding["id"] and f["status"] == "rejected"
               for f in rejected["findings"])


def test_unknown_finding_returns_404():
    assert client.post("/api/findings/does-not-exist/approve").status_code == 404
