"""What changed between two revisions, computed on the solids.

Two booleans on the kernel's B-rep: material added (new minus old) and material removed (old minus new). Their volumes,
bounding boxes and the number of separate regions are exact OCCT results (evidence class ``computed``); the picture
draws the new revision in grey with the added material in green and the removed material in red, from the same
tessellations. Nothing is estimated: when the kernel cannot build either revision or a boolean fails, there is no diff.

    from form import geomdiff
    d = geomdiff.compute(st, p, 3, 5)       # {"added": {"volume_mm3", "regions", "bbox"}, "removed": {...}, ...}
    png = geomdiff.png_path(st, p, d)

The kernel side (``op_geomdiff``) runs in the worker only; the rest is plain Python.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

VERSION = 3                    # part of the cache key: change the computation or the picture, change this
ADDED = (46, 160, 90)
REMOVED = (214, 64, 52)
SAME = (190, 186, 178)
EPS_MM3 = 1e-3                 # below this a boolean remainder is numerical dust, not a change


# ── kernel side (worker process) ───────────────────────────────────────────

def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def _region(shape, tol):
    from .kernel import _tessellate
    solids = [s for s in (shape.solids() if shape is not None else []) if s.volume > EPS_MM3]
    vol = float(sum(s.volume for s in solids))
    out = {"volume_mm3": round(vol, 3), "regions": len(solids), "bbox": None, "mesh": None}
    if not solids:
        return out
    from build123d import Compound
    c = Compound(solids)
    bb = c.bounding_box()
    out["bbox"] = [[round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)], [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)]]
    P, T = _tessellate(c, tol)
    out["mesh"] = {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32))}
    return out


def own_copy(shape):
    """A deep copy of a build123d shape (BRepBuilderAPI_Copy: its own geometry, tolerances and triangulation)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    c = BRepBuilderAPI_Copy(shape.wrapped, True, False)       # copy geometry, not the mesh
    try:
        return type(shape)(c.Shape())
    except Exception:                                          # a class that does not take a raw shape
        from build123d import Shape
        return Shape.cast(c.Shape())


def op_geomdiff(key, recipe_id, values, key_b, recipe_b, values_b, tol=0.08):
    """Added (b - a) and removed (a - b) material between two built designs, with meshes for drawing."""
    from .kernel import _get, _tessellate
    # copies: the booleans (OCCT's default mode grows the tolerances of their arguments in place) and the
    # tessellation below would otherwise change the shapes the kernel keeps for every later view of these revisions
    A = own_copy(_get(key, recipe_id, values, 0.05)["shape"])
    B = own_copy(_get(key_b, recipe_b, values_b, 0.05)["shape"])
    added, removed = B - A, A - B
    P, T = _tessellate(B, tol)
    return {"volume_a_mm3": round(float(A.volume), 3), "volume_b_mm3": round(float(B.volume), 3),
            "added": _region(added, tol), "removed": _region(removed, tol),
            "base": {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32))}}


KERNEL_OPS = {"geomdiff": op_geomdiff}


# ── studio side (any process) ──────────────────────────────────────────────

def _dir(st, p, a: int, b: int) -> Path:
    from .studio import H
    ka, kb = st.keys(p, a)["geometry"], st.keys(p, b)["geometry"]
    return st.dir(p["id"]) / "artifacts" / "side" / ("geomdiff-" + H("geomdiff", VERSION, ka, kb)[:16])


