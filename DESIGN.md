# AI RTI Guardian — Design Doc

An AI-powered transparency infrastructure for India. A citizen describes what they
want to know in plain language; the system routes it to the right authority, drafts a
legally precise RTI, flags sensitivity factors, tracks statutory deadlines, analyzes the
response for anomalies, and drafts a first appeal when needed.

The product is built around **risk reduction**, not just convenience. The core principle:
*minimize unnecessary exposure, preserve evidence, and — for high-sensitivity matters —
avoid making one citizen a single point of failure.*

---

## Non-negotiable principles

1. **Never certify safety.** The system surfaces *factors* and *precautions*. It never
   emits a composite "you are safe" score. Risk UI describes the request content and
   recommends precautions; it never vets a person's physical safety.
2. **Inference is sourced or it doesn't ship.** Any claim about a person/entity
   ("appears in prior cases") must link to a public record. No model-generated
   accusations. This is a defamation boundary, not a nicety.
3. **The platform is not the publisher.** Distributed disclosure preserves and routes
   evidence to trusted parties with consent; it does not itself publish documents.
4. **Minimize exposure, don't fake anonymity.** The official Central RTI portal collects
   applicant info by design. We do not pretend to hide identity from the government.
5. **Secrets live in env vars.** No keys in source. Ever.

---

## Scope ladder (what to build, in order)

### MVP (v1) — the single loop  ← **this repo builds this**
`plain language → authority routing → precise RTI draft → sensitivity factors →
deadline tracking → response analysis → first-appeal draft`

This is a complete, shippable product on its own. Everything below is deferred.

### v1.5 — response anomaly detection (tractable, high value)  ← **built**
Pattern spotting on uploaded responses: same vendor repeated, bids sharing an address,
post-award amount jumps, payment before completion certificate, referenced-but-missing
pages, evasive answers / wrongful exemption claims.

Implemented in `anomalies.py` as a **deterministic rule-based pass**: every finding
points at the exact triggering text, so results are reproducible and carry no
fabrication risk. `/api/analyze` runs this first, then the LLM drafts the follow-up
*grounded only in the detected findings*. If the LLM is unavailable, detection still
returns findings and a recommended action — the draft is simply skipped.
`ponytail:` regex/heuristic over raw text — upgrade path is structured table
extraction from PDFs, then the same rules over typed columns.

### v2 — collaboration detection
Detect overlapping requests about the same project/parcel/contract. Offer opt-in
anonymous collaboration. Never reveal identity without consent.

### v3 — distributed disclosure workflow
Consent-based secure preservation + routing to trusted journalists/lawyers/CSOs.

### v4 — knowledge graph
Officer → Dept → Tender → Contractor → Payment → Project → Location → prior RTI →
audit objection. Multi-language entity resolution across gov PDFs. Hardest piece; last.

### Cross-cutting — demand-as-signal
Aggregate repeated RTI categories into a proactive-disclosure signal for governments
(RTI Act §4 suo motu disclosure).

---

## MVP architecture (deliberately minimal)

- **Backend:** Python + FastAPI. One LLM call path to an OpenAI-compatible endpoint.
- **LLM:** user's custom endpoint (OpenAI `/chat/completions` shape), configured via env.
- **Storage:** SQLite (stdlib). Tracks filed requests + statutory deadline.
- **Frontend:** one static HTML page, no build step.

Deliberate simplifications (known ceilings):
- Authority routing + sensitivity flags come from the LLM, not an authority database.
  `ponytail:` naive routing — upgrade path is a real authority/department registry.
- Deadlines use the standard RTI timeline (30 days; 48h for life/liberty) computed
  client-of-record side; no holiday calendar. Upgrade path: jurisdiction calendars.
- No auth / single-user local tool. Upgrade path: real accounts before any hosting.

## Statutory timeline (used by deadline tracker)
- Standard response: **30 days** from filing.
- Life or liberty of a person: **48 hours**.
- First appeal: within **30 days** of response (or of the deadline, if no response).
These are the headline figures; a production build needs holiday/jurisdiction calendars.

## Data model (SQLite)
`requests(id, created_at, subject, authority, body, sensitivity, filed_on,
deadline_on, status, response_text)`

## API surface (MVP)
- `POST /api/draft`    → {query} → {authority, subject, body, sensitivity[], precautions[]}
- `POST /api/requests` → persist a filed request, compute deadline
- `GET  /api/requests` → list with days-remaining
- `POST /api/analyze`  → {request_id, response_text} → anomalies[] + follow-up/appeal draft
