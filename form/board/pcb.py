"""A KiCad board as a document Form Studio can change: read every pad with its net, shape and layers, the tracks
and vias, the outline and keep-outs and the rules of its net classes; move footprints, add and remove tracks and
vias, add footprints from the person's KiCad libraries; write the file back.

The tree is Form Studio's own reading of the S-expressions (form/board/sexpr.py) and is written back atom for atom,
so everything this module does not understand (zones, graphics, 3D models, text) is kept as it was. No KiCad code.

    doc = Pcb.load("board.kicad_pcb")       # with the rules in board.kicad_pro beside it
    doc.pads(), doc.tracks(), doc.vias(), doc.outline(), doc.keepouts(), doc.rules.for_net("GND")
    doc.add_segment(a, b, width, "F.Cu", net); doc.add_via(at, size, drill, net); doc.move_footprint("U1", x, y, 90)
    doc.save("routed.kicad_pcb")

Coordinates here are the file's own (mm, y down). The frame of form/board/model.py (y up, origin at the outline's
centre) is the enclosure's; `to_frame` and `from_frame` go between them.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import uuid
from pathlib import Path

from . import geom, kicad, model
from .sexpr import Sym, atoms, children, dump, first, head, num, parse, sym, value, xy

CU = re.compile(r"^(F|B|In\d+)\.Cu$")
NS = uuid.UUID("6f0c2a3e-52b1-4c0d-9a54-6b3d4f5a7c10")
KICAD_DEFAULTS = {"clearance": 0.2, "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3}
DEFAULT_SOURCE = "assumed: KiCad's values for a new project's Default net class (no .kicad_pro beside the board)"
BOARD_DEFAULTS = {"min_copper_edge_clearance": 0.5, "min_hole_clearance": 0.25, "min_hole_to_hole": 0.25,
                  "min_track_width": 0.0, "min_clearance": 0.0, "min_via_diameter": 0.0,
                  "min_through_hole_diameter": 0.0, "min_via_annular_width": 0.0}


class Rules:
    """Net classes and board minimums, from the .kicad_pro (JSON) beside the board, or KiCad's defaults, said so."""

    def __init__(self, pro: dict | None = None, file: str = ""):
        self.file = file
        self.classes: dict[str, dict] = {}
        self.patterns: list[tuple[str, str]] = []
        self.assign: dict[str, str] = {}
        self.board = dict(BOARD_DEFAULTS)
        self.board_from: dict[str, str] = {k: "assumed: KiCad's default" for k in BOARD_DEFAULTS}
        self.source = DEFAULT_SOURCE
        ns = (pro or {}).get("net_settings") or {}
        for c in ns.get("classes") or []:
            name = str(c.get("name") or "Default")
            self.classes[name] = {k: float(c[k]) for k in KICAD_DEFAULTS if isinstance(c.get(k), (int, float))}
        for p in ns.get("netclass_patterns") or []:
            if p.get("pattern") and p.get("netclass"):
                self.patterns.append((str(p["pattern"]), str(p["netclass"])))
        for net, cl in (ns.get("netclass_assignments") or {}).items():
            self.assign[str(net)] = str(cl[0] if isinstance(cl, list) and cl else cl)
        ds = (((pro or {}).get("board") or {}).get("design_settings") or {}).get("rules") or {}
        for k in BOARD_DEFAULTS:
            if isinstance(ds.get(k), (int, float)):
                self.board[k] = float(ds[k])
                self.board_from[k] = f"specified: {file}"
        if self.classes:
            self.source = f"specified: the net classes in {file}"
        d = self.classes.setdefault("Default", {})
        self.assumed = [k for k in KICAD_DEFAULTS if k not in d]
        for k, v in KICAD_DEFAULTS.items():
            d.setdefault(k, v)

    @classmethod
    def beside(cls, pcb: Path) -> "Rules":
        pro = Path(pcb).with_suffix(".kicad_pro")
        if pro.is_file():
            try:
                return cls(json.loads(pro.read_text(encoding="utf-8")), pro.name)
            except (OSError, ValueError):
                pass
        return cls()

    def class_of(self, net: str) -> str:
        if net in self.assign and self.assign[net] in self.classes:
            return self.assign[net]
        for pat, cl in self.patterns:
            if cl not in self.classes:
                continue
            if fnmatch.fnmatchcase(net, pat):
                return cl
            try:
                if re.fullmatch(pat, net):
                    return cl
            except re.error:
                pass
        return "Default"

    def for_net(self, net: str) -> dict:
        cl = self.class_of(net)
        d = dict(self.classes["Default"])
        d.update(self.classes.get(cl) or {})
        d["clearance"] = max(d["clearance"], self.board["min_clearance"])
        d["track_width"] = max(d["track_width"], self.board["min_track_width"])
        d["class"] = cl
        return d

    def describe(self) -> dict:
        return {"source": self.source, "classes": self.classes, "board": self.board, "board_from": self.board_from,
                "assumed": ([f"Default.{k}" for k in self.assumed] if self.file else list(KICAD_DEFAULTS)),
                "patterns": [{"pattern": p, "netclass": c} for p, c in self.patterns]}


