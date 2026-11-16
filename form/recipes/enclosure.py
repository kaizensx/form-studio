"""Electronics enclosure: a box and a screw-down lid printed side by side.

Corner bosses take brass heat-set inserts (CNC Kitchen dimensions, see form/parts.py) or self-tapping
screws; PCB standoffs follow a hole pattern (defaults: Raspberry Pi 4/5, 58 x 49 mm). Wall cut-outs for
USB-C plugs and round parts (buttons, LEDs, jacks) and vent slots in the lid. The USB-C opening is sized
from the plug overmold, which is what has to pass through the wall.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Circle, Cylinder, Plane, Pos, Rot, SlotOverall, extrude, fillet

from .. import parts
from .base import Feature, Param, Recipe, RecipeError, Stage
from ..parts import checked

A = (Align.CENTER, Align.CENTER, Align.MIN)
PCB_T = 1.6          # common FR-4 board thickness (specified for most boards; measure yours)
GAP = 8.0            # between box and lid on the plate


def _rbox(w, d, h, r, z=0.0):
    b = Pos(0, 0, z) * Box(w, d, h, align=A)
    r = min(r, w / 2 - 0.05, d / 2 - 0.05)
    return fillet(b.edges().filter_by(Axis.Z), r) if r > 0.05 else b


class Enclosure(Recipe):
    id = "enclosure"
    title = "Electronics enclosure"
    summary = ("A box and screw-down lid for a circuit board: corner bosses for heat-set inserts or self-tapping screws, "
               "PCB standoffs on the board's hole pattern, USB-C and round wall cut-outs, and lid vents.")
    solids = 2
    fit = {"cavity": "usbc_w", "mating": "usbc_plug_w", "clearance": "port_clearance",
           "label": "USB-C opening ↔ plug overmold", "per_side": True, "window": [0.2, 1.2]}

    params = [
        Param("inner_w", "Inner width", 104, 30, 200, 0.5, "mm", "brief", "cavity", "Free space inside, left to right."),
        Param("inner_d", "Inner depth", 72, 30, 180, 0.5, "mm", "brief", "cavity", "Free space inside, front to back."),
        Param("inner_h", "Inner height", 30, 10, 120, 0.5, "mm", "brief", "cavity", "From the floor to the underside of the lid."),
        Param("pcb_w", "Board width", 85, 10, 190, 0.1, "mm", "brief", "standoffs",
              "Default: Raspberry Pi 4/5 mechanical drawing, 85 × 56 mm.", "specified"),
        Param("pcb_d", "Board depth", 56, 10, 170, 0.1, "mm", "brief", "standoffs", "", "specified"),
        Param("hole_x", "Board hole spacing X", 58, 0, 180, 0.1, "mm", "brief", "standoffs",
              "Centre to centre. Raspberry Pi 4/5: 58 mm.", "specified"),
        Param("hole_y", "Board hole spacing Y", 49, 0, 160, 0.1, "mm", "brief", "standoffs", "Raspberry Pi 4/5: 49 mm.", "specified"),
        Param("hole_dx", "Hole pattern offset X", -10, -80, 80, 0.1, "mm", "brief", "standoffs",
              "Hole-pattern centre minus board centre. Raspberry Pi: holes 3.5 mm from the left edge, so −10 mm.", "specified"),
        Param("usbc_plug_w", "USB-C plug width", 12.35, 8, 16, 0.05, "mm", "brief", "ports",
              "Overmold of the plug that must pass the wall. 12.35 × 6.5 mm is the USB Type-C specification maximum; "
              "measure your cable.", "specified"),
        Param("usbc_plug_h", "USB-C plug height", 6.5, 2.5, 10, 0.05, "mm", "brief", "ports", "", "specified"),
        Param("wall", "Wall", 2.0, 1.2, 5, 0.1, "mm", "form", "body"),
        Param("floor", "Floor", 2.0, 1.2, 5, 0.1, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 4, 0.5, 15, 0.5, "mm", "form", "body"),
        Param("fasten", "Lid screws into", 1, 0, 1, 1, "", "interface", "bosses",
              "1 = brass heat-set inserts (CNC Kitchen sizes), 0 = self-tapping straight into the plastic."),
        Param("lid_screw", "Lid screw size", 3, 2, 5, 0.5, "M", "interface", "bosses", "Metric: 2, 2.5, 3, 4 or 5."),
        Param("boss_d", "Corner boss diameter", 8.5, 5, 16, 0.1, "mm", "form", "bosses",
              "With inserts it must leave the published minimum wall around the insert hole."),
        Param("pcb_screw", "Board screw size", 2.5, 2, 4, 0.5, "M", "interface", "standoffs", "Raspberry Pi: M2.5."),
        Param("standoff_d", "Standoff diameter", 7.5, 4, 12, 0.1, "mm", "form", "standoffs"),
        Param("standoff_h", "Standoff height", 5, 2, 20, 0.5, "mm", "form", "standoffs", "Space under the board."),
        Param("lid_t", "Lid thickness", 2.0, 1.2, 6, 0.1, "mm", "form", "lid"),
        Param("lid_head", "Lid screw head", 0, 0, 2, 1, "", "interface", "lid_screws",
              "0 = pan head on the surface, 1 = socket head in a counterbore, 2 = countersunk."),
        Param("lip_h", "Lid lip height", 3, 0, 8, 0.5, "mm", "form", "lip", "Locates the lid inside the walls. 0 = none."),
        Param("lip_wall", "Lid lip wall", 1.6, 1.2, 3, 0.1, "mm", "form", "lip"),
        Param("lip_clearance", "Lip clearance / side", 0.25, 0, 0.8, 0.05, "mm", "interface", "lip"),
        Param("usbc", "USB-C openings", 1, 0, 2, 1, "", "form", "ports", "In the front wall."),
        Param("usbc_x", "USB-C position X", 0, -90, 90, 0.5, "mm", "form", "ports", "First opening, from the box centre."),
        Param("usbc_z", "USB-C centre height", 9, 3, 100, 0.1, "mm", "form", "ports",
              "Above the floor. Standoff + board + about 2 mm for a board-edge receptacle."),
        Param("port_clearance", "Port clearance / side", 0.35, 0, 2, 0.05, "mm", "interface", "ports"),
        Param("round_n", "Round holes", 2, 0, 6, 1, "", "form", "holes", "In the back wall: buttons, LEDs, jacks."),
        Param("round_d", "Round hole diameter", 6.5, 2, 20, 0.1, "mm", "form", "holes"),
        Param("round_z", "Round hole height", 15, 3, 100, 0.5, "mm", "form", "holes", "Centre, above the floor."),
        Param("vents", "Vent slots", 8, 0, 30, 1, "", "form", "vents", "Through the lid."),
        Param("vent_w", "Vent slot width", 2, 1, 6, 0.1, "mm", "form", "vents"),
        Param("vent_l", "Vent slot length", 40, 5, 150, 0.5, "mm", "form", "vents"),
    ]
    features = [
        Feature("body", "Shell", "structure"),
        Feature("cavity", "Cavity", "access"),
        Feature("bosses", "Corner bosses", "structure"),
        Feature("inserts", "Insert / screw holes", "interface", "Heat-set insert pockets or self-tap pilot holes."),
        Feature("standoffs", "PCB standoffs", "interface"),
        Feature("board_holes", "Board screw holes", "interface"),
        Feature("ports", "USB-C openings", "access"),
        Feature("holes", "Round holes", "access"),
        Feature("lid", "Lid", "structure"),
        Feature("lip", "Lid lip", "interface", "Keeps the lid square on the box."),
        Feature("lid_screws", "Lid screw holes", "interface"),
        Feature("vents", "Vent slots", "access"),
    ]

    # ---- geometry helpers -----------------------------------------------------------------------------
    @staticmethod
    def g(v):
        W, D = v["inner_w"] + 2 * v["wall"], v["inner_d"] + 2 * v["wall"]
        H = v["floor"] + v["inner_h"]
        r_in = max(0.5, v["corner_r"] - v["wall"])
        bx, by = v["inner_w"] / 2 - v["boss_d"] / 2, v["inner_d"] / 2 - v["boss_d"] / 2
        size, psize = parts.size_name(v["lid_screw"]), parts.size_name(v["pcb_screw"])
        return {"W": W, "D": D, "H": H, "r_in": r_in, "bosses": [(sx * bx, sy * by) for sx in (-1, 1) for sy in (-1, 1)],
                "size": size, "psize": psize,
                "usb_w": v["usbc_plug_w"] + 2 * v["port_clearance"], "usb_h": v["usbc_plug_h"] + 2 * v["port_clearance"],
                "lid_y": -(D + GAP),
                "holes": [(v["hole_dx"] + sx * v["hole_x"] / 2, sy * v["hole_y"] / 2) for sx in (-1, 1) for sy in (-1, 1)]}

    def _fastener(self, v, depth_avail):
        g = self.g(v)
        if v["fasten"]:
            return parts.heat_insert_pocket(g["size"])
        return parts.self_tap_pilot(g["size"], depth=min(depth_avail, float(g["size"][1:]) * 3))

    def _board_fastener(self, v):
        g = self.g(v)
        avail = v["standoff_h"] + v["floor"] - 0.8
        if v["fasten"]:
            return parts.heat_insert_pocket(g["psize"])
        return parts.self_tap_pilot(g["psize"], depth=avail)

    def _lid_hole(self, v):
        head = {0: "pan", 1: "socket", 2: "countersunk"}[int(v["lid_head"])]
        return parts.screw_clearance(self.g(v)["size"], v["lid_t"], head=head, fit="normal", recess=bool(v["lid_head"]))

    def constraints(self, v):
        out = []
        for k in ("fasten", "lid_head", "usbc", "round_n", "vents"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        for k in ("lid_screw", "pcb_screw"):
            if parts.size_name(v[k]) not in parts.CLEARANCE:
                out.append(RecipeError(f"M{v[k]:g} is not a size FORM has data for", self.spec(k).feature, "Use 2, 2.5, 3, 4 or 5.", [k]))
        if out:
            return out
        g = self.g(v)
        if g["W"] > 250 or g["D"] > 250:
            return [RecipeError(f"Box is {g['W']:.0f} × {g['D']:.0f} mm", "body", "Keep it within the print bed.", ["inner_w", "inner_d"])]
        if g["D"] * 2 + GAP > 250:
            out.append(RecipeError("Box and lid side by side are deeper than common print beds", "lid",
                                   "Make the box shallower front to back.", ["inner_d"]))
        try:
            fx = self._fastener(v, v["inner_h"] - 1)
            bf = self._board_fastener(v)
            lh = self._lid_hole(v)
        except RecipeError as e:
            return [RecipeError(str(e), "lid_screws" if "head" in str(e) else "bosses", e.hint or "Change the screw or the lid.",
                                ["lid_t", "lid_head", "lid_screw"])]
        if v["fasten"] and v["boss_d"] < fx["boss_min_d"] - 1e-9:
            out.append(RecipeError(f"Boss Ø{v['boss_d']:g} leaves under {fx['min_wall']:g} mm around the {g['size']} insert",
                                   "bosses", f"Use a boss of at least {fx['boss_min_d']:.1f} mm.", ["boss_d", "lid_screw"]))
        if not v["fasten"] and v["boss_d"] < fx["hole_d"] + 2.4:
            out.append(RecipeError("Boss is too thin around the pilot hole", "bosses", "Widen the boss.", ["boss_d"]))
        if fx["depth"] > v["inner_h"] - 1:
            out.append(RecipeError("The screw hole is deeper than the boss is tall", "inserts", "Make the box taller.", ["inner_h"]))
        if v["fasten"] and v["standoff_d"] < bf["boss_min_d"] - 1e-9:
            out.append(RecipeError(f"Standoff Ø{v['standoff_d']:g} leaves under {bf['min_wall']:g} mm around the {g['psize']} insert",
                                   "standoffs", f"Use standoffs of at least {bf['boss_min_d']:.1f} mm.", ["standoff_d", "pcb_screw"]))
        if v["fasten"] and bf["depth"] > v["standoff_h"] + v["floor"] - 0.6:
            out.append(RecipeError(f"The {g['psize']} insert pocket ({bf['depth']:.1f} mm) does not fit in the standoff and floor",
                                   "board_holes", "Raise the standoffs, or use self-tapping screws.", ["standoff_h", "fasten"]))
        if v["boss_d"] > min(v["inner_w"], v["inner_d"]) / 3:
            out.append(RecipeError("Corner bosses take up too much of the box", "bosses", "Use a smaller boss or a bigger box.", ["boss_d"]))
        # board fits inside, clear of the walls and the corner bosses
        hw, hd = v["pcb_w"] / 2, v["pcb_d"] / 2
        if hw > v["inner_w"] / 2 - 0.5 or hd > v["inner_d"] / 2 - 0.5:
            out.append(RecipeError(f"The {v['pcb_w']:g} × {v['pcb_d']:g} mm board does not fit inside", "cavity",
                                   "Make the box bigger.", ["inner_w", "inner_d", "pcb_w", "pcb_d"]))
        else:
            bx, by = g["bosses"][3]
            cx, cy = min(hw, bx), min(hd, by)
            dist = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5 if (hw < bx or hd < by) else 0.0
            if dist < v["boss_d"] / 2 + 0.5 and v["standoff_h"] < v["inner_h"]:
                out.append(RecipeError("A board corner runs into a corner boss", "bosses",
                                       "Make the box bigger, or the bosses smaller.", ["inner_w", "inner_d", "boss_d"]))
        if v["hole_x"] > v["pcb_w"] or v["hole_y"] > v["pcb_d"] or abs(v["hole_dx"]) + v["hole_x"] / 2 > hw:
            out.append(RecipeError("The hole pattern falls outside the board", "standoffs", "Check the board drawing.",
                                   ["hole_x", "hole_y", "hole_dx"]))
        if v["hole_x"] > 0 and v["hole_x"] < v["standoff_d"] + 1 or v["hole_y"] > 0 and v["hole_y"] < v["standoff_d"] + 1:
            out.append(RecipeError("Standoffs overlap", "standoffs", "Use thinner standoffs.", ["standoff_d"]))
        if v["standoff_h"] + PCB_T > v["inner_h"] - 3:
            out.append(RecipeError("No room above the board", "standoffs", "Lower the standoffs or make the box taller.",
                                   ["standoff_h", "inner_h"]))
        # wall cut-outs
        top_ok = v["inner_h"] - (v["lip_h"] + 0.5 if v["lip_h"] else 0)
        if v["usbc"]:
            if v["usbc_z"] - g["usb_h"] / 2 < 0.8 or v["usbc_z"] + g["usb_h"] / 2 > top_ok:
                out.append(RecipeError("USB-C opening runs into the floor or the lid lip", "ports", "Move it up or down.",
                                       ["usbc_z", "lip_h"]))
            n = int(v["usbc"])
            xs = [v["usbc_x"] + i * (g["usb_w"] + 6) for i in range(n)]
            lim = v["inner_w"] / 2 - v["boss_d"] - 0.5
            if min(xs) - g["usb_w"] / 2 < -lim or max(xs) + g["usb_w"] / 2 > lim:
                out.append(RecipeError("USB-C opening runs into a corner boss", "ports", "Move it toward the centre.", ["usbc_x", "usbc"]))
        if v["round_n"]:
            n = int(v["round_n"])
            span = n * v["round_d"] + (n - 1) * max(4, v["round_d"] / 2)
            if span > v["inner_w"] - 2 * v["boss_d"] - 2:
                out.append(RecipeError("The round holes do not fit along the back wall", "holes", "Use fewer or smaller holes.",
                                       ["round_n", "round_d"]))
            if v["round_z"] - v["round_d"] / 2 < 0.8 or v["round_z"] + v["round_d"] / 2 > top_ok:
                out.append(RecipeError("Round holes run into the floor or the lid lip", "holes", "Move them up or down.",
                                       ["round_z", "round_d"]))
        if v["vents"]:
            n = int(v["vents"])
            pitch = v["vent_w"] * 2.2
            free_w = v["inner_w"] - 2 * (v["lip_wall"] + v["lip_clearance"] + 3)
            if n * pitch > free_w:
                out.append(RecipeError("The vent slots do not fit across the lid", "vents", "Use fewer or narrower slots.",
                                       ["vents", "vent_w"]))
            if v["vent_l"] > v["inner_d"] - 2 * (v["lip_wall"] + v["lip_clearance"] + 3):
                out.append(RecipeError("Vent slots are longer than the lid allows", "vents", "Shorten them.", ["vent_l"]))
        if v["lip_h"] and v["lip_wall"] + v["lip_clearance"] > v["boss_d"]:
            out.append(RecipeError("Lid lip is thicker than the corner bosses", "lip", "Thin the lip.", ["lip_wall"]))
        return out

    def build(self, v):
        g = self.g(v)
        W, D, H, t, iw, idp = g["W"], g["D"], g["H"], v["wall"], v["inner_w"], v["inner_d"]
        shell = _rbox(W, D, H, v["corner_r"])
        stages = [Stage("body", shell)]
        s = shell - _rbox(iw, idp, H, g["r_in"], z=v["floor"])
        stages.append(Stage("cavity", s))

        # corner bosses: a column tangent to both inner walls, filled into the corner
        bd = v["boss_d"]
        cols = None
        for (x, y) in g["bosses"]:
            sx, sy = (1 if x > 0 else -1), (1 if y > 0 else -1)
            c = Pos(x, y, v["floor"] - 0.01) * Cylinder(bd / 2, v["inner_h"] + 0.01, align=A)
            c = c + Pos(x + sx * bd / 4, y + sy * bd / 4, v["floor"] - 0.01) * Box(bd / 2 + 0.2, bd / 2 + 0.2, v["inner_h"] + 0.01, align=A)
            cols = c if cols is None else cols + c
        s = s + (cols & _rbox(iw + 0.02, idp + 0.02, H, g["r_in"], z=0))
        stages.append(Stage("bosses", s))
        fx = self._fastener(v, v["inner_h"] - 1)
        cut = None
        for (x, y) in g["bosses"]:
            c = Pos(x, y, H) * fx.shape
            cut = c if cut is None else cut + c
        s = s - cut
        stages.append(Stage("inserts", s))

        # standoffs on the board's hole pattern
        so = None
        for (x, y) in g["holes"]:
            c = Pos(x, y, v["floor"] - 0.01) * Cylinder(v["standoff_d"] / 2, v["standoff_h"] + 0.01, align=A)
            so = c if so is None else so + c
        s = s + so
        stages.append(Stage("standoffs", s))
        bf = self._board_fastener(v)
        cut = None
        for (x, y) in g["holes"]:
            c = Pos(x, y, v["floor"] + v["standoff_h"]) * bf.shape
            cut = c if cut is None else cut + c
        s = s - cut
        stages.append(Stage("board_holes", s))

        if v["usbc"]:
            cut = None
            for i in range(int(v["usbc"])):
                x = v["usbc_x"] + i * (g["usb_w"] + 6)
                slot = extrude(Plane.XZ * SlotOverall(g["usb_w"], g["usb_h"]), amount=t + 1, both=True)
                c = Pos(x, -D / 2 + t / 2, v["floor"] + v["usbc_z"]) * slot
                cut = c if cut is None else cut + c
            s = s - cut
            stages.append(Stage("ports", s))
        if v["round_n"]:
            n = int(v["round_n"])
            pitch = v["round_d"] + max(4, v["round_d"] / 2)
            cut = None
            for i in range(n):
                x = (i - (n - 1) / 2) * pitch
                hole = extrude(Plane.XZ * Circle(v["round_d"] / 2), amount=t + 1, both=True)
                c = Pos(x, D / 2 - t / 2, v["floor"] + v["round_z"]) * hole
                cut = c if cut is None else cut + c
            s = s - cut
            stages.append(Stage("holes", s))

        # lid, printed beside the box with its outer face on the bed
        Y0, lt = g["lid_y"], v["lid_t"]
        lid = Pos(0, Y0, 0) * _rbox(W, D, lt, v["corner_r"])
        s = s + lid
        stages.append(Stage("lid", s))
        if v["lip_h"] > 0:
            c, lw = v["lip_clearance"], v["lip_wall"]
            ow, od = iw - 2 * c, idp - 2 * c
            ring = _rbox(ow, od, v["lip_h"], max(0.5, g["r_in"] - c)) - _rbox(ow - 2 * lw, od - 2 * lw, v["lip_h"] + 1,
                                                                               max(0.5, g["r_in"] - c - lw), z=-0.5)
            notch = None
            for (x, y) in g["bosses"]:
                # square notch from just inside the boss to the corner: the lip ends square, no slivers
                sx, sy = (1 if x > 0 else -1), (1 if y > 0 else -1)
                e = bd / 2 + c + 0.2
                k = Pos(x + sx * (bd - e) / 2, y + sy * (bd - e) / 2, -0.5) * Box(bd + e, bd + e, v["lip_h"] + 1, align=A)
                notch = k if notch is None else notch + k
            ring = Pos(0, Y0, lt - 0.01) * (ring - notch)
            s = s + ring
            stages.append(Stage("lip", s))
        lh = self._lid_hole(v)
        cut = None
        for (x, y) in g["bosses"]:
            c = Pos(x, Y0 + y, 0) * Rot(180, 0, 0) * lh.shape       # opening on the bed face, through the lid
            cut = c if cut is None else cut + c
        s = s - cut
        stages.append(Stage("lid_screws", s))
        if v["vents"]:
            n = int(v["vents"])
            pitch = v["vent_w"] * 2.2
            cut = None
            for i in range(n):
                x = (i - (n - 1) / 2) * pitch
                c = Pos(x, Y0, -0.5) * extrude(Plane.XY * SlotOverall(v["vent_l"], v["vent_w"], rotation=90), amount=lt + 1)
                cut = c if cut is None else cut + c
            s = s - cut
            stages.append(Stage("vents", s))
        return checked(stages)

    def derived(self, v):
        g = self.g(v)
        fx, bf, lh = self._fastener(v, v["inner_h"] - 1), self._board_fastener(v), self._lid_hole(v)
        L = v["lid_t"] + (fx["insert_length"] if v["fasten"] else fx["depth"])
        rows = [
            {"key": "outer_w", "label": "Outer width", "value": g["W"], "unit": "mm", "feature": "body", "formula": "inner + 2 × wall"},
            {"key": "outer_d", "label": "Outer depth", "value": g["D"], "unit": "mm", "feature": "body", "formula": "inner + 2 × wall"},
            {"key": "outer_h", "label": "Box height", "value": g["H"], "unit": "mm", "feature": "body", "formula": "floor + inner height"},
            {"key": "usbc_w", "label": "USB-C opening width", "value": g["usb_w"], "unit": "mm", "feature": "ports",
             "formula": "plug width + 2 × clearance", "interface": True},
            {"key": "usbc_h", "label": "USB-C opening height", "value": g["usb_h"], "unit": "mm", "feature": "ports",
             "formula": "plug height + 2 × clearance"},
            {"key": "lid_screw_len", "label": f"Lid screw length ({g['size']})", "value": L, "unit": "mm", "feature": "lid_screws",
             "formula": "lid thickness + insert length" if v["fasten"] else "lid thickness + pilot depth"},
            {"key": "board_top", "label": "Board top above floor", "value": v["standoff_h"] + PCB_T, "unit": "mm",
             "feature": "standoffs", "formula": "standoff + 1.6 mm board (assumed)"},
        ]
        return rows + fx.derived("inserts", "lid_fastener.", ("hole_d",)) + bf.derived("board_holes", "board_fastener.") \
            + lh.derived("lid_screws", "lid_hole.")

    def measure(self, v, faces_by_feature):
        out = []
        ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get("inserts", [])
              if f.geom_type.name == "CYLINDER" and f.bounding_box().size.Z > 1]
        if ds:
            out.append({"key": "lid_fastener.hole_d", "label": "Boss hole diameter", "intended": self._fastener(v, v["inner_h"] - 1)["hole_d"],
                        "modelled": min(ds)})
        g = self.g(v)
        first = [f.bounding_box() for f in faces_by_feature.get("ports", [])
                 if abs(f.center().X - v["usbc_x"]) < g["usb_w"] / 2 + 0.01]
        if first and v["usbc"]:
            w = max(b.max.X for b in first) - min(b.min.X for b in first)
            out.append({"key": "usbc_w", "label": "USB-C opening width", "intended": g["usb_w"], "modelled": w})
        return out

    def statics(self, v, solid_volume_mm3, com):
        fx = self._fastener(v, v["inner_h"] - 1)
        g = self.g(v)
        checks = []
        if v["fasten"]:
            wall = (v["boss_d"] - fx["hole_d"]) / 2
            checks.append({"id": "insert_wall", "label": f"Wall around {g['size']} inserts", "value": f"{wall:.2f} mm",
                           "status": "PASS" if wall >= fx["min_wall"] else "FAIL",
                           "detail": f"Boss Ø{v['boss_d']:g} around a Ø{fx['hole_d']:g} hole. CNC Kitchen publishes "
                                     f"{fx['min_wall']:g} mm as the minimum wall for this insert (specified).",
                           "evidence": "computed", "feature": "bosses"})
        head = v["inner_h"] - v["standoff_h"] - PCB_T
        checks.append({"id": "headroom", "label": "Space above the board", "value": f"{head:.1f} mm",
                       "status": "PASS" if head >= 10 else "WARN",
                       "detail": "Inner height − standoff − 1.6 mm board (assumed thickness). Check your tallest part "
                                 "(USB and Ethernet jacks on a Raspberry Pi stand about 16 mm).",
                       "evidence": "computed", "feature": "standoffs"})
        return {"insert_wall_mm": (v["boss_d"] - fx["hole_d"]) / 2, "headroom_mm": head, "checks": checks}

    def test_piece(self, v, shape):
        g = self.g(v)
        s = v["boss_d"] + v["wall"] + 6
        h = g["H"]
        slab = Pos(-g["W"] / 2 + s / 2, -g["D"] / 2 + s / 2, 0) * Box(s, s, h, align=A)
        piece = shape & slab
        return piece, {"label": "Corner boss", "doc": "One corner of the box with its boss and insert or pilot hole. "
                       "Checks the insert goes in straight and the screw bites.", "height": h}
