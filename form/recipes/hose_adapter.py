"""Universal hose and pipe adapter: any two diameters, each end going inside or over what it meets.

Printed upright, end A on the plate. Each end is either a spigot that goes inside a hose or socket (the size you give
is that hose's inner diameter) or a socket that goes over a pipe or stub (the size you give is that pipe's outer
diameter). A clearance per side sets the fit: positive for a slip fit on rigid parts (vacuum tools), zero or negative
for a tight push into a soft hose. Spigots taper slightly towards the tip and can carry sawtooth barbs; sockets taper
slightly towards the bottom so a pipe wedges in. Everything that faces down is within 35° of vertical, so it prints with no
support: the transition cone, the socket shoulder, the grip collar's underside and the barbs.

Common sizes (measure yours): vacuum cleaner wands and hoses 32 mm and 35 mm outer diameter; garden hose 13 mm (1/2")
and 19 mm (3/4") inner diameter; shop-vac hoses 1.25" (32 mm) and 2.5" (63 mm).
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Cylinder, Plane, Polygon, Pos, Rot, fillet, revolve

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import FOOT

LEAD = 0.6          # lead-in at every mouth and tip (radial; 35° from vertical where it faces down)
STOP = 1.5          # radial shoulder at the bottom of a socket: the pipe stops against it
K = 1 / math.tan(math.radians(35))   # rise per mm of radius on a downward-facing revolved face: 35° from vertical, so a
                                     # coarsely tessellated cone of any size never reads steeper than 45°
BARB_RAMP = 15.0    # barb ramp angle from the axis (gentle, so the hose slides on)
A_ = (Align.CENTER, Align.CENTER, Align.MIN)


def _rev(pts):
    """Revolve a closed (r, z) outline about Z. Consecutive duplicate points are dropped."""
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    if abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return revolve(Plane.XZ * Polygon(*out, align=None), Axis.Z, 360)


def _circle_radii(face):
    for e in face.edges():
        if e.geom_type.name == "CIRCLE":
            yield e.radius, e.center().Z


class HoseAdapter(Recipe):
    id = "hose_adapter"
    title = "Hose and pipe adapter"
    summary = ("Joins any two hoses, pipes or vacuum fittings: each end goes inside or over what it meets, "
               "with a measured fit, optional barbs and a support-free transition.")
    category = "Workshop"
    tags = ("hose", "vacuum", "pipe", "adapter", "garden", "dust extraction", "reducer")
    fit = {"cavity": "a_fit", "mating": "d_a", "clearance": "clear_a",
           "label": "End A ↔ what it fits", "per_side": True, "window": [0.1, 0.8]}

    params = [
        Param("d_a", "End A size", 35.0, 6, 120, 0.05, "mm", "brief", "end_a",
              "Measure it with calipers. Goes over (socket): the pipe's outer diameter, e.g. a 35 mm vacuum wand. "
              "Goes inside (spigot): the hose's inner diameter."),
        Param("fits_a", "End A goes", 1, 0, 1, 1, "", "interface", "end_a",
              "0 = inside the hose or socket (a spigot), 1 = over the pipe (a socket)."),
        Param("clear_a", "End A clearance / side", 0.2, -0.5, 1.0, 0.05, "mm", "interface", "end_a",
              "Gap per side between this end and what it meets. 0.1–0.3 slips onto rigid parts; 0 to −0.4 grips a soft hose."),
        Param("len_a", "End A length", 30, 8, 80, 0.5, "mm", "form", "end_a", "How far the hose or pipe goes on."),
        Param("barbs_a", "End A barbs", 0, 0, 6, 1, "", "form", "barbs", "Sawtooth ridges on a spigot end that hold a soft hose. 0 = smooth."),
        Param("d_b", "End B size", 32.0, 6, 120, 0.05, "mm", "brief", "end_b",
              "Measure it with calipers. Goes over: the pipe's outer diameter. Goes inside: the hose's or socket's inner diameter, "
              "e.g. a 32 mm vacuum tool socket or a 19 mm (3/4\") garden hose."),
        Param("fits_b", "End B goes", 0, 0, 1, 1, "", "interface", "end_b",
              "0 = inside the hose or socket (a spigot), 1 = over the pipe (a socket)."),
        Param("clear_b", "End B clearance / side", 0.15, -0.5, 1.0, 0.05, "mm", "interface", "end_b"),
        Param("len_b", "End B length", 30, 8, 80, 0.5, "mm", "form", "end_b"),
        Param("barbs_b", "End B barbs", 0, 0, 6, 1, "", "form", "barbs"),
        Param("barb_h", "Barb height", 0.8, 0.3, 2.0, 0.05, "mm", "form", "barbs", "How far each barb stands proud of the spigot."),
        Param("wall", "Wall", 2.4, 1.6, 6, 0.1, "mm", "form", "transition", "Six 0.4 mm lines by default: stiff enough to push hard."),
        Param("cone", "Transition angle", 30, 15, 35, 1, "deg", "form", "transition",
              "Slope of the cone between the ends, from the axis. Up to 35° prints without support at any size."),
        Param("taper", "Friction taper", 0.5, 0, 2, 0.05, "deg", "interface", "end_a",
              "Spigots narrow towards the tip and sockets towards the bottom, so the joint wedges tight."),
        Param("collar", "Grip collar", 1, 0, 1, 1, "", "form", "collar", "1 = a fluted ring above end A to grip and twist, and a stop for its hose."),
        Param("collar_w", "Collar height above the wall", 3.5, 1.5, 10, 0.5, "mm", "form", "collar"),
        Param("collar_h", "Collar length", 9, 4, 30, 0.5, "mm", "form", "collar"),
        Param("flutes", "Collar flutes", 16, 0, 40, 1, "", "form", "grip", "Shallow vertical grooves for grip. 0 = smooth."),
    ]
    features = [
        Feature("end_a", "End A", "interface", "Printed on the plate."),
        Feature("collar", "Grip collar", "structure"),
        Feature("transition", "Transition", "structure", "Cone between the two ends, never steeper than 35° from the axis."),
        Feature("end_b", "End B", "interface"),
        Feature("barbs", "Barbs", "interface", "Sawtooth ridges that hold a soft hose."),
        Feature("bore", "Bore and sockets", "interface", "The flow path; socket ends are cut here."),
        Feature("grip", "Flutes", "finish"),
    ]

    # ---- geometry -------------------------------------------------------------------------------
    @staticmethod
    def g(v):
        out = {}
        for e in ("a", "b"):
            d, c, L = v[f"d_{e}"], v[f"clear_{e}"], v[f"len_{e}"]
            sock = v[f"fits_{e}"] >= 0.5
            t = L * math.tan(math.radians(v["taper"]))
            if sock:
                r = d / 2 + c                       # socket radius at the mouth (after the lead-in)
                ro = r + v["wall"]                  # outside of the socket
                inner_end = r - t - STOP            # bore radius past the shoulder
                stop = STOP
            else:
                r = d / 2 - c                       # spigot radius at its root
                ro = r
                inner_end = r - v["wall"]
                stop = 0.0
            out[e] = {"sock": sock, "r": r, "ro": ro, "t": t, "rin": inner_end, "stop": stop, "L": L,
                      "fit": d + 2 * c}             # socket: its diameter; spigot: d + (d - OD) — the gap model is the same
        A, B = out["a"], out["b"]
        hc = v["collar_h"] if v["collar"] >= 0.5 else 0.0
        tan = math.tan(math.radians(v["cone"]))
        dr = max(abs(B["ro"] - A["ro"]), abs(B["rin"] - A["rin"]))
        Lt = max(dr / tan, 2.0)
        zt0 = A["L"] + max(hc, A["stop"] * K)
        zt1 = zt0 + Lt
        H = zt1 + B["stop"] * K + B["L"]          # the shoulder under a top socket faces down: same slope rule
        tips = [s["rin"] - s["t"] for s in (A, B) if not s["sock"]]      # a spigot's bore narrows towards its tip
        out.update(hc=hc, Lt=Lt, zt0=zt0, zt1=zt1, H=H, rc=A["ro"] + v["collar_w"], bore=2 * min([A["rin"], B["rin"]] + tips))
        return out

    def constraints(self, v):
        out = []
        for k in ("fits_a", "fits_b", "barbs_a", "barbs_b", "collar", "flutes"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        for e, E in (("a", "A"), ("b", "B")):
            s = g[e]
            if s["rin"] - (0 if s["sock"] else s["t"]) < 1.0:
                out.append(RecipeError(f"End {E} leaves a bore under 2 mm", f"end_{e}",
                                       "Thin the wall, or give this end a larger size.", [f"d_{e}", "wall"]))
            if v[f"barbs_{e}"] and s["sock"]:
                out.append(RecipeError(f"End {E} is a socket; barbs go on an end that goes inside a hose", "barbs",
                                       f"Set End {E} barbs to 0, or make End {E} go inside.", [f"barbs_{e}", f"fits_{e}"]))
            pitch = v["barb_h"] / math.tan(math.radians(BARB_RAMP)) + 1.5
            if v[f"barbs_{e}"] * pitch > s["L"] - LEAD - 3:
                out.append(RecipeError(f"{int(v[f'barbs_{e}'])} barbs need {v[f'barbs_{e}'] * pitch + LEAD + 3:.0f} mm; End {E} is "
                                       f"{s['L']:g} mm long", "barbs", "Lengthen the end, lower the barbs or use fewer.",
                                       [f"barbs_{e}", f"len_{e}", "barb_h"]))
        if v["wall"] < LEAD + 0.8:
            out.append(RecipeError("Wall is too thin for the lead-in chamfers", "transition", "Thicken the wall.", ["wall"]))
        if v["collar"] >= 0.5 and v["collar_h"] < v["collar_w"] * K + 1.5:
            out.append(RecipeError("Collar is shorter than its sloped underside needs", "collar",
                                   "Lengthen the collar or make it less tall.", ["collar_h", "collar_w"]))
        return out

    def build(self, v):
        g = self.g(v)
        A, B = g["a"], g["b"]
        La, H, zt0, zt1 = A["L"], g["H"], g["zt0"], g["zt1"]
        zb = H - B["L"]
        # ---- end A (on the plate) ----
        if A["sock"]:
            pa = [(0, 0), (A["ro"] - FOOT, 0), (A["ro"], FOOT * K), (A["ro"], La), (0, La)]
        else:
            tip = A["r"] - A["t"]
            pa = [(0, 0), (tip - LEAD, 0), (tip, LEAD * K), (A["r"], La), (0, La)]
        s = _rev(pa)
        stages = [Stage("end_a", s)]
        # ---- collar ----
        if g["hc"] > 0:
            rc, hc = g["rc"], g["hc"]
            ring = _rev([(A["ro"] - 0.5, La), (A["ro"], La), (rc, La + (rc - A["ro"]) * K), (rc, La + hc), (A["ro"] - 0.5, La + hc)])
            try:
                ring = fillet(ring.edges().filter_by(lambda e: e.geom_type.name == "CIRCLE" and abs(e.center().Z - (La + hc)) < 1e-6
                                                     and e.radius > rc - 1e-6), min(1.2, v["collar_w"] / 2))
            except Exception:
                pass
            s = s + ring
            stages.append(Stage("collar", s))
        # ---- neck and cone ----
        s = s + _rev([(0, La - 0.01), (A["ro"], La - 0.01), (A["ro"], zt0), (B["ro"], zt1), (B["ro"], zb + 0.01), (0, zb + 0.01)])
        stages.append(Stage("transition", s))
        # ---- end B (on top) ----
        if B["sock"]:
            pb = [(0, zb), (B["ro"], zb), (B["ro"], H - LEAD), (B["ro"] - LEAD, H), (0, H)]
        else:
            tip = B["r"] - B["t"]
            pb = [(0, zb), (B["r"], zb), (tip, H - LEAD), (tip - LEAD, H), (0, H)]
        s = s + _rev(pb)
        stages.append(Stage("end_b", s))
        # ---- barbs ----
        barbs = None
        for e, s0 in (("a", A), ("b", B)):
            n = int(round(v[f"barbs_{e}"]))
            if not n or s0["sock"]:
                continue
            h = v["barb_h"]
            ramp = h / math.tan(math.radians(BARB_RAMP))
            pitch = ramp + 1.5
            r0 = s0["r"] - s0["t"] - 0.3                       # just inside the spigot so the barb fuses
            if e == "a":                                       # spigot radius at height z: tip (r - t) up to root (r)
                z_tip, z_root = LEAD * K, La
            else:
                z_tip, z_root = H - LEAD, zb
            rad = lambda z: s0["r"] - s0["t"] * (z - z_root) / (z_tip - z_root)
            for i in range(n):
                if e == "a":                                   # hose comes from below: ramp up, flat back facing up
                    z0 = LEAD * K + 1.5 + i * pitch
                    pts = [(r0, z0), (rad(z0), z0), (rad(z0 + ramp) + h, z0 + ramp), (r0, z0 + ramp)]
                else:                                          # hose comes from above: ramp down, sloped back facing down
                    z1 = H - LEAD - 1.5 - i * pitch
                    z2 = z1 - ramp - h * K
                    pts = [(r0, z1), (rad(z1), z1), (rad(z1 - ramp) + h, z1 - ramp), (rad(z2), z2), (r0, z2)]
                b = _rev(pts)
                barbs = b if barbs is None else barbs + b
        if barbs is not None:
            s = s + barbs
            stages.append(Stage("barbs", s))
        # ---- bore ----
        if A["sock"]:
            ia = [(A["r"] + LEAD, -1), (A["r"] + LEAD, 0), (A["r"], LEAD * K), (A["r"] - A["t"], La), (A["rin"], La + A["stop"] * K)]
        else:
            ia = [(A["rin"] - A["t"], -1), (A["rin"] - A["t"], 0), (A["rin"], La)]
        if B["sock"]:
            ib = [(B["rin"], zt1), (B["r"] - B["t"], zb), (B["r"], H - LEAD), (B["r"] + LEAD, H), (B["r"] + LEAD, H + 1)]
        else:
            ib = [(B["rin"], zb), (B["rin"] - B["t"], H), (B["rin"] - B["t"], H + 1)]
        bore = _rev([(0, -1)] + ia + [(A["rin"], zt0), (B["rin"], zt1)] + ib + [(0, H + 1)])
        s = s - bore
        stages.append(Stage("bore", s))
        # ---- flutes ----
        n = int(round(v["flutes"]))
        if g["hc"] > 0 and n:
            rc, hc = g["rc"], g["hc"]
            rg = min(2.2, math.pi * rc / n * 0.42)               # scallop radius: about 40% of the pitch
            cuts = None
            for i in range(n):
                a = 2 * math.pi * i / n
                c = Pos((rc + rg * 0.15) * math.cos(a), (rc + rg * 0.15) * math.sin(a), La) * Cylinder(rg, hc + 2, align=A_)
                cuts = c if cuts is None else cuts + c
            s = s - cuts
            stages.append(Stage("grip", s))
        return stages

    # ---- interfaces -----------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        rows = []
        for e, E in (("a", "A"), ("b", "B")):
            s = g[e]
            rows.append({"key": f"{e}_fit", "label": f"End {E} fit size", "value": s["fit"], "unit": "mm", "feature": f"end_{e}",
                         "formula": "size + 2 × clearance (socket: its bore; spigot: size + the gap it leaves)", "interface": False})
            rows.append({"key": f"{e}_size", "label": f"End {E} {'socket bore' if s['sock'] else 'spigot diameter'}",
                         "value": 2 * s["r"], "unit": "mm", "feature": "bore" if s["sock"] else f"end_{e}",
                         "formula": "size + 2 × clearance, at the mouth" if s["sock"] else "size − 2 × clearance, at the root",
                         "interface": True})
        rows += [{"key": "transition_len", "label": "Transition length", "value": g["Lt"], "unit": "mm", "feature": "transition",
                  "formula": "largest radius change / tan(transition angle)", "interface": False},
                 {"key": "bore_min", "label": "Narrowest bore", "value": g["bore"], "unit": "mm", "feature": "bore",
                  "formula": "smallest inner diameter: what limits the flow", "interface": False},
                 {"key": "length", "label": "Overall length", "value": g["H"], "unit": "mm", "feature": "transition",
                  "formula": "end A + collar or shoulder + transition + end B", "interface": False}]
        return rows

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        out = []
        H = g["H"]
        for e, E, lo, hi in (("a", "A", LEAD, g["a"]["L"]), ("b", "B", H - g["b"]["L"], H - LEAD)):
            s = g[e]
            if s["sock"]:
                faces = faces_by_feature.get("bore", [])
            else:
                faces = [f for k, fs in faces_by_feature.items() if k not in ("bore", "barbs", "grip") for f in fs]
            rs = [r for f in faces for r, z in _circle_radii(f) if lo - 1e-6 <= z <= hi + 1e-6 and
                  (r < s["r"] + s["t"] + 1e-6)]
            if s["sock"]:
                rs = [r for r in rs if r > s["r"] - s["t"] - 1e-6]
            if rs:
                out.append({"key": f"{e}_size", "label": f"End {E} {'socket bore' if s['sock'] else 'spigot diameter'}",
                            "intended": 2 * s["r"], "modelled": 2 * max(rs)})
        return out
