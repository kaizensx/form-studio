"""Several meshes of one mechanism: tie the dimensions where the parts meet. numpy and scipy; the source helper is text.

Parts reconstructed one by one are each editable, but the rail of one and the slot of the other are separate Params:
change one and the parts no longer fit. Here the interfaces are found from the meshes, in the coordinates the files
share (parts exported from one assembly sit where they belong):

- two walls facing each other across a small gap (opposite normals, parallel, overlapping, at most `near` apart): the
  coordinate Param of one part's wall and that of the other's are bound, the second written as the first plus a
  clearance Param (a rail in a slot, a slider between guides);
- a round hole in one part and a round pin or boss in the other on one axis: the diameters are bound the same way,
  with the diametral clearance as the Param;
- equal levels (a face of each part at the same height, touching) are bound with no clearance.

`bind` returns the bindings with their evidence (what was measured, where); `combined_source` writes the program
recipes of the parts (program.py) as one multi-part design whose bound Params are one Param plus a clearance. The
multi-mesh `reconstruct` entry point (outside this package) calls both after reconstructing each part.

    bind(parts, near=1.0, tol=0.05) -> {"bindings": [...], "pairs": [...], "summary": str}
        parts: [{"name": str, "V": (n, 3), "F": (m, 3), "origin": (3,), "params": [program Param dicts]}]
               (pipeline.reconstruct's report carries "origin" and "params" under layers["2"] for the program route)
    combined_source(parts, bindings, title) -> str
        parts: [{"name": str, "source": program recipe text}]
"""
from __future__ import annotations

import re

import numpy as np

AXES = {"X": 0, "Y": 1, "Z": 2}


def _walls(V, F, axis, value, eps):
    """Triangles of a mesh lying on the plane (axis = value): (their corners (n, 3, 3), normal sign along the axis,
    areas)."""
    from .mesh import tri_normals
    N, A = tri_normals(V, F)
    C = V[F].mean(axis=1)
    k = AXES[axis]
    on = (np.abs(C[:, k] - value) <= eps) & (np.abs(N[:, k]) > 0.999)
    return V[F[on]], np.sign(N[on, k]), A[on]


def _overlap(Ta, Tb, k, reach):
    """Do two sets of triangles on parallel planes face each other: does some triangle of one overlap some triangle of
    the other, seen across the planes (their extents in the other two coordinates, `reach` apart at most)?"""
    if not len(Ta) or not len(Tb):
        return False
    other = [i for i in range(3) if i != k]
    la, ha = Ta[:, :, other].min(axis=1), Ta[:, :, other].max(axis=1)
    lb, hb = Tb[:, :, other].min(axis=1), Tb[:, :, other].max(axis=1)
    sep = np.maximum(la[:, None, :] - hb[None, :, :], lb[None, :, :] - ha[:, None, :]).max(axis=2)
    return bool((sep <= reach).any())


