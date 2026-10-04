"""Make the repo root importable so `import app...` works under pytest."""

import os
import pathlib
import sys
import tempfile

import pytest

# Point persistence at a throwaway file BEFORE app.store is imported, so the
# global store never restores (or pollutes) the developer's demo state.
_TMP_STATE = pathlib.Path(tempfile.gettempdir()) / "bahi_test_state.json"
if _TMP_STATE.exists():
    _TMP_STATE.unlink()
os.environ["BAHI_STATE_FILE"] = str(_TMP_STATE)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _offline_agent(monkeypatch):
    """Tests must never hit the network: force the deterministic offline agent.

    Individual tests can override by setting BAHI_AGENT_BACKEND themselves.
    """
    monkeypatch.setenv("BAHI_AGENT_BACKEND", "none")


@pytest.fixture(autouse=True)
def _clean_store():
    """Give every test a pristine store.

    The API module holds one global store; without this, a decision made in
    test_api silently leaks into test_explainability and the failures look like
    product bugs rather than fixture bugs.
    """
    from app.store import store

    store.reset()
    yield
    store.reset()
