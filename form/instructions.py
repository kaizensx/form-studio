"""Assembly instructions as a PDF, from the design's own assembly declaration.

Every step is one part going onto what is already assembled: the parts already in place in grey, the new part in
signal orange at its exploded offset (``Part.explode``, relative to its parent) with arrows to where it seats. The order
is the declaration's tree: a part comes after the part it is attached to or moves on, in declaration order otherwise.
The step text is the part's own ``note`` when the design gives one; otherwise it says only what the declaration says
(which part it goes on, by which joint or mate). Part volumes on the parts page are the kernel's (computed). Nothing is
invented: a design without an assembly declaration has no instructions.

    from form import instructions
    out = instructions.build(st, p)     # {"pdf": path, "pages": [png paths], "steps": [...]}

The kernel side (``op_instructions``) runs in the worker only; the rest is plain Python with Pillow.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

VERSION = 1
PAGE = (1240, 1754)                 # A4 at 150 dpi
NEW = (226, 77, 38)
DONE = (196, 192, 182)


# ── kernel side (worker process) ───────────────────────────────────────────

def op_instructions(key, recipe_id, values, tol=0.08):
    from . import assembly as asm
    from .kernel import _get, _tessellate
    from .recipes import RecipeError
    model = _get(key, recipe_id, values, 0.05)
    a = asm.get(model)
    if a is None or a.get("error") or a["spec"].derived:
        raise RecipeError("This design does not declare how its parts go together, so there are no assembly instructions.",
                          "", "Ask the agent to add an assembly() with Parts, joints and an explode offset for each part.")
    spec, parts = a["spec"], []
    for p, placed, printed in zip(spec.parts, a["placed"], a["printed"]):
        parent, j = spec.link(p.id)
        P, T = _tessellate(placed, tol)
        parts.append({"id": p.id, "label": p.label, "note": p.note, "parent": parent, "explode": list(p.explode),
                      "joint": ({"label": j.label or j.id, "kind": j.kind, "range": list(j.range)} if j is not None else None),
                      "volume_mm3": round(float(printed.volume), 2),
                      "positions": base64.b64encode(P.astype(np.float32).tobytes()).decode("ascii"),
                      "indices": base64.b64encode(T.astype(np.uint32).tobytes()).decode("ascii")})
    mates = [{"a": m.a, "b": m.b, "kind": m.kind, "label": m.label} for m in spec.mates]
    return {"parts": parts, "mates": mates}


KERNEL_OPS = {"instructions": op_instructions}


# ── ordering and text (any process) ────────────────────────────────────────

def order(parts: list) -> list:
    """Parts in assembly order: each after its parent, otherwise as declared."""
    ids = {p["id"] for p in parts}
    out, done = [], set()
    while len(out) < len(parts):
        moved = False
        for p in parts:
            if p["id"] not in done and (not p["parent"] or p["parent"] not in ids or p["parent"] in done):
                out.append(p)
                done.add(p["id"])
                moved = True
        if not moved:                      # a loop is refused when the design is saved; never spin here
            out += [p for p in parts if p["id"] not in done]
            break
    return out


def step_text(p: dict, by: dict, mates: list) -> str:
    if p.get("note"):
        return p["note"].strip()
    if not p["parent"]:
        return f"Place the {p['label'].lower()}."
    on = by.get(p["parent"], {}).get("label", p["parent"]).lower()
    j = p.get("joint")
    if j:
        unit = "°" if j["kind"] == "hinge" else " mm"
        return f"Fit the {p['label'].lower()} on the {on}; it moves on “{j['label']}” ({j['kind']}, {j['range'][0]:g}–{j['range'][1]:g}{unit})."
    m = next((m for m in mates if {m["a"], m["b"]} == {p["id"], p["parent"]}), None)
    if m:
        return f"Fit the {p['label'].lower()} to the {on} ({m['label'] or m['kind']} fit)."
    return f"Fix the {p['label'].lower()} to the {on}."


# ── drawing ────────────────────────────────────────────────────────────────

def _mesh(p, rgb, shift=(0.0, 0.0, 0.0)):
    P = np.frombuffer(base64.b64decode(p["positions"]), np.float32).reshape(-1, 3) + np.asarray(shift, np.float32)
    col = np.tile(np.array([*rgb, 255], np.uint8), (len(P), 1))
    return {"feature": p["id"], "positions": base64.b64encode(P.astype(np.float32).tobytes()).decode("ascii"),
            "indices": p["indices"], "colors": base64.b64encode(col.tobytes()).decode("ascii")}


def _centre(p):
    P = np.frombuffer(base64.b64decode(p["positions"]), np.float32).reshape(-1, 3)
    return (P.min(0) + P.max(0)) / 2 if len(P) else np.zeros(3)


def _font(size):
    from PIL import ImageFont
    f = Path(__file__).resolve().parent / "fonts" / "FormMark-Bold.ttf"
    try:
        return ImageFont.truetype(str(f), size)
    except OSError:
        return ImageFont.load_default(size=size)


def text(d, xy, s, font, fill):
    """Draw s; the bundled font has no superscript three, so "³" is drawn as a small raised 3."""
    from PIL import ImageFont
    x, y = xy
    small = font.font_variant(size=max(8, int(font.size * 0.62))) if isinstance(font, ImageFont.FreeTypeFont) else font
    for k, chunk in enumerate(s.replace("→", "->").split("³")):
        if k:
            d.text((x, y - int(font.size * 0.08)), "3", fill=fill, font=small)
            x += d.textlength("3", font=small)
        d.text((x, y), chunk, fill=fill, font=font)
        x += d.textlength(chunk, font=font)


def _wrap(d, text, font, width):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + ([cur] if cur else [])


def _page(title, sub, img, body_lines, footer):
    from PIL import Image, ImageDraw
    from . import render
    pg = Image.new("RGB", PAGE, render.PAPER)
    d = ImageDraw.Draw(pg)
    d.text((90, 90), title, fill=render.INK, font=_font(54))
    if sub:
        d.text((90, 162), sub, fill=render.MUTED, font=_font(26))
    if img is not None:
        img = img.copy()
        img.thumbnail((PAGE[0] - 180, 1060))
        pg.paste(img, ((PAGE[0] - img.width) // 2, 230))
        y = 230 + img.height + 50
    else:
        y = 240
    f = _font(30)
    for line in body_lines:
        for w in _wrap(d, line, f, PAGE[0] - 180):
            text(d, (90, y), w, f, render.INK)
            y += 44
        y += 10
    d.text((90, PAGE[1] - 80), footer, fill=render.MUTED, font=_font(20))
    return pg


def _frame(parts):
    pts = np.concatenate([np.frombuffer(base64.b64decode(p["positions"]), np.float32).reshape(-1, 3) for p in parts])
    return pts.min(0), pts.max(0)


def build(st, p: dict, n: int | None = None) -> dict:
    """Write the instructions for revision n (default the head). Cached by the geometry key."""
    from . import render
    from .studio import H
    r = st.rev(p, n)
    gk = st.keys(p, r["n"])["geometry"]
    out = st.dir(p["id"]) / "artifacts" / "side" / ("instructions-" + H("instructions", VERSION, gk, p["name"])[:16])
    meta = out / "instructions.json"
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    raw = st._k("instructions", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"])
    parts = order(raw["parts"])
    by = {q["id"]: q for q in parts}
    # the frame holds every part, assembled and exploded, so the camera never jumps between steps
    flo, fhi = _frame(parts)
    ex = [np.asarray(q["explode"]) for q in parts]
    flo, fhi = np.minimum(flo, flo + np.min(ex, axis=0)), np.maximum(fhi, fhi + np.max(ex, axis=0))
    foot = f"{p['name']} · r{r['n']:02d} · Form Studio"
    pages, steps = [], []
    full = render.render_png({"mesh": [_mesh(q, render.PALETTE[i % len(render.PALETTE)]) for i, q in enumerate(parts)]}, [], "iso", size=(1060, 760), overlay=False,
                             frame_box=(flo, fhi), as_image=True)
    lines = [f"{i + 1}. {q['label']} · {q['volume_mm3'] / 1000:.2f} cm³" for i, q in enumerate(parts)]
    pages.append(_page(p["name"], f"Assembly instructions · {len(parts)} parts · r{r['n']:02d}", full,
                       ["Parts (volumes computed on the solids):"] + lines, foot))
    placed = []
    for i, q in enumerate(parts):
        text = step_text(q, by, raw["mates"])
        shift = np.asarray(q["explode"], float)
        mesh = [_mesh(x, DONE) for x in placed] + [_mesh(q, NEW, shift)]
        lines = []
        if np.linalg.norm(shift) > 1e-6:
            c = _centre(q)
            lines = [(np.array([[*(c + shift), *c]]), NEW)]
        img = render.render_png({"mesh": mesh}, [], "iso", size=(1060, 760), overlay=False, frame_box=(flo, fhi),
                                lines=lines, as_image=True)
        steps.append({"n": i + 1, "part": q["id"], "label": q["label"], "text": text, "from_design": bool(q.get("note"))})
        pages.append(_page(f"Step {i + 1}", q["label"], img, [text], foot))
        placed.append(q)
    out.mkdir(parents=True, exist_ok=True)
    pngs = []
    for k, pg in enumerate(pages):
        f = out / f"page-{k + 1}.png"
        pg.save(f)
        pngs.append(f.name)
    name = f"{p['id']}_r{r['n']:02d}_assembly.pdf"
    pages[0].save(out / name, "PDF", resolution=150.0, save_all=True, append_images=pages[1:],
                  title=f"{p['name']} assembly instructions", producer="Form Studio")
    res = {"rev": r["n"], "key": out.name, "pdf": name, "pages": pngs, "steps": steps, "parts": len(parts),
           "pdf_path": str(out / name)}
    meta.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res
