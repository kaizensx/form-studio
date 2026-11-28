"""The Bench entry of the engineering calculators (the Bench is form/studies.py).

One entry, "calc", among the studies of the Design chapter: for a design a calculator wrote, the calculation run again
on the head revision's values. It is computed when listed (it is cheap), so it is never stale: change the hook's
length and the entry's strain is the new length's. Its headline is the calculator's own, its evidence names the
standard, and its data is the full sheet (values with their evidence, checks, equations, sources). A design no
calculator wrote has no calculation to show: the entry says so and names the tool that writes one.
"""
from __future__ import annotations

ID = "calc"
LABEL = "Engineering calculation"


def state(ctx) -> dict:
    from . import design
    c = design.record(ctx.st.source_text(ctx.p))
    if c is None:
        return {"state": "n/a", "why": "No calculation: this design was not written by a calculator (calculate, or `form calc`, "
                                       "sizes a snap fit, hinge, spring, bolted joint, gear pair, cam or fit and writes it)."}
    r = design.recompute(c, {**ctx.rev["values"], **c["const"]})
    worst = [k for k in r["checks"] if k["status"] in ("FAIL", "WARN")]
    return {"state": "current", "rev": ctx.p["head"], "live": True,
            "headline": ("FAIL: " if r["status"] == "FAIL" else "") + r["headline"],
            "evidence": "computed (" + (r.get("standard") or c["calculator"]) + ")",
            "detail": "; ".join(f"{k['status']} {k['label']}: {k['value']}" for k in worst) or "every check passes",
            "data": {"calculator": c["calculator"], "status": r["status"], "sheet": r}}


def register_studies(register) -> None:
    """The Bench's hook for later waves (form/studies.py PROVIDERS)."""
    from ..studies import Study
    register(Study(
        id=ID, group="study", label=LABEL,
        doc="The standard's calculation behind this design (snap fit, hinge, spring, bolted joint, gears, cam, fit), "
            "run again on this revision's values, every number labelled computed, specified or assumed.",
        evidence="computed (the standard named)", state_fn=state,
        run=lambda ctx: {k: v for k, v in state(ctx).items() if k in ("headline", "evidence", "detail", "data")},
        inputs=("values", "the calculation in the design's source", "the materials library"),
        by="engine", app="calc", tool="calculate", order=16, extra={"chapter": "design"}))
