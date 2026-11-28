"""Makers' generators (wave S): one-click, print-ready parts that stay editable designs.

A generator turns a few answers (a name, a picture, a shaft size) into a real design: a parametric source with
sliders, the full code, the checks and the slice, never a baked STL. There are three kinds:

  source   a design file in form/makers/templates/<template>.py. The template is itself a working design (it builds
           as it is, so it is tested as it is); the generator writes what it was given into its MAKE dict (the text,
           the picture as a height grid) and stores the file as the design's source.
  recipe   a built-in recipe with good defaults for one purpose (a Gridfinity tray, a tablet stand).
  calc     a calculator of form/calc that writes the geometry (the spur-gear pair, sized by ISO 21771).

    from form import makers
    makers.catalogue()                                   every generator, its presets and inputs
    makers.make(st, "name_tag", text="ANNA", preset="keychain", values={"cap_h": 9})

The same call is `form make <generator> ...` (form/makers/cli.py), an MCP tool per generator (make_name_tag, ...;
form/makers/tools.py) and a start option on Home (GET /api/makers, POST /api/makers/<id>).

Nothing here reaches the network. A picture is read from the path the person gave, reduced to a grid of grey levels
and written into the design; the picture itself is not copied anywhere.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
GRID = 140                 # samples along the longer side of a picture (about 0.7 mm apart on a 100 mm lithophane)
MAX_IMAGE_BYTES = 40_000_000


class MakeError(ValueError):
    def __init__(self, message: str, hint: str = "", params: list | None = None):
        super().__init__(message)
        self.hint = hint
        self.params = params or []


@dataclass(frozen=True)
class Generator:
    id: str
    title: str
    line: str                      # what Home says on the start option
    summary: str
    kind: str                      # source | recipe | calc
    target: str                    # template file, recipe id or calculator id
    presets: dict = field(default_factory=dict)   # name -> {"label", "values", "text"?}
    default: str = ""              # the preset used when none is named
    inputs: tuple = ()             # extra inputs beyond the parameters: "text", "image"
    tags: tuple = ()

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "line": self.line, "summary": self.summary, "kind": self.kind,
                "presets": [{"id": k, "label": p["label"], "values": p.get("values", {})} for k, p in self.presets.items()],
                "default": self.default or next(iter(self.presets), ""), "inputs": list(self.inputs),
                "tool": f"make_{self.id}", "cli": f"form make {self.id}", "tags": list(self.tags)}


GENERATORS: dict[str, Generator] = {g.id: g for g in (
    Generator("name_tag", "Name tag or keychain", "A name tag or keychain",
              "Raised or engraved lettering in real font outlines on a rounded plate, with a keyring hole.",
              "source", "name_tag",
              {"keychain": {"label": "Keychain", "values": {"ring": 1, "cap_h": 8}},
               "name_tag": {"label": "Name tag", "values": {"ring": 0, "cap_h": 12, "margin": 6}},
               "engraved": {"label": "Engraved tag", "values": {"sunk": 1, "ring": 1, "cap_h": 12, "plate_t": 3.6}}},
              "keychain", ("text",), ("keychain", "name", "tag", "label", "text", "sign")),
    Generator("lithophane", "Lithophane or relief", "A lithophane or relief from a picture",
              "A picture as a height field: thick where it is dark (a lithophane to hold to the light) or high where it "
              "is bright (a relief).", "source", "relief",
              {"lithophane": {"label": "Lithophane", "values": {"invert": 1, "min_t": 0.8, "max_t": 3.0}},
               "relief": {"label": "Relief", "values": {"invert": 0, "min_t": 1.6, "max_t": 4.0, "frame_t": 4.6}}},
              "lithophane", ("image",), ("lithophane", "relief", "picture", "photo", "image", "heightmap")),
    Generator("gridfinity", "Gridfinity bin or tray", "A Gridfinity bin or tray",
              "Gridfinity-compatible bins, shallow trays and baseplates from the built-in recipes.", "recipe",
              "gridfinity_bin",
              {"bin": {"label": "Bin", "values": {}},
               "tray": {"label": "Tray", "values": {"grid_x": 3, "grid_y": 2, "height_u": 3, "compart_x": 3,
                                                    "compart_y": 2, "label": 0, "scoop": 1, "scoop_r": 8, "floor": 1.6}},
               "parts_tray": {"label": "Parts tray", "values": {"grid_x": 2, "grid_y": 2, "height_u": 3, "compart_x": 4,
                                                                "compart_y": 3, "label": 0, "scoop": 1, "scoop_r": 6, "floor": 1.6}},
               "baseplate": {"label": "Baseplate", "recipe": "gridfinity_baseplate", "values": {}}},
              "bin", (), ("gridfinity", "bin", "tray", "storage", "organizer", "baseplate")),
    Generator("knob", "Knob", "A knob for a D-shaft",
              "A knurled or smooth knob with a dished cap, a pointer and a D-shaft bore with an optional set screw.",
              "source", "knob",
              {"knurled": {"label": "Knurled", "values": {"knurl": 1}},
               "smooth": {"label": "Smooth", "values": {"knurl": 0}},
               "large": {"label": "Large knurled", "values": {"knurl": 1, "knob_d": 44, "height": 24}}},
              "knurled", (), ("knob", "dial", "d-shaft", "potentiometer", "knurl", "grip")),
    Generator("cable_clip", "Cable clip", "A cable clip",
              "Snap-in clips for one to four cables, screwed to a wall or desk through a countersunk tab.",
              "source", "cable_clip",
              {"single": {"label": "One cable", "values": {"count": 1}},
               "double": {"label": "Two cables", "values": {"count": 2}},
               "thick": {"label": "Thick cable", "values": {"count": 1, "cable_d": 10, "wall": 2.4}}},
              "single", (), ("cable", "clip", "cord", "wire", "organizer")),
    Generator("hook", "Wall hook", "A wall hook",
              "A J hook on a back plate with two countersunk screw holes, printed on its side so the layers run "
              "along the arm.", "source", "hook",
              {"coat": {"label": "Coat hook", "values": {}},
               "small": {"label": "Key hook", "values": {"plate_h": 50, "opening": 10, "width": 12, "t": 4}},
               "heavy": {"label": "Heavy hook", "values": {"t": 7, "width": 22, "opening": 24}}},
              "coat", (), ("hook", "wall", "coat", "hanger", "keys")),
    Generator("stand", "Phone or tablet stand", "A phone or tablet stand",
              "A leaning stand with a front lip, a backrest and a charging cut-out, sized for a phone or a tablet.",
              "recipe", "device_stand",
              {"phone": {"label": "Phone", "values": {}},
               "tablet": {"label": "Tablet", "values": {"device_thickness": 9, "device_height": 240, "device_width": 170,
                                                         "device_mass": 520, "width": 150, "depth": 150, "back_h": 110,
                                                         "lip_h": 11, "base_t": 6, "back_t": 8, "strut_t": 7}}},
              "phone", (), ("phone", "tablet", "stand", "dock", "holder", "desk")),
    Generator("drawer_divider", "Drawer divider", "A drawer divider",
              "An insert that fills a drawer and divides it into rows and columns of rounded compartments.",
              "source", "drawer_divider",
              {"cutlery": {"label": "Cutlery", "values": {}},
               "desk": {"label": "Desk drawer", "values": {"cols": 4, "rows": 2, "height": 40}},
               "small": {"label": "Small parts", "values": {"cols": 4, "rows": 4, "height": 30, "width": 120, "depth": 120}}},
              "cutlery", (), ("drawer", "divider", "insert", "organizer", "tray", "compartments")),
    Generator("hinge_box", "Hinged box", "A box with a print-in-place hinge",
              "A box and a lid printed open in one piece, joined by a pin hinge whose clearance comes from the fit "
              "model, closed by a snap latch.", "source", "hinge_box",
              {"box": {"label": "Hinged box", "values": {}},
               "slim": {"label": "Slim hinged case", "values": {"inner_w": 100, "inner_d": 40, "half_h": 11}},
               "deep": {"label": "Deep hinged box", "values": {"inner_w": 70, "inner_d": 60, "half_h": 24}}},
              "box", (), ("box", "hinge", "hinged", "print-in-place", "case", "lid")),
    Generator("threaded_jar", "Threaded jar", "A jar with a screw lid",
              "A jar and its lid with a printed thread: a 45-degree printing profile at any pitch, or ISO metric "
              "(ISO 68-1 profile, ISO 261 coarse pitch).", "source", "threaded_jar",
              {"printing": {"label": "Printing thread", "values": {"iso": 0}},
               "iso": {"label": "ISO metric", "values": {"iso": 1}},
               "spice": {"label": "Spice jar", "values": {"iso": 0, "inner_d": 40, "height": 70, "pitch": 3}}},
              "printing", (), ("jar", "thread", "screw", "lid", "container", "iso metric")),
    Generator("spur_gears", "Spur gear pair", "A spur gear pair",
              "Two involute spur gears in mesh at the working centre distance, sized by the gear calculator "
              "(ISO 21771 geometry, Lewis bending).", "calc", "gear",
              {"1:2": {"label": "1:2", "values": {"module": 1.5, "z1": 15, "z2": 30, "face": 8, "bore1": 5, "bore2": 8, "backlash": 0.15}},
               "1:3": {"label": "1:3", "values": {"module": 1.25, "z1": 14, "z2": 42, "face": 7, "bore1": 5, "bore2": 8, "backlash": 0.15}},
               "1:1": {"label": "1:1", "values": {"module": 2, "z1": 20, "z2": 20, "face": 8, "bore1": 6, "bore2": 6, "backlash": 0.15}}},
              "1:2", (), ("gear", "gears", "spur", "involute", "gearbox", "transmission")),
)}


def catalogue() -> list[dict]:
    return [g.public() for g in GENERATORS.values()]


def get(gid: str) -> Generator:
    g = GENERATORS.get(str(gid).replace("-", "_"))
    if g is None:
        raise MakeError(f"No generator “{gid}”.", "Generators: " + ", ".join(GENERATORS) + ".")
    return g


def template_text(name: str) -> str:
    return (TEMPLATES / f"{name}.py").read_text(encoding="utf-8")


def _set_make(src: str, make: dict) -> str:
    """The template with its MAKE literal replaced by `make` (the rest of the file unchanged)."""
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", "") == "MAKE":
            lines = src.splitlines(keepends=True)
            head = "".join(lines[:n.lineno - 1])
            tail = "".join(lines[n.end_lineno:])
            return head + "MAKE = " + _literal(make) + "\n" + tail
    raise MakeError("The template has no MAKE dict.", "Every source template declares MAKE = {...} at module level.")


def _literal(d: dict) -> str:
    """A dict literal, one key per line, long strings wrapped so the file stays readable."""
    out = ["{"]
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 100:
            chunks = [v[i:i + 100] for i in range(0, len(v), 100)]
            out.append(f"    {k!r}: (" + "\n        ".join(repr(c) for c in chunks) + "),")
        else:
            out.append(f"    {k!r}: {v!r},")
    out.append("}")
    return "\n".join(out)


def read_make(src: str) -> dict | None:
    """The MAKE dict of a generated design's source, or None when the design was not made by a generator."""
    if not src or "MAKE = " not in src:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", "") == "MAKE":
            try:
                v = ast.literal_eval(n.value)
            except (ValueError, SyntaxError):
                return None
            return v if isinstance(v, dict) and v.get("generator") else None
    return None


