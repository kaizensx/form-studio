"""Cable clip: a row of snap-in channels for cables of a measured diameter, on a stick-on or screw-down base, or on a
clamp that pushes onto the edge of a desk.

Each channel is a round bore slightly larger than the cable with an opening narrower than it at the top. Its two
lips are fingers: relief slots between neighbouring channels let each lip bend on its own, so a cable pushes in and
stays. The snap check is a beam estimate of the strain in the stiffest lip while the cable passes; it ignores the
cable's jacket squashing, which makes the real push easier.

Print orientation, so nothing needs support:
  base   on its base; the channel roofs are only the bore above the opening, and the opening is kept wide enough
         that the bore never overhangs more than 50° (so it prints clean).
  desk   on its side: the whole clamp is one profile, channels run straight up.
"""
from __future__ import annotations

import math

from build123d import (Align, Axis, Box, Circle, Cylinder, Plane, Polygon, Pos, Rectangle, Rot, chamfer, extrude, fillet)

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import countersink

A = (Align.CENTER, Align.CENTER, Align.MIN)
RELIEF = 1.2          # gap between neighbouring channels' C-rings
FREE = 40.0           # each C-ring is free to flex from this far below its middle (degrees); its outside faces down
                      # at most this much there, so it still prints without support
MAX_ROOF = 50.0       # the bore's roof may face down at most this far past vertical (degrees)
E_MPA = 3500.0        # assumed modulus for the clamp-force estimate (PLA is often quoted at 3.5 GPa)


def foot(shape, w: float = 0.3, h: float = 0.5):
    """Chamfer the edges on the print plate, w in and h up: steeper than 45°, so the faceted chamfer round a curved
    edge never reads as an overhang, and it still hides the first layer's flare."""
    z0 = shape.bounding_box().min.Z
    cs = [f.center() for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
          and f.normal_at().Z < -0.999]
    for c in cs:
        try:
            f = min((f for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
                     and f.normal_at().Z < -0.999), key=lambda f: (f.center() - c).length)
            shape = chamfer(f.edges(), length=w, length2=h, reference=f)
        except Exception:
            pass
    return shape


