# Bahi — your ledger, verified

> **WCC Launchpad 30** · Track: **Agentic AI** · 30-hour national online hackathon
> An agentic, **human-in-the-loop** assistant that turns a micro-business's pile of
> invoices into a clean, verified ledger — flagging mismatches, drafting the fix,
> and letting the owner approve **every** change, with each decision explained and sourced.

**In one line:** *Bahi finds the mistakes only a CA would notice, names the rule each one broke,
shows you the exact `before → after` — and refuses to touch your books until you say yes.*

<p align="center">
  <b>Start here →</b>
  <a href="docs/evidence.md">the problem is real</a> ·
  <a href="#the-rule-graph">the reasoning is inspectable</a> ·
  <a href="#90-second-demo-script-for-judges">it works in one click</a>
</p>

---

## Why this wins (rubric in one screen)

| Criterion | How Bahi delivers |
|-----------|-------------------|
| User insight (15) | Built for a solo shop owner / freelancer with no accountant. **Real cited evidence** (CBIC/GST notices, MSME delay reports) in [`docs/evidence.md`](docs/evidence.md). |
| Core solution (24) | ONE workflow: ingest → reconcile → explain → **owner approves** → clean ledger + audit log. CSV in, CSV out. |
| Technical depth (24) | Deterministic engine + rule **knowledge graph** + agent + audit log + n8n webhook + persistence. Works **offline**; LLM optional. |
| Originality (15) | Every finding is a *path in a rule graph*, and the graph is **interactive** — click a rule to see what it checks, what it connects to, and how often it fired. |
| Usability (12) | Upload your own CSV, one button per finding, downloads, plain language, full keyboard access. |
| Responsible design (10) | Human approves every write · **every decision is reversible** · vendor names redacted before any model call · **delete-all** control · immutable audit log. |

## The one journey

```
load books → reconcile against the RULE GRAPH → findings queue
   → agent explains + drafts a fix → OWNER approves/rejects
   → approved fixes applied to the ledger → audit log records everything
```

## Quickstart

```powershell
# 1. create + activate the virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. install dependencies
pip install -r requirements.txt
pip install -r requirements-tools.txt   # optional: the `graphify` dev tool

# 3. (optional) enable the LLM explainer — Groq or OpenRouter only
copy .env.example .env      # then paste GROQ_API_KEY or OPENROUTER_API_KEY

# 4. run
python -m uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

The app runs **with zero API keys**: the agent falls back to a deterministic,
offline explainer. Add a key only to make the wording friendlier.

## 90-second demo script (for judges)

**Fastest path: press one button.** The UI ships a **▶ Run guided demo (60s)** control that
performs steps 1–5 for you and then **deliberately pauses at step 4** to ask for your approval —
because that pause *is* the product.

1. **Load sample books** → 8 real-world invoices appear.
2. **Reconcile** → 8 findings (**5 error · 2 warn · 1 info**): wrong GST slab, wrong GST
   maths, missing ledger entry, amount mismatch, duplicate, new vendor, bill dated out of period.
3. Open a finding → *why* it fired, the exact numbers, and the proposed change.
4. **Approve** → a modal shows the diff **`4270.0 → 4720.0 (Δ +450)`** *before* anything is
   written. Say out loud: *"It stopped. Nothing moves until I say so."*
5. **Undo this decision** → the books roll back to `4270`. Nothing is permanent.
6. Click a **rule node** in the graph → *"R1.2 checks GST = value × rate; it links to R1.1."*
7. **Export clean ledger** → download a CSV. **Delete all my data** → everything is gone.

> **Talking point for *Responsible design (10)*:** the approval modal, the `auto_writes: 0`
> figure returned by `/api/metrics`, and the reversible audit log are **three independent
> proofs** that a human — not the model — owns every write.

## Deploy

```bash
docker build -t bahi .
docker run -p 8000:8000 -e GROQ_API_KEY=... -v bahi-state:/srv/.bahi bahi
```

Deployment is *strongly recommended* by the organisers; if you cannot deploy,
ship a reliable executable demo plus a video. Set keys as environment variables
on the host — `.env` is git-ignored and not baked into the image.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
**47 tests** cover every rule, CSV ingest/export, the approval + **revoke** workflow, the
audit log, persistence, the n8n webhook, the explainability endpoints and the HTTP API.
They run fully offline (`BAHI_AGENT_BACKEND=none`) so CI never depends on a provider —
and a **golden regression corpus** fails the build if reconciliation ever drifts.

## Project layout

```
app/
  models.py    domain objects (Invoice, LedgerEntry, Finding, AuditEvent)
  rules.py     the bookkeeping RULE KNOWLEDGE GRAPH (R1.1 … R5.1)
  engine.py    deterministic reconciliation engine + outcome summary
  io.py        CSV ingest + export (with row-level error messages)
  agent.py     explain + draft layer (Groq / OpenRouter, offline fallback)
  store.py     state, approvals + reversals, audit log, persistence
  main.py      FastAPI service + static UI + n8n webhook