# ---- pictures --------------------------------------------------------------------------------------------------

def encode_grid(gray, grid: int = GRID) -> dict:
    """A greyscale PIL image as the MAKE fields of a height grid: {"grid": [nx, ny], "pixels": base64(zlib(bytes))},
    rows from the top of the picture, 0 = black, 255 = white."""
    w, h = gray.size
    s = grid / max(w, h)
    nx, ny = max(8, round(w * s)), max(8, round(h * s))
    from PIL import Image
    from PIL import ImageFilter
    # smoothed by about one sample, so no ridge or groove of the picture is narrower than a nozzle can draw
    small = gray.resize((nx, ny), Image.Resampling.BOX).filter(ImageFilter.GaussianBlur(1.0))
    data = small.tobytes()
    return {"grid": [nx, ny], "pixels": base64.b64encode(zlib.compress(data, 9)).decode("ascii")}


def decode_grid(make: dict):
    """(nx, ny, bytes) of a MAKE height grid."""
    nx, ny = make["grid"]
    data = zlib.decompress(base64.b64decode(make["pixels"]))
    if len(data) != nx * ny:
        raise MakeError("The picture grid in this design is damaged.", "Make the design again from the picture.")
    return int(nx), int(ny), data


def read_picture(path) -> tuple:
    """(PIL greyscale image, {"picture", "sha256"}) from a file the person gave. EXIF rotation is applied."""
    p = Path(str(path)).expanduser()
    if not p.is_file():
        raise MakeError(f"No picture at {p}.", "Give the path of a PNG, JPEG, WebP, BMP or TIFF file.", ["image"])
    if p.stat().st_size > MAX_IMAGE_BYTES:
        raise MakeError("The picture is larger than 40 MB.", "Use a smaller copy; the relief samples it to a "
                        f"{GRID}-point grid anyway.", ["image"])
    raw = p.read_bytes()
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        import io
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))      # transparent areas read as white (thin)
            bg.alpha_composite(img.convert("RGBA"))
            img = bg
        gray = img.convert("L")
    except (UnidentifiedImageError, OSError) as e:
        raise MakeError(f"Not a picture Form Studio can read: {p.name} ({type(e).__name__}).",
                        "Give a PNG, JPEG, WebP, BMP or TIFF file.", ["image"]) from None
    return gray, {"picture": p.name, "sha256": hashlib.sha256(raw).hexdigest()}