def _q(v: float) -> float:
    return round(float(v), 6)


def _layers(node) -> list[str]:
    c = first(node, "layers")
    if c is not None:
        return [str(a) for a in atoms(c)]
    v = value(node, "layer")
    return [str(v)] if v is not None else []


def expand_cu(names: list[str], cu: list[str]) -> list[str]:
    out = []
    for n in names:
        if n == "*.Cu":
            out += cu
        elif n == "F&B.Cu":
            out += [x for x in cu if x in ("F.Cu", "B.Cu")]
        elif CU.match(n):
            out.append(n)
    return [x for i, x in enumerate(out) if x not in out[:i]]


class Pcb:
    def __init__(self, tree: list, path: Path | None = None, rules: Rules | None = None):
        if head(tree) != "kicad_pcb":
            raise ValueError(f"Not a KiCad board (it starts with “{head(tree) or '?'}”, not kicad_pcb).")
        self.tree = tree
        self.path = Path(path) if path else None
        self.rules = rules or (Rules.beside(self.path) if self.path else Rules())
        self.version = int(num(value(tree, "version"), 0) or 0)
        self._fps = None

    # ---- reading ---------------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Pcb":
        p = Path(path)
        return cls(parse(p.read_text(encoding="utf-8", errors="replace")), p)

    def text(self) -> str:
        return dump(self.tree)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(self.text(), encoding="utf-8")
        tmp.replace(path)
        return path

    def cu_layers(self) -> list[str]:
        lay = first(self.tree, "layers")
        names = [str(c[1]) for c in (lay or [])[1:] if isinstance(c, list) and len(c) >= 2]
        cu = [n for n in names if CU.match(n)]
        return cu or ["F.Cu", "B.Cu"]

    def nets(self) -> dict[int, str]:
        out = {}
        for n in children(self.tree, "net"):
            a = atoms(n)
            if a:
                out[int(num(a[0], 0) or 0)] = str(a[1]) if len(a) > 1 else ""
        return out

    def net_id(self, name: str, create: bool = True) -> int:
        nets = self.nets()
        for i, n in nets.items():
            if n == name:
                return i
        if not create:
            raise KeyError(name)
        i = max(nets, default=0) + 1
        node = [Sym("net"), sym(i), name]
        last = max((k for k, c in enumerate(self.tree) if isinstance(c, list) and head(c) == "net"), default=None)
        if last is None:
            if 0 not in nets:
                self.tree.append([Sym("net"), sym(0), ""])
            self.tree.append(node)
        else:
            self.tree.insert(last + 1, node)
        return i

    def footprints(self) -> list[dict]:
        if self._fps is not None:
            return self._fps
        cu = self.cu_layers()
        out = []
        for fp in self.tree[1:]:
            if not (isinstance(fp, list) and head(fp) in ("footprint", "module")):
                continue
            at = first(fp, "at")
            aa = atoms(at) if at is not None else []
            pos = (num(aa[0], 0.0), num(aa[1], 0.0)) if len(aa) >= 2 else (0.0, 0.0)
            ang = num(aa[2], 0.0) if len(aa) >= 3 else 0.0
            lay = str(value(fp, "layer") or "F.Cu")
            name = str(atoms(fp)[0]) if atoms(fp) else ""
            ref = kicad._prop(fp, "Reference") or ""
            court, pads_box, pads = [], [], []
            for g in fp[1:]:
                if isinstance(g, list) and head(g).startswith("fp_") and str(value(g, "layer") or "").endswith(".CrtYd"):
                    loop, line, circ = kicad._shape_polyline(g, head(g))
                    court += (loop or []) + (line or [])
                    if circ:
                        (cx, cy), d = circ
                        court += [(cx - d / 2, cy - d / 2), (cx + d / 2, cy + d / 2)]
            for pad in children(fp, "pad"):
                a = atoms(pad)
                pat = first(pad, "at")
                pa = atoms(pat) if pat is not None else []
                lx, ly = (num(pa[0], 0.0), num(pa[1], 0.0)) if len(pa) >= 2 else (0.0, 0.0)
                pang = num(pa[2], 0.0) if len(pa) >= 3 else 0.0
                size = [num(x) for x in atoms(first(pad, "size") or [])]
                w, h = (size + [None, None])[:2]
                if w is None:
                    continue
                h = w if h is None else h
                r = model.rot((lx, ly), ang)
                net = first(pad, "net")
                na = atoms(net) if net is not None else []
                dr = first(pad, "drill")
                dvals = [num(x) for x in atoms(dr) if num(x) is not None] if dr is not None else []
                kind = str(a[1]) if len(a) > 1 else ""
                shape = str(a[2]) if len(a) > 2 else "rect"
                pads_box += [(lx - max(w, h) / 2, ly - max(w, h) / 2), (lx + max(w, h) / 2, ly + max(w, h) / 2)]
                pads.append({"num": str(a[0]) if a else "", "kind": kind, "shape": shape,
                             "x": pos[0] + r[0], "y": pos[1] + r[1], "local": (lx, ly), "w": w, "h": h, "angle": pang,
                             "rratio": num(value(pad, "roundrect_rratio"), 0.25),
                             "layers": expand_cu(_layers(pad), cu), "net": int(num(na[0], 0) or 0) if na else 0,
                             "net_name": str(na[1]) if len(na) > 1 else "", "drill": (min(dvals) if dvals else None),
                             "drill_max": (max(dvals) if dvals else None), "ref": ref, "node": pad})
            local = court or pads_box
            box = None
            if local:
                xs, ys = [q[0] for q in local], [q[1] for q in local]
                box = (min(xs), min(ys), max(xs), max(ys))
            out.append({"ref": ref, "value": kicad._prop(fp, "Value") or "", "lib": name, "x": pos[0], "y": pos[1],
                        "rot": ang, "side": "bottom" if lay.startswith("B.") else "top", "pads": pads, "box": box,
                        "box_from": "courtyard" if court else "pads (no courtyard in the footprint)",
                        "height": kicad._height(fp), "mount": bool(model.MOUNT_LIB.search(name)),
                        "tht": any(p["kind"] in ("thru_hole", "np_thru_hole") for p in pads),
                        "locked": first(fp, "locked") is not None or Sym("locked") in fp, "node": fp})
        self._fps = out
        return out

    def footprint(self, ref: str) -> dict:
        for f in self.footprints():
            if f["ref"] == ref:
                return f
        raise KeyError(ref)

    def pads(self) -> list[dict]:
        return [p for f in self.footprints() for p in f["pads"]]

    def tracks(self) -> list[dict]:
        out = []
        for s in self.tree[1:]:
            if isinstance(s, list) and head(s) in ("segment", "arc"):
                a, b = xy(s, "start"), xy(s, "end")
                w = num(value(s, "width"))
                if a and b and w:
                    out.append({"a": a, "b": b, "w": w, "layer": str(value(s, "layer") or ""),
                                "net": int(num(value(s, "net"), 0) or 0), "arc": head(s) == "arc", "node": s})
        return out

    def vias(self) -> list[dict]:
        out = []
        cu = self.cu_layers()
        for v in children(self.tree, "via"):
            at, sz, dr = xy(v, "at"), num(value(v, "size")), num(value(v, "drill"))
            if at and sz:
                out.append({"at": at, "size": sz, "drill": dr or 0.0, "layers": expand_cu(_layers(v), cu) or cu,
                            "net": int(num(value(v, "net"), 0) or 0), "node": v})
        return out

    def zones(self) -> list[dict]:
        out = []
        for z in children(self.tree, "zone"):
            pol = first(z, "polygon")
            pts = kicad._pts(pol) if pol is not None else []
            ko = first(z, "keepout")
            out.append({"net": int(num(value(z, "net"), 0) or 0), "net_name": str(value(z, "net_name") or ""),
                        "layers": expand_cu(_layers(z), self.cu_layers()), "polygon": pts, "name": str(value(z, "name") or ""),
                        "keepout": ({head(r): str(atoms(r)[0]) for r in ko[1:] if isinstance(r, list) and atoms(r)}
                                    if ko is not None else None)})
        return out

    def keepouts(self) -> list[dict]:
        return [z for z in self.zones() if z["keepout"] is not None and len(z["polygon"]) >= 3]

    def edges(self) -> tuple[list, list, list]:
        """(outline, cut-outs, notes): the largest closed Edge.Cuts loop and the loops inside it, file coordinates."""
        lines, loops, notes = [], [], []

        def take(g, xf=None):
            loop, line, circ = kicad._shape_polyline(g, head(g))
            tr = xf or (lambda q: q)
            if loop:
                loops.append([tr(q) for q in loop])
            if line:
                lines.append([tr(q) for q in line])
            if circ:
                loops.append([tr(q) for q in model.circle(circ[0], circ[1] / 2)])
        for g in self.tree[1:]:
            if isinstance(g, list) and head(g).startswith("gr_") and str(value(g, "layer") or "") == "Edge.Cuts":
                take(g)
            elif isinstance(g, list) and head(g) in ("footprint", "module"):
                at = first(g, "at")
                aa = atoms(at) if at is not None else []
                pos = (num(aa[0], 0.0), num(aa[1], 0.0)) if len(aa) >= 2 else (0.0, 0.0)
                ang = num(aa[2], 0.0) if len(aa) >= 3 else 0.0
                for e in g[1:]:
                    if isinstance(e, list) and head(e).startswith("fp_") and str(value(e, "layer") or "") == "Edge.Cuts":
                        take(e, lambda q, pos=pos, ang=ang: (pos[0] + model.rot(q, ang)[0], pos[1] + model.rot(q, ang)[1]))
        chained, bad = model.chain(lines)
        loops += chained
        if bad:
            notes.append(f"{len(bad)} piece(s) of the board outline do not close into a loop; they are left out.")
        if not loops:
            return [], [], notes + ["No closed board outline (Edge.Cuts) was found."]
        loops.sort(key=lambda lp: -abs(model.area(lp)))
        return loops[0], loops[1:], notes

    def frame_origin(self) -> tuple[float, float]:
        outline, _c, _n = self.edges()
        if not outline:
            return 0.0, 0.0
        (x0, y0), (x1, y1) = model.bbox(outline)
        return round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4)

    # ---- changing --------------------------------------------------------------------------------------------------
    def _uuid(self, *key) -> list:
        u = str(uuid.uuid5(NS, "|".join(str(k) for k in key)))
        return [Sym("uuid"), u] if self.version >= 20240101 or not self.version else [Sym("tstamp"), Sym(u)]

    def add_segment(self, a, b, width: float, layer: str, net: int) -> list:
        a, b = (_q(a[0]), _q(a[1])), (_q(b[0]), _q(b[1]))
        node = [Sym("segment"), [Sym("start"), sym(a[0]), sym(a[1])], [Sym("end"), sym(b[0]), sym(b[1])],
                [Sym("width"), sym(_q(width))], [Sym("layer"), layer], [Sym("net"), sym(int(net))],
                self._uuid("segment", a, b, width, layer, net)]
        self.tree.append(node)
        return node

    def add_via(self, at, size: float, drill: float, net: int, layers=("F.Cu", "B.Cu")) -> list:
        at = (_q(at[0]), _q(at[1]))
        node = [Sym("via"), [Sym("at"), sym(at[0]), sym(at[1])], [Sym("size"), sym(_q(size))], [Sym("drill"), sym(_q(drill))],
                [Sym("layers"), *[str(x) for x in layers]], [Sym("net"), sym(int(net))],
                self._uuid("via", at, size, drill, net)]
        self.tree.append(node)
        return node

    def clear_routes(self, nets: set | None = None) -> int:
        """Remove tracks and vias (of the given net ids, or all). Returns how many went."""
        keep, gone = [self.tree[0]], 0
        for c in self.tree[1:]:
            if isinstance(c, list) and head(c) in ("segment", "arc", "via") and (
                    nets is None or int(num(value(c, "net"), 0) or 0) in nets):
                gone += 1
            else:
                keep.append(c)
        self.tree[:] = keep
        return gone

    def move_footprint(self, ref: str, x: float, y: float, rot: float | None = None) -> None:
        f = self.footprint(ref)
        node = f["node"]
        new = f["rot"] if rot is None else float(rot) % 360.0
        d = new - f["rot"]
        at = first(node, "at")
        if at is None:
            at = [Sym("at")]
            node.insert(2, at)
        at[1:] = [sym(_q(x)), sym(_q(y))] + ([sym(_q(new))] if abs(new) > 1e-9 else [])
        if abs(d) > 1e-9:
            for c in node[1:]:
                if isinstance(c, list) and head(c) in ("pad", "property", "fp_text"):
                    a = first(c, "at")
                    if a is None:
                        continue
                    aa = atoms(a)
                    if len(aa) < 2:
                        continue
                    ang = ((num(aa[2], 0.0) if len(aa) >= 3 else 0.0) + d) % 360.0
                    keep_tail = [t for t in aa[3:]]
                    a[1:] = [aa[0], aa[1]] + ([sym(_q(ang))] if abs(ang) > 1e-9 or keep_tail else []) + keep_tail
        self._fps = None

    def set_pad_net(self, ref: str, pad: str, net_name: str) -> None:
        nid = self.net_id(net_name)
        for p in self.footprint(ref)["pads"]:
            if p["num"] == pad:
                n = first(p["node"], "net")
                if n is None:
                    p["node"].append([Sym("net"), sym(nid), net_name])
                else:
                    n[1:] = [sym(nid), net_name]
        self._fps = None

    def add_footprint_tree(self, fp: list, ref: str, value_: str, at, rot: float = 0.0, nets: dict | None = None,
                           lib_id: str = "") -> None:
        """Place a footprint read from a .kicad_mod (top side): its tree is copied, moved, named and its pads netted."""
        import copy
        node = copy.deepcopy(fp)
        node[0] = Sym("footprint")
        if lib_id:
            node[1] = lib_id
        for k in ("at", "layer", "version", "generator", "generator_version", "uuid", "tstamp"):
            for c in [c for c in node[1:] if isinstance(c, list) and head(c) == k]:
                node.remove(c)
        node.insert(2, [Sym("layer"), "F.Cu"])
        node.insert(3, [Sym("at"), sym(0), sym(0)])
        node.insert(3, self._uuid("footprint", ref))
        for name, val in (("Reference", ref), ("Value", value_)):
            done = False
            for p in children(node, "property"):
                if atoms(p) and str(atoms(p)[0]) == name:
                    p[2] = val
                    done = True
            for t in children(node, "fp_text"):
                if atoms(t) and str(atoms(t)[0]) == name.lower():
                    t[2] = val
                    done = True
            if not done:
                node.append([Sym("property"), name, val, [Sym("at"), sym(0), sym(0), sym(0)],
                             [Sym("layer"), "F.SilkS" if name == "Reference" else "F.Fab"]])
        for pad in children(node, "pad"):
            for c in children(pad, "net"):
                pad.remove(c)
            nm = (nets or {}).get(str(atoms(pad)[0]) if atoms(pad) else "")
            if nm:
                pad.append([Sym("net"), sym(self.net_id(nm)), nm])
        self.tree.append(node)
        self._fps = None
        self.move_footprint(ref, at[0], at[1], rot)

    # ---- frames ----------------------------------------------------------------------------------------------------
    def to_frame(self, p, origin=None):
        o = origin or self.frame_origin()
        return p[0] - o[0], o[1] - p[1]

    def from_frame(self, p, origin=None):
        o = origin or self.frame_origin()
        return p[0] + o[0], o[1] - p[1]


