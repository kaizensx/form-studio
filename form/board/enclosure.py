"""An enclosure around a board, written as a design's code: one feature per step, every size a parameter.

The source this writes is an ordinary FeatureDesign (form/featureprog.py) that the person and the agent edit like any
other: shell with four corner lugs, cavity, standoffs under the board's mounting holes, an opening for each connector
that mates through a wall (sized from the plug's envelope, aligned to the connector's face), a lid printed beside
the box with a locating lip, and vents. Standard parts come from Wave G's tables (form/catalog.py) and are cut with
its mating features (form/placement.py apply): heat-set inserts in the standoffs and the lugs, the board screws and
the lid screws. They are placed from the values inside the design (std_parts), so they follow every change of a
wall, a clearance or a height, and assembly() lists them as purchased hardware for the parts list.

The board itself is a constant in the source (BOARD), written from the file it came from and named with its SHA-256,
so the design's geometry key changes when the board it was made for changes. The checks (form/board/fit.py) measure
the solids against the board as it is now in the project, so a board that changed after the enclosure was made
fails where it no longer lines up.

Frames: the box is modelled open side up with the board centred over the origin; the lid is modelled in its
assembled place and moved to the print layout (outer face on the bed, beside the box) by one transform, which
assembly() and board_layout() state.
"""
from __future__ import annotations

import math
import pprint

GAP = 8.0                  # between box and lid on the plate
ROUND = 4


def board_constant(board: dict) -> dict:
    """What the enclosure's geometry needs from the board model, rounded, in the board frame."""
    r = lambda x: None if x is None else round(float(x), ROUND)
    (x0, y0), (x1, y1) = [min(p[0] for p in board["outline"]), min(p[1] for p in board["outline"])], \
                         [max(p[0] for p in board["outline"]), max(p[1] for p in board["outline"])]
    ext = {"x0": x0, "x1": x1, "y0": y0, "y1": y1}
    top_h = bot_h = 0.0
    for c in board["components"]:
        (cx0, cy0), (cx1, cy1) = c["bbox"]
        ext = {"x0": min(ext["x0"], cx0), "x1": max(ext["x1"], cx1), "y0": min(ext["y0"], cy0), "y1": max(ext["y1"], cy1)}
        h = (c.get("height") or {}).get("value")
        if h is not None:
            if c["side"] == "top":
                top_h = max(top_h, h)
            else:
                bot_h = max(bot_h, h)
    openings = []
    for k in board["connectors"]:
        if k["side"] == "up":
            continue
        h = (k.get("height") or {}).get("value")
        pl = k["plug"]
        if h is None or pl.get("h") is None:
            continue
        openings.append({"ref": k["ref"], "side": k["side"], "face": r(k["face"]), "u": r(k["centre_u"]),
                         "board_side": k["board_side"], "z_mid": r(h / 2), "plug_w": r(pl["w"]), "plug_h": r(pl["h"])})
    return {"file": board["file"], "sha256": board["sha256"][:16], "origin": board["origin"],
            "thickness": r(board["thickness"]["value"]),
            "outline_box": [r(x0), r(y0), r(x1), r(y1)],
            "parts_box": [r(ext["x0"]), r(ext["y0"]), r(ext["x1"]), r(ext["y1"])],
            "top_h": r(top_h), "bottom_h": r(bot_h),
            "holes": [{"ref": h["ref"], "x": r(h["x"]), "y": r(h["y"]), "d": r(h["d"]), "screw": h["screw"]}
                      for h in board["mounting_holes"]],
            "openings": openings}


