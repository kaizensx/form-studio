"""1/4 inch square-drive ratchet wrench: a sawtooth wheel from craft.ratchet with a 6.35 mm drive, a pawl drawn from
the tooth gap it sits in, a spring pocket, a printed pivot pin and a screwed cover, in an ergonomic flat handle.
Four printed parts declared as an assembly with the wheel's ratchet step. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Circle, Cylinder, Kind, Pos, Rot, extrude, offset

from form import craft, parts
from form.recipes.base import (Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage, hinge)

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Ratchet wrench, 1/4 inch drive",
    "category": "assembly",
    "tags": ["ratchet", "wrench", "spanner", "pawl", "socket", "square drive", "1/4", "6.35", "tool", "handle",
             "mechanism", "assembly", "spring", "cover", "ergonomic", "sawtooth"],
    "techniques": ["craft.ratchet sawtooth wheel (radial locking faces)", "pawl tip drawn as the tooth gap offset by "
                   "a clearance, arm leaning out past the tooth tips", "pocket = pawl swept through its lift angle, "
                   "grown by a clearance (2D offset)", "handle plan as a spline outline, big edge radii",
                   "wheel printed disc-down and turned over by assembly()", "hinge(step=360/teeth) for the wheel, "
                   "hinge for the pawl's lift, Mate pin and contact"],
    "lessons": [
        "Standard first: a 1/4 inch drive is a 6.35 mm square (ISO 1174 / ASME B107.4); chamfer its end and corners so "
        "sockets start, and leave room for a detent ball. A printed drive is for light work; the geometry is the lesson.",
        "Draw the pawl from the tooth gap it engages: its tip face lies on the locking face (offset by the clearance), "
        "its inner flank follows the tooth's slope, and its arm leans outward past the tooth tips. The locking load then "
        "runs along the arm into the pivot (the pawl is a strut, not a lever), and the slope lifts it when the wheel "
        "turns the free way.",
        "The pawl's lift is computed (tooth height / arm length) and its pocket is the pawl swept through that angle, "
        "grown by a clearance. A pocket drawn by eye either jams the pawl or lets it fall out of the tooth.",
        "A ratchet wheel looks the same every tooth: declare its joint with step = 360 / teeth, so the assembly check "
        "tests the positions it can rest at instead of reporting the pawl it is meant to hit.",
        "Hand tools get big radii: 3.5 mm on the handle's top edges, a waist behind the head and a swell under the palm; "
        "the spring and the cover screws are bought parts in the BOM, not printed compromises.",
    ],
}


def _rot2(p, a):
    c, s = math.cos(a), math.sin(a)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


class Design(Recipe):
    title, summary = "Ratchet wrench", "1/4\" drive ratchet: sawtooth wheel, sprung pawl, cover and an ergonomic handle."
    solids = 4
    params = [
        Param("teeth", "Wheel teeth", 18, 12, 30, 1, "", "form", "wheel", "More teeth = smaller swing to re-engage."),
        Param("wheel_od", "Wheel diameter", 26, 22, 34, 0.5, "mm", "form", "wheel"),
        Param("tooth_h", "Tooth height", 1.8, 1.2, 2.5, 0.1, "mm", "form", "wheel"),
        Param("drive", "Square drive", 6.35, 6.35, 6.35, 0.01, "mm", "brief", "drive",
              "1/4 inch drive, ISO 1174-1 / ASME B107.4.", "specified"),
        Param("length", "Overall length", 150, 120, 200, 1, "mm", "form", "handle"),
        Param("clearance", "Running clearance", 0.3, 0.2, 0.5, 0.05, "mm", "interface", "pawl",
              "Between separately printed moving parts."),
    ]
    features = [Feature("handle", "Handle", "structure"), Feature("pocket", "Wheel and pawl pocket", "interface"),
                Feature("wheel", "Ratchet wheel", "structure"), Feature("drive", "1/4\" square drive", "interface"),
                Feature("pawl", "Pawl", "structure"), Feature("cover", "Cover", "structure")]

    FLOOR, T, COVER, LEDGE, WALL = 3.0, 6.0, 2.0, 4.5, 4.0

    def constraints(self, v):
        if v["tooth_h"] > v["wheel_od"] * math.pi / v["teeth"] * 0.7:
            return [RecipeError("The teeth are taller than they are wide", "wheel", "Use fewer teeth or lower ones.",
                                ["teeth", "tooth_h"])]
        return []

    # ---- geometry in the assembled frame (wheel centre at the origin, handle along +X) ------------------------
    def _layout(self, v):
        n, R, th, g = int(v["teeth"]), v["wheel_od"] / 2, v["tooth_h"], v["clearance"]
        d = 2 * math.pi / n
        A, C = (R - th, 0.0), (R * math.cos(d), R * math.sin(d))
        L_ac = math.hypot(C[0] - A[0], C[1] - A[1])
        u = ((C[0] - A[0]) / L_ac, (C[1] - A[1]) / L_ac)            # up the tooth's slope
        nrm = (u[1], -u[0])                                          # off the slope, into the gap
        # tip face on the locking face (y = 0), offset by g; inner flank parallel to the slope, offset by g
        s1 = (g - (A[1] + g * nrm[1])) / u[1]
        p1 = (A[0] + g * nrm[0] + s1 * u[0], g)
        p2 = (R + 1.2, g)
        q = (A[0] + g * nrm[0] + L_ac * u[0], A[1] + g * nrm[1] + L_ac * u[1])
        tang = (-math.sin(d), math.cos(d))
        dd = _rot2(tang, -math.radians(22))                          # arm leans 22 deg outward of the tip circle
        nd = (dd[1], -dd[0])
        w, arm = 5.0, 11.0
        P = (q[0] + arm * dd[0] + w / 2 * nd[0], q[1] + arm * dd[1] + w / 2 * nd[1])
        poly = [p1, p2, (P[0] + w / 2 * nd[0], P[1] + w / 2 * nd[1]), (P[0] - w / 2 * nd[0], P[1] - w / 2 * nd[1]), q]
        tip = ((p1[0] + p2[0]) / 2, g)
        lift = (th + 0.6) / math.hypot(tip[0] - P[0], tip[1] - P[1])  # radians to clear a tooth
        # sign: the lift turns the tip outward (+X)
        t1 = _rot2((tip[0] - P[0], tip[1] - P[1]), lift)
        sgn = 1 if t1[0] + P[0] > tip[0] else -1
        # turn the whole mechanism so the pawl sits on the handle's axis
        psi = -math.atan2(P[1], P[0])                                # pivot on the handle's axis
        return dict(n=n, R=R, th=th, g=g, poly=poly, P=P, w=w, lift=sgn * math.degrees(lift), psi=math.degrees(psi))

    def _pawl2d(self, L):
        pin_r = 1.6
        f = craft.polygon_profile(L["poly"]) + Pos(*L["P"], 0) * Circle(L["w"] / 2 + 0.6)
        return f, pin_r

    def _heights(self, v):
        z_w = self.FLOOR + 0.3                                       # wheel and pawl underside
        H = z_w + self.T + 0.4 + self.COVER + 0.2                    # cover sits 0.2 below the top
        return z_w, H

    def build(self, v):
        L = self._layout(v)
        R, g, n = L["R"], L["g"], L["n"]
        z_w, H = self._heights(v)
        turn = Rot(0, 0, L["psi"])
        Px, Py = L["P"]
        pawl2d, pin_r = self._pawl2d(L)
        # --- snippet: pocket = the pawl swept through its lift angle, grown by the clearance, plus the wheel's circle
        swept = [Pos(Px, Py, 0) * Rot(0, 0, a) * Pos(-Px, -Py, 0) * pawl2d
                 for a in (0, L["lift"] / 2, L["lift"] * 1.15)]
        pocket2d = Circle(R + g)
        for s in swept:
            pocket2d = pocket2d + offset(s, g, kind=Kind.ARC)
        # --- end snippet
        recess2d = offset(pocket2d, self.LEDGE, kind=Kind.ARC)
        # --- snippet: the whole plan as ONE closed spline (head arc, waist, palm swell, round end): one smooth side
        # face, so the 4 mm hand radius goes on in one pass; a head made by offsetting the pocket would give dozens of
        # small arcs that fillet slowly and badly
        Lt = v["length"]
        Rh = R + g + self.LEDGE + self.WALL                              # head radius round the wheel
        Pd = math.hypot(Px, Py)
        hl = L["w"] / 2 + 0.6 + g + self.LEDGE + self.WALL + 1.0         # half-width over the pawl's lobe
        xn = max(Rh, Pd) + 9
        beam = [(Lt, 0), (Lt - 9, 11.5), (0.8 * Lt, 12.5), (0.55 * Lt, 11.5), (max(0.3 * Lt, xn + 12), 10.5),
                (xn, hl)]
        arc = [(Rh * math.cos(math.radians(a)), Rh * math.sin(math.radians(a))) for a in range(60, 301, 30)]
        outline = beam + arc + [(x, -y) for x, y in reversed(beam[1:])]
        plan = craft.spline_profile(outline)
        if (turn * recess2d - plan).area > 0.05:
            raise RecipeError("The handle's outline does not cover the head's pocket", "handle",
                              "Use a smaller wheel or a longer handle.", ["wheel_od", "length"])
        handle = extrude(plan, H)
        handle = craft.safe_fillet(handle, handle.edges().group_by(Axis.Z)[-1], 3.5)
        handle = craft.attempt("bed chamfer", [("1 mm", lambda: handle.chamfer(1.0, None, handle.edges().group_by(Axis.Z)[0])),
                                               ("sharp", lambda: handle)], "", ["length"])
        # --- end snippet
        handle = handle - Pos(Lt - 11, 0, -1) * Cylinder(4, H + 2, align=BOTTOM)
        stages = [Stage("handle", handle)]
        # pocket, cover recess, drive hole through the floor, pivot pin, spring bore, cover screw pilots
        handle = handle - Pos(0, 0, H - self.COVER - 0.2) * extrude(turn * recess2d, 5)
        handle = handle - Pos(0, 0, self.FLOOR) * extrude(turn * pocket2d, H)
        j_r = 5.5
        handle = handle - Pos(0, 0, -1) * Cylinder(j_r + g, H, align=BOTTOM)
        pin = Pos(0, 0, self.FLOOR - 0.5) * turn * Pos(Px, Py, 0) * Cylinder(pin_r, H - self.COVER - 0.2 - 0.4 - self.FLOOR + 0.5,
                                                                             align=BOTTOM)
        handle = handle + pin
        # spring: a 3 mm bore from the pocket wall, square to the pawl's outer edge, at mid height
        p2, pe = L["poly"][1], L["poly"][2]
        mx, my = (p2[0] + pe[0]) / 2, (p2[1] + pe[1]) / 2
        ex, ey = pe[0] - p2[0], pe[1] - p2[1]
        el = math.hypot(ex, ey)
        out = (ey / el, -ex / el)                                  # outward normal of the pawl's outer edge
        ang = math.degrees(math.atan2(out[1], out[0]))
        bore = Pos(mx, my, z_w + self.T / 2) * Rot(0, 0, ang) * Rot(0, 90, 0) * Cylinder(1.7, 5.5, align=BOTTOM)
        handle = handle - turn * bore
        pil = parts.self_tap_pilot("M3", 6).shape
        screws = self._screws(L, v)
        for x, y in screws:
            handle = handle - Pos(x, y, H - self.COVER - 0.2) * pil
        stages.append(Stage("pocket", handle))

        # wheel, modelled as it sits (disc underside at z = 0, journal and drive below), printed disc-down
        rt = craft.ratchet(teeth=n, od=2 * R, tooth_h=L["th"], thickness=self.T, bore=0)
        wheel = turn * rt.shapes["wheel"]
        wheel = wheel + Pos(0, 0, -(self.FLOOR + 0.3 + 0.2)) * Cylinder(j_r, self.FLOOR + 0.3 + 0.4, align=BOTTOM)
        layout = Pos(Lt * 0.25, -38, 0)
        flip = lambda s: layout * Pos(0, 0, self.T) * Rot(180, 0, 0) * s
        body = handle + flip(wheel)
        stages.append(Stage("wheel", body))
        # 1/4" square drive with chamfered corners and end, and a detent-ball dimple
        a = v["drive"]
        sq = Box(a, a, 8.0, align=(Align.CENTER, Align.CENTER, Align.MAX))
        sq = craft.attempt("drive corners", [("0.6 mm chamfer", lambda: sq.chamfer(0.6, None, sq.edges().filter_by(Axis.Z))),
                                             ("square", lambda: sq)], "", ["drive"])
        sq = craft.attempt("drive lead-in", [("0.8 mm chamfer", lambda: sq.chamfer(0.8, None, sq.edges().group_by(Axis.Z)[0])),
                                             ("square", lambda: sq)], "", ["drive"])
        sq = sq - Pos(a / 2 + 0.9, 0, -4.5) * Cylinder(1.6, 3, rotation=(0, 90, 0))
        drive = Pos(0, 0, -(self.FLOOR + 0.3) + 0.05) * sq
        wheel = wheel + drive
        body = handle + flip(wheel)
        stages.append(Stage("drive", body))
        # pawl, printed flat beside the wheel
        pawl = extrude(pawl2d, self.T) - Pos(Px, Py, -1) * Cylinder(pin_r + 0.25, self.T + 2, align=BOTTOM)
        pawl = craft.safe_fillet(pawl, pawl.edges().group_by(Axis.Z)[-1], 0.5)
        pawl_at = Pos(Lt * 0.5 - Px, -38 - Py, 0)
        body = body + pawl_at * turn * pawl
        stages.append(Stage("pawl", body))
        # cover: the recess outline less a clearance, countersunk M3 screws
        cover = extrude(offset(recess2d, -0.2, kind=Kind.ARC), self.COVER)
        cover = craft.safe_fillet(cover, cover.edges().group_by(Axis.Z)[-1], 0.6)
        cs = parts.screw_clearance("M3", self.COVER, head="countersunk", fit="close")
        cover = turn * cover
        for x, y in screws:
            cover = cover - Pos(x, y, self.COVER) * cs.shape
        cover_at = Pos(Lt * 0.8, -38, 0)
        body = body + cover_at * cover
        stages.append(Stage("cover", body))
        self._places = dict(wheel=(Lt * 0.25, -38), pawl=pawl_at, cover=(Lt * 0.8, -38))
        return parts.checked(stages)

    def _screws(self, L, v):
        """Two cover screws in the middle of the ledge: behind the wheel and beyond the pawl, on the handle axis."""
        R = L["R"]
        far = max(max(math.hypot(*p) for p in L["poly"]), math.hypot(*L["P"]) + L["w"] / 2 + 0.6)
        return [(-(R + L["g"] + self.LEDGE / 2), 0.0), (far + L["g"] + self.LEDGE / 2, 0.0)]

    def derived(self, v):
        L = self._layout(v)
        return [{"key": "index", "label": "Ratchet swing to the next tooth", "value": round(360 / L["n"], 2),
                 "unit": "deg", "feature": "wheel", "formula": "360 / teeth", "interface": False},
                {"key": "pawl_lift", "label": "Pawl lift to clear a tooth", "value": round(abs(L["lift"]), 2), "unit": "deg",
                 "feature": "pawl", "formula": "(tooth height + 0.6) / tip-to-pivot distance", "interface": True},
                {"key": "drive", "label": "Square drive across flats", "value": v["drive"], "unit": "mm", "feature": "drive",
                 "formula": "1/4 inch, ISO 1174-1 (specified)", "interface": True}]

    def assembly(self, v):
        L = self._layout(v)
        z_w, H = self._heights(v)
        Lt = v["length"]
        th = math.radians(L["psi"])
        Px, Py = _rot2(L["P"], th)
        wx, wy = Lt * 0.25, -38
        px, py = Lt * 0.5 - L["P"][0], -38 - L["P"][1]
        cx, cy = Lt * 0.8, -38
        # a point inside each printed part (print frame)
        pawl_pt = _rot2(((L["poly"][0][0] + L["poly"][1][0]) / 2, L["g"] + 1.0), th)
        return Assembly(
            parts=[Part("handle", "Handle", (Lt * 0.6, 0, 1.0), note="Lay the handle down, pocket up."),
                   Part("wheel", "Ratchet wheel", (wx, wy, 1.0), move=(-wx, wy, z_w + self.T), rotate=(180, 0, 0),
                        explode=(0, 0, 30), note="Drop the wheel in, drive first, through the floor."),
                   Part("pawl", "Pawl", (px + pawl_pt[0], py + pawl_pt[1], 1.0), move=(-px, -py, z_w),
                        explode=(0, 0, 45), note="Put the spring in its bore, then the pawl on its pin against it."),
                   Part("cover", "Cover", (cx + 0.0, cy + 0.0, 1.0), move=(-cx, -cy, H - self.COVER - 0.2),
                        explode=(0, 0, 60), note="Screw the cover on.")],
            joints=[hinge("wheel", (0, 0, 1), (0, 0, 0), (-360 / L["n"] * 3, 0), 4, parent="handle",
                          step=360 / L["n"], id="ratchet", label="Ratchet (free way)"),
                    hinge("pawl", (0, 0, 1), (Px, Py, 0), (min(0, L["lift"]), max(0, L["lift"])), 5,
                          parent="handle", id="pawl_lift", label="Pawl lift")],
            mates=[Mate("pawl", "handle", "pin", 0.25, "Pawl on its pivot pin"),
                   Mate("cover", "handle", "contact", 0.0, "Cover on its ledge")],
            hardware=[Hardware("Compression spring", "3 x 8 mm, 0.3 mm wire", 1, "stock", "Presses the pawl into the "
                               "teeth.", after="pawl"),
                      Hardware("M3 countersunk screw", "M3 x 6", 2, "ISO 10642", "Fix the cover.", after="cover")])

    def appearance(self, v):
        return [{"features": ["wheel", "drive", "pawl"], "finish": "metal", "color": "#a9b0b7"},
                {"features": ["handle", "pocket", "cover"], "finish": "matte", "color": "#c0392b"}]