# ---- making a design ---------------------------------------------------------------------------------------------

def _values(g: Generator, preset: str, values: dict | None) -> tuple[str, dict]:
    pname = preset or g.default or next(iter(g.presets), "")
    if pname and pname not in g.presets:
        raise MakeError(f"{g.title} has no preset “{preset}”.", "Presets: " + ", ".join(g.presets) + ".")
    vals = dict(g.presets.get(pname, {}).get("values", {}))
    for k, v in (values or {}).items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise MakeError(f"{k} = {v!r} is not a number.", "Parameters are numbers in mm, degrees or counts.", [k]) from None
        vals[k] = float(v)
    return pname, vals


def source_for(gid: str, text: str | None = None, image=None, preset: str = "", grid: int = GRID) -> tuple[str, dict]:
    """(design source, MAKE) for a source generator, without the kernel: what make() stores."""
    g = get(gid)
    if g.kind != "source":
        raise MakeError(f"{g.title} is made from a {g.kind}, not a source template.")
    src = template_text(g.target)
    make = dict(read_make(src) or {})
    make.update({"generator": g.id, "preset": preset or g.default})
    if "text" in g.inputs:
        from .. import marks
        t = marks.clean(text if text is not None else make.get("text", ""))
        if not t:
            raise MakeError("The text is empty.", "Give the letters to print (Latin letters, digits and spaces; up to "
                            f"{marks.MAX_CHARS} characters).", ["text"])
        make["text"] = t
    if "image" in g.inputs:
        if image is None:
            raise MakeError("A lithophane needs a picture.", "Give the path of a picture (PNG, JPEG, WebP, BMP, TIFF).",
                            ["image"])
        gray, info = read_picture(image)
        make.update(info)
        make.update(encode_grid(gray, grid))
    return _set_make(src, make), make


