"""The window's pro-density surfaces: the version compare sheet and the tree's PMI section (plain Python, no kernel).

    GET /api/projects/<id>/compare?a=<n>&b=<m>     two revisions side by side: what each feature did (added, removed,
                                                    changed, suppressed, the same), the parameters that changed, and
                                                    the design source as a line diff. b defaults to the head.
    GET /api/projects/<id>/pmi                      what the drawing declares (form/drawing): datums, GD&T, fits with
                                                    their limits, surface texture and notes, and who declared each

Nothing here builds a solid. The volume, size and body-count deltas come from the geometric diff (form/geomdiff.py,
`/geomdiff`), which the window asks for separately because it runs booleans in the kernel. A feature is "changed"
when its method's code differs, a parameter it reads differs, or its faces in the two builds differ (the build
signatures both revisions already keep); the reason is said with it.
"""
from __future__ import annotations

import ast
import difflib

CONTEXT = 3                    # unchanged lines kept around each change in the script diff
MAX_ROWS = 4000                # a diff longer than this is cut, and says so


def _methods(source: str) -> dict:
    """{feature id: (label, method text, suppressed)} of a FeatureDesign source; {} for anything else."""
    from . import modelling
    try:
        _tree, _c, nodes = modelling._methods(source)
    except Exception:                                   # noqa: BLE001 - a plain Recipe, or source that does not parse
        return {}
    from . import featureprog
    src = featureprog.strip_partial(source)
    out = {}
    for fid, fn in nodes.items():
        kw = modelling._deco_kw(fn)
        out[fid] = (kw.get("label") or fid.replace("_", " ").capitalize(), ast.get_source_segment(src, fn) or "",
                    bool(kw.get("suppressed")))
    return out


def _features(st, p: dict, n: int, source: str | None) -> list:
    """[(id, label, method text, suppressed)] in build order: from the source when it is a FeatureDesign, else the recipe."""
    m = _methods(source or "")
    if m:
        return [(fid, lab, txt, sup) for fid, (lab, txt, sup) in m.items()]
    try:
        rec = st.recipe(p, n)
    except Exception:                                   # noqa: BLE001
        return []
    return [(f.id, f.label, "", bool(getattr(f, "suppressed", False))) for f in rec.features]


def _spec(st, p: dict, n: int, key: str):
    try:
        return st.recipe(p, n).spec(key)
    except Exception:                                   # noqa: BLE001
        return None


def _signature(st, p: dict, n: int) -> dict | None:
    """The per-feature face signature of a revision's build, when it is already recorded (never builds)."""
    try:
        gk = st.keys(p, n)["geometry"]
        s = st.read(p, "geometry", gk)
    except Exception:                                   # noqa: BLE001
        return None
    return (s or {}).get("signature")


def script_diff(a: str, b: str) -> dict:
    """The design source as a line diff: rows of {t: ctx|del|add|gap, a, b, text} (line numbers 1-based)."""
    la, lb = (a or "").splitlines(), (b or "").splitlines()
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    rows, added, removed = [], 0, 0
    for g in sm.get_grouped_opcodes(CONTEXT):
        if rows:
            rows.append({"t": "gap", "a": None, "b": None, "text": ""})
        for tag, i1, i2, j1, j2 in g:
            if tag == "equal":
                rows += [{"t": "ctx", "a": i1 + k + 1, "b": j1 + k + 1, "text": la[i1 + k]} for k in range(i2 - i1)]
                continue
            if tag in ("replace", "delete"):
                rows += [{"t": "del", "a": i + 1, "b": None, "text": la[i]} for i in range(i1, i2)]
                removed += i2 - i1
            if tag in ("replace", "insert"):
                rows += [{"t": "add", "a": None, "b": j + 1, "text": lb[j]} for j in range(j1, j2)]
                added += j2 - j1
    cut = len(rows) > MAX_ROWS
    return {"rows": rows[:MAX_ROWS], "cut": cut, "added": added, "removed": removed, "same": not added and not removed,
            "lines_a": len(la), "lines_b": len(lb)}