def compute(st, p: dict, a: int, b: int | None = None) -> dict:
    """The geometric diff of revision a against b (default: the head). Cached by both geometry keys."""
    from .studio import StudioError
    b = p["head"] if b is None else int(b)
    a = int(a)
    ra, rb = st.rev(p, a), st.rev(p, b)          # raises for an unknown revision
    if a == b:
        raise StudioError("Pick two different revisions.", "Compare an earlier revision with the head.")
    out = _dir(st, p, a, b)
    meta = out / "diff.json"
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    raw = st._k("geomdiff", timeout=300, key=st.keys(p, a)["geometry"], recipe_id=st.rid(p, a), values=ra["values"],
                key_b=st.keys(p, b)["geometry"], recipe_b=st.rid(p, b), values_b=rb["values"], p=p, rev=a)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mesh.json").write_text(json.dumps({k: raw[k]["mesh"] for k in ("added", "removed")} | {"base": raw["base"]}), encoding="utf-8")
    res = {"a": a, "b": b, "evidence": "computed",
           "volume_a_mm3": raw["volume_a_mm3"], "volume_b_mm3": raw["volume_b_mm3"],
           "net_mm3": round(raw["volume_b_mm3"] - raw["volume_a_mm3"], 3),
           "added": {k: raw["added"][k] for k in ("volume_mm3", "regions", "bbox")},
           "removed": {k: raw["removed"][k] for k in ("volume_mm3", "regions", "bbox")},
           "same": raw["added"]["regions"] == 0 and raw["removed"]["regions"] == 0,
           "key": out.name, "image": "diff.png"}
    res["text"] = summary(res)
    _render(out, res, f"{p['name']} · r{a:02d} -> r{b:02d}")
    meta.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def summary(d: dict) -> str:
    if d["same"]:
        return f"r{d['a']:02d} and r{d['b']:02d} have the same solid."
    def part(x, word):
        if not x["regions"]:
            return f"nothing {word}"
        return f"{x['volume_mm3']:.1f} mm³ {word} in {x['regions']} region{'s' if x['regions'] != 1 else ''}"
    return (f"r{d['a']:02d} → r{d['b']:02d}: {part(d['added'], 'added')}, {part(d['removed'], 'removed')}; "
            f"net {d['net_mm3']:+.1f} mm³ (computed on the solids).")


def _render(out: Path, d: dict, title: str) -> None:
    from . import render
    m = json.loads((out / "mesh.json").read_text(encoding="utf-8"))
    mesh = []
    for kind, rgb in (("added", ADDED), ("removed", REMOVED), ("base", SAME)):   # changes first: they win a depth tie
        x = m.get(kind)
        if not x:
            continue
        n = len(base64.b64decode(x["positions"])) // 12
        col = np.tile(np.array([*rgb, 255], dtype=np.uint8), (n, 1))
        mesh.append({"feature": kind, "positions": x["positions"], "indices": x["indices"], "colors": _b64(col)})
    from PIL import Image, ImageDraw
    from .instructions import _font, text
    boxes = [d[k]["bbox"] for k in ("added", "removed") if d[k]["bbox"]]
    zoom = None
    if boxes:                                  # the second view is framed on what changed, with some of the part around it
        lo, hi = np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)
        pad = max(4.0, 0.35 * float(np.max(hi - lo)))
        zoom = (lo - pad, hi + pad)
    imgs = [render.render_png({"mesh": mesh}, [], view="iso", size=(720, 520), overlay=False, as_image=True),
            render.render_png({"mesh": mesh}, [], view="iso", size=(720, 520), overlay=False, as_image=True, frame_box=zoom)]
    W = sum(i.width for i in imgs)
    sheet = Image.new("RGB", (W, max(i.height for i in imgs) + 70), render.PAPER)
    x = 0
    for i in imgs:
        sheet.paste(i, (x, 40))
        x += i.width
    dr = ImageDraw.Draw(sheet)
    text(dr, (18, 14), title, _font(20), render.INK)
    f, y = _font(17), sheet.height - 34
    x = 18
    for label, rgb in ((f"added {d['added']['volume_mm3']:.1f} mm³", ADDED), (f"removed {d['removed']['volume_mm3']:.1f} mm³", REMOVED)):
        dr.rectangle((x, y + 3, x + 12, y + 15), fill=rgb)
        text(dr, (x + 18, y), label, f, render.INK)
        x += 40 + int(dr.textlength(label, font=f))
    text(dr, (x, y), f"net {d['net_mm3']:+.1f} mm³ · computed on the solids", f, render.MUTED)
    sheet.save(out / "diff.png")


def png_path(st, p: dict, d: dict) -> Path:
    return st.dir(p["id"]) / "artifacts" / "side" / d["key"] / d["image"]
