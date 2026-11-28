"""The Bench entry of the strength studies (the Bench is form/studies.py).

The Bench lists every study of a design with its state. Strength registers one entry, "strength", through the hook
the Bench gives later waves: this module is named in `studies.PROVIDERS` and has `register_studies(register)`, so the
entry appears in the Bench, the palette, `form study list` and list_studies.

A design can hold several strength studies (form/fea/study.py), each with its own key and stored result, so the entry
keeps its own record (`state_fn`): it is current only when every defined study is current for the head revision,
stale when any is, and its headline is the lowest safety factor among the current static studies (or the first
study's headline when none gives one). Its run action solves every study that is not current, one after another.
With no study defined it is "never", and names the tool that defines one.
"""
from __future__ import annotations

ID = "strength"
EVIDENCE = "simulated (FEA, linear static, converged to N %)"
ORDER = ("running", "failed", "unavailable", "stale", "never", "current")     # the entry shows its worst study


def summary(st, p: dict) -> dict:
    """The state of the design's strength studies as one Bench entry. Importable without the Bench."""
    from . import HOW_TO_GET, python
    from . import study
    rows = study.listing(st, p)
    if not rows:
        out = {"state": "never", "headline": "", "studies": [],
               "why": "No strength study is defined for this design yet (strength_study: pick the faces that are held "
                      "and the faces that are loaded)."}
        if python(st.cfg) is None:
            out.update({"state": "unavailable", "state_before": "never", "why": HOW_TO_GET})
        return out
    worst = min(rows, key=lambda r: ORDER.index(r["state"]) if r["state"] in ORDER else 0)
    out = {"state": worst["state"], "studies": rows, "rev": worst.get("rev") or worst.get("last_rev"), "headline": ""}
    factors = []
    for r in rows:
        if r["state"] != "current" or r["kind"] != "static":
            continue
        res = study.result(st, p, r["id"]).get("result") or {}
        if res.get("safety_factor"):
            factors.append((res["safety_factor"]["value"], res))
    if factors:
        _, res = min(factors, key=lambda x: x[0])
        out.update({"headline": res["headline"], "evidence": res["evidence"]})
    else:
        first = next((r for r in rows if r.get("headline")), None)
        if first:
            out.update({"headline": first["headline"], "evidence": first.get("evidence") or EVIDENCE})
    if worst["state"] in ("stale", "failed", "unavailable"):
        out["why"] = worst.get("why") or (worst.get("error") or {}).get("message") or ""
    if worst["state"] == "running":
        out["job"] = worst.get("job")
    return out


def run_all(st, pid: str, force: bool = False) -> dict:
    """Solve every study of the design that is not current. Returns the entry's summary afterwards."""
    from . import study
    p = st.load(pid)
    for r in study.listing(st, p):
        if force or r["state"] in ("never", "stale", "failed"):
            study.run(st, pid, r["id"], force=force)
    p = st.load(pid)
    s = summary(st, p)
    return {"headline": s.get("headline") or "", "evidence": s.get("evidence") or EVIDENCE,
            "detail": f"{len(s.get('studies') or [])} strength studies", "data": {"studies": s.get("studies")}}


def register_studies(register) -> None:
    """The Bench's hook for later waves (form/studies.py PROVIDERS)."""
    from ..studies import Study
    register(Study(
        id=ID, group="study", label="Strength",
        doc="Stress, displacement and a safety factor under the loads you define, with the discretisation error "
            "stated; also natural frequencies and buckling.",
        evidence=EVIDENCE,
        run=lambda ctx: run_all(ctx.st, ctx.p["id"]),
        state_fn=lambda ctx: summary(ctx.st, ctx.p),
        needs=("step",), inputs=("geometry", "material", "supports and loads", "engine"),
        by="engine", app="strength", tool="strength_study", heavy=True, order=24))
