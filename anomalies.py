"""Rule-based anomaly detection on RTI response text.

Deterministic and auditable: every finding points at the exact text that triggered
it, so there is no fabrication risk and results are reproducible without an LLM.
This runs as the first pass in /api/analyze; the LLM only drafts the follow-up.

ponytail: regex/heuristic scan over raw text — a known ceiling. It catches the common
money/tender red flags in plain-text or lightly-tabulated responses. Upgrade path:
structured table extraction from PDFs, then run these same rules over typed columns.
"""
from __future__ import annotations

import re
from collections import Counter

# Indian currency amounts: ₹, Rs, INR with lakh/crore or plain digits with separators.
_AMOUNT = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|lakh|lac|lakhs)?",
    re.IGNORECASE,
)
# A vendor/company token: a Capitalized name run ending in company suffix word(s).
# The name part is restricted to Capitalized words so it won't swallow a leading
# "Contract to ..."; the suffix group is ordered longest-first and may chain a
# trailing "Pvt Ltd" so the whole company name is captured as one match.
_VENDOR = re.compile(
    r"\b((?:[A-Z][\w&.\-]*\s+){1,5}?"
    r"(?:Private\s+Limited|Pvt\.?\s*Ltd\.?|Limited|Ltd\.?|Enterprises|"
    r"Constructions?|Infra(?:structure)?|Builders|Traders|Associates|Corporation|& Co\.?)"
    r"(?:\s+Pvt\.?\s*Ltd\.?|\s+Private\s+Limited)?)",
)
# Addresses: a line that looks like a street/plot address (has a PIN or 'No.'/'Plot').
_ADDRESS = re.compile(
    r"((?:(?:plot|flat|door|no\.?|#)\s*[\w/\-]+[,\s].*?)?\b\d{6}\b)", re.IGNORECASE
)
_PAGE_REF = re.compile(r"\bpages?\s*(\d+)\s*(?:to|-|–|through)\s*(\d+)\b", re.IGNORECASE)
_PAGE_ENCLOSED = re.compile(r"\b(?:enclosed|annexed|attached|supplied|provided)\b", re.IGNORECASE)

# Phrases that signal evasion or a (possibly wrongful) exemption claim.
_EVASIVE = [
    (r"not\s+(?:available|traceable|found|maintained)", "Records claimed unavailable/not maintained"),
    (r"does not (?:hold|have)", "Authority claims it does not hold the record"),
    (r"section\s*8\s*\(1\)\s*\(?[a-j]\)?", "Exemption claimed under RTI §8(1) — check if validly applied"),
    (r"third[-\s]?party", "Third-party information cited — may need §11 process, not denial"),
    (r"vague|not\s+specific|cannot be construed", "Request dismissed as vague — often an improper ground"),
    (r"transferred\s+to", "Claims transfer to another authority — verify §6(3) was followed"),
]

CROR = {"crore", "cr"}
LAKH = {"lakh", "lac", "lakhs"}


def _to_rupees(num: str, unit: str | None) -> float:
    val = float(num.replace(",", ""))
    if unit:
        u = unit.lower()
        if u in CROR:
            return val * 1e7
        if u in LAKH:
            return val * 1e5
    return val


def _fmt(n: float) -> str:
    if n >= 1e7:
        return f"₹{n / 1e7:.2f} crore"
    if n >= 1e5:
        return f"₹{n / 1e5:.2f} lakh"
    return f"₹{n:,.0f}"


def detect(text: str) -> list[dict]:
    """Return a list of {finding, evidence} dicts. Empty if nothing matched."""
    findings: list[dict] = []
    low = text.lower()

    # 1. Same vendor appearing many times -> possible single-vendor capture.
    vendors = [re.sub(r"\s+", " ", m.group(1)).strip(" .,") for m in _VENDOR.finditer(text)]
    norm = Counter(v.lower() for v in vendors)
    for name_lower, count in norm.most_common():
        if count >= 3:
            display = next(v for v in vendors if v.lower() == name_lower)
            findings.append({
                "finding": f"Same vendor appears {count} times",
                "evidence": f'"{display}" occurs {count} times — check for single-vendor capture.',
            })

    # 2. Multiple entities sharing one address -> possible shell/collusive bids.
    addrs = Counter(re.sub(r"\s+", " ", m.group(1)).strip(" .,").lower() for m in _ADDRESS.finditer(text))
    for addr, count in addrs.items():
        if count >= 2:
            findings.append({
                "finding": "Address shared by multiple entries",
                "evidence": f'Address ending "{addr[-40:]}" appears {count} times — possible collusive/shell bidders.',
            })

    # 3. Large post-award / amount jumps -> cost escalation.
    amounts = [_to_rupees(m.group(1), m.group(2)) for m in _AMOUNT.finditer(text) if m.group(1)]
    amounts = [a for a in amounts if a > 0]
    if len(amounts) >= 2:
        lo, hi = min(amounts), max(amounts)
        if lo > 0 and hi / lo >= 1.5:
            pct = (hi / lo - 1) * 100
            findings.append({
                "finding": f"Amount increased ~{pct:.0f}%",
                "evidence": f"Values range {_fmt(lo)} to {_fmt(hi)} — verify against the sanctioned/awarded amount.",
            })

    # 4. Payment before completion certificate.
    if "payment" in low and re.search(r"completion certificate|completion report", low):
        pay = low.find("payment")
        cert = low.find("completion certificate")
        if cert == -1:
            cert = low.find("completion report")
        if pay != -1 and cert != -1 and pay < cert:
            findings.append({
                "finding": "Payment appears before completion certificate",
                "evidence": "The word 'payment' precedes the completion certificate — confirm the payment/CC dates.",
            })

    # 5. Pages referenced but attachments not clearly supplied.
    for m in _PAGE_REF.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if b > a and not _PAGE_ENCLOSED.search(text):
            findings.append({
                "finding": f"Pages {a}-{b} referenced but not confirmed as supplied",
                "evidence": f'Response mentions pages {a}-{b} with no "enclosed/annexed" nearby — request the missing pages.',
            })
            break

    # 6. Evasive answers / exemption claims to verify.
    for pattern, label in _EVASIVE:
        m = re.search(pattern, low)
        if m:
            snippet = text[max(0, m.start() - 20): m.end() + 40].replace("\n", " ").strip()
            findings.append({"finding": label, "evidence": f'…{snippet}…'})

    return findings


def recommend(findings: list[dict]) -> str:
    """Heuristic action from findings alone (LLM refines the actual draft)."""
    if not findings:
        return "none"
    denial = any(k in f["finding"].lower() or k in f["evidence"].lower()
                 for f in findings for k in ("exemption", "unavailable", "does not hold",
                                             "vague", "transfer", "not confirmed as supplied",
                                             "not maintained"))
    return "first_appeal" if denial else "follow_up_rti"
