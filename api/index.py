"""Vercel serverless entrypoint. Vercel's Python runtime serves the ASGI `app`.

The project root is added to sys.path so the function can import the top-level
app.py / storage.py / anomalies.py modules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402,F401  (Vercel discovers this `app`)