def pad_copper(p: dict) -> tuple:
    """A pad's copper as a geom Shape and whether it is exact."""
    return geom.pad_shape(p["shape"], (p["x"], p["y"]), p["w"], p["h"], p["angle"], p["rratio"] or 0.25)


# ---- new boards ----------------------------------------------------------------------------------------------------
def blank(w: float, d: float, thickness: float = 1.6, origin=(100.0, 100.0), version: int = 20240108) -> Pcb:
    """An empty two-layer board with a w x d rectangular outline (KiCad 8 format)."""
    ox, oy = origin
    S = Sym
    tree = [S("kicad_pcb"), [S("version"), sym(version)], [S("generator"), "form_studio"], [S("generator_version"), "8.0"],
            [S("general"), [S("thickness"), sym(float(thickness))], [S("legacy_teardrops"), S("no")]],
            [S("paper"), "A4"],
            [S("layers"), [sym(0), "F.Cu", S("signal")], [sym(31), "B.Cu", S("signal")],
             [sym(36), "B.SilkS", S("user"), "B.Silkscreen"], [sym(37), "F.SilkS", S("user"), "F.Silkscreen"],
             [sym(38), "B.Mask", S("user")], [sym(39), "F.Mask", S("user")], [sym(44), "Edge.Cuts", S("user")],
             [sym(46), "B.CrtYd", S("user"), "B.Courtyard"], [sym(47), "F.CrtYd", S("user"), "F.Courtyard"],
             [sym(48), "B.Fab", S("user")], [sym(49), "F.Fab", S("user")]],
            [S("setup"), [S("pad_to_mask_clearance"), sym(0)]],
            [S("net"), sym(0), ""]]
    doc = Pcb(tree, rules=Rules())
    cs = [(ox, oy), (ox + w, oy), (ox + w, oy + d), (ox, oy + d)]
    for i in range(4):
        a, b = cs[i], cs[(i + 1) % 4]
        tree.append([S("gr_line"), [S("start"), sym(float(a[0])), sym(float(a[1]))], [S("end"), sym(float(b[0])), sym(float(b[1]))],
                     [S("stroke"), [S("width"), sym(0.05)], [S("type"), S("default")]], [S("layer"), "Edge.Cuts"],
                     doc._uuid("edge", i, w, d)])
    return doc


