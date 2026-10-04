"""Bahi — an agentic, human-in-the-loop ledger assistant for micro-businesses.

Package layout:
    models.py  domain objects (Invoice, LedgerEntry, Finding, AuditEvent)
    rules.py   the bookkeeping RULE KNOWLEDGE GRAPH
    engine.py  deterministic reconciliation engine
    agent.py   explain + draft layer (offline-first, optional LLM)
    store.py   in-memory state, approval workflow, audit log
    main.py    FastAPI service + static UI
"""

__version__ = "0.1.0"
