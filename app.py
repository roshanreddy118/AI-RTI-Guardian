"""AI RTI Guardian — MVP single loop.

plain language -> authority routing -> RTI draft -> sensitivity factors ->
deadline tracking -> response analysis -> first-appeal draft.

Run:  uvicorn app:app --reload
Env:  LLM_ENDPOINT, LLM_API_KEY, LLM_MODEL (see .env.example)
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import anomalies
import storage

# index.html sits next to app.py locally; on Vercel the bundler may place it at the
# cwd or repo root. Resolve against the first location that actually exists.
_HERE = Path(__file__).resolve().parent
INDEX_HTML = next(
    (p for p in (_HERE / "index.html", _HERE.parent / "index.html", Path.cwd() / "index.html")
     if p.exists()),
    _HERE / "index.html",
)

# --- config (secrets stay in env; never hardcode) --------------------------
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "https://ai-server-lime.vercel.app/api/chat")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# RTI statutory timeline (headline figures; no holiday calendar — see DESIGN.md)
STANDARD_DAYS = 30
LIFE_LIBERTY_HOURS = 48

app = FastAPI(title="AI RTI Guardian")


# --- storage (Postgres on Vercel, SQLite locally — see storage.py) ---------
storage.init_db()


# --- LLM client ------------------------------------------------------------
def llm(messages: list[dict], want_json: bool = True) -> str:
    """Call an OpenAI-compatible chat endpoint. Raises HTTPException on failure."""
    if not LLM_API_KEY:
        raise HTTPException(500, "LLM_API_KEY is not set. Copy .env.example to .env and fill it in.")
    # max_tokens headroom: reasoning models (e.g. gpt-oss) spend a large hidden
    # reasoning trace (observed up to ~5k chars) BEFORE the answer; too small a
    # budget leaves no room for the JSON and content comes back empty.
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 4000}
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(
            LLM_ENDPOINT,
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise HTTPException(502, f"LLM endpoint error: {e}") from e
    # Tolerate OpenAI shape, reasoning-model shape (answer in `reasoning` when
    # `content` is empty), and a bare {content/text} shape.
    try:
        msg = data["choices"][0]["message"]
        return msg.get("content") or msg.get("reasoning") or ""
    except (KeyError, IndexError, TypeError):
        return data.get("content") or data.get("text") or json.dumps(data)


def _extract_json(raw: str) -> dict | None:
    """Pull the first complete JSON object out of raw text (handles prose wrappers
    and strings containing braces). Returns None if none parses."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def llm_json(messages: list[dict]) -> dict:
    raw = llm(messages, want_json=True)
    parsed = _extract_json(raw)
    if parsed is None:
        # Reasoning models sometimes emit no content and leave an unterminated
        # object; one retry nudging for a short, pure-JSON answer usually fixes it.
        retry = llm(messages + [{"role": "user", "content":
                   "Reply with ONLY the JSON object, no reasoning, no prose."}], want_json=True)
        parsed = _extract_json(retry)
        if parsed is None:
            snippet = (retry or raw or "").strip()[:200] or "(empty response)"
            raise HTTPException(502, f"LLM did not return valid JSON. Got: {snippet}")
    return parsed


# --- prompts ---------------------------------------------------------------
DRAFT_SYS = (
    "You are an Indian RTI (Right to Information Act 2005) drafting assistant. "
    "Given a citizen's plain-language request (any Indian language or English), you: "
    "(1) identify the most likely public authority / department that holds the records; "
    "(2) write a precise RTI application that SEEKS RECORDS, never makes accusations; "
    "(3) list sensitivity FACTORS (not a safety verdict) and concrete PRECAUTIONS. "
    "Never claim a request is 'safe'. Describe content-based factors only. "
    'Reply ONLY as JSON: {"authority": str, "subject": str, "body": str, '
    '"sensitivity_level": "routine"|"potentially_sensitive"|"higher_sensitivity", '
    '"sensitivity_factors": [str], "precautions": [str]}. '
    "The body must be addressed to the PIO, request specific records, and ask for "
    "certified copies. Do not invent names of officials."
)