def add_part(doc: Pcb, ref: str, at, pads: list, rot: float = 0.0, lib: str = "Form:Synthetic", value_: str = "",
             courtyard: tuple | None = None, height: float | None = None, side: str = "top") -> None:
    """A plain footprint for synthetic boards and tests. pads: [{"num", "at": (x, y) local, "size": (w, h),
    "shape": rect|circle|oval|roundrect, "kind": smd|thru_hole, "drill": d, "net": name}]. Its numbers are made up."""
    S = Sym
    F = "B" if side == "bottom" else "F"
    node = [S("footprint"), lib, [S("layer"), f"{F}.Cu"], doc._uuid("footprint", ref), [S("at"), sym(0), sym(0)],
            [S("property"), "Reference", ref, [S("at"), sym(0), sym(-2), sym(0)], [S("layer"), f"{F}.SilkS"]],
            [S("property"), "Value", value_ or ref, [S("at"), sym(0), sym(2), sym(0)], [S("layer"), f"{F}.Fab"]]]
    if height is not None:
        node.append([S("property"), "Height", f"{height:g}", [S("at"), sym(0), sym(0), sym(0)], [S("layer"), f"{F}.Fab"]])
    xs = [p["at"][0] + sx * p["size"][0] / 2 for p in pads for sx in (-1, 1)]
    ys = [p["at"][1] + sy * p["size"][1] / 2 for p in pads for sy in (-1, 1)]
    c = courtyard or (min(xs) - 0.25, min(ys) - 0.25, max(xs) + 0.25, max(ys) + 0.25)
    node.append([S("fp_rect"), [S("start"), sym(float(c[0])), sym(float(c[1]))], [S("end"), sym(float(c[2])), sym(float(c[3]))],
                 [S("stroke"), [S("width"), sym(0.05)], [S("type"), S("solid")]], [S("layer"), f"{F}.CrtYd"]])
    for p in pads:
        kind = p.get("kind", "smd")
        pad = [S("pad"), str(p["num"]), S(kind), S(p.get("shape", "rect")),
               [S("at"), sym(float(p["at"][0])), sym(float(p["at"][1]))],
               [S("size"), sym(float(p["size"][0])), sym(float(p["size"][1]))]]
        if kind in ("thru_hole", "np_thru_hole"):
            pad.append([S("drill"), sym(float(p.get("drill", 0.8)))])
            pad.append([S("layers"), "*.Cu", "*.Mask"])
        else:
            pad.append([S("layers"), f"{F}.Cu", f"{F}.Paste", f"{F}.Mask"])
        if p.get("shape") == "roundrect":
            pad.append([S("roundrect_rratio"), sym(float(p.get("rratio", 0.25)))])
        if p.get("net"):
            pad.append([S("net"), sym(doc.net_id(p["net"])), p["net"]])
        node.append(pad)
    doc.tree.append(node)
    doc._fps = None
    doc.move_footprint(ref, at[0], at[1], rot)