NAMES = {"name_tag": "{text} {label}", "lithophane": "{Label}", "gridfinity": "Gridfinity {label}", "knob": "{Label} knob",
         "cable_clip": "Cable clip, {label}", "hook": "{Label}", "stand": "{Label} stand",
         "drawer_divider": "Drawer divider, {label}", "hinge_box": "{Label}", "threaded_jar": "Jar ({Label})",
         "spur_gears": "Spur gears {label}"}


def design_name(g: Generator, preset: str, text: str = "") -> str:
    """The new design's name: "MAYA keychain", "Gridfinity tray", "Knurled knob"."""
    label = g.presets.get(preset, {}).get("label", g.title)
    return NAMES.get(g.id, "{Label}").format(text=text, label=label.lower(), Label=label).strip()


def _brief(g: Generator, preset: str, make: dict | None) -> str:
    what = g.presets.get(preset, {}).get("label", g.title)
    extra = ""
    if make and make.get("text"):
        extra = f" Text “{make['text']}”."
    if make and make.get("picture"):
        extra = f" From the picture {make['picture']} (SHA-256 {make['sha256'][:12]}…)."
    return f"{g.title}: {what}, made by Form Studio's {g.id} generator.{extra}"


def hinge_clearance(st) -> tuple[float, str, str]:
    """The print-in-place clearance per side for the person's printer: 0.35 mm (assumed) moved by the calibration's
    measured bias (a printer that prints internal widths 0.1 mm narrow gets 0.05 mm more per side)."""
    base = 0.35
    try:
        corr = st.calibration.correction(st.profile())
    except Exception:                                    # noqa: BLE001
        return base, "assumed", "0.35 mm per side, the FDM print-in-place rule of thumb (no calibration read)."
    if not corr.get("n"):
        return base, "assumed", "0.35 mm per side, the FDM print-in-place rule of thumb; no calibration for this printer."
    c = round(min(0.6, max(0.2, base - corr["bias"] / 2)), 2)
    src = "calibrated" if corr["source"] == "calibrated" else "assumed"
    return c, src, (f"0.35 mm per side moved by the printer's measured bias {corr['bias']:+.3f} mm "
                    f"({corr['n']} measured widths, {corr['source']}): {c:g} mm.")


