"""The Bench entry "Tolerance stack-up" (the Bench is form/studies.py), among the Check studies.

A design can hold several stacks (form/stack/__init__.py: definitions in stacks.json, results stored under a key of
everything they depend on), so the entry keeps its own record: current only when every stack is current for the head
revision, stale when any is, never when none is defined (it names the tool that defines one). Its headline is the
stack with the lowest Cpk, else the first; running it computes every stack that is not current.
"""
from __future__ import annotations

import math

ID = "stack"
LABEL = "Tolerance stack-up"
ORDER = ("stale", "never", "current")


def summary(st, p: dict) -> dict:
    from . import listing, stored
    rows = listing(st, p)
    if not rows:
        return {"state": "never", "headline": "", "stacks": [],
                "why": "No stack is defined yet: pick the two faces of a gap (tolerance_stack, or `form stack add`)."}
    worst = min(rows, key=lambda r: ORDER.index(r["state"]))
    out = {"state": worst["state"], "stacks": rows, "rev": worst.get("rev") or worst.get("last_rev"), "headline": ""}
    best = None
    for r in rows:
        if r["state"] != "current":
            continue
        res = stored(st, p, r["id"])[0] or {}
        c = ((res.get("capability") or {}).get("rss") or {}).get("cpk")
        k = c if isinstance(c, (int, float)) and math.isfinite(c) else math.inf
        if best is None or k < best[0]:
            best = (k, res)
    if best is not None:
        res = best[1]
        out["headline"] = (res.get("name") + ": " if res.get("name") else "") + res.get("headline", "")
        out["evidence"] = res.get("evidence")
    elif rows[0].get("headline"):
        out["headline"] = rows[0]["headline"]
    if worst["state"] == "stale":
        out["why"] = worst.get("why", "")
    return out


def run_all(st, pid: str, force: bool = False) -> dict:
    from . import listing, run
    p = st.load(pid)
    for r in listing(st, p):
        if force or r["state"] != "current":
            run(st, pid, r["id"])
    s = summary(st, st.load(pid))
    return {"headline": s.get("headline") or "", "evidence": s.get("evidence") or "computed",
            "detail": f"{len(s.get('stacks') or [])} stack(s)", "data": {"stacks": s.get("stacks")}}


def register_studies(register) -> None:
    from ..studies import Study
    from . import EVIDENCE
    register(Study(
        id=ID, group="study", label=LABEL,
        doc="The gap between two picked faces through the mates and each part's dimensions: worst case, RSS and "
            "Monte Carlo, Cpk, each tolerance's share, at a temperature span, and what to tighten first.",
        evidence=EVIDENCE,
        run=lambda ctx: run_all(ctx.st, ctx.p["id"]),
        state_fn=lambda ctx: summary(ctx.st, ctx.p),
        inputs=("geometry", "the stacks defined", "tolerances: request, drawing fits and GD&T, ISO 2768, process",
                "materials (expansion)"),
        by="engine", app="stack", tool="tolerance_stack", order=19, extra={"chapter": "check", "cli": "form stack"}))
