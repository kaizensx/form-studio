"""Verdicts: what a tool result says about a design, read the same way whatever tool produced it.

A tool result that reports checks leads with two keys (form/digest.py):

    verdict   "FAIL" | "WARN" | "PASS" | "UNCHECKED"   the worst check status (UNCHECKED: no checks have run)
    blocking  ["Thinnest wall: 0.00 mm [computed]", ...] one line per FAIL row, empty when nothing fails

The chat's end-of-run gate (form/chat.py) reads tool results with `fails()`: it takes `verdict`/`blocking` where a
result has them, and otherwise finds the FAIL rows itself, in any of the shapes results use: digest check lines
("FAIL  label: value  [evidence]"), check dicts ({"status": "FAIL", "label", "value"}), and a proof sheet when one is
present ({"proof": {"rows"|"checks"|"claims": [{"verdict"|"status": "FAIL", ...}]}}). Nothing here knows a check by
name: a new check, or a new proof row, is gated the moment it reports FAIL.
"""
from __future__ import annotations

import json
import re

ORDER = ("PASS", "WARN", "FAIL")
_LINE = re.compile(r"^\s*FAIL\s+(.+?)\s*$")
_ACK = re.compile(r"\bfail(?:s|ed|ing|ure|ures)?\b|\bFAIL\b|n[ãa]o passa|falha", re.I)


def of_checks(checks: list) -> tuple[str, list[str]]:
    """(verdict, blocking) of a check list: rows as dicts ({"status", "label", "value", "evidence"}) or as digest
    lines ("FAIL  label: value  [evidence]")."""
    worst, blocking, seen = None, [], False
    for c in checks or []:
        st, text = _row(c)
        if st is None:
            continue
        seen = True
        if st in ORDER and (worst is None or ORDER.index(st) > ORDER.index(worst)):
            worst = st
        if st == "FAIL":
            blocking.append(text)
    if not seen:
        return "UNCHECKED", []
    return worst or "PASS", blocking


def _row(c) -> tuple[str | None, str]:
    if isinstance(c, str):
        m = re.match(r"^\s*(PASS|WARN|FAIL|N/A)\s+(.+?)\s*$", c)
        return (m.group(1), m.group(2)) if m else (None, c)
    if isinstance(c, dict):
        st = str(c.get("verdict") or c.get("status") or "").upper() or None
        label = c.get("label") or c.get("claim") or c.get("id") or "check"
        value = c.get("value")
        ev = c.get("evidence")
        return st, f"{label}: {value}" + (f" [{ev}]" if ev else "") if value not in (None, "") else str(label)
    return None, ""


def lead(result: dict) -> dict:
    """The result with `verdict` and `blocking` as its first keys, from its `checks` (and its proof sheet when it has
    one). A result without checks gets verdict UNCHECKED."""
    rows = list(result.get("checks") or [])
    proof = result.get("proof")
    if isinstance(proof, dict):
        rows += _proof_rows(proof)
    v, b = of_checks(rows)
    part = result.get("partial") or {}
    if isinstance(part, dict) and part.get("failed"):
        b = b + [f"Partial build: {part['failed']} did not build"]
        v = "FAIL"
    rest = {k: x for k, x in result.items() if k not in ("verdict", "blocking")}
    return {"verdict": v, "blocking": b, **rest}


def _proof_rows(proof: dict) -> list:
    for k in ("rows", "checks", "claims", "items"):
        if isinstance(proof.get(k), list):
            return proof[k]
    return []


def _objects(text: str) -> list:
    """Every JSON value in a tool result's text (results are one JSON document, or JSON after a line of prose)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        return [json.loads(text)]
    except ValueError:
        pass
    out, dec, i = [], json.JSONDecoder(), 0
    while True:
        j = min([x for x in (text.find("{", i), text.find("[", i)) if x >= 0], default=-1)
        if j < 0:
            return out
        try:
            obj, end = dec.raw_decode(text, j)
            out.append(obj)
            i = end
        except ValueError:
            i = j + 1


def fails(text: str) -> list[dict]:
    """[{"project": id | None, "rows": [blocking line, ...], "verdict": str}] for every report of checks in a tool
    result's text (one per project reported). A report with no FAIL row is returned with rows=[]: it clears that
    project's earlier failures (the agent fixed them)."""
    out = []
    for obj in _objects(text):
        _walk(obj, None, out, 0)
    return out


def _walk(o, project, out: list, depth: int) -> None:
    if depth > 6:
        return
    if isinstance(o, list):
        for x in o:
            _walk(x, project, out, depth + 1)
        return
    if not isinstance(o, dict):
        return
    pid = o.get("project") if isinstance(o.get("project"), str) else project
    if "verdict" in o and isinstance(o.get("blocking"), list):
        out.append({"project": pid, "verdict": str(o["verdict"]), "rows": [str(x) for x in o["blocking"]]})
    elif isinstance(o.get("checks"), list) or isinstance(o.get("proof"), dict):
        led = lead(o)
        if led["verdict"] != "UNCHECKED":
            out.append({"project": pid, "verdict": led["verdict"], "rows": led["blocking"]})
    for k, x in o.items():
        if k in ("checks", "blocking", "proof"):
            continue
        if isinstance(x, (dict, list)):
            _walk(x, pid, out, depth + 1)


def acknowledged(rows: list[str], reply: str) -> bool:
    """The agent's reply says the failing checks fail: it names each one (its label), or says "fail" plainly."""
    if not rows:
        return True
    text = reply or ""
    if _ACK.search(text):
        return True
    low = text.lower()
    return all(r.split(":")[0].strip().lower() in low for r in rows if r.split(":")[0].strip())


def continuation(open_fails: dict) -> str:
    """The one message the gate sends when a reply ended without reporting FAIL rows."""
    lines = []
    for pid, rows in open_fails.items():
        lines.append(f"{pid or 'the design'}:")
        lines += [f"- FAIL {r}" for r in rows]
    return ("Form Studio check before this reply ends: these checks FAIL, and your reply did not report them.\n"
            + "\n".join(lines) + "\n"
            "Fix them (change the design, then read get_project again) or tell the person plainly which checks fail, "
            "what that means for the design and what you would change. Do not call the design done while a check "
            "fails. This reminder is sent once.")
