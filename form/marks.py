"""Text and marks on parts: raised or sunk lettering, and a revision stamp that ties a print to its revision.

    from form import marks
    s = marks.emboss_text(s, "DOCK", on=(0, -D / 2, 8), normal=(0, -1, 0), height=6, depth=0.6)
    s = marks.deboss_text(s, "v2", on=some_planar_face, height=5, depth=0.5)
    s = marks.revision_stamp(s)            # "r04 a3f1" sunk into the underside

The font ships with FORM (form/fonts/FormMark-Bold.ttf: Instrument Sans at weight 700, overlaps removed, SIL OFL
1.1) and is always passed to the kernel by path, so the same text builds the same solid on macOS, Windows and Linux.
System fonts are never used.

`height` is the cap height in millimetres (the height of a capital H), not a font size.

Printability is measured, not promised: `analyse()` reports the cap height, the text width and an estimate of the
thinnest stroke (2 x area / outline length of each glyph, the mean stroke width of the narrowest glyph), and
`checks()` turns them into check rows: strokes under one nozzle width cannot be drawn by the slicer; under two they
are a single line.

The revision stamp reads "r04 a3f1": the revision number, then the first four hex digits of a hash of the design
id and that revision's parameter values (`short_hash`). `form history <project>` lists the stamp of every revision.
The kernel worker gets the revision and the project's label text for each call (`context()`); outside a FORM
project (a test, a script) pass the text yourself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FONT = Path(__file__).resolve().parent / "fonts" / "FormMark-Bold.ttf"
FONT_NAME = "FORM Mark Bold (Instrument Sans 700, SIL OFL 1.1)"
OVERLAP = 0.05           # mm the text solid reaches past the surface so the boolean never leaves a skin
MIN_CAP_MM = 4.0         # below this, FDM lettering is hard to read (assumption; shown as such)
MAX_CHARS = 32

_ctx: dict = {}          # set by the kernel worker for each call: {"rev", "text", "hash", "nozzle"}
_ratio: dict = {}        # font path -> cap height per unit font size
_glyphs: dict = {}       # (font, char) -> (area, outline length, advance) at font size 10


# ---- context: what the worker knows about the project for this call ---------------------------------------------

def set_context(ctx: dict | None) -> None:
    _ctx.clear()
    _ctx.update(ctx or {})


def context() -> dict:
    """{"rev": 4, "text": "Hallway dock", "hash": "a3f1", "nozzle": 0.4} inside a FORM build; {} elsewhere."""
    return dict(_ctx)


def short_hash(recipe_id: str, values: dict) -> str:
    """Four hex digits identifying a design at a set of values (what the stamp carries next to the revision)."""
    blob = json.dumps([recipe_id, {k: round(float(v), 6) for k, v in sorted(values.items())}], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:4]


def stamp_text(rev: int | None = None, hash4: str | None = None) -> str:
    """"r04 a3f1". Without arguments it reads the worker context; outside a project it is "r00 0000"."""
    rev = _ctx.get("rev", 0) if rev is None else rev
    hash4 = _ctx.get("hash", "0000") if hash4 is None else hash4
    return f"r{int(rev):02d} {hash4}"


def clean(text: str) -> str:
    """Printable Latin text the bundled font has glyphs for; anything else is dropped (and that is reported)."""
    out = "".join(ch for ch in str(text) if ch == " " or (ch.isprintable() and ord(ch) < 0x250))
    return " ".join(out.split())[:MAX_CHARS]


# ---- geometry -----------------------------------------------------------------------------------------------

def _err(msg, hint="", feature="mark", params=None):
    from .recipes.base import RecipeError
    return RecipeError(msg, feature, hint, params or [])


def _font(font) -> str:
    f = Path(font) if font else FONT
    if not f.is_file():
        raise _err(f"Font file not found: {f}", "Pass font=<path to a .ttf>, or leave it out to use FORM's bundled font.")
    return str(f)


def cap_ratio(font=None) -> float:
    """Cap height of the font per unit of font size, measured on a capital H in the kernel."""
    f = _font(font)
    if f not in _ratio:
        from build123d import Text
        _ratio[f] = Text("H", 10, font_path=f).bounding_box().size.Y / 10
    return _ratio[f]


def sketch(text: str, height: float, font=None):
    """The text as a flat build123d sketch centred on the origin, `height` mm tall at the capitals."""
    from build123d import Align, Text
    t = clean(text)
    if not t:
        raise _err("The text is empty", "Give the label some text (letters, digits, spaces).")
    if height <= 0:
        raise _err("Text height must be above 0 mm")
    f = _font(font)
    return Text(t, height / cap_ratio(f), font_path=f, align=(Align.CENTER, Align.CENTER))


def _plane(shape, on, normal, up):
    """Where the text goes: a planar face, a Plane, a Location, or a point with a normal. X of the plane is the
    reading direction; seen from outside (against the normal) the text reads left to right, capitals up."""
    from build123d import Face, Location, Plane, Vector
    if isinstance(on, Plane):
        return on
    if isinstance(on, Location):
        return Plane(on)
    if isinstance(on, Face):
        if on.geom_type.name != "PLANE":
            raise _err("Text can only be placed on a flat face", "Pick a planar face, or give a point and a normal.")
        origin, n = on.center(), on.normal_at(on.center())
    else:
        if normal is None:
            raise _err("A point needs a normal", "Pass normal=(x, y, z): the direction the text faces.")
        origin, n = Vector(*on), Vector(*normal).normalized()
    if up is not None:
        y = Vector(*up)
        x = y.cross(n)
    elif abs(n.Z) > 0.999:                    # floor or ceiling: read along +X
        x = Vector(1, 0, 0)
    else:                                     # a wall: capitals point up
        x = Vector(0, 0, 1).cross(n)
    if x.length < 1e-9:
        raise _err("The text's up direction is along its normal", "Give a different up=(x, y, z).")
    return Plane(origin=origin, x_dir=x.normalized(), z_dir=n)


def text_solid(text: str, plane, height: float, depth: float, font=None, sunk: bool = False):
    """The lettering as a solid on `plane`: raised `depth` above it, or (sunk) reaching `depth` below it."""
    from build123d import extrude
    if depth <= 0:
        raise _err("Text depth must be above 0 mm")
    sk = sketch(text, height, font)
    start = plane.offset(-depth if sunk else -OVERLAP)
    return extrude(start * sk, amount=depth + OVERLAP)


def _apply(shape, text, on, normal, up, height, depth, font, sunk):
    plane = _plane(shape, on, normal, up)
    tool = text_solid(text, plane, height, depth, font, sunk)
    before = len(shape.solids())
    try:
        out = shape - tool if sunk else shape + tool
    except Exception as e:
        raise _err(f"The text could not be {'cut into' if sunk else 'added to'} the part ({type(e).__name__})",
                   "Move the text, make it smaller, or reduce its depth.") from e
    if not out.is_valid or len(out.solids()) != before or (not sunk and out.volume <= shape.volume):
        raise _err("The text does not sit on the part" if not sunk else "The text cut splits the part",
                   "Place raised text on a face of the part; keep sunk text shallower than the wall behind it.")
    return out


def emboss_text(shape, text: str, on, height: float = 6.0, depth: float = 0.6, font=None, normal=None, up=None):
    """Raise `text` out of a flat face. on: a planar Face of the shape, a Plane, a Location, or a point (x, y, z)
    together with normal=(x, y, z). height: cap height, mm. depth: how far the letters stand out, mm."""
    return _apply(shape, text, on, normal, up, height, depth, font, sunk=False)


def deboss_text(shape, text: str, on, height: float = 6.0, depth: float = 0.6, font=None, normal=None, up=None):
    """Sink `text` into a flat face. Same arguments as emboss_text; depth is how deep the letters go, mm."""
    return _apply(shape, text, on, normal, up, height, depth, font, sunk=True)


def revision_stamp(shape, text: str | None = None, at: tuple | None = None, height: float = 6.0, depth: float = 0.4,
                   font=None):
    """Sink the revision stamp ("r04 a3f1") into the underside so a printed part can be traced to its revision.

    The stamp goes on the plane z = lowest point of the shape, centred under the bounding box or at at=(x, y).
    Seen from below it reads left to right. 0.4 mm is two 0.2 mm layers; on the plate face it prints cleanly.
    text defaults to stamp_text() (revision and hash from the project the worker is building for).
    """
    from build123d import Plane
    bb = shape.bounding_box()
    x, y = at if at is not None else ((bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2)
    plane = Plane(origin=(x, y, bb.min.Z), x_dir=(1, 0, 0), z_dir=(0, 0, -1))
    return _apply(shape, text or stamp_text(), plane, None, None, height, depth, font, sunk=True)


# ---- printability ---------------------------------------------------------------------------------------------

def _glyph(ch: str, f: str):
    k = (f, ch)
    if k not in _glyphs:
        from build123d import Text
        try:
            faces = Text(ch, 10, font_path=f).faces()
        except Exception:
            faces = []
        area = sum(x.area for x in faces)
        outline = sum(w.length for x in faces for w in x.wires())
        _glyphs[k] = (area, outline)
    return _glyphs[k]


def analyse(text: str, height: float, depth: float = 0.6, font=None) -> dict:
    """Measured in the kernel: {"text", "cap_height_mm", "width_mm", "stroke_mm", "thinnest_glyph", "dropped"}.

    stroke_mm estimates the thinnest stroke: for each glyph, 2 x area / outline length (exact for a long bar,
    a mean for real letters), scaled to this height; the smallest glyph value is reported.
    """
    f = _font(font)
    t = clean(text)
    scale = (height / cap_ratio(f)) / 10
    worst, worst_ch = None, ""
    for ch in sorted(set(t.replace(" ", ""))):
        area, outline = _glyph(ch, f)
        if outline <= 0:
            continue
        s = 2 * area / outline * scale
        if worst is None or s < worst:
            worst, worst_ch = s, ch
    width = sketch(t, height, f).bounding_box().size.X if t else 0.0
    return {"text": t, "cap_height_mm": float(height), "width_mm": float(width), "depth_mm": float(depth),
            "stroke_mm": float(worst) if worst is not None else 0.0, "thinnest_glyph": worst_ch,
            "dropped": len(str(text).strip()) - len(t) if len(str(text).strip()) > len(t) else 0, "font": FONT_NAME}


def checks(info: dict, nozzle: float | None = None, raised: bool = True, id: str = "mark", label: str = "Label",
           feature: str = "mark") -> list[dict]:
    """Check rows for a piece of text (pass analyse()'s result). Strokes against the nozzle, cap height against
    a legibility floor. nozzle defaults to the worker context, then 0.4 mm."""
    assumed = nozzle is None and "nozzle" not in _ctx
    nz = float(nozzle if nozzle is not None else _ctx.get("nozzle", 0.4))
    s, h = info["stroke_mm"], info["cap_height_mm"]
    st = "FAIL" if s < nz else ("WARN" if s < 2 * nz else "PASS")
    kind = "raised" if raised else "sunk"
    out = [{"id": f"{id}_stroke", "label": f"{label}: stroke width", "status": st, "value": f"{s:.2f} mm",
            "detail": f"“{info['text']}”, {kind}, {h:g} mm capitals: the thinnest strokes (glyph “{info['thinnest_glyph']}”) "
                      f"are about {s:.2f} mm, estimated as 2 × area ÷ outline length. A {nz:g} mm nozzle"
                      + (" (assumed)" if assumed else "") + f" cannot draw strokes under {nz:g} mm; under {2 * nz:g} mm "
                      "they are a single line. Raise the text height to thicken them.",
            "evidence": "computed", "feature": feature}]
    hs = "FAIL" if h < MIN_CAP_MM / 2 else ("WARN" if h < MIN_CAP_MM else "PASS")
    out.append({"id": f"{id}_height", "label": f"{label}: text height", "status": hs, "value": f"{h:.1f} mm",
                "detail": f"Capital height. Under {MIN_CAP_MM:g} mm, printed lettering is hard to read on an FDM part "
                          f"(a rule of thumb); under {MIN_CAP_MM / 2:g} mm it does not resolve.",
                "evidence": "heuristic", "feature": feature})
    return out