def bind(parts: list, near: float = 1.0, tol: float = 0.05) -> dict:
    """Bindings between the Params of parts that meet (see the module's doc)."""
    out, pairs = [], []
    world = []
    for p in parts:
        O = np.asarray(p.get("origin", (0.0, 0.0, 0.0)), dtype=np.float64)
        rows = []
        for q in p.get("params", []):
            kind = q.get("kind")
            if kind in AXES:
                rows.append((q, kind, O[AXES[kind]] + q["value"], O[AXES[kind]] - q["value"] if q.get("mirrored") else None))
            elif kind == "d":
                rows.append((q, "d", q["value"], None))
        world.append(rows)
    eps = max(tol / 4, 1e-4)
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            A, B = parts[i], parts[j]
            found = []
            for qa, ka, wa, wa2 in world[i]:
                if ka == "d":
                    continue
                for qb, kb, wb, wb2 in world[j]:
                    if kb != ka:
                        continue
                    for sa, va in ((1, wa), (-1, wa2)):
                        if va is None:
                            continue
                        for sb, vb in ((1, wb), (-1, wb2)):
                            if vb is None:
                                continue
                            gap = vb - va
                            if abs(gap) > near:
                                continue
                            Ca, na, _ = _walls(A["V"], A["F"], ka, va, eps)
                            Cb, nb, _ = _walls(B["V"], B["F"], kb, vb, eps)
                            if not len(Ca) or not len(Cb):
                                continue
                            k = AXES[ka]
                            # facing: A's wall normal points toward B's wall, B's back toward A's (or they touch)
                            if abs(gap) <= eps:
                                facing = np.any(na[:, None] == -nb[None, :])
                            else:
                                facing = np.any(na == np.sign(gap)) and np.any(nb == -np.sign(gap))
                            if not facing or not _overlap(Ca, Cb, k, 0.0):
                                continue
                            OA = float(np.asarray(A.get("origin", (0, 0, 0)), dtype=np.float64)[k])
                            OB = float(np.asarray(B.get("origin", (0, 0, 0)), dtype=np.float64)[k])
                            found.append({"kind": "contact" if abs(gap) <= eps else "gap", "axis": ka,
                                          "a": {"part": A["name"], "key": qa["key"], "label": qa["label"], "side": sa},
                                          "b": {"part": B["name"], "key": qb["key"], "label": qb["label"], "side": sb},
                                          "gap_mm": round(float(gap) if abs(gap) > eps else 0.0, 4), "offset_mm": OA - OB,
                                          "clearance_mm": round(float(abs(gap)) if abs(gap) > eps else 0.0, 4),
                                          "at_mm": round(float(va), 4),
                                          "evidence": f"walls of {A['name']} at {ka} {va:.3f} and of {B['name']} at {ka} "
                                                      f"{vb:.3f} face each other ({abs(gap):.3f} mm apart; computed from "
                                                      "the meshes)"})
            # round fits: a diameter Param in each part, nearly equal, with circles on one axis
            for qa, ka, da, _ in world[i]:
                if ka != "d":
                    continue
                for qb, kb, db, _ in world[j]:
                    if kb != "d" or abs(db - da) > 2 * near:
                        continue
                    if _coaxial(A, qa, B, qb, tol):
                        found.append({"kind": "fit", "axis": None,
                                      "a": {"part": A["name"], "key": qa["key"], "label": qa["label"], "side": 1},
                                      "b": {"part": B["name"], "key": qb["key"], "label": qb["label"], "side": 1},
                                      "clearance_mm": round(float(db - da), 4), "at_mm": None,
                                      "evidence": f"a Ø{da:g} of {A['name']} and a Ø{db:g} of {B['name']} on one axis "
                                                  "(computed from the meshes)"})
            # one binding per pair of Params
            seen = set()
            for b in found:
                key = (b["a"]["key"], b["b"]["key"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(b)
            if found:
                pairs.append({"a": A["name"], "b": B["name"], "bindings": len(seen)})
    summ = (f"{len(out)} interface dimension{'s' if len(out) != 1 else ''} tied between "
            + (", ".join(f"{p['a']} and {p['b']} ({p['bindings']})" for p in pairs) if pairs else "no parts")
            + " (computed from the meshes)")
    return {"bindings": out, "pairs": pairs, "summary": summ}


def _coaxial(A, qa, B, qb, tol):
    """Is there a circle of each diameter on one axis, in the two meshes? (cylindrical walls at that radius about a
    common line along X, Y or Z)."""
    from .mesh import tri_normals
    ra, rb = qa["value"] / 2, qb["value"] / 2
    for k in range(3):
        cs = []
        for P, r in ((A, ra), (B, rb)):
            N, _ = tri_normals(P["V"], P["F"])
            C = P["V"][P["F"]].mean(axis=1)
            side = np.abs(N[:, k]) < 1e-3
            if side.sum() < 6:
                cs.append(None)
                continue
            # centres of the circle: each wall point minus r along its normal (outward for a pin, inward for a hole)
            o = [i for i in range(3) if i != k]
            cand = np.r_[C[side][:, o] - r * N[side][:, o], C[side][:, o] + r * N[side][:, o]]
            cs.append(cand)
        if cs[0] is None or cs[1] is None:
            continue
        from scipy.spatial import cKDTree
        t = cKDTree(cs[1])
        d, _ = t.query(cs[0], k=1)
        if int((d <= max(tol, 0.02)).sum()) >= 6:
            return True
    return False


# ---- one multi-part source -------------------------------------------------------------------------------------------

_PARAM = re.compile(r"^(\s*)Param\('([a-z]+\d+)', ")


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "part"


def combined_source(parts: list, bindings: list, title: str = "Assembly") -> str:
    """One design from the program recipes of several parts: each part's build is a method, its Params prefixed with the
    part's name, and every bound Param of the second part written as the first part's Param plus a clearance Param.
    The design's solids are the parts in place (as the meshes put them); assembly() lists them."""
    heads, params, feats, bodies = [], [], [], []
    slugs = [_slug(p["name"]) for p in parts]
    bound = {}                                         # (part slug, key) -> expression
    clear = []
    for n, b in enumerate(bindings, 1):
        sa, sb = _slug(b["a"]["part"]), _slug(b["b"]["part"])
        a_ = f"v['{sa}_{b['a']['key']}']"
        if b["kind"] == "fit":                         # one diameter plus the diametral fit
            ck, gap = f"fit{n}", b["clearance_mm"]
            expr = f"({a_} + v['{ck}'])"
        else:                                          # world coordinate of b = world coordinate of a + the gap
            ck, gap = f"fit{n}", b.get("gap_mm", 0.0)
            sa_, sb_ = b["a"]["side"], b["b"]["side"]
            off = b.get("offset_mm", 0.0)
            inner = f"{off:g} + {'' if sa_ > 0 else '-'}{a_}" + (f" + v['{ck}']" if b["kind"] != "contact" else "")
            expr = f"({'' if sb_ > 0 else '-'}({inner}))"
        if b["kind"] != "contact":
            lab = f"Fit {n}: {b['a']['part']} to {b['b']['part']}" + (f" along {b['axis']}" if b.get("axis") else " (diameter)")
            lo, hi = min(gap - 0.5, -0.2), max(gap + 0.5, 0.2)
            clear.append(f"        Param({ck!r}, {lab!r}, {gap:g}, {lo:g}, {hi:g}, 0.01, 'mm', 'interface', 'fits', "
                         f"{b['evidence']!r}, provenance='mesh'),")
        bound[(sb, b["b"]["key"])] = expr
    for p, sl in zip(parts, slugs):
        src = p["source"]
        lines = src.splitlines()
        try:
            i_par = next(i for i, ln in enumerate(lines) if ln.strip() == "params = [")
            i_feat = next(i for i, ln in enumerate(lines) if ln.strip() == "features = [")
            i_build = next(i for i, ln in enumerate(lines) if ln.strip() == "def build(self, v):")
            i_ret = max(i for i, ln in enumerate(lines) if ln.strip() == "return stages")
        except StopIteration:
            raise ValueError(f"{p['name']}: not a recipe written by the program route") from None
        for ln in lines[:lines.index("class Design(Recipe):")]:
            if ln.startswith(("from ", "import ")) and ln not in heads:
                heads.append(ln)
            m = re.match(r"^(O|OVER) = (.*)$", ln)
            if m:
                heads.append(f"{m.group(1)}_{sl.upper()} = {m.group(2)}")
        for ln in lines[i_par + 1:i_feat - 1]:
            m = _PARAM.match(ln)
            if not m:
                continue
            key = m.group(2)
            if (sl, key) in bound:
                continue                               # driven by the other part (plus a clearance)
            ln = ln.replace(f"Param('{key}', '", f"Param('{sl}_{key}', '{p['name']}: ", 1)
            ln = re.sub(r"'form', '([^']+)'", lambda m: f"'form', '{sl}_{m.group(1)}'", ln, count=1)
            params.append(ln)
        for ln in lines[i_feat + 1:i_build - 2]:
            if ln.strip().startswith("Feature("):
                ln = re.sub(r"Feature\('([^']+)', '", lambda m: f"Feature('{sl}_{m.group(1)}', '{p['name']}: ", ln, count=1)
                feats.append(ln)
        body = lines[i_build + 1:i_ret]
        out = [f"    def _{sl}(self, v):"]
        for ln in body:
            ln = re.sub(r"v\['([a-z]+\d+)'\]", lambda m: bound.get((sl, m.group(1)), f"v['{sl}_{m.group(1)}']"), ln)
            ln = re.sub(r"Stage\('([^']+)'", lambda m: f"Stage('{sl}_{m.group(1)}'", ln)
            ln = re.sub(r"_f = '([^']+)'", lambda m: f"_f = '{sl}_{m.group(1)}'", ln)
            ln = re.sub(r"\bOVER\b", f"OVER_{sl.upper()}", ln)
            ln = re.sub(r"origin=O\b", f"origin=O_{sl.upper()}", ln)
            out.append(ln)
        out.append("        return stages")
        bodies.append("\n".join(out))
    heads = [h for h in heads if not h.startswith("from form.recipes.base")] + \
        ["from build123d import Compound", "from form.recipes.base import Feature, Param, Recipe, Stage",
         "from form.recipes.assembly import Assembly, Part"]
    parts_code = ", ".join(f"Part({sl!r}, {p['name']!r}, solid={k})" for k, (sl, p) in enumerate(zip(slugs, parts)))
    text = "\n".join([
        f'"""{title}: {len(parts)} parts reconstructed from meshes by Form Studio (Layer 2, sketches and extrusions, '
        'beta), with the dimensions where they meet tied together.\n\n'
        + "\n".join(f"- {b['evidence']}" for b in bindings) + '\n"""',
        *sorted(set(heads), key=heads.index),
        "",
        "",
        "class Design(Recipe):",
        f"    title = {title!r}",
        "    summary = 'Parts rebuilt from meshes; interface dimensions are shared Params plus a clearance.'",
        f"    solids = {len(parts)}",
        "    params = [",
        *params,
        *clear,
        "    ]",
        "    features = [",
        *feats,
        "        Feature('fits', 'Fits between the parts', 'interface', 'Clearances where the parts meet.'),",
        "    ]",
        "",
        "    def build(self, v):",
        "        stages, solids = [], []",
        *[f"        st = self._{sl}(v)\n        stages += st\n        solids.append(st[-1].shape)" for sl in slugs],
        "        stages.append(Stage('fits', Compound(children=solids)))",
        "        return stages",
        "",
        "    def assembly(self, v):",
        f"        return Assembly(parts=[{parts_code}])",
        "",
        *bodies,
    ]) + "\n"
    return text


def describe(bindings) -> list:
    """Plain lines for a report."""
    out = []
    for b in bindings:
        if b["kind"] == "fit":
            out.append(f"{b['a']['part']} {b['a']['label']} and {b['b']['part']} {b['b']['label']}: one diameter, "
                       f"{b['clearance_mm']:+g} mm fit")
        else:
            out.append(f"{b['a']['part']} and {b['b']['part']} along {b['axis']} at {b['at_mm']:g} mm: "
                       + ("touching" if b["kind"] == "contact" else f"{b['clearance_mm']:g} mm apart"))
    return out
