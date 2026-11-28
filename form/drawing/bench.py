"""The Bench entries of engineering drawings (the Bench is form/studies.py).

Two entries: the drawing itself (a document: PDF, SVG, DXF and previews, on the sheet the design or the person chose,
A3 by default) and STEP AP242 with semantic PMI (a route: the drawing's dimensions, tolerances, datums and GD&T on the
solid's faces, read back annotation by annotation). Their keys are the drawing's own cache key (form.drawing.cache_key:
geometry, spec, options, release, and the title block's material and mass), so a dragged dimension, a new datum or a
new material makes them stale. Nothing here needs the kernel to say a state: probe() reads what was made.
"""
from __future__ import annotations

import json
from pathlib import Path


def _key(ctx) -> str:
    from . import _resolve, cache_key
    r, spec, sheet, projection = _resolve(ctx.st, ctx.p, None, None, None)
    return cache_key(ctx.st, ctx.p, r, spec, sheet, projection)


def _result(d: dict) -> dict:
    rep = d.get("report") or {}
    comp = rep.get("completeness") or {}
    a = rep.get("annotations") or {}
    bits = [comp.get("text", "")]
    if a:
        bits.append(f"{a.get('gdt', 0)} GD&T, {a.get('datums', 0)} datums")
    if rep.get("overlaps"):
        bits.append(f"{len(rep['overlaps'])} overlaps")
    head = f"{rep.get('sheet', 'A3')} · " + ", ".join(b for b in bits if b)
    t = d.get("title") or {}
    detail = "; ".join(x for x in (
        f"scale {rep['scale']}" if rep.get("scale") else "",
        f"material {t['material']}" if t.get("material") else "no material in the title block",
        f"mass {t['mass']} ({t.get('mass_evidence', '')})" if t.get("mass") else "") if x)
    files = [d["paths"][k] for k in ("pdf", "svg", "dxf") if k in (d.get("paths") or {})]
    return {"headline": head, "evidence": "computed (HLR on the B-rep; dimensions proved by a nudged build)",
            "detail": detail, "files": files,
            "data": {"rev": d.get("rev"), "key": d.get("key"), "completeness": comp, "title": t}}


def _run(ctx) -> dict:
    from . import build
    return _result(build(ctx.st, ctx.p))


def _probe(ctx):
    from . import cached
    d = cached(ctx.st, ctx.p)
    return _result(d) if d else None


def _pmi_result(d: dict, chk: dict) -> dict:
    return {"headline": f"{chk['passed']} of {chk['written']} annotations read back", "evidence": "computed (read back from the file)",
            "detail": chk.get("note", ""), "files": [chk["path"]], "data": {"schema": chk.get("schema"), "rows": chk.get("rows")}}


def _pmi_run(ctx) -> dict:
    from . import build, export_pmi
    chk = export_pmi(ctx.st, ctx.p)
    return _pmi_result(build(ctx.st, ctx.p, formats=()), chk)


def _pmi_probe(ctx):
    from . import cached
    d = cached(ctx.st, ctx.p, formats=())
    if not d:
        return None
    f = Path(d["dir"]) / "pmi_check.json"
    return _pmi_result(d, json.loads(f.read_text(encoding="utf-8"))) if f.is_file() else None


def register_studies(register) -> None:
    """The Bench's hook for later waves (form/studies.py PROVIDERS)."""
    from ..studies import Study
    register(Study(
        id="drawing", group="document", label="Drawing",
        doc="A shop drawing from the solid: hidden-line views, a section, every size parameter dimensioned once, ISO 286 "
            "fits, GD&T, and a title block with the material and the mass from the B-rep.",
        evidence="computed", run=_run, probe=_probe, key=_key,
        inputs=("geometry", "the drawing spec", "sheet and projection", "material", "release"),
        app="drawing", tool="drawing", heavy=False, order=21))
    register(Study(
        id="drawing.pmi", group="route", label="STEP with PMI",
        doc="STEP AP242 with the drawing's dimensions, tolerances, datums and GD&T attached to faces, read back and "
            "compared annotation by annotation.",
        evidence="computed (read back from the file)", run=_pmi_run, probe=_pmi_probe,
        key=lambda ctx: _key(ctx) + ".pmi",
        inputs=("geometry", "the drawing spec", "material"), tool="export_pmi", order=13))