def add_keepout(doc: Pcb, polygon: list, layers=("F.Cu", "B.Cu"), tracks: bool = False, vias: bool = False,
                footprints: bool = True, name: str = "") -> None:
    S = Sym
    al = lambda ok: S("allowed" if ok else "not_allowed")
    doc.tree.append([S("zone"), [S("net"), sym(0)], [S("net_name"), ""], [S("layers"), *[str(x) for x in layers]],
                     doc._uuid("zone", name, polygon), [S("name"), name], [S("hatch"), S("edge"), sym(0.5)],
                     [S("keepout"), [S("tracks"), al(tracks)], [S("vias"), al(vias)], [S("pads"), S("allowed")],
                      [S("copperpour"), S("not_allowed")], [S("footprints"), al(footprints)]],
                     [S("polygon"), [S("pts"), *[[S("xy"), sym(float(x)), sym(float(y))] for x, y in polygon]]]])


# ---- the person's KiCad footprint libraries ----------------------------------------------------------------------------
def library_dirs(cfg: dict | None, kind: str) -> list[Path]:
    """Where KiCad's standard libraries are on this computer (kind: "symbols" or "footprints"): [cad].kicad_<kind>,
    $FORM_KICAD_<KIND>, KiCad's own KICAD<n>_<KIND>_DIR, and the folders KiCad's installers use. Only folders that
    exist are returned; nothing is downloaded."""
    import glob
    import os
    import sys
    env = "SYMBOL" if kind == "symbols" else "FOOTPRINT"
    cand = [((cfg or {}).get("cad") or {}).get(f"kicad_{kind}", ""), os.environ.get(f"FORM_KICAD_{kind.upper()}", "")]
    cand += [os.environ.get(f"KICAD{n}_{env}_DIR", "") for n in (10, 9, 8, 7, 6)]
    if sys.platform == "darwin":
        for app in ["/Applications/KiCad/KiCad.app"] + sorted(glob.glob("/Applications/KiCad*/KiCad.app")):
            cand.append(f"{app}/Contents/SharedSupport/{kind}")
    elif sys.platform.startswith("win"):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cand += [str(Path(r) / "share" / "kicad" / kind) for r in sorted(glob.glob(str(Path(pf) / "KiCad" / "*")), reverse=True)]
    else:
        cand += [f"/usr/share/kicad/{kind}", f"/usr/local/share/kicad/{kind}",
                 f"/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/share/kicad/{kind}"]
    out = []
    for c in cand:
        for part in str(c).split(os.pathsep) if c else []:
            p = Path(part).expanduser()
            if p.is_dir() and p not in out:
                out.append(p)
    return out