TEMPLATE = '''"""Enclosure for the board {file} (read by Form Studio; SHA-256 {sha}...).

Made by `board_import`: a box with four corner lugs, standoffs under the board's mounting holes, an opening for each
connector that mates through a wall, and a lid with a locating lip and vents, printed beside the box. Change any
parameter; import the board again to bring a changed board in (the checks then say what no longer lines up).
"""
import math

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, RectangleRounded, Rot, extrude, fillet

from form import catalog, patterns, parts, placement
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Assembly, Part, Param, RecipeError

# The board, in the board frame (mm; x right, y back, z up from the board's underside; origin at the centre of the
# outline's bounding box). Written from the board file; heights are only those the file, a board STEP or the person
# gave. Re-import the board rather than editing these numbers.
BOARD = {board}

GAP = {gap}
A = (Align.CENTER, Align.CENTER, Align.MIN)


def _rbox(x0, y0, x1, y1, h, r, z=0.0):
    b = Pos((x0 + x1) / 2, (y0 + y1) / 2, z) * Box(x1 - x0, y1 - y0, h, align=A)
    r = min(r, (x1 - x0) / 2 - 0.05, (y1 - y0) / 2 - 0.05)
    return fillet(b.edges().filter_by(Axis.Z), r) if r > 0.05 else b


class Design(FeatureDesign):
    title = {title!r}
    summary = "An enclosure made around a circuit board: standoffs on its holes, openings at its connectors, a lid with a lip."
    solids = 2
    refine = False                    # the fit to the board is measured on these exact solids
    params = [
        Param("wall", "Wall", 2.0, 1.2, 5, 0.1, "mm", "form", "shell"),
        Param("floor", "Floor", 2.0, 1.2, 5, 0.1, "mm", "form", "shell"),
        Param("corner_r", "Corner radius", 3.0, 0.5, 12, 0.5, "mm", "form", "shell"),
        Param("clearance", "Board to wall", 1.0, 0.3, 6, 0.1, "mm", "interface", "cavity",
              "Gap between the board (and the parts on it) and the inner walls, each side."),
        Param("standoff_h", "Standoff height", {standoff_h}, 2, 30, 0.5, "mm", "interface", "standoffs",
              "Space under the board. At least the insert pocket and the tallest part under the board."),
        Param("standoff_d", "Standoff diameter", {standoff_d}, 4, 16, 0.1, "mm", "form", "standoffs"),
        Param("headroom", "Space over the tallest part", 2.0, 0, 30, 0.5, "mm", "interface", "cavity",
              "Between the tallest part on the board and the underside of the lid."),
        Param("lug_d", "Corner lug diameter", {lug_d}, 5, 16, 0.1, "mm", "form", "shell",
              "Lugs at the outside corners take the lid screws' inserts, clear of the board."),
        Param("lid_screw", "Lid screw size", {lid_screw}, 2, 5, 0.5, "M", "interface", "lid", "Metric: 2, 2.5, 3, 4 or 5."),
        Param("lid_t", "Lid thickness", 2.0, 1.2, 6, 0.1, "mm", "form", "lid"),
        Param("lip_h", "Lid lip height", 2.5, 0, 8, 0.5, "mm", "form", "lip", "Locates the lid inside the walls. 0 = none."),
        Param("lip_wall", "Lid lip wall", 1.6, 1.0, 3, 0.1, "mm", "form", "lip"),
        Param("lip_clearance", "Lip clearance / side", 0.25, 0, 0.8, 0.05, "mm", "interface", "lip"),
        Param("port_clearance", "Opening clearance / side", 0.35, 0, 2, 0.05, "mm", "interface", "openings",
              "Added around each plug's envelope."),
        Param("vents", "Vent slots", 6, 0, 30, 1, "", "form", "vents", "Through the lid, over the board."),
        Param("vent_w", "Vent slot width", 2.0, 1, 6, 0.1, "mm", "form", "vents"),
    ]

    def setup(self, v):
        b, w, c = BOARD, v["wall"], v["clearance"]
        bx0, by0, bx1, by1 = b["parts_box"]
        cav = [bx0 - c, by0 - c, bx1 + c, by1 + c]                # inner walls
        out = [cav[0] - w, cav[1] - w, cav[2] + w, cav[3] + w]      # outer walls
        r_l = v["lug_d"] / 2
        k = r_l / math.sqrt(2)                                      # lug centre: tangent to the cavity's corner
        lugs = [(cav[0] - k, cav[1] - k), (cav[2] + k, cav[1] - k), (cav[0] - k, cav[3] + k), (cav[2] + k, cav[3] + k)]
        zb = v["floor"] + v["standoff_h"]
        zt = zb + b["thickness"]
        H = zt + b["top_h"] + v["headroom"]
        ymin = min(out[1], min(y for _x, y in lugs) - r_l)
        Y0 = 2 * ymin - GAP                                         # the lid, turned over, prints beside the box
        return {{"cav": cav, "out": out, "lugs": lugs, "zb": zb, "zt": zt, "H": H, "Y0": Y0, "r_l": r_l,
                "r_in": max(0.5, v["corner_r"] - w)}}

    def to_print(self, v, shape):
        """The lid from its assembled place (on the box) to the print layout (outer face on the bed)."""
        g = self.ctx
        return Rot(180, 0, 0) * Pos(0, -g["Y0"], -(g["H"] + v["lid_t"])) * shape

    def profile(self, v, h, z=0.0):
        g = self.ctx
        o = g["out"]
        s = _rbox(o[0], o[1], o[2], o[3], h, v["corner_r"], z)
        for (x, y) in g["lugs"]:
            s = s + Pos(x, y, z) * Cylinder(g["r_l"], h, align=A)
        return s

    @feature("Shell", role="structure")
    def shell(self, v, body):
        return self.profile(v, self.ctx["H"])

    @feature("Cavity", role="access")
    def cavity(self, v, body):
        g = self.ctx
        c = g["cav"]
        return body - _rbox(c[0], c[1], c[2], c[3], g["H"], g["r_in"], z=v["floor"])

    @feature("Standoffs", role="interface", doc="A column under each mounting hole; its insert is a standard part.")
    def standoffs(self, v, body):
        g = self.ctx
        for h in BOARD["holes"]:
            body = body + Pos(h["x"], h["y"], v["floor"] - 0.01) * Cylinder(v["standoff_d"] / 2, v["standoff_h"] + 0.01, align=A)
        return body

    @feature("Connector openings", role="access", doc="Each plug's envelope plus clearance, centred on its connector's face.")
    def openings(self, v, body):
        g = self.ctx
        for o in BOARD["openings"]:
            w, h = o["plug_w"] + 2 * v["port_clearance"], o["plug_h"] + 2 * v["port_clearance"]
            z = (g["zt"] + o["z_mid"]) if o["board_side"] == "top" else (g["zb"] - o["z_mid"])
            # a corner radius up to 3.4 x the clearance still passes the plug's rectangular envelope
            prof = RectangleRounded(w, h, max(0.05, min(1.0, 3.4 * v["port_clearance"], h / 2 - 0.05)))
            L = v["wall"] + v["clearance"] + 3.0
            if o["side"] in ("-y", "+y"):
                wall_y = g["cav"][1] - v["wall"] / 2 if o["side"] == "-y" else g["cav"][3] + v["wall"] / 2
                cut = Pos(o["u"], wall_y, z) * extrude(Plane.XZ * prof, amount=L / 2, both=True)
            else:
                wall_x = g["cav"][0] - v["wall"] / 2 if o["side"] == "-x" else g["cav"][2] + v["wall"] / 2
                cut = Pos(wall_x, o["u"], z) * extrude(Plane.YZ * prof, amount=L / 2, both=True)
            body = body - cut
        return body

    @feature("Lid", role="structure")
    def lid(self, v, body):
        g = self.ctx
        return body + self.to_print(v, self.profile(v, v["lid_t"], z=g["H"]))

    @feature("Lid lip", role="interface", doc="A ring under the lid that sits inside the walls.")
    def lip(self, v, body):
        if v["lip_h"] <= 0:
            return body
        g = self.ctx
        c, lw, cl = g["cav"], v["lip_wall"], v["lip_clearance"]
        z = g["H"] - v["lip_h"]
        ring = _rbox(c[0] + cl, c[1] + cl, c[2] - cl, c[3] - cl, v["lip_h"] + 0.01, max(0.5, g["r_in"] - cl), z) - \\
            _rbox(c[0] + cl + lw, c[1] + cl + lw, c[2] - cl - lw, c[3] - cl - lw, v["lip_h"] + 1, max(0.5, g["r_in"] - cl - lw), z - 0.5)
        return body + self.to_print(v, ring)

    @feature("Vents", role="access")
    def vents(self, v, body):
        n = int(round(v["vents"]))
        if n <= 0:
            return body
        g = self.ctx
        c = g["cav"]
        m = v["lip_wall"] + v["lip_clearance"] + 3
        L = (c[3] - c[1]) - 2 * m
        if L < v["vent_w"] * 2:
            return body
        pat = patterns.slot_array(v["vent_w"], min(L, 60.0), count=n, web=1.2 * v["vent_w"], depth=v["lid_t"] + 0.4)
        cut = Pos((c[0] + c[2]) / 2, (c[1] + c[3]) / 2, g["H"] + v["lid_t"] + 0.1) * pat.shape
        return body - self.to_print(v, cut)

    def std_parts(self, v):
        """Standard parts from Form Studio's tables (form.catalog), placed from the values so they follow every change:
        a heat-set insert in each standoff and lug, the board screws (bought; no cut, they pass through the board) and
        the lid screws with their clearance holes. The lid prints turned over beside the box, so a lug at (x, y) on
        the box is at (x, Y0 - y) on the plate, with the lid's outer face on the bed (z = 0)."""
        g = self.setup(v)
        out = []

        def add(spec, at, normal, depth, cut=True):
            out.append({{"id": f"board_std_{{len(out) + 1}}", "spec": catalog.resolve(spec), "at": tuple(float(x) for x in at),
                        "normal": tuple(float(x) for x in normal), "depth": float(depth), "qty": 1, "cut": cut, "snap": "given"}})
        t = BOARD["thickness"]
        for h in BOARD["holes"]:
            add({{"family": "heat_insert", "size": h["screw"]}}, (h["x"], h["y"], g["zb"]), (0, 0, 1), v["standoff_h"] + v["floor"])
        for h in BOARD["holes"]:
            n = parts.heat_insert(h["screw"])["insert_length"]
            L = parts.screw_length(h["screw"], t + 0.8 * n, t + n + 1.0)
            add({{"family": "iso7380", "size": h["screw"], "length": L, "recess": "no"}}, (h["x"], h["y"], g["zt"]), (0, 0, 1), t, cut=False)
        size = parts.size_name(v["lid_screw"])
        for (x, y) in g["lugs"]:
            add({{"family": "heat_insert", "size": size}}, (x, y, g["H"]), (0, 0, 1), g["H"])
        n = parts.heat_insert(size)["insert_length"]
        L = parts.screw_length(size, v["lid_t"] + 0.8 * n, v["lid_t"] + n + 1.0)
        for (x, y) in g["lugs"]:
            add({{"family": "iso7380", "size": size, "length": L, "recess": "no"}}, (x, g["Y0"] - y, 0.0), (0, 0, -1), v["lid_t"])
        return out

    @feature("Inserts and screws", role="interface", doc="Insert pockets in the standoffs and lugs, lid screw holes.")
    def inserts(self, v, body):
        for q in self.std_parts(v):
            body = placement.apply(body, q)
        return body

    def board_layout(self, v):
        """Where the board and the lid are, for the fit checks (form/board/fit.py) and the app."""
        g = self.setup(v)
        return {{"board_z": g["zb"], "board_top": g["zt"], "H": g["H"], "cavity": g["cav"], "outer": g["out"],
                "lugs": g["lugs"], "lid_move": [0.0, g["Y0"], g["H"] + v["lid_t"]], "lid_rotate": [180.0, 0.0, 0.0],
                "split_y": g["Y0"] / 2, "lid_t": v["lid_t"], "wall": v["wall"],
                "board_sha256": BOARD["sha256"], "board_origin": BOARD["origin"]}}

    def constraints(self, v):
        out = []
        size = parts.size_name(v["lid_screw"])
        if size not in parts.CLEARANCE:
            return [RecipeError(f"M{{v['lid_screw']:g}} is not a size Form Studio has data for", "lid", "Use 2, 2.5, 3, 4 or 5.", ["lid_screw"])]
        g = self.setup(v)
        for h in BOARD["holes"]:
            pocket = parts.heat_insert_pocket(h["screw"])
            if v["standoff_h"] + v["floor"] < pocket["depth"] + 0.8:
                out.append(RecipeError(f"The {{h['screw']}} insert pocket ({{pocket['depth']:.1f}} mm) does not fit in the standoff and floor",
                                       "standoffs", "Raise the standoffs or thicken the floor.", ["standoff_h", "floor"]))
                break
            if v["standoff_d"] < pocket["boss_min_d"] - 1e-9:
                out.append(RecipeError(f"Standoff Ø{{v['standoff_d']:g}} leaves under {{pocket['min_wall']:g}} mm around the {{h['screw']}} insert",
                                       "standoffs", f"Use at least {{pocket['boss_min_d']:.1f}} mm.", ["standoff_d"]))
                break
        if BOARD["bottom_h"] and v["standoff_h"] < BOARD["bottom_h"] + 0.5:
            out.append(RecipeError(f"Parts under the board stand {{BOARD['bottom_h']:g}} mm; the standoffs are {{v['standoff_h']:g}} mm",
                                   "standoffs", "Raise the standoffs.", ["standoff_h"]))
        lp = parts.heat_insert_pocket(size)
        if v["lug_d"] < lp["boss_min_d"] - 1e-9:
            out.append(RecipeError(f"Lug Ø{{v['lug_d']:g}} leaves under {{lp['min_wall']:g}} mm around the {{size}} insert", "shell",
                                   f"Use at least {{lp['boss_min_d']:.1f}} mm.", ["lug_d", "lid_screw"]))
        top_ok = g["H"] - (v["lip_h"] + 0.5 if v["lip_h"] else 0)
        for o in BOARD["openings"]:
            h = o["plug_h"] + 2 * v["port_clearance"]
            z = (g["zt"] + o["z_mid"]) if o["board_side"] == "top" else (g["zb"] - o["z_mid"])
            if z - h / 2 < v["floor"] + 0.6:
                out.append(RecipeError(f"The opening for {{o['ref']}} runs into the floor", "openings",
                                       "Raise the standoffs.", ["standoff_h"]))
            if z + h / 2 > top_ok:
                out.append(RecipeError(f"The opening for {{o['ref']}} runs into the lid's lip", "openings",
                                       "Add headroom, or lower the lip.", ["headroom", "lip_h"]))
        return out

    def assembly(self, v):
        g = self.setup(v)
        lay = self.board_layout(v)
        c = g["cav"]
        cx, wy = (c[0] + c[2]) / 2, c[1] - v["wall"] / 2           # a point in the front wall, and over it in the lid
        return Assembly(
            parts=[Part("box", "Box", (cx, wy, v["floor"] / 2),
                        note="Press the inserts into the standoffs and lugs, then screw the board down."),
                   Part("lid", "Lid", (cx, g["Y0"] - wy, v["lid_t"] / 2),
                        move=tuple(lay["lid_move"]), rotate=tuple(lay["lid_rotate"]), explode=(0, 0, v["lip_h"] + 25),
                        note="Turn the lid over and press it on: the lip goes inside the walls.")],
            hardware=self.bought(v))

    def bought(self, v):
        """The inserts and screws as purchased hardware (their standard designations), for the parts list."""
        import dataclasses
        return [dataclasses.replace(h, note="For the board enclosure: " + (
            "press it into its pocket." if "insert" in h.name.lower() else "screw it into its insert."))
            for h in placement.hardware(self.std_parts(v))]
'''