def make(st, gid: str, values: dict | None = None, text: str | None = None, image=None, preset: str = "",
         name: str = "", purpose: str | None = None) -> dict:
    """Make a generator's design in the Studio: built in the kernel before it is saved. Returns
    {project, name, head, generator, preset, parameters, make, next}."""
    g = get(gid)
    pname, vals = _values(g, preset, values)
    made = None
    if g.kind == "calc":
        from ..calc import CalcError
        from ..calc import tools as calc_tools
        try:
            inputs = {k: int(x) if float(x).is_integer() else x for k, x in vals.items()}
            r = calc_tools.call(st, g.target, {"kind": "external", **inputs}, build=True, name=name or design_name(g, pname),
                                purpose=purpose)
        except CalcError as e:
            raise MakeError(str(e), e.hint, e.params) from None
        p = st.load(r["project"])
    elif g.kind == "recipe":
        rid = g.presets.get(pname, {}).get("recipe", g.target)
        r = st.recipes[rid]
        known = {q.key for q in r.params}
        bad = sorted(set(vals) - known)
        if bad:
            raise MakeError(f"{g.title} has no parameter {', '.join(bad)}.", "Parameters: " + ", ".join(sorted(known)) + ".", bad)
        p = st.create(name or design_name(g, pname), rid,
                      _brief(g, pname, None), vals, purpose=purpose)
    else:
        src, made = source_for(g.id, text=text, image=image, preset=pname)
        known = param_keys(src)
        bad = sorted(set(vals) - known)
        if bad:
            raise MakeError(f"{g.title} has no parameter {', '.join(bad)}.", "Parameters: " + ", ".join(sorted(known)) + ".", bad)
        clear = None
        if g.id == "hinge_box" and "clearance" not in vals:
            clear = hinge_clearance(st)
            vals["clearance"] = clear[0]
        p = st.create_design(name or design_name(g, pname, made.get("text", "")), src, brief=_brief(g, pname, made), values=vals, purpose=purpose)
        if clear is not None:
            with st.lock(p["id"]):
                q = st.load(p["id"])
                q["revisions"][-1].setdefault("provenance", {})["clearance"] = {"source": clear[1], "note": clear[2]}
                st.save(q)
            p = st.load(p["id"])
    rev = st.rev(p)
    out = {"project": p["id"], "name": p["name"], "head": p["head"], "generator": g.id, "preset": pname,
           "parameters": sorted(rev["values"]),
           "next": "render(project, view='sheet') to look; preview_change/commit_change edit the parameters; "
                   "run_pipeline checks and slices it for a print design."}
    if made:
        out["make"] = {k: v for k, v in made.items() if k != "pixels"}
    return out


def param_keys(src: str) -> set:
    """The parameter keys a design source declares (read from its Param(...) calls; nothing is imported here, so the
    engine never loads OCCT)."""
    import re
    return set(re.findall(r"""\bParam\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""", src))
