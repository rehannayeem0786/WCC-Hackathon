# Evidence pack — the problem is real

> Scores under **User insight and problem evidence (15 points)**.
> Two kinds of evidence: **secondary** (published, verifiable — §1) and
> **primary** (your own interviews/survey — §3, still to be done).

## 1. The problem, in verified public data

| # | Finding | Why it matters to Bahi | Source |
|---|---------|------------------------|--------|
| E1 | **"A majority of show-cause notices issued to taxpayers under GST last year pertained to 'data discrepancies' in tax return filings."** | Reconciliation mismatches are literally the **#1 cause** of Indian tax notices — not fraud, just mismatched records. | *The Hindu*, 24 Sep 2024, Vikas Dhoot — "Most GST notices due to data mismatches, CBIC to deploy tech to address pain points" (senior CBIC official speaking). |
| E2 | **₹7.34 lakh crore** owed to Indian MSMEs in delayed/unpaid invoices (down from ₹10 lakh crore in the prior edition, still vast). | Small businesses' money is trapped inside badly reconciled invoices. | C2FO with **GAME** & **FISME**, *Delayed Payments 3.0 Report*, Dec 2024. |
| E3 | **> ₹80,000 crore** of GST notices issued for AY 2018–22 **due to mismatches in purchase and sale data**. | The same mismatch pattern, at scale, costing real money. | Pankaj Chaudhary, MoS for Finance, **Rajya Sabha** answer, 29 Aug 2025. |
| E4 | MSME delayed payments have risen to **more than 4.6% of India's GVA**; ~45–50% of MSMEs are paid on time. | Even the "good" case means **half of MSMEs are late**, and mismatched bills are a leading cause. | Anil Gupta, Head of Crisil Research, via *Businessworld*, 29 Oct 2025. |
| E5 | The government is building tech **specifically to resolve filing mismatches**. | A regulator admitted the problem needs national tooling — Bahi is that tool at a shopkeeper's scale. | Same CBIC interview as E1. |

**Thesis:** *Indian small businesses lose money and attract tax notices not because they lie, but because their bills, ledgers and filings don't match — and nobody has time to reconcile them by hand.*

## 2. Target user & persona

**Primary user:** a solo shop owner, freelancer, small clinic or neighbourhood service business (1–10 people) with **no accountant on staff**.

| Attribute | Detail |
|-----------|--------|
| Current tool | Excel / WhatsApp / a paper *bahi* / Tally-in-name-only |
| Current process | Re-type bills at month-end; hope the numbers agree |
| Failure mode | Discovered at filing time → notice, penalty, or lost input credit |
| What they'd pay for | *"Tell me what's wrong, in one line, and let me press one button."* |

## 3. ⚠️ PRIMARY research you must still run — this is most of the 15

Judges explicitly want **research, observation, interviews or survey data**.
Pre-event research is **allowed** (Rule 02), so do it *before* the clock starts.

- [ ] **8–12 interviews**, 15 min each — shop owners, freelancers, one CA/tax practitioner
- [ ] **Survey**, target 40+ responses, in local trader / freelancer groups
- [ ] **3 anonymised "messy ledger" walkthroughs** (screen-share their real process)
- [ ] Capture **1 hard number**: hours/month reconciling, or the last mismatch found

Suggested questions
1. Walk me through how you closed your books last month.
2. When did a bill/ledger mismatch last cost you money or time? What happened?
3. How long does a month-end check take, and who does it?
4. What happens when your invoice and your bank entry disagree?

**Then** record sample size + 3 quotes + 3 charts → `evidence/interviews.md`.

## 4. Map each pain to a Bahi rule (traceability)

| Pain we must verify | Bahi rule | Product behaviour |
|---------------------|-----------|-------------------|
| "I don't know if the GST on a bill is right" | **R1.1 / R1.2** | Checks slab legality + recomputes the maths, explains it |
| "Bills go missing before filing" | **R2.1** | Flags invoices with no ledger entry |
| "I've paid the same bill twice" | **R3.1** | Duplicate vendor + invoice detection |
| "The ledger says ₹X, the bill says ₹Y" | **R2.2** | Amount mismatch, with the exact difference |
| "A new/unknown supplier appeared" | **R4.1** | New-vendor review |
| "That bill is from the wrong month" | **R5.1** | Period check |
| "I don't trust software to edit my books" | — | **Human approves every change; nothing is irreversible** |

## 5. Differentiation vs. what exists today

| Alternative | What it does | Where Bahi differs |
|-------------|--------------|--------------------|
| Tally / Zoho Books | Full accounting suite | Steep learning curve; no plain-language "why" per mismatch |
| CA / outsourced bookkeeper | Correct, expensive | Bahi is the affordable first pass before it reaches them |
| Generic LLM chatbot | Answers questions | Bahi has a **deterministic rule engine** — every finding cites a rule, evidence, and an exact reversible change |
| Manual Excel check | Free | Slow; exactly the errors above are what manual checking misses |

**Distinctive insight:** most tools show you an error *message*. Bahi shows you a
**rule graph** — which rule fired, the exact fields it used, the rule it connects
to, and the precise, revocable change it proposes. That is why a shopkeeper can
trust it enough to press "Approve".

## 6. Expected product outcome (for the "clear outcome" criterion)

Demoed on the bundled sample books:

| Metric | Value | Source |
|--------|-------|--------|
| Invoices checked | 8 | `/api/state` summary |
| Errors found | see live run | rule engine |
| Amount at risk | ₹ shown live | `/api/state` summary |
| Est. minutes saved | `findings × ~4 min` | `engine.summarise()` |

State the measurement rule out loud to judges: **~4 minutes of manual checking per finding**, so the number is auditable rather than invented.