def source(board: dict, name: str = "", lid_screw: float = 3.0) -> tuple[str, dict]:
    """The design source of an enclosure for this board, and the defaults it was written with."""
    from .. import parts
    b = board_constant(board)
    pockets = [parts.heat_insert_pocket(h["screw"]) for h in b["holes"]] or [parts.heat_insert_pocket("M3")]
    floor = 2.0
    standoff_h = max(5.0, max(p["depth"] for p in pockets) + 0.8 - floor, (b["bottom_h"] or 0) + 1.0)
    standoff_h = math.ceil(standoff_h * 2) / 2
    standoff_d = math.ceil((max(p["boss_min_d"] for p in pockets) + 0.6) * 10) / 10
    lug = parts.heat_insert_pocket(parts.size_name(lid_screw))
    lug_d = math.ceil((lug["boss_min_d"] + 1.0) * 10) / 10
    text = TEMPLATE.format(file=b["file"], sha=b["sha256"], board=pprint.pformat(b, width=110, sort_dicts=False),
                           gap=GAP, title=(name or f"Enclosure for {b['file']}"), standoff_h=standoff_h,
                           standoff_d=standoff_d, lug_d=lug_d, lid_screw=float(lid_screw))
    return text, {"standoff_h": standoff_h, "standoff_d": standoff_d, "lug_d": lug_d, "floor": floor}


def layout(b: dict, v: dict) -> dict:
    """board_layout() of the generated design, computed here without the kernel (the same arithmetic as setup())."""
    w, c = v["wall"], v["clearance"]
    bx0, by0, bx1, by1 = b["parts_box"]
    cav = [bx0 - c, by0 - c, bx1 + c, by1 + c]
    out = [cav[0] - w, cav[1] - w, cav[2] + w, cav[3] + w]
    r_l = v["lug_d"] / 2
    k = r_l / math.sqrt(2)
    lugs = [(cav[0] - k, cav[1] - k), (cav[2] + k, cav[1] - k), (cav[0] - k, cav[3] + k), (cav[2] + k, cav[3] + k)]
    zb = v["floor"] + v["standoff_h"]
    zt = zb + b["thickness"]
    H = zt + b["top_h"] + v["headroom"]
    ymin = min(out[1], min(y for _x, y in lugs) - r_l)
    Y0 = 2 * ymin - GAP
    return {"board_z": zb, "board_top": zt, "H": H, "cavity": cav, "outer": out, "lugs": lugs, "Y0": Y0,
            "lid_move": [0.0, Y0, H + v["lid_t"]], "lid_rotate": [180.0, 0.0, 0.0]}
