"""Storage box: a box and its lid, printed side by side. Three lids on one box:

  0  sliding lid: a flat plate with 45° bevelled edges that slides into matching grooves from the front. The
     grooves' roofs are the 45° bevel, so the box prints upright with no support; the lid prints flat.
  1  press-on lid: a plate with a skirt that drops inside the walls, held by friction. Printed top face down.
  2  hinged lid: three knuckles and a pin (a 1.75 mm filament offcut). The box knuckles sit on 45° brackets so
     they print without support; the lid knuckle is squared on top, which is flat on the plate when printed.

Inside corners are rounded at the floor so things scoop out, every outside edge on the plate has a 45° foot
chamfer, and an optional label recess on the front takes a 12 mm label-maker tape or a paper slip.
"""
from __future__ import annotations

import math

from build123d import (Align, Axis, Box, Circle, Cylinder, Plane, Polygon, Pos, Rot, Sphere, chamfer, extrude, fillet)

from .assembly import Assembly, Hardware, Part, hinge, slide
from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import A, FOOT, teardrop

GAP = 8.0          # mm between box and lid on the plate
BEVEL = 50.0       # sliding lid bevel and groove roof, degrees from horizontal
LIDS = {0: "sliding", 1: "press-on", 2: "hinged"}


def _rrect(w, d, h, r, z=0.0):
    b = Box(w, d, h, align=A)
    r = min(r, w / 2 - 0.05, d / 2 - 0.05)
    if r > 0.05:
        b = fillet(b.edges().filter_by(Axis.Z), r)
    return Pos(0, 0, z) * b


