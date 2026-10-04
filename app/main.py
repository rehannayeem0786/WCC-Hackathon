"""FastAPI service + static UI for Bahi.

Run:  .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload
Then: open http://127.0.0.1:8000
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, Response

from .agent import agent_status
from .io import IngestError, TEMPLATE_CSV, findings_to_csv, ledger_to_csv
from .rules import rule_graph
from .store import store

BASE = Path(__file__).resolve().parent.parent
WEB = BASE / "web"

app = FastAPI(title="Bahi", version="0.2.0",
              description="Agentic, human-in-the-loop ledger assistant.")


def _csv(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "agent": agent_status()}


@app.get("/api/rule-graph")
def rules() -> dict:
    """The explainable rule knowledge graph (nodes + edges)."""
    return rule_graph()


@app.get("/api/findings/{finding_id}/preview")
def preview(finding_id: str) -> dict:
    """Exact before → after of an approval, applied to NOTHING yet."""
    try:
        return store.preview(finding_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown finding: {finding_id}")


@app.get("/api/findings/{finding_id}/chain")
def chain(finding_id: str) -> dict:
    """Rule -> linked rules -> evidence -> impact: the whole reasoning chain."""
    try:
        return store.chain(finding_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown finding: {finding_id}")


@app.get("/api/metrics")
def metrics() -> dict:
    """Aggregate, auditable numbers — every one derived from real events."""
    return store.metrics()


@app.post("/api/load-sample")
def load_sample() -> dict:
    store.load_sample()
    store.run(use_agent=False)
    return store.snapshot()


@app.post("/api/reconcile")
def reconcile(use_agent: bool = True) -> dict:
    if not store.invoices:
        raise HTTPException(status_code=400, detail="No invoices loaded. Call /api/load-sample first.")
    store.run(use_agent=use_agent)
    return store.snapshot()


@app.get("/api/state")
def state() -> dict:
    return store.snapshot()


@app.post("/api/findings/{finding_id}/revoke")
def revoke(finding_id: str) -> dict:
    """Undo an approve/reject AND roll the books back to the prior state.

    Registered BEFORE the generic {decision} route so it is not shadowed by it.
    """
    try:
        store.revoke(finding_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown finding: {finding_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.snapshot()


@app.post("/api/findings/{finding_id}/{decision}")
def decide(finding_id: str, decision: str, by: str = "owner") -> dict:
    try:
        store.decide(finding_id, decision, by=by)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown finding: {finding_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.snapshot()


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...)) -> dict:
    """Upload the owner's own invoices CSV — the real-world entry point."""
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        store.ingest_csv(text, source=file.filename or "upload")
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.run(use_agent=True)
    return store.snapshot()


@app.get("/api/template.csv")
def template() -> Response:
    """Blank CSV the owner can fill with their own bills."""
    return _csv(TEMPLATE_CSV, "bahi-invoices-template.csv")


@app.get("/api/export/ledger.csv")
def export_ledger() -> Response:
    if not store.ledger:
        raise HTTPException(status_code=400, detail="Ledger is empty.")
    return _csv(ledger_to_csv(store.ledger), "bahi-ledger.csv")


@app.get("/api/export/findings.csv")
def export_findings() -> Response:
    if not store.findings:
        raise HTTPException(status_code=400, detail="No findings to export.")
    return _csv(findings_to_csv(store.findings), "bahi-findings.csv")


@app.post("/api/purge")
def purge() -> dict:
    """Right to delete: wipes every bit of the owner's data."""
    store.reset()
    return store.snapshot()


class InvoiceIn(BaseModel):
    """Payload that n8n (or any integration) posts to Bahi."""

    vendor: str = Field(min_length=1, examples=["Sri Balaji Traders"])
    invoice_no: str = Field(min_length=1, examples=["SBT-1003"])
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2026-06-01"])
    taxable_value: float = Field(ge=0)
    gst_rate: float = Field(ge=0)
    gst_amount: float = Field(ge=0)
    category: str = "general"
    id: Optional[str] = None


@app.post("/api/webhook/invoice")
def webhook_invoice(payload: InvoiceIn) -> dict:
    """Integration entry point: one invoice in, its findings out.

    Kept deliberately fast (no LLM call) so an automation workflow can poll it
    safely; the UI's *Reconcile* adds the plain-language wording afterwards.
    """
    try:
        invoice = store.add_invoice(payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.run(use_agent=False)
    related = [f.model_dump() for f in store.findings if f.invoice_id == invoice.id]
    return {"ok": True, "invoice_id": invoice.id, "findings": related,
            "total_findings": len(store.findings)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(WEB / "app.js", media_type="application/javascript")