class CableClip(Recipe):
    id = "cable_organizer"
    title = "Cable organizer"
    summary = ("Snap-in channels for cables of a measured diameter, on a stick-on or screw-down base or a clamp for the "
               "edge of a desk. Each lip is a finger that bends on its own.")
    category = "Wall & desk"
    tags = ("cable", "cable management", "organizer", "desk", "clip", "wire", "adhesive", "clamp")
    fit = {"cavity": "channel_d", "mating": "cable_d", "clearance": "cable_clear",
           "label": "Channel ↔ cable", "per_side": True, "window": [0.0, 0.8]}

    params = [
        Param("mount", "Mount", 0, 0, 1, 1, "", "form", "base",
              "0 = flat base (double-sided tape, or a screw with Screw tab), 1 = clamp that pushes onto a desk edge."),
        Param("cables", "Cables", 3, 1, 8, 1, "", "brief", "channels", "How many channels, side by side."),
        Param("cable_d", "Cable diameter", 6.0, 2.0, 16.0, 0.05, "mm", "brief", "channels",
              "Measure it with calipers across the jacket. USB-C and Lightning leads are about 3–4 mm, laptop chargers "
              "about 5–6 mm, mains leads about 7–8 mm."),
        Param("cable_clear", "Channel clearance / side", 0.15, -0.2, 0.6, 0.05, "mm", "interface", "channels",
              "Gap round the cable in its bore. Negative grips it."),
        Param("snap", "Opening / cable", 0.82, 0.6, 0.95, 0.01, "", "interface", "channels",
              "Width of the opening as a fraction of the cable. Smaller holds harder and pushes in harder."),
        Param("length", "Clip length", 12, 6, 40, 0.5, "mm", "form", "base", "Along the cables."),
        Param("ring", "Ring wall", 1.6, 1.3, 3.0, 0.1, "mm", "form", "fingers",
              "Wall of the C round each cable. Thinner snaps in more easily; 1.3 mm is the thinnest that prints three clean lines."),
        Param("base_t", "Base thickness", 2.0, 1.2, 6, 0.1, "mm", "form", "base", "Under the bores."),
        Param("screw", "Screw tab", 0, 0, 1, 1, "", "form", "screw", "Base mount: 1 = a tab with a countersunk screw hole."),
        Param("screw_d", "Screw diameter", 3.5, 2.0, 5.0, 0.1, "mm", "brief", "screw", "Shank of the screw (wood screw, #6 ≈ 3.5 mm)."),
        Param("desk_t", "Desk thickness", 25, 10, 60, 0.1, "mm", "brief", "clamp",
              "Desk clamp: measure the desk top's edge with calipers or a ruler."),
        Param("grip", "Grip / side", -0.2, -0.6, 0.5, 0.05, "mm", "interface", "clamp",
              "Desk clamp: gap between each pad and the desk. Negative = interference, so the clamp springs onto the desk."),
        Param("jaw", "Jaw length", 22, 12, 50, 0.5, "mm", "form", "clamp", "Desk clamp: how far the jaws reach over the desk."),
        Param("jaw_t", "Jaw thickness", 3.6, 2.4, 8, 0.1, "mm", "form", "clamp"),
        Param("strain_allow", "Allowed strain", 3.0, 1.0, 8.0, 0.1, "%", "process", "fingers",
              "Strain the lips may see while a cable snaps in. PLA yields at roughly 3–4 %, PETG around 4–6 % (assumed)."),
    ]
    features = [
        Feature("base", "Base", "structure"),
        Feature("channels", "Cable channels", "interface", "Round bores a little larger than the cable."),
        Feature("fingers", "Snap lips", "interface", "The C round each cable, free to flex down to 40° below its middle."),
        Feature("screw", "Screw tab", "access"),
        Feature("clamp", "Desk clamp", "interface", "Two jaws with flat pads that spring onto the desk edge."),
        Feature("soften", "Edges", "finish"),
    ]

    # ---- helpers ------------------------------------------------------------------------------------------------
    def g(self, v) -> dict:
        n = int(round(v["cables"]))
        cd = v["cable_d"] + 2 * v["cable_clear"]
        R, t = cd / 2, v["ring"]
        w = v["snap"] * v["cable_d"]
        pitch = 2 * (R + t) + RELIEF
        ys = [(i - (n - 1) / 2) * pitch for i in range(n)]
        zc = v["base_t"] + R
        Ro = R + t
        zr = zc - Ro * math.sin(math.radians(FREE))            # each C is free above this height
        return {"n": n, "cd": cd, "R": R, "Ro": Ro, "t": t, "w": w, "pitch": pitch, "ys": ys, "zc": zc, "zr": zr,
                "top": zc + Ro, "half": ys[-1] + Ro, "G": v["desk_t"] + 2 * v["grip"], "mount": int(round(v["mount"]))}

    def constraints(self, v):
        out = []
        for key in ("mount", "cables", "screw"):
            if abs(v[key] - round(v[key])) > 1e-9:
                out.append(RecipeError(f"{self.spec(key).label} must be a whole number", self.spec(key).feature,
                                       "Use a whole number.", [key]))
        if out:
            return out
        g = self.g(v)
        if g["w"] >= v["cable_d"] - 0.2:
            out.append(RecipeError("The opening is as wide as the cable: nothing would hold it", "fingers",
                                   "Lower the opening ratio.", ["snap"]))
        need = 2 * g["R"] * math.sin(math.radians(90 - MAX_ROOF))
        if g["w"] < need - 1e-6:
            out.append(RecipeError(f"An opening of {g['w']:.1f} mm leaves the bore's roof overhanging; it needs at least "
                                   f"{need:.1f} mm to print without support", "fingers",
                                   f"Raise the opening ratio to {need / v['cable_d'] + 0.005:.2f} or more, or reduce the clearance.",
                                   ["snap", "cable_clear"]))
        if g["zr"] < 0.6:
            out.append(RecipeError("The base under the rings is too thin", "base", "Thicken the base.", ["base_t"]))
        if g["mount"] == 1:
            if v["jaw"] < 12:
                out.append(RecipeError("The jaws are too short to hold", "clamp", "Lengthen the jaws.", ["jaw"]))
            if g["G"] < 5:
                out.append(RecipeError("The jaw gap is under 5 mm", "clamp", "Check the desk thickness.", ["desk_t", "grip"]))
        return out

    def rail(self, v, g):
        """The channels' cross-section in a local (y, z) plane: base on z = 0, a C round each cable, opening up."""
        h, zr, zc = g["half"], g["zr"], g["zc"]
        prof = Pos(0, zr / 2) * Rectangle(2 * h, zr)
        for y in g["ys"]:
            prof = prof + Pos(y, zc) * Circle(g["Ro"])
        for sgn in (-1, 1):                                     # the outer sides run straight down from the equator
            prof = prof + Pos(sgn * (h - g["Ro"] / 2), zc / 2) * Rectangle(g["Ro"], zc)
        return prof & (Pos(0, g["top"] / 2) * Rectangle(2 * h + 2, g["top"]))    # nothing below the plate

    def _rail_cuts(self, v, g):
        """Bores and openings, as a 2D sketch in the same (y, z) plane."""
        zc, top, R, w = g["zc"], g["top"], g["R"], g["w"]
        cut = None
        for y in g["ys"]:
            c = Pos(y, zc) * Circle(R) + Pos(y, (zc + top + 1) / 2) * Rectangle(w, top + 1 - zc)
            cut = c if cut is None else cut + c
        return cut

    # ---- geometry -----------------------------------------------------------------------------------------------
    def build(self, v):
        g = self.g(v)
        return self._base(v, g) if g["mount"] == 0 else self._desk(v, g)

    def _base(self, v, g):
        L = v["length"]
        to3d = lambda sk: extrude(Plane.YZ * sk, L / 2, both=True)
        body = to3d(self.rail(v, g))
        stages = [Stage("base", body)]
        stages.append(Stage("channels", body - to3d(sum_circles(g))))
        s = body - to3d(self._rail_cuts(v, g))
        stages.append(Stage("fingers", s))
        if v["screw"] >= 0.5:
            d = v["screw_d"]
            head = round(d * 2.0, 1)
            tab_w = head + 6
            ty = g["half"] + tab_w / 2 - 1
            tt = max(v["base_t"], (head - d - 0.4) / 2 + 0.2 + 1.2)   # the countersink, and 1.2 mm under it
            box = Box(L, tab_w + 2, tt, align=A)
            tab = Pos(0, ty, 0) * fillet(box.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], min(L / 2 - 0.1, tab_w / 2))
            s = s + tab
            s = s - Pos(0, g["half"] + tab_w / 2, tt) * countersink(head, d + 0.4)
            stages.append(Stage("screw", s))
        s = foot(s)
        try:
            s = fillet([e for e in s.edges().filter_by(Axis.X) if e.center().Z > g["zc"] + g["R"]
                        and any(abs(abs(e.center().Y - y) - g["w"] / 2) < 1e-6 for y in g["ys"])], min(0.5, g["t"] / 3))
        except Exception:
            pass
        stages.append(Stage("soften", s))
        return stages

    def _desk(self, v, g):
        """On its side: the clamp's profile in X (into the desk) and Y (up), extruded along the cables (Z)."""
        L, jt, G = v["length"], v["jaw_t"], g["G"]
        sp = max(jt, 3.0)                                       # spine in front of the desk edge
        jaw = v["jaw"]
        pad = min(8.0, jaw * 0.4)
        relief = 0.6
        rail_w = 2 * g["half"]
        jb = max(jaw, rail_w + 2)                               # the lower jaw also carries the rail
        # clamp: desk front at x = 0, the lower pad at y = 0, the upper pad at y = G
        outer = Polygon((-sp, -jt), (jb, -jt), (jb, 0), (jb - pad, 0), (jb - pad, -relief), (0, -relief), (0, G + relief),
                        (jaw - pad, G + relief), (jaw - pad, G), (jaw, G), (jaw, G + jt), (-sp, G + jt), align=None)
        prof = outer
        r = min(jt / 2 - 0.05, 2.0)
        corners = [p for p in prof.vertices() if abs(p.X + sp) < 1e-6 or (abs(p.X - jaw) < 1e-6 and abs(p.Y - (G + jt)) < 1e-6)
                   or (abs(p.X - jb) < 1e-6 and abs(p.Y + jt) < 1e-6)]
        prof = fillet(corners, r)
        inner = [p for p in prof.vertices() if abs(p.X) < 1e-6 and (abs(p.Y + relief) < 1e-6 or abs(p.Y - G - relief) < 1e-6)]
        if inner:
            prof = fillet(inner, min(2.0, jaw - pad - 1))       # the jaws' roots, where they bend
        tips = [p for p in prof.vertices() if (abs(p.X - jaw) < 1e-6 and abs(p.Y - G) < 1e-6) or (abs(p.X - jb) < 1e-6 and abs(p.Y) < 1e-6)]
        if tips:
            prof = chamfer(tips, min(1.0, pad / 4))             # lead-in onto the desk
        clamp = extrude(prof, L, dir=(0, 0, 1))
        stages = [Stage("clamp", clamp)]
        # the rail hangs under the lower jaw, lips pointing down
        xr = g["half"] + 1
        place = lambda sk: Pos(xr, -jt, 0) * (Rot(0, 0, 180) * sk)
        body = clamp + extrude(place(self.rail(v, g)), L, dir=(0, 0, 1))
        stages.append(Stage("base", body))
        s = body - extrude(place(Pos(0, 0) * sum_circles(g)), L, dir=(0, 0, 1))
        stages.append(Stage("channels", s))
        s = body - extrude(place(self._rail_cuts(v, g)), L, dir=(0, 0, 1))
        stages.append(Stage("fingers", s))
        s = foot(s)
        try:
            s = chamfer(s.edges().group_by(Axis.Z)[-1], 0.5)
        except Exception:
            pass
        stages.append(Stage("soften", s))
        return stages

    # ---- interfaces ---------------------------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        out = [{"key": "channel_d", "label": "Channel bore", "value": g["cd"], "unit": "mm", "feature": "channels",
                "formula": "cable + 2 × clearance", "interface": True},
               {"key": "opening", "label": "Opening", "value": g["w"], "unit": "mm", "feature": "fingers",
                "formula": "cable × opening ratio", "interface": True}]
        if g["mount"] == 1:
            out.append({"key": "jaw_gap", "label": "Jaw gap at the pads", "value": g["G"], "unit": "mm", "feature": "clamp",
                        "formula": "desk thickness + 2 × grip", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        out = []
        cyl = [f for fs in faces_by_feature.values() for f in fs if f.geom_type.name == "CYLINDER"]
        rs = [f.radius for f in cyl if hasattr(f, "radius") and abs(f.radius - g["R"]) < 0.5]
        if rs:
            out.append({"key": "channel_d", "label": "Channel bore", "intended": g["cd"],
                        "modelled": 2 * min(rs, key=lambda r: abs(r - g["R"]))})
        ax = 1 if g["mount"] == 0 else 0                         # the openings' width runs along Y (base) or X (desk)
        walls = [f for f in faces_by_feature.get("fingers", []) if f.geom_type.name == "PLANE"
                 and abs(abs(tuple(f.normal_at())[ax]) - 1) < 1e-6]
        if walls:
            cs = sorted((tuple(f.center())[ax], round(tuple(f.normal_at())[ax])) for f in walls)
            gaps = [b[0] - a[0] for a, b in zip(cs, cs[1:]) if a[1] == 1 and b[1] == -1]
            near = [x for x in gaps if abs(x - g["w"]) < 0.3]
            if near:
                out.append({"key": "opening", "label": "Opening", "intended": g["w"], "modelled": near[0]})
        if g["mount"] == 1:
            pads = [f for f in faces_by_feature.get("clamp", []) if f.geom_type.name == "PLANE" and abs(abs(f.normal_at().Y) - 1) < 1e-6
                    and -0.01 < f.center().Y < g["G"] + 0.01]
            ys = sorted(f.center().Y for f in pads)
            if len(ys) >= 2:
                out.append({"key": "jaw_gap", "label": "Jaw gap at the pads", "intended": g["G"], "modelled": ys[-1] - ys[0]})
        return out

    # ---- models -------------------------------------------------------------------------------------------------
    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        delta = max(0.0, (v["cable_d"] - g["w"]) / 2)
        Lc = g["top"] - g["zr"]                                  # a lip bends from where its C leaves the base
        t = g["t"]
        eps = 1.5 * t * delta / Lc ** 2 * 100
        allow = v["strain_allow"]
        st = "PASS" if eps <= allow else ("WARN" if eps <= 1.5 * allow else "FAIL")
        checks = [{"id": "snap", "label": "Lip strain while snapping in", "status": st, "value": f"{eps:.1f} %",
                   "detail": f"Each side of the C is taken as a cantilever {Lc:.1f} mm long (from where it leaves the base) and {t:.1f} mm thick, "
                             f"pushed {delta:.2f} mm aside as the {v['cable_d']:g} mm cable passes the {g['w']:.2f} mm opening: "
                             f"ε = 1.5·t·δ/L² ≈ {eps:.1f} % against {allow:g} % allowed (assumed). The cable's jacket also "
                             "squashes, which this ignores, so the real push is easier. A heuristic, not a test.",
                   "evidence": "heuristic", "feature": "fingers"}]
        out = {"snap_strain_pct": eps}
        if g["mount"] == 1:
            d = max(0.0, -v["grip"])
            Lj = v["jaw"]
            I = v["length"] * v["jaw_t"] ** 3 / 12
            F = 3 * E_MPA * I * d / Lj ** 3 * 2                    # both jaws open by d
            e_j = 1.5 * v["jaw_t"] * (2 * d) / Lj ** 2 * 100
            out["clamp_force_n"] = F
            checks.append({"id": "clamp", "label": "Clamp grip", "status": "PASS" if (F >= 2 or d == 0) and e_j <= allow else "WARN",
                           "value": f"{F:.0f} N", "detail": f"The pads are {2 * d:.2f} mm closer than the desk is thick; the jaws "
                           f"({Lj:g} mm long, {v['jaw_t']:g} mm thick) open to fit, pressing about {F:.0f} N on the desk with "
                           f"{e_j:.1f} % strain at their roots. E = {E_MPA:.0f} MPa assumed. A beam estimate.",
                           "evidence": "model", "feature": "clamp"})
        out["checks"] = checks
        return out


def sum_circles(g):
    """The channel bores as one sketch in the rail's (y, z) plane."""
    c = None
    for y in g["ys"]:
        k = Pos(y, g["zc"]) * Circle(g["R"])
        c = k if c is None else c + k
    return c
