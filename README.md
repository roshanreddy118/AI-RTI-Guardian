# AI RTI Guardian — MVP

Plain-language → correct authority → precise RTI draft → sensitivity factors →
deadline tracking → response analysis → first-appeal draft.

See [DESIGN.md](DESIGN.md) for the full vision and phased roadmap. This repo is the v1
single loop only.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with your endpoint + key
set -a && source .env && set +a   # load env into the shell
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

## Env vars
- `LLM_ENDPOINT` — OpenAI-compatible `/chat/completions` style endpoint
- `LLM_API_KEY`  — bearer key (kept out of source; `.env` is gitignored)
- `LLM_MODEL`    — model name sent to the endpoint

## Response analysis (v1.5)
`/api/analyze` runs a **deterministic rule-based detector** (`anomalies.py`) first —
repeated vendors, shared bidder addresses, cost escalation, payment-before-completion,
missing referenced pages, evasive/wrongful-exemption answers. Each finding cites the
exact triggering text (reproducible, no fabrication). The LLM then drafts the follow-up
or first appeal grounded only in those findings. Detection still works if the LLM is
down — only the draft is skipped.

## Test (no network needed)
```bash
python3 test_core.py        # deadlines + JSON-salvage fallback
python3 test_anomalies.py   # every detection rule + the clean-response silence
```
These cover the pieces that silently break the product if they regress.

## Known simplifications (see DESIGN.md)
- Authority routing + sensitivity come from the LLM, not an authority registry.
- Deadlines use headline RTI figures (30 days / 48h) with no holiday calendar.
- Single-user local tool, no auth. Add accounts before hosting.
