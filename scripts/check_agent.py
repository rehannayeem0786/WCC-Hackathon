"""Diagnostic: verify the configured LLM backend (Groq / OpenRouter) works.

Usage:  .\\.venv\\Scripts\\python.exe scripts\\check_agent.py
Exit codes: 0 = live call OK, 1 = offline (no key), 2 = live call failed.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.agent import _chat, agent_status, enhance, resolve_backend  # noqa: E402
from app.models import Finding  # noqa: E402


def main() -> int:
    status = agent_status()
    print("agent_status:", status)

    backend = resolve_backend()
    if backend is None:
        print("\nOFFLINE MODE — no GROQ_API_KEY / OPENROUTER_API_KEY found in .env")
        return 1

    print(f"\n1) live connectivity test -> {backend.name} ({backend.model})")
    try:
        reply = _chat(backend, [
            {"role": "system", "content": "You are a test. Always reply with JSON."},
            {"role": "user", "content": 'Reply with exactly this JSON: {"ok": true}'},
        ])
        print("   OK  ->", reply.strip()[:160])
    except Exception as exc:  # noqa: BLE001
        print(f"   FAIL -> {type(exc).__name__}: {exc}")
        return 2

    print("\n2) enhance() on a real finding (why/suggestion rewritten)")
    finding = Finding(
        id="R1.2:INV-003", rule_id="R1.2", severity="error",
        title="GST amount does not match 18% rate",
        invoice_id="INV-003",
        why="On 2,000.00 taxable value at 18%, GST should be 360.00 but the invoice shows 300.00.",
        evidence={"vendor": "Deccan Hardware", "taxable_value": 2000.0, "gst_rate": 18.0,
                  "expected_gst": 360.0, "actual_gst": 300.0},
        suggestion="Correct the GST amount to 360.00.",
    )
    before = finding.why
    enhance(finding, backend)
    print("   before:", before)
    print("   after :", finding.why)
    print("   fix   :", finding.suggestion)
    print("\nAll good — the agent is live." if finding.why != before
          else "\nConnected, but the model returned the original text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