def find_footprint(lib_id: str, dirs: list[Path]) -> Path | None:
    lib, _, name = lib_id.partition(":")
    if not name:
        return None
    for d in dirs:
        for f in (d / f"{lib}.pretty" / f"{name}.kicad_mod", d / f"{name}.kicad_mod"):
            if f.is_file():
                return f
    return None


def from_netlist(netlist: dict, size: tuple, dirs: list[Path], thickness: float = 1.6) -> tuple[Pcb, dict]:
    """A new board from a schematic's netlist (form/board/schematic.py): a size[0] x size[1] outline, each part's
    footprint read from the person's KiCad libraries (the Footprint field, "Lib:Name") and its pads given their
    nets. Parts are laid in rows inside the outline; `place` then places them. A part whose footprint is not named
    or not found is listed in "missing" and left off the board, never replaced by a guess."""
    doc = blank(size[0], size[1], thickness)
    pin_net = {}
    for net in netlist["nets"]:
        for n in net["nodes"]:
            pin_net[(n["ref"], n["pin"])] = net["name"]
    placed, missing = [], []
    x = y = 3.0
    row_h = 0.0
    for c in sorted(netlist["components"], key=lambda c: c["ref"]):
        fp = c.get("footprint") or ""
        f = find_footprint(fp, dirs) if fp else None
        if f is None:
            missing.append({"ref": c["ref"], "footprint": fp,
                            "why": "no Footprint field" if not fp else "not found in the KiCad footprint libraries"})
            continue
        tree = parse(f.read_text(encoding="utf-8", errors="replace"))
        nets = {pin: nm for (ref, pin), nm in pin_net.items() if ref == c["ref"]}
        doc.add_footprint_tree(tree, c["ref"], c.get("value", ""), (0.0, 0.0), 0.0, nets, fp)
        box = doc.footprint(c["ref"])["box"] or (-1, -1, 1, 1)
        bw, bh = box[2] - box[0], box[3] - box[1]
        if x + bw > size[0] - 3.0 and x > 3.0:
            x, y, row_h = 3.0, y + row_h + 1.0, 0.0
        doc.move_footprint(c["ref"], 100.0 + x - box[0], 100.0 + y - box[1], 0.0)
        x += bw + 1.0
        row_h = max(row_h, bh)
        placed.append(c["ref"])
    return doc, {"placed": placed, "missing": missing, "nets": len(doc.nets()) - 1,
                 "note": "Parts are laid in rows, not placed: board_place places them."}