web/           single-page review UI (no build step) + interactive rule graph
data/          sample invoices + ledger that trigger every rule
docs/          evidence.md — cited research backing the problem
scripts/       check_agent.py (agent connectivity diagnostic)
tests/         engine · workflow · API · explainability (47)
Dockerfile     lean runtime image for deployment
```

## The rule graph

Every finding cites a rule node; rules link to each other so the reasoning is
followable. See `/api/rule-graph`.

| Rule | Checks | Severity |
|------|--------|:--------:|
| R1.1 | GST rate is a legal slab (0/5/12/18/28) | error |
| R1.2 | GST amount = taxable value × rate | error |
| R2.1 | Invoice has a matching ledger entry | error |
| R2.2 | Ledger amount equals the invoice total | warn |
| R3.1 | No duplicate vendor + invoice number | error |
| R4.1 | Vendor is already known | info |
| R5.1 | Invoice date is inside the accounting period | warn |

## API (16 routes)

| Method | Path | What it does |
|--------|------|--------------|
| GET | `/api/health` | liveness + agent backend |
| GET | `/api/state` | full snapshot (findings, ledger, audit) |
| GET | `/api/rule-graph` | the rule knowledge graph (nodes + edges) |
| POST | `/api/load-sample` | load the bundled demo books |
| POST | `/api/reconcile` | run the engine (optionally + AI wording) |
| POST | `/api/ingest` | upload your own invoices CSV |
| GET | `/api/template.csv` | blank CSV to fill in |
| GET | `/api/export/ledger.csv` | download the clean ledger |
| GET | `/api/export/findings.csv` | download the findings report |
| **GET** | **`/api/findings/{id}/preview`** | **exact before → after, writes NOTHING** |
| **GET** | **`/api/findings/{id}/chain`** | **rule → linked rules → evidence → impact** |
| **GET** | **`/api/metrics`** | **rules fired, approvals, reversals, `auto_writes: 0`** |
| POST | `/api/findings/{id}/approve` | apply a fix (human approval) |
| POST | `/api/findings/{id}/reject` | decline a fix |
| POST | `/api/findings/{id}/revoke` | **undo a decision + roll the books back** |
| POST | `/api/purge` | right-to-delete: wipe everything |
| POST | `/api/webhook/invoice` | n8n / integration entry point |

### Built-in regression guarantee
`tests/test_explainability.py` contains a **golden corpus**: the sample books
must always produce exactly 8 findings (5 error / 2 warn / 1 info) and the engine
must be byte-identical across runs. If a change breaks reconciliation, CI fails.


## Agent configuration (Groq / OpenRouter only)

Set one key in `.env`; `BAHI_AGENT_BACKEND` selects the provider (`auto` prefers Groq).

| Provider | Env vars | Default model |
|----------|----------|---------------|
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | `openai/gpt-oss-120b` |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | `meta-llama/llama-3.3-70b-instruct` |

Both are called through the OpenAI-compatible `/chat/completions` endpoint.
Findings are rewritten in parallel (6 workers), so a 17-item queue resolves in
a few seconds. With no key the app uses the engine's deterministic explanations
— the demo **never** depends on the network. `BAHI_REDACT_PII=true` masks
vendor names before any remote call.

### Verifying your key

```powershell
.\.venv\Scripts\python.exe scripts\check_agent.py   # live connectivity + enhance test
```

> **Note:** Groq retired the Llama models. If you see `HTTP 404` from `api.groq.com`,
> set `GROQ_MODEL` to a model that currently exists (`openai/gpt-oss-120b`
> or `qwen/qwen3.8-27b`).

## n8n integration (sponsor angle)

Point an n8n workflow at the API to make Bahi part of an everyday automation:

1. **Webhook → Bahi**: POST `/api/load-sample` (or an ingest endpoint) then `/api/reconcile`.
2. **Notify**: read `/api/state` and message the owner a summary (Telegram/WhatsApp/email).
3. **Approve**: call `/api/findings/{id}/approve` from a chat button.

Because approval is a plain HTTP call, the human stays in the loop even from a phone.

## Responsible design

- **Human oversight** — no write happens without an explicit `approve`.
- **Explainability** — every finding carries rule id, plain-language reason, evidence and the exact change.
- **Privacy** — local-first; vendor names redacted before any model call.
- **Accountability** — immutable audit log; duplicate-marking and edits are reversible.

## Knowledge graph (graphify)

`graphify` is installed in the venv and maps this repo into a queryable graph:

```powershell
.\.venv\Scripts\graphify.exe update app     # rebuild the code graph (no LLM)
.\.venv\Scripts\graphify.exe god-nodes --graph app/graphify-out/graph.json
```

Run `graphify vscode install` to register the assistant skill, then type
`/graphify .` in chat. The tool, its source clone and its generated output are
**dev-only and git-ignored** — they are how this codebase was mapped, not part of
what ships.

