"""Named variants of a design: "Travel version", "Thick walls".

A variant is a name and a complete set of parameter values, stored in the project (project.json, "variants").
It points at a revision when its values are exactly that revision's, otherwise it is a saved draft that has not
been committed. Nothing about a variant is estimated: its geometry is built by the kernel on demand, and its
print time, grams and checks are shown only when a revision with the same values has current outputs.

    variants.save(st, p, "Thick walls", values={"wall": 3})     # values are changes on top of the head
    variants.board(st, p)                                        # head + every variant, with metrics and differences
    variants.promote(st, p, "thick-walls")                       # check out its revision, or commit it as a new one
"""
from __future__ import annotations

import re
import time

from .studio import H, StudioError

MAX_VARIANTS = 24


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "variant"


def _same(a: dict, b: dict) -> bool:
    return set(a) == set(b) and all(abs(float(a[k]) - float(b[k])) < 1e-9 for k in a)


def _rev_of(st, p: dict, values: dict) -> int | None:
    """The revision whose values these are (head first, then the newest), or None for a saved draft."""
    rid = st.rid(p)
    for r in [st.rev(p)] + sorted(p["revisions"], key=lambda r: -r["n"]):
        if (r.get("recipe") or p["recipe"]) == rid and _same(r["values"], values):
            return r["n"]
    return None


def find(p: dict, ident: str) -> dict:
    ident = str(ident or "").strip()
    for v in p.get("variants", []):
        if v["id"] == ident or v["name"].lower() == ident.lower():
            return v
    raise StudioError(f"No variant called “{ident}”.", "List them with list_variants (MCP) or `form variants list <project>`.",
                      status=404)


def save(st, p: dict, name: str, values: dict | None = None, rev: int | None = None, note: str = "", by: str = "you",
         source: str = "") -> dict:
    """Save a variant. values: changes on top of the head (or of rev). Without values it is the head (or rev) itself.
    A variant with the same name is replaced. The candidate must build before it is saved."""
    name = " ".join(str(name or "").split())[:60]
    if not name:
        raise StudioError("Give the variant a name.", "For example “Travel version” or “Thick walls”.")
    with st.lock(p["id"]):
        p = st.load(p["id"])
        base = st.rev(p, rev)
        rid = st.rid(p, base["n"])
        if rid != st.rid(p):
            raise StudioError(f"r{base['n']:02d} was built from different design source than the head.",
                              "Check that revision out first, then save the variant.")
        unknown = [k for k in (values or {}) if k not in base["values"]]
        if unknown:
            raise StudioError("Unknown parameter(s): " + ", ".join(unknown) + ".", "List valid keys with describe_recipe or `form recipe <id>`.")
        vals = st._validate(rid, {**base["values"], **{k: float(v) for k, v in (values or {}).items()}})
        st._k("summary", key="pv-" + H(rid, vals), recipe_id=rid, values=vals, tol=0.1, p=p)      # it must build
        vid = _slug(name)
        old = [v for v in p.get("variants", []) if v["id"] != vid]
        if len(old) >= MAX_VARIANTS:
            raise StudioError(f"A project keeps up to {MAX_VARIANTS} variants.", "Delete one first.")
        rec = {"id": vid, "name": name, "values": vals, "recipe": rid, "note": str(note or "")[:300], "by": by,
               "created": time.time(), "source": source or ("revision" if _rev_of(st, p, vals) else "draft")}
        p["variants"] = old + [rec]
        st.decide(p, "variant", f"Variant “{name}” saved" + (f" ({rec['note']})" if rec["note"] else "") + ".")
        st.save(p)
        return describe(st, p, rec)


def delete(st, p: dict, ident: str) -> dict:
    with st.lock(p["id"]):
        p = st.load(p["id"])
        v = find(p, ident)
        p["variants"] = [x for x in p["variants"] if x["id"] != v["id"]]
        st.decide(p, "variant", f"Variant “{v['name']}” deleted.")
        st.save(p)
        return {"deleted": v["id"]}


def promote(st, p: dict, ident: str, origin: str = "user") -> dict:
    """Make a variant the head: check out the revision it points at, or commit its values as a new revision."""
    v = find(p, ident)
    if v.get("recipe") and v["recipe"] != st.rid(p):
        raise StudioError(f"“{v['name']}” was saved for different design source than the head.",
                          "Check out the revision it was saved from, then promote it.", status=409)
    n = _rev_of(st, p, v["values"])
    if n is not None:
        if n == p["head"]:
            return {"head": n, "how": "already the head", "variant": v["id"]}
        p = st.checkout(p, n)
        return {"head": p["head"], "how": f"checked out r{n:02d}", "variant": v["id"]}
    head = st.rev(p)
    changes = {k: x for k, x in v["values"].items() if k in head["values"] and abs(x - head["values"][k]) > 1e-9}
    p = st.commit(p, changes, f"Promoted variant “{v['name']}”", origin)
    return {"head": p["head"], "how": f"committed as r{p['head']:02d}", "variant": v["id"]}