class StorageBox(Recipe):
    id = "storage_box"
    title = "Box with lid"
    summary = ("A storage box sized from the inside, with a sliding, press-on or hinged lid, optional dividers and a "
               "label recess; box and lid print side by side without support.")
    category = "Storage"
    tags = ("box", "lid", "storage", "sliding lid", "hinge", "organiser", "dividers")
    solids = 2

    params = [
        Param("inner_w", "Inner width", 80, 20, 160, 0.5, "mm", "brief", "cavity", "Free space inside, left to right. Measure what it must hold."),
        Param("inner_d", "Inner depth", 60, 20, 150, 0.5, "mm", "brief", "cavity", "Free space inside, front to back."),
        Param("inner_h", "Inner height", 36, 8, 140, 0.5, "mm", "brief", "cavity", "From the floor to the underside of the lid."),
        Param("lid", "Lid", 0, 0, 2, 1, "", "form", "lid", "0 = sliding, 1 = press-on, 2 = hinged with a filament pin."),
        Param("wall", "Wall", 2.4, 1.6, 4, 0.1, "mm", "form", "shell", "Six lines at 0.4 mm. A sliding lid needs groove + clearance + 1.2 mm."),
        Param("floor", "Floor", 1.6, 1.2, 4, 0.1, "mm", "form", "shell"),
        Param("corner_r", "Corner radius", 6, 1, 15, 0.5, "mm", "form", "shell", "Outside, in plan. At least the wall + 0.5 mm."),
        Param("scoop_r", "Inside floor radius", 3, 0, 10, 0.5, "mm", "form", "cavity", "Rounds the inside floor edges so small parts scoop out. At most the inside corner radius (corner − wall)."),
        Param("lid_t", "Lid thickness", 2.4, 1.6, 4, 0.1, "mm", "form", "lid"),
        Param("lid_clear", "Lid clearance / side", 0.2, 0.05, 0.6, 0.05, "mm", "interface", "lid",
              "Gap around the lid in its grooves or around its skirt. Smaller holds tighter; tune it with your printer."),
        Param("groove", "Groove depth", 0.9, 0.6, 2.0, 0.1, "mm", "interface", "groove", "Sliding lid: how far its bevelled edge reaches into each wall."),
        Param("lip_h", "Skirt height", 6, 3, 15, 0.5, "mm", "form", "lid_lip", "Press-on and hinged lids: how deep the skirt drops inside the walls."),
        Param("skirt_t", "Skirt wall", 1.6, 1.2, 3, 0.1, "mm", "form", "lid_lip"),
        Param("dividers", "Dividers", 0, 0, 5, 1, "", "form", "dividers", "Evenly spaced, front to back."),
        Param("divider_t", "Divider thickness", 1.6, 1.2, 3, 0.1, "mm", "form", "dividers"),
        Param("label", "Label recess", 1, 0, 1, 1, "", "form", "label", "1 = a 0.6 mm recess on the front for a label."),
        Param("label_h", "Label height", 12, 6, 30, 0.5, "mm", "form", "label", "12 mm suits label-maker tape."),
        Param("knuckle_r", "Knuckle radius", 3.5, 2.5, 6, 0.1, "mm", "form", "knuckles", "Hinged lid."),
        Param("hinge_gap", "Hinge gap", 0.4, 0.2, 1.0, 0.05, "mm", "interface", "knuckles",
              "Hinged lid: between neighbouring knuckles, and between the knuckles and the wall or lid."),
        Param("pin_d", "Pin diameter", 1.75, 1.0, 3.0, 0.05, "mm", "brief", "pin_hole",
              "Hinged lid. A length of 1.75 mm filament works as the pin; measure yours.", "specified"),
        Param("pin_clear", "Pin clearance / side", 0.15, 0.0, 0.5, 0.05, "mm", "interface", "pin_hole"),
        Param("open_deg", "Opening angle", 110, 30, 170, 1, "deg", "form", "lid_knuckle", "Hinged lid: how far the hinge is checked to open."),
    ]
    features = [
        Feature("shell", "Box", "structure"),
        Feature("cavity", "Cavity", "access"),
        Feature("dividers", "Dividers", "structure"),
        Feature("label", "Label recess", "finish"),
        Feature("groove", "Lid grooves", "interface", "Sliding lid: 45° grooves in the side and back walls."),
        Feature("knuckles", "Box knuckles", "interface", "Hinged lid: two knuckles on 45° brackets behind the back wall."),
        Feature("lid", "Lid", "structure"),
        Feature("lid_lip", "Lid skirt", "interface", "Press-on and hinged lids: drops inside the walls."),
        Feature("grip", "Finger dish", "access", "Sliding lid: a shallow dish to push it open."),
        Feature("lid_knuckle", "Lid knuckle", "interface"),
        Feature("pin_hole", "Pin hole", "interface"),
    ]

    # ---- dimensions ------------------------------------------------------------------------------------------------
    @staticmethod
    def kind(v):
        return int(round(v["lid"]))

    def g(self, v):
        k, w, c = self.kind(v), v["wall"], v["lid_clear"]
        W, D = v["inner_w"] + 2 * w, v["inner_d"] + 2 * w
        r_in = max(0.5, v["corner_r"] - w)
        if k == 0:
            H = v["floor"] + v["inner_h"] + v["lid_t"]          # the lid sits between the walls, flush with the top
            z_lid = H - v["lid_t"]
        else:
            H = v["floor"] + v["inner_h"]
            z_lid = H
        gq = v["groove"]
        return {"k": k, "W": W, "D": D, "H": H, "r_in": r_in, "z_lid": z_lid, "c": c,
                "lid_w": v["inner_w"] + 2 * gq, "groove_w": v["inner_w"] + 2 * (gq + c),
                "lid_back": v["inner_d"] / 2 + gq, "skirt_w": v["inner_w"] - 2 * c, "skirt_d": v["inner_d"] - 2 * c,
                "xo": W + GAP}

    def hinge_dims(self, v):
        g = self.g(v)
        W, D, H, t, R, gp = g["W"], g["D"], g["H"], v["lid_t"], v["knuckle_r"], v["hinge_gap"]
        ya, za = D / 2 + R + gp, H + t - R          # hinge axis: behind the back wall, knuckle tops flush with the lid
        L = W - 2 * max(v["corner_r"], 3)
        kl = (L - 2 * gp) / 3
        return W, D, H, t, R, gp, ya, za, L, kl

    def back_setback(self, v):
        """Hinged lid: gap behind its skirt. Near the hinge the skirt's back face swings past the box's inner top edge,
        which sits sqrt(a² + b²) from the axis; the face must start at least that far out (see the legacy hinged_box)."""
        W, D, H, t, R, gp = self.hinge_dims(v)[:6]
        a, b = R + gp + v["wall"], R - t
        return v["lid_clear"] + (math.hypot(a, b) - a) + 0.15

    def front_setback(self, v):
        """Hinged lid: gap in front of its skirt. As the lid opens, the skirt's lower front edge (below the axis by dz,
        d in front of it) first moves forward, by at most hypot(d, dz) − d, before it rises clear of the front wall."""
        W, D, H, t, R, gp, ya, za = self.hinge_dims(v)[:8]
        d = ya + v["inner_d"] / 2
        dz = (za - H) + v["lip_h"]
        return max(v["lid_clear"], math.hypot(d, dz) - d + 0.15)

    def constraints(self, v):
        out = []
        for key in ("lid", "dividers", "label"):
            if abs(v[key] - round(v[key])) > 1e-9:
                out.append(RecipeError(f"{self.spec(key).label} must be a whole number", self.spec(key).feature, "Use whole numbers.", [key]))
        if out:
            return out
        g, k = self.g(v), self.kind(v)
        if v["corner_r"] < v["wall"] + 0.5:
            out.append(RecipeError("Corner radius is under the wall + 0.5 mm", "shell", "Raise the corner radius or thin the wall.",
                                   ["corner_r", "wall"]))
        if v["corner_r"] > min(g["W"], g["D"]) / 2 - 1:
            out.append(RecipeError("Corner radius is larger than the box", "shell", "Reduce the corner radius.", ["corner_r"]))
        if k == 0:
            if v["wall"] - v["groove"] - v["lid_clear"] < 1.2:
                out.append(RecipeError(f"The grooves leave {v['wall'] - v['groove'] - v['lid_clear']:.1f} mm of wall; 1.2 mm holds three lines",
                                       "groove", "Thicken the wall, or make the groove shallower.", ["wall", "groove", "lid_clear"]))
            if v["lid_t"] - v["groove"] < 1.0:
                out.append(RecipeError("The lid's bevelled edge is under 1 mm thick", "lid", "Thicken the lid or make the groove shallower.",
                                       ["lid_t", "groove"]))
        else:
            if v["lip_h"] > v["inner_h"] - 2:
                out.append(RecipeError("The skirt is deeper than the box", "lid_lip", "Shorten the skirt.", ["lip_h", "inner_h"]))
            if g["skirt_w"] - 2 * v["skirt_t"] < 6 or g["skirt_d"] - 2 * v["skirt_t"] < 6:
                out.append(RecipeError("The box is too small for a skirt", "lid_lip", "Enlarge the box or thin the skirt.", ["inner_w", "inner_d"]))
        if k == 2:
            W, D, H, t, R, gp, ya, za, L, kl = self.hinge_dims(v)
            if kl < 5:
                out.append(RecipeError("Knuckles are too short", "knuckles", "Widen the box or reduce the corner radius.", ["inner_w", "corner_r"]))
            if R - (v["pin_d"] / 2 + v["pin_clear"]) < 1.2:
                out.append(RecipeError("Knuckle wall around the pin is under 1.2 mm", "knuckles", "Raise the knuckle radius or use a thinner pin.",
                                       ["knuckle_r", "pin_d"]))
            if R < t:
                out.append(RecipeError("Knuckle radius is smaller than the lid thickness", "lid_knuckle", "Raise the knuckle radius.",
                                       ["knuckle_r", "lid_t"]))
            if v["inner_d"] - self.front_setback(v) - self.back_setback(v) < 2 * v["skirt_t"] + 6:
                out.append(RecipeError("The hinged lid's skirt has no room between its front and back reliefs", "lid_lip",
                                       "Make the box deeper or the skirt shallower.", ["inner_d", "lip_h"]))
            if za - R * 0.64 - (R + gp + R * 0.77 + 0.5) * 1.19 < v["floor"] + 2:
                out.append(RecipeError("The knuckle brackets reach below the box", "knuckles", "Make the box taller or the knuckles smaller.",
                                       ["inner_h", "knuckle_r"]))
        if v["label"] >= 0.5:
            room = (g["z_lid"] - v["lid_clear"] if k == 0 else g["H"]) - 4
            if v["label_h"] > room:
                out.append(RecipeError(f"The label recess is {v['label_h']:g} mm tall; the front has {max(room, 0):.0f} mm",
                                       "label", "Lower the label height or make the box taller.", ["label_h", "inner_h"]))
        return out

    # ---- build -----------------------------------------------------------------------------------------------------
    def build(self, v):
        g = self.g(v)
        k, W, D, H, w, c = g["k"], g["W"], g["D"], g["H"], v["wall"], g["c"]
        r = v["corner_r"]
        body = _rrect(W, D, H, r)
        body = chamfer(body.edges().group_by(Axis.Z)[0], FOOT)
        stages = [Stage("shell", body)]
        # cavity: rounded in plan, and along the floor
        cav = _rrect(v["inner_w"], v["inner_d"], H, g["r_in"], v["floor"])
        if v["scoop_r"] > 0.05:
            try:
                cav = fillet(cav.edges().group_by(Axis.Z)[0], min(v["scoop_r"], g["r_in"] - 0.1,
                                                                  v["inner_h"] / 3))
            except Exception:
                pass
        s = body - cav
        stages.append(Stage("cavity", s))

        n = int(round(v["dividers"]))
        if n:
            top = (g["z_lid"] - c - 0.6) if k == 0 else (H - v["lip_h"] - 0.6)
            pitch = v["inner_w"] / (n + 1)
            for i in range(1, n + 1):
                x = -v["inner_w"] / 2 + i * pitch
                s = s + Pos(x, 0, v["floor"] - 0.5) * Box(v["divider_t"], v["inner_d"] + 0.2, top - v["floor"] + 0.5, align=A)
            stages.append(Stage("dividers", s))

        if v["label"] >= 0.5:
            lw = min(0.62 * W, max(20.0, W - 2 * r - 8))
            zc = ((g["z_lid"] - c) if k == 0 else H) / 2 + 0.5
            dep = 0.6
            cut = Box(lw, dep + 1, v["label_h"], align=(Align.CENTER, Align.MAX, Align.CENTER))
            cut = chamfer(cut.edges().filter_by(Axis.X).group_by(Axis.Z)[-1].sort_by(Axis.Y)[-1:], dep)   # 45° roof, no ceiling
            s = s - Pos(0, -D / 2 + dep, zc) * cut
            stages.append(Stage("label", s))

        if k == 0:
            stages += self._sliding(v, g, s)
        elif k == 1:
            stages += self._press(v, g, s)
        else:
            stages += self._hinged(v, g, s)
        return stages

    # sliding lid ---------------------------------------------------------------------------------------------------
    def _slide_plate(self, v, g, grow: float, front_extra: float):
        """The lid (grow = 0), or the groove cutter (grow = clearance): a plate whose left, right and back top edges are
        bevelled at BEVEL° from horizontal, with the back corners rounded concentric with the box's outer corners.
        The cutter is the lid offset outward by `grow` everywhere. The bevel is a little steeper than 45° so the
        groove's roof (the same surface, facing down in the box) stays printable after tessellation."""
        gq, t = v["groove"], v["lid_t"]
        phi = math.radians(BEVEL)
        a0 = v["inner_w"] / 2 + gq                               # lid half width
        # lid bevel: from (a0, t - gq·tanφ) to (a0 - gq, t). Offset that line by `grow` along its outward normal and
        # cut it with the cutter's side x = a0 + grow and top z = t + grow.
        nx, nz = math.sin(phi), math.cos(phi)
        px, pz = a0 + grow * nx, t - gq * math.tan(phi) + grow * nz
        dx, dz = -math.cos(phi), math.sin(phi)                   # along the bevel, up and in
        z_side = pz + (a0 + grow - px) / dx * dz
        x_top = px + (t + grow - pz) / dz * dx
        run, rise = a0 + grow - x_top, t + grow - z_side
        hw = a0 + grow
        y0, y1 = -g["D"] / 2 - front_extra, v["inner_d"] / 2 + gq + grow
        rb = max(0.3, v["corner_r"] - v["wall"] + gq + grow)
        def plan(extra_front):
            b = Box(2 * hw, y1 - y0 + extra_front, 1, align=(Align.CENTER, Align.MIN, Align.MIN))
            b = Pos(0, y0 - extra_front, 0) * b
            b = fillet([e for e in b.edges().filter_by(Axis.Z) if e.center().Y > y1 - 1e-6], rb)
            return b.faces().sort_by(Axis.Z)[-1]                  # normal +Z
        low = Pos(0, 0, -grow - 1) * extrude(plan(0), z_side + grow)
        top = extrude(Pos(0, 0, z_side - 1) * plan(rise + 2), rise, taper=90 - BEVEL)
        top = top & Pos(0, y0, z_side - 1) * Box(4 * hw, y1 - y0 + 10, rise + 2, align=(Align.CENTER, Align.MIN, Align.MIN))
        return low + top

    def _sliding(self, v, g, s):
        c, z0 = g["c"], g["z_lid"]
        cutter = Pos(0, 0, z0) * self._slide_plate(v, g, c, 2.0)
        s = s - cutter
        # the rounded front corners above the groove floor belong to the lid: the box stops square behind them, so no
        # groove runs out through a curved corner, and the lid's front completes the box's outline when it is closed
        r, D, W = v["corner_r"], g["D"], g["W"]
        s = s - Pos(0, -D / 2 - 1, z0 - c) * Box(W + 2, r + 1, 50, align=(Align.CENTER, Align.MIN, Align.MIN))
        out = [Stage("groove", s)]
        cap = _rrect(W, D, v["lid_t"], r) & Pos(0, -D / 2 - 1, -1) * Box(W + 2, r - c + 1, v["lid_t"] + 2,
                                                                         align=(Align.CENTER, Align.MIN, Align.MIN))
        lid = self._slide_plate(v, g, 0.0, 0.0) + cap
        # soften the front top edge, then a shallow finger dish near the front
        try:
            fe = [e for e in lid.edges() if e.center().Z > v["lid_t"] - 1e-6 and e.bounding_box().size.Z < 1e-6
                  and e.center().Y < -D / 2 + r - c - 1e-3]
            lid = fillet(fe, min(0.8, v["lid_t"] / 3))
        except Exception:
            pass
        try:                                                  # first-layer flare: only on the cap's outline
            lid = chamfer([e for e in lid.edges().group_by(Axis.Z)[0] if e.center().Y < -D / 2 + r - c - 1e-3
                           and abs(e.center().Y - (-D / 2 + r - c)) > 1e-3], 0.3)
        except Exception:
            pass
        place = Pos(g["xo"], 0, 0)
        s = s + place * lid
        out.append(Stage("lid", s))
        depth = min(1.0, v["lid_t"] - 1.2)
        if depth > 0.2:
            rs = 14.0
            dish = Pos(g["xo"], -g["D"] / 2 + 11, v["lid_t"] + rs - depth) * Rot(90, 0, 0) * Sphere(rs)   # poles to the sides: no pole in the dish
            s = s - dish
            out.append(Stage("grip", s))
        return out

    # press-on lid ----------------------------------------------------------------------------------------------------
    def _lid_plate(self, v, g):
        """The press-on and hinged lid plate as printed: top face down on the plate, outline the box's."""
        t = v["lid_t"]
        p = _rrect(g["W"], g["D"], t, v["corner_r"])
        p = chamfer(p.edges().group_by(Axis.Z)[0], FOOT)       # the lid's top edge in use
        return p

    def _skirt(self, v, g, y_front, y_back, z):
        """A rounded-rectangle skirt from z to z + lip_h (print frame), outer edge chamfered for a lead-in."""
        sw = g["skirt_w"]
        d = y_back - y_front
        rr = max(0.5, g["r_in"] - g["c"])
        outer = Pos(0, (y_front + y_back) / 2, 0) * _rrect(sw, d, v["lip_h"], rr)
        inner = Pos(0, (y_front + y_back) / 2, 0) * _rrect(sw - 2 * v["skirt_t"], d - 2 * v["skirt_t"], v["lip_h"] + 2,
                                                            max(0.3, rr - v["skirt_t"]), -1)
        sk = outer - inner
        e_out = [e for e in sk.edges().group_by(Axis.Z)[-1]
                 if abs(e.position_at(0.5).X) > sw / 2 - v["skirt_t"] / 2 - 1e-6
                 or abs(e.position_at(0.5).Y - (y_front + y_back) / 2) > d / 2 - v["skirt_t"] / 2 - 1e-6]
        try:
            sk = chamfer(e_out, 0.4)                          # lead-in on the outside of the skirt's free edge
        except Exception:
            pass
        return Pos(0, 0, z) * sk

    def _press(self, v, g, s):
        xo, t = g["xo"], v["lid_t"]
        s = s + Pos(xo, 0, 0) * self._lid_plate(v, g)
        out = [Stage("lid", s)]
        sk = self._skirt(v, g, -g["skirt_d"] / 2, g["skirt_d"] / 2, t - 0.01)
        s = s + Pos(xo, 0, 0) * sk
        out.append(Stage("lid_lip", s))
        return out

    # hinged lid --------------------------------------------------------------------------------------------------------
    def lid_to_print(self, v):
        g = self.g(v)
        return Pos(g["xo"], 0, 0) * Rot(180, 0, 0) * Pos(0, 0, -(g["H"] + v["lid_t"]))

    def _hinged(self, v, g, s):
        W, D, H, t, R, gp, ya, za, L, kl = self.hinge_dims(v)
        out = []
        along = Rot(0, 90, 0)
        # a bracket under each box knuckle: a line at 50° from horizontal, tangent to the knuckle's lower back, down to
        # the wall. Everything under the knuckle then faces down by less than 45°.
        b = math.radians(50)
        tp = (ya + R * math.sin(b), za - R * math.cos(b))                      # tangent point
        zw = tp[1] - (tp[0] - (D / 2 - 0.5)) * math.tan(b)
        for x0 in (-L / 2, L / 2 - kl):
            xc = x0 + kl / 2
            br = Plane.YZ * Polygon((D / 2 - 0.5, za), (ya, za), tp, (D / 2 - 0.5, zw), align=None)
            s = s + Pos(xc, 0, 0) * extrude(br, kl / 2, both=True) + Pos(xc, ya, za) * along * Cylinder(R, kl)
        out.append(Stage("knuckles", s))

        T = self.lid_to_print(v)
        plate = Pos(0, 0, H) * _rrect(W, D, t, v["corner_r"])
        plate = chamfer(plate.edges().group_by(Axis.Z)[-1], FOOT)  # the lid's top edge (on the plate when printed)
        s = s + T * plate
        out.append(Stage("lid", s))
        y_front = -v["inner_d"] / 2 + self.front_setback(v)
        y_back = v["inner_d"] / 2 - self.back_setback(v)
        # printed upside down, so the skirt's assembled span [y_front, y_back] is [-y_back, -y_front] on the plate
        s = s + Pos(g["xo"], 0, 0) * self._skirt(v, g, -y_back, -y_front, t - 0.01)
        out.append(Stage("lid_lip", s))
        kn = Pos(0, ya, za) * along * Cylinder(R, kl) + Pos(0, ya, za) * Box(kl, 2 * R, R, align=A) \
            + Pos(0, (D / 2 - 1 + ya) / 2, H) * Box(kl, ya - (D / 2 - 1), t, align=A)
        s = s + T * kn
        out.append(Stage("lid_knuckle", s))
        hd = v["pin_d"] + 2 * v["pin_clear"]
        s = s - Pos(0, ya, za) * teardrop(hd, L + 2, Plane.YZ)            # box knuckles: roof up as printed
        pa = T * Pos(0, ya, za)
        s = s - Pos(pa.position.X, pa.position.Y, pa.position.Z) * teardrop(hd, kl + 2, Plane.YZ)   # lid knuckle, as printed
        out.append(Stage("pin_hole", s))
        return out

    # ---- interfaces ------------------------------------------------------------------------------------------------
    def derived(self, v):
        g, k = self.g(v), self.kind(v)
        out = [{"key": "outer", "label": "Outside size", "value": g["W"], "unit": "mm", "feature": "shell",
                "formula": f"inner + 2 × wall; {g['W']:.1f} × {g['D']:.1f} × {g['H'] + (v['lid_t'] if k else 0):.1f} mm closed",
                "interface": False}]
        if k == 0:
            out += [{"key": "groove_w", "label": "Groove width", "value": g["groove_w"], "unit": "mm", "feature": "groove",
                     "formula": "inner width + 2 × (groove + clearance)", "interface": True},
                    {"key": "lid_w", "label": "Sliding lid width", "value": g["lid_w"], "unit": "mm", "feature": "lid",
                     "formula": "inner width + 2 × groove", "interface": True}]
        else:
            out.append({"key": "skirt_w", "label": "Skirt outside width", "value": g["skirt_w"], "unit": "mm", "feature": "lid_lip",
                        "formula": "inner width − 2 × clearance", "interface": True})
        if k == 2:
            L, kl = self.hinge_dims(v)[8:]
            out += [{"key": "hole_d", "label": "Pin hole", "value": v["pin_d"] + 2 * v["pin_clear"], "unit": "mm", "feature": "pin_hole",
                     "formula": "pin + 2 × clearance", "interface": True},
                    {"key": "pin_len", "label": "Pin length", "value": L, "unit": "mm", "feature": "pin_hole",
                     "formula": "outer width − 2 × max(corner radius, 3)", "interface": False},
                    {"key": "skirt_front", "label": "Skirt front relief", "value": self.front_setback(v), "unit": "mm",
                     "feature": "lid_lip", "formula": "the skirt's lower front edge swings forward as the lid opens", "interface": False},
                    {"key": "skirt_back", "label": "Skirt back relief", "value": self.back_setback(v), "unit": "mm",
                     "feature": "lid_lip", "formula": "clearance + swing past the back wall's inner edge + 0.15", "interface": False}]
        return out

    def measure(self, v, fb):
        g, k = self.g(v), self.kind(v)
        def span_x(faces, lo=-1e9, hi=1e9):
            xs = [f.center().X for f in faces if f.geom_type.name == "PLANE" and abs(abs(f.normal_at(f.center()).X) - 1) < 1e-6
                  and lo < f.center().X < hi]
            return max(xs) - min(xs) if len(xs) >= 2 else None
        out = []
        half = g["W"] / 2 + GAP / 2
        if k == 0:
            a = span_x(fb.get("groove", []), hi=half)
            if a is not None:
                out.append({"key": "groove_w", "label": "Groove width", "intended": g["groove_w"], "modelled": a})
            b = span_x([f for f in fb.get("lid", []) + fb.get("grip", []) if f.center().Y > -g["D"] / 2 + v["corner_r"]], lo=half)
            if b is not None:
                out.append({"key": "lid_w", "label": "Sliding lid width", "intended": g["lid_w"], "modelled": b})
        else:
            sk = [f for f in fb.get("lid_lip", []) if f.geom_type.name == "PLANE"]
            xs = [f.center().X - g["xo"] for f in sk if abs(abs(f.normal_at(f.center()).X) - 1) < 1e-6]
            if xs:
                out.append({"key": "skirt_w", "label": "Skirt outside width", "intended": g["skirt_w"], "modelled": 2 * max(abs(x) for x in xs)})
        if k == 2:
            rs = [f.radius for f in fb.get("pin_hole", []) if f.geom_type.name == "CYLINDER"]
            if rs:
                out.append({"key": "hole_d", "label": "Pin hole", "intended": v["pin_d"] + 2 * v["pin_clear"], "modelled": 2 * min(rs)})
        return out

    def assembly(self, v):
        g, k = self.g(v), self.kind(v)
        xo, H, t = g["xo"], g["H"], v["lid_t"]
        box = Part("body", "Box", 0, note="Set the box on the bench, open side up.")
        if k == 0:
            travel = g["lid_back"] + g["D"] / 2
            return Assembly(parts=[box, Part("lid", "Sliding lid", 1, move=(-xo, 0, g["z_lid"]), explode=(0, -travel * 0.7, 12),
                                             note="Slide the lid into the grooves from the front, bevelled side up.")],
                            joints=[slide("lid", (0, -1, 0), (0, travel * 0.9), label="Lid slide")])
        if k == 1:
            return Assembly(parts=[box, Part("lid", "Lid", 1, move=(-xo, 0, H + t), rotate=(180, 0, 0), explode=(0, 0, v["lip_h"] + 22),
                                             note="Press the lid on: the skirt goes inside the walls.")],
                            joints=[slide("lid", (0, 0, 1), (0, v["lip_h"] + 2), label="Lid lift")])
        W, D, H, t, R, gp, ya, za, L, kl = self.hinge_dims(v)
        n = int(round(v["open_deg"] / 5)) + 1
        from .assembly import Access
        return Assembly(
            parts=[box, Part("lid", "Lid", 1, move=(-xo, 0, H + t), rotate=(180, 0, 0), explode=(0, 0, v["lip_h"] + 22),
                             note="Lower the lid on: the skirt goes into the box, the lid knuckle between the two box knuckles.")],
            joints=[hinge("lid", (-1, 0, 0), (0, ya, za), (0, v["open_deg"]), samples=n, label="Lid hinge")],
            hardware=[Hardware("Hinge pin", f"Ø{v['pin_d']:g} × {L:.0f} mm", 1, "1.75 mm filament offcut, or steel rod of the same diameter",
                               "Push the pin through the three knuckles from the left and trim it flush.", after="lid",
                               access=(Access(at=(-L / 2, ya, za), axis=(1, 0, 0), tool_d=v["pin_d"], length=L),))])
