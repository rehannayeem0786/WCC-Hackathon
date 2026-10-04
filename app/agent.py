"""Explain + draft layer ("the agent").

Offline-first: with no key configured the engine's deterministic ``why`` /
``suggestion`` text is used verbatim, so the whole product still works.
When a key is present it uses one of the two supported providers — **Groq** or
**OpenRouter** (both expose the OpenAI-compatible ``/chat/completions`` API).
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import httpx
from dotenv import load_dotenv

from .models import Finding
from .rules import get_rule

# Load .env once at import so GROQ_API_KEY / OPENROUTER_API_KEY are picked up.
# override=False -> real environment variables always win over the file.
load_dotenv(override=False)

GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Groq retired the Llama models; gpt-oss-120b is its current flagship.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
}


class AgentHTTPError(RuntimeError):
    """Raised when a provider returns a non-2xx response."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class Backend:
    name: str
    base_url: str
    api_key: str = field(repr=False)  # never leak the key into logs/tracebacks
    model: str = ""


def resolve_backend() -> Optional[Backend]:
    """Pick a backend from env. Returns None -> deterministic offline mode."""
    pref = os.getenv("BAHI_AGENT_BACKEND", "auto").strip().lower()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if pref == "none":
        return None

    groq = Backend("groq", GROQ_BASE, groq_key,
                   os.getenv("GROQ_MODEL", DEFAULT_MODELS["groq"]))
    openrouter = Backend("openrouter", OPENROUTER_BASE, or_key,
                         os.getenv("OPENROUTER_MODEL", DEFAULT_MODELS["openrouter"]))

    if pref == "groq":
        return groq if groq_key else None
    if pref == "openrouter":
        return openrouter if or_key else None
    # auto
    if groq_key:
        return groq
    if or_key:
        return openrouter
    return None


def agent_status() -> dict:
    backend = resolve_backend()
    redact = os.getenv("BAHI_REDACT_PII", "true").strip().lower() in ("1", "true", "yes")
    if backend is None:
        return {"mode": "offline", "provider": None, "model": None,
                "redact_pii": redact,
                "note": "No GROQ_API_KEY / OPENROUTER_API_KEY set — using deterministic explanations."}
    return {"mode": "llm", "provider": backend.name, "model": backend.model,
            "redact_pii": redact}


def _redact(text: str, vendor: str) -> str:
    """Replace the vendor name with a pseudonym before any remote call."""
    if not vendor:
        return text
    return text.replace(vendor, "the vendor")


def _post_chat(backend: Backend, payload: dict, timeout: float) -> str:
    headers = {
        "Authorization": f"Bearer {backend.api_key}",
        "Content-Type": "application/json",
    }
    if backend.name == "openrouter":
        headers["HTTP-Referer"] = "https://wecodecoders.in/events/wcc-launchpad-30"
        headers["X-Title"] = "Bahi"
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{backend.base_url}/chat/completions",
                           headers=headers, json=payload)
    if resp.status_code >= 400:
        raise AgentHTTPError(resp.status_code, resp.text)
    return resp.json()["choices"][0]["message"]["content"]


def _chat(backend: Backend, messages: list[dict], timeout: float = 30.0) -> str:
    """Call the provider; fall back off JSON mode if the model rejects it."""
    base = {
        "model": backend.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 220,
    }
    try:
        return _post_chat(backend, {**base, "response_format": {"type": "json_object"}}, timeout)
    except AgentHTTPError as exc:
        if exc.status in (400, 422):  # model does not support JSON mode
            return _post_chat(backend, base, timeout)
        raise


SYSTEM_PROMPT = (
    "You are Bahi, a friendly bookkeeping assistant for a small shop owner in "
    "India who has no accounting background. For the finding you are given, "
    "return STRICT JSON with two keys: \"why\" (one short sentence, plain "
    "English, use Rs for money) and \"suggestion\" (one short actionable "
    "sentence). Do not invent numbers; only use the numbers provided."
)


def enhance(finding: Finding, backend: Optional[Backend] = None) -> Finding:
    """Return the finding with a friendlier why/suggestion, or unchanged."""
    backend = backend if backend is not None else resolve_backend()
    if backend is None:
        return finding
    rule = get_rule(finding.rule_id)
    redact = os.getenv("BAHI_REDACT_PII", "true").strip().lower() in ("1", "true", "yes")
    vendor = str(finding.evidence.get("vendor", ""))

    payload = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "severity": finding.severity,
        "title": finding.title,
        "why": finding.why,
        "suggestion": finding.suggestion,
        "evidence": finding.evidence,
    }
    user_text = json.dumps(payload, ensure_ascii=False, default=str)
    if redact:
        user_text = _redact(user_text, vendor)

    try:
        content = _chat(backend, [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ])
        parsed = json.loads(content)
        if parsed.get("why"):
            finding.why = str(parsed["why"]).strip()
        if parsed.get("suggestion"):
            finding.suggestion = str(parsed["suggestion"]).strip()
    except Exception:
        # Never fail the workflow because the model is unreachable.
        return finding
    return finding


def enhance_all(findings: list[Finding], max_workers: int = 6) -> list[Finding]:
    """Rewrite every finding's wording in parallel (keeps the demo snappy).

    Sequential calls would take ~30s for a 17-finding queue; this cuts it to a
    couple of seconds while still tolerating individual provider failures.
    """
    backend = resolve_backend()
    if backend is None or not findings:
        return findings
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(enhance, f, backend) for f in findings]
        for future in as_completed(futures):
            future.result()  # enhance() never raises; this surfaces bugs only
    return findings