def compare(st, p: dict, a: int, b: int | None = None) -> dict:
    """Revision a against b (default: the head), read from both revisions' records and sources."""
    from .studio import StudioError
    b = p["head"] if b is None else int(b)
    a = int(a)
    ra, rb = st.rev(p, a), st.rev(p, b)                 # raises for a revision that does not exist
    if a == b:
        raise StudioError("Pick two different revisions.", "Compare an earlier revision with the head.")
    sa, sb = st.source_text(p, a) or "", st.source_text(p, b) or ""
    va, vb = ra.get("values") or {}, rb.get("values") or {}
    params = []
    for k in list(va) + [k for k in vb if k not in va]:
        x, y = va.get(k), vb.get(k)
        if x is not None and y is not None and abs(float(x) - float(y)) <= 1e-9:
            continue
        sp = _spec(st, p, b, k) or _spec(st, p, a, k)
        params.append({"key": k, "label": sp.label if sp else k, "unit": sp.unit if sp else "",
                       "feature": getattr(sp, "feature", "") if sp else "", "group": getattr(sp, "group", "") if sp else "",
                       "from": x, "to": y})
    by_feature: dict = {}
    for c in params:
        if c["feature"]:
            by_feature.setdefault(c["feature"], []).append(c["label"])
    fa, fb = _features(st, p, a, sa), _features(st, p, b, sb)
    ma = {f[0]: f for f in fa}
    sig_a, sig_b = _signature(st, p, a), _signature(st, p, b)
    feats = []
    for fid, lab, txt, sup in fb:
        old = ma.get(fid)
        if old is None:
            feats.append({"id": fid, "label": lab, "state": "added", "why": "new in r%02d" % b})
            continue
        why = []
        if old[3] != sup:
            feats.append({"id": fid, "label": lab, "state": "suppressed" if sup else "restored",
                          "why": "suppressed by hand" if sup else "built again"})
            continue
        if txt and old[2] and txt != old[2]:
            why.append("its code changed")
        if by_feature.get(fid):
            why.append("its values changed: " + ", ".join(by_feature[fid]))
        if old[1] != lab:
            why.append("renamed from " + old[1])
        if not why and sig_a is not None and sig_b is not None and sig_a.get(fid) != sig_b.get(fid):
            why.append("its faces in the solid changed: another feature changed what it made")
        feats.append({"id": fid, "label": lab, "state": "changed" if why else "same", "why": "; ".join(why)})
    ids_b = {f[0] for f in fb}
    removed = [{"id": fid, "label": lab, "state": "removed", "why": "not in r%02d" % b}
               for fid, lab, _t, _s in fa if fid not in ids_b]
    feats += removed

    def rev(r):
        return {"n": r["n"], "note": r.get("note") or "", "origin": r.get("origin") or "user", "ts": r.get("ts"),
                "summary": r.get("summary") or ""}
    return {"project": p["id"], "a": a, "b": b, "rev_a": rev(ra), "rev_b": rev(rb), "params": params, "features": feats,
            "script": script_diff(sa, sb), "source_a_lines": len(sa.splitlines()), "evidence": {
                "features": "read from both sources and the builds' face signatures (no build)",
                "params": "the revisions' values", "script": "a line diff of the design source"}}


def pmi(st, p: dict, n: int | None = None) -> dict:
    """What the drawing declares for revision n (default the head), without drawing it: datums, GD&T, fits (with the
    ISO 286 limits the last drawing computed, when one is made), surface texture and notes. Each says who declared it."""
    from . import drawing as dr
    r = st.rev(p, n)
    d = dr.design_spec(st.recipe(p, r["n"]), r["values"])
    s = dr.stored_spec(st, p["id"])
    out = {"rev": r["n"], "datums": [], "gdt": [], "fits": [], "surface": [], "notes": [],
           "general": s.get("general", d.get("general")) or "m", "error": d.get("_error") or ""}
    for src, spec in (("design", d), ("you", s)):
        for k in ("datums", "gdt", "fits", "surface", "notes"):
            for x in spec.get(k) or []:
                out[k].append({"by": src, **(x if isinstance(x, dict) else {"text": str(x)})})
    made = None
    try:
        made = dr.cached(st, p, r["n"])
    except Exception:                                   # noqa: BLE001 - no drawing made yet: the limits are not known
        made = None
    limits = {}
    for f in ((made or {}).get("report") or {}).get("fits") or []:
        limits[(f.get("class"), round(float(f.get("nominal") or 0), 4))] = f
    if limits:
        for f in out["fits"]:
            for (cls, _nom), lim in limits.items():
                if cls and cls == f.get("class"):
                    f["limits"] = {"min": lim.get("min"), "max": lim.get("max"), "nominal": lim.get("nominal")}
                    break
    out["drawn"] = bool(made)
    out["count"] = sum(len(out[k]) for k in ("datums", "gdt", "fits", "surface", "notes"))
    out["evidence"] = "declared (the design's drawing() and what you set); limits computed by ISO 286 when a drawing is made"
    return out


def route_get(st, p: dict, rest: str, q: dict):
    if rest == "/compare":
        return compare(st, p, int(q["a"]), int(q["b"]) if q.get("b") else None)
    if rest == "/pmi":
        return pmi(st, p, int(q["rev"]) if q.get("rev") else None)
    return None
