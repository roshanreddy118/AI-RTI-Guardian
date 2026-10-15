"""One runnable check for the two pieces that silently break the product:
deadline computation and the JSON-salvage fallback. No network, no framework.

Run: python3 test_core.py
"""
import json
import os
import tempfile
from datetime import date

# Force the local SQLite backend at a temp path so tests never touch Neon/prod.
os.environ.setdefault("LLM_API_KEY", "test")
os.environ.pop("DATABASE_URL", None)
import pathlib  # noqa: E402
import storage  # noqa: E402

storage.IS_PG = False
storage.SQLITE_PATH = pathlib.Path(tempfile.mkdtemp()) / "test.db"
import app  # noqa: E402  (imports storage, calls init_db at module load)

storage.init_db()


def test_standard_deadline_is_30_days():
    r = app.create_request(app.RequestIn(
        subject="pension file", authority="PIO X", body="...", filed_on="2026-01-01"))
    assert r["deadline_on"] == "2026-01-31", r
    print("ok: standard deadline = 30 days")


def test_life_liberty_is_next_day():
    # 48h from 2026-01-01 00:00 lands on 2026-01-03.
    r = app.create_request(app.RequestIn(
        subject="detained relative", authority="PIO Y", body="...",
        filed_on="2026-01-01", life_liberty=True))
    assert r["deadline_on"] == "2026-01-03", r
    print("ok: life/liberty deadline = 48h")


def test_days_remaining_sign():
    # A request filed 60 days ago must show a negative days_remaining (overdue).
    past = (date.today().replace() )
    app.create_request(app.RequestIn(
        subject="old req", authority="PIO Z", body="...",
        filed_on="2020-01-01"))
    rows = app.list_requests()
    overdue = [r for r in rows if r["subject"] == "old req"][0]
    assert overdue["days_remaining"] < 0, overdue
    print("ok: overdue request reports negative days_remaining")


def test_json_salvage_handles_chatter():
    # Model wraps JSON in prose/markdown — salvage must still parse it.
    raw = 'Sure! Here you go:\n```json\n{"authority": "PIO", "subject": "x"}\n```'
    app.llm = lambda *a, **k: raw          # stub the network call
    out = app.llm_json([{"role": "user", "content": "hi"}])
    assert out["authority"] == "PIO", out
    print("ok: JSON salvage recovers from wrapped output")


def test_json_salvage_clean_passthrough():
    app.llm = lambda *a, **k: json.dumps({"ok": True})
    assert app.llm_json([])["ok"] is True
    print("ok: clean JSON passes through")


def test_json_salvage_brace_inside_string():
    # Regression: a '}' inside a JSON string value must not end extraction early.
    # The old rfind/find salvage would also break if trailing prose followed.
    raw = 'Here: {"draft": "Use {placeholder} here", "recommended_action": "none"} -- done.'
    app.llm = lambda *a, **k: raw
    out = app.llm_json([])
    assert out["draft"] == "Use {placeholder} here", out
    assert out["recommended_action"] == "none", out
    print("ok: JSON salvage respects braces inside strings")


def test_json_salvage_empty_raises_with_snippet():
    app.llm = lambda *a, **k: "no json at all here"
    try:
        app.llm_json([])
    except app.HTTPException as e:
        assert "no json at all here" in str(e.detail), e.detail
        print("ok: empty/invalid JSON raises a diagnosable error")
        return
    raise AssertionError("expected HTTPException")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print("\nAll checks passed.")