ANALYZE_SYS = (
    "You draft RTI follow-ups for a citizen. A deterministic scanner has ALREADY found "
    "the accountability red flags and will be shown to you as DETECTED FINDINGS, each "
    "with the exact evidence text. Your job: draft ONE appropriate document grounded ONLY "
    "in those findings and the response text — a FIRST APPEAL if information was wrongly "
    "denied/incomplete, otherwise a clarifying FOLLOW-UP RTI. Do not invent findings or "
    "facts beyond the evidence given. Address it to the First Appellate Authority (appeal) "
    "or PIO (follow-up), cite the relevant RTI Act section where the evidence supports it. "
    'Reply ONLY as JSON: {"recommended_action": "first_appeal"|"follow_up_rti"|"none", '
    '"draft": str}.'
)


# --- schemas ---------------------------------------------------------------
class DraftIn(BaseModel):
    query: str


class RequestIn(BaseModel):
    subject: str
    authority: str
    body: str
    sensitivity: str = "routine"
    life_liberty: bool = False
    filed_on: str | None = None  # ISO date; defaults to today


class AnalyzeIn(BaseModel):
    request_id: int | None = None
    response_text: str


# --- endpoints -------------------------------------------------------------
@app.get("/")
def index():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    raise HTTPException(500, f"index.html not found (looked near {INDEX_HTML})")


@app.post("/api/draft")
def draft(inp: DraftIn):
    if not inp.query.strip():
        raise HTTPException(400, "query is empty")
    return llm_json(
        [{"role": "system", "content": DRAFT_SYS}, {"role": "user", "content": inp.query}]
    )


@app.post("/api/requests")
def create_request(inp: RequestIn):
    filed = date.fromisoformat(inp.filed_on) if inp.filed_on else date.today()
    if inp.life_liberty:
        deadline = datetime.combine(filed, datetime.min.time()) + timedelta(hours=LIFE_LIBERTY_HOURS)
        deadline_on = deadline.date().isoformat()
    else:
        deadline_on = (filed + timedelta(days=STANDARD_DAYS)).isoformat()
    new_id = storage.insert_request(
        datetime.now().isoformat(timespec="seconds"),
        inp.subject, inp.authority, inp.body, inp.sensitivity,
        filed.isoformat(), deadline_on,
    )
    return {"id": new_id, "deadline_on": deadline_on}


@app.get("/api/requests")
def list_requests():
    today = date.today()
    out = []
    for d in storage.all_requests():
        d["days_remaining"] = (date.fromisoformat(d["deadline_on"]) - today).days
        out.append(d)
    return out


@app.post("/api/analyze")
def analyze(inp: AnalyzeIn):
    if not inp.response_text.strip():
        raise HTTPException(400, "response_text is empty")

    # Pass 1: deterministic, auditable detection (no LLM, no fabrication).
    found = anomalies.detect(inp.response_text)
    action = anomalies.recommend(found)

    # Pass 2: LLM drafts the follow-up, grounded in the detected findings.
    findings_block = "\n".join(f"- {f['finding']}: {f['evidence']}" for f in found) or "(none)"
    user_msg = (
        f"DETECTED FINDINGS:\n{findings_block}\n\n"
        f"SUGGESTED ACTION: {action}\n\n"
        f"RESPONSE TEXT:\n{inp.response_text}"
    )
    try:
        drafted = llm_json(
            [{"role": "system", "content": ANALYZE_SYS}, {"role": "user", "content": user_msg}]
        )
    except HTTPException:
        # Detection still works without the LLM; surface findings, skip the draft.
        drafted = {"recommended_action": action, "draft": ""}

    result = {
        "anomalies": found,
        "recommended_action": drafted.get("recommended_action", action),
        "draft": drafted.get("draft", ""),
    }
    if inp.request_id is not None:
        storage.mark_analyzed(inp.request_id, inp.response_text)
    return result