def _metrics(st, p: dict, values: dict, n: int | None) -> dict:
    """What is known about a set of values. Geometry is computed now; slice and checks only if a revision has them."""
    rid = st.rid(p)
    s = st._k("summary", key="pv-" + H(rid, values), recipe_id=rid, values=values, tol=0.1, p=p, rev=n)
    lo, hi = s["bbox"]
    out = {"bbox_mm": [round(b - a, 2) for a, b in zip(lo, hi)], "volume_cm3": round(s["volume_mm3"] / 1000, 2),
           "evidence": {"volume_cm3": "computed", "bbox_mm": "computed"}, "slice": None, "checks": None, "fit": None}
    try:
        fit = st.fit(p, values)
        if fit:
            out["fit"] = {"yield": fit["yield"], "evidence": "modelled"}
    except Exception:
        pass
    if n is not None:
        try:
            keys = st.keys(p, n)
            sl = st.read(p, "slice", keys["slice"])
            if sl and sl.get("time_s"):
                out["slice"] = {"time_s": sl["time_s"], "filament_g": sl.get("filament_g"), "evidence": "simulated",
                                "slicer": sl.get("slicer_name") or "Bambu Studio"}
            ch = st.read(p, "checks", keys["checks"])
            if ch:
                out["checks"] = {**ch["rollup"], "evidence": "computed"}
        except StudioError:
            pass
    return out


def describe(st, p: dict, v: dict, metrics: bool = True) -> dict:
    head = st.rev(p)
    recipe = st.recipe(p)
    n = _rev_of(st, p, v["values"]) if (v.get("recipe") or st.rid(p)) == st.rid(p) else None
    diffs = []
    for k, x in v["values"].items():
        if k in head["values"] and abs(x - head["values"][k]) > 1e-9:
            try:
                sp = recipe.spec(k)
                diffs.append({"key": k, "label": sp.label, "unit": sp.unit, "from": head["values"][k], "to": x})
            except KeyError:
                pass
    out = {"id": v["id"], "name": v["name"], "note": v.get("note", ""), "by": v.get("by", "you"), "created": v.get("created"),
           "source": v.get("source", ""), "rev": n, "is_head": n == p["head"], "differences": diffs, "values": v["values"]}
    if metrics:
        try:
            out["metrics"] = _metrics(st, p, v["values"], n)
        except StudioError as e:                      # the recipe changed under it: say so, keep the variant
            out["error"] = e.public()
    return out


def listing(st, p: dict, metrics: bool = False) -> list:
    return [describe(st, p, v, metrics) for v in p.get("variants", [])]


def board(st, p: dict) -> dict:
    """The head and every variant side by side: metrics with how each is known, and differences from the head."""
    head = st.rev(p)
    base = {"id": "@head", "name": f"Head r{p['head']:02d}", "note": head.get("note", ""), "rev": p["head"], "is_head": True,
            "differences": [], "values": head["values"], "metrics": _metrics(st, p, head["values"], p["head"])}
    rows = listing(st, p, metrics=True)
    # which metrics differ at all: the board highlights those
    def val(r, k):
        m = r.get("metrics") or {}
        return {"volume": m.get("volume_cm3"), "time": (m.get("slice") or {}).get("time_s"), "grams": (m.get("slice") or {}).get("filament_g"),
                "fit": (m.get("fit") or {}).get("yield"), "size": tuple(m.get("bbox_mm") or [])}[k]
    differs = [k for k in ("volume", "time", "grams", "fit", "size") if len({val(r, k) for r in [base] + rows}) > 1]
    return {"head": p["head"], "cards": [base] + rows, "differs": differs,
            "note": "Volume and size are computed from the built solid. Print time and grams appear only for a variant that is a "
                    "revision with a current slice (simulated). Fit yield is modelled."}


def view(st, p: dict, ident: str) -> dict:
    """Kernel geometry of a variant for the 3D cards."""
    if ident == "@head":
        return st.view(p, tol=0.08)
    v = find(p, ident)
    rid = st.rid(p)
    out = st._k("view", key="pv-" + H(rid, v["values"]), recipe_id=rid, values=v["values"], tol=0.08, p=p,
                rev=_rev_of(st, p, v["values"]))
    out["companions"] = []
    return out
