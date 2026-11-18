"""Self-watering planter: a reservoir pot and an inner pot that hangs in it, printed side by side.

The inner pot takes a nursery pot (or soil) and hangs from a conical flange that seats in a matching cone in the
reservoir's rim, so it centres itself and its floor sits above the water. A cotton wick through the centre hole draws
water up; a ring of small holes drains surplus back down. Water goes in through the fill notch, which cuts through the
flange and the rim on one side, into the gap between the two walls.

Every downward-facing surface is 40° from vertical or steeper (the flange underside and its seat, the foot chamfer),
so both parts print upright without support. The outside can be smooth or fluted; the flutes are lofted, the inside of
the reservoir is a plain cone, so the wall is never thinner than `wall`.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Cylinder, Plane, Polyline, Pos, RegularPolygon, loft, make_face

from .assembly import Assembly, Hardware, Part
from .base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)
K = 1 / math.tan(math.radians(40))      # rise per mm of radius on a downward-facing revolved face (40° from vertical)
FOOT = 0.4                              # foot chamfer, radial
GAP = 8.0                               # between the parts on the plate


N = 64              # sides of the polygons the hidden round surfaces (cavities, inner pot, seat) are lofted from
N_SMOOTH = 160      # sides of a smooth (unfluted) outside, which is seen


def _lathe(profile, n=N):
    """A body of revolution as a loft of fine regular polygons through (r, z) points, z increasing.

    Planar facets instead of true cones: OCCT's volume and the exported mesh then agree exactly (a true 110 mm cone
    meshes 0.5 % small at the export tolerance and fails "STL matches the CAD solid"). Each facet is a face, and
    face attribution grows with the face count, so the polygons stay as coarse as the surface allows."""
    return loft([Plane.XY.offset(z) * RegularPolygon(r, n) for r, z in profile], ruled=True)


def _section(R, a, n, z, twist=0.0):
    """A horizontal outline at height z: a circle of radius R, or n soft flutes of depth a about it."""
    if n < 1 or a <= 0:
        return Plane.XY.offset(z) * RegularPolygon(R, N_SMOOTH)
    # a fine polygon (6 facets per flute): planar faces keep OCCT's volume, booleans and the exported mesh in exact
    # agreement (a B-spline or arc loft drifts by tenths of a percent once it is cut)
    k = 6 * n
    pts = []
    for i in range(k):
        t = 2 * math.pi * i / k
        r = R + a * math.cos(n * (t - twist))
        pts.append((r * math.cos(t), r * math.sin(t)))
    return Plane.XY.offset(z) * make_face(Polyline(*pts, close=True))


def _radii(faces, cx, z):
    """Distances from the axis at x = cx of the vertices that lie at height z."""
    for f in faces:
        for p in f.vertices():
            if abs(p.Z - z) < 1e-6:
                yield math.hypot(p.X - cx, p.Y)


class PlantPot(Recipe):
    id = "plant_pot"
    title = "Self-watering planter"
    summary = ("A reservoir pot and an inner pot sized to your nursery pot: a cotton wick keeps the soil moist for days. "
               "Self-centring flange, fill notch, smooth or fluted.")
    category = "Home"
    tags = ("plant", "planter", "pot", "self-watering", "garden", "herbs", "succulent")
    solids = 2
    fit = {"cavity": "pot_bore", "mating": "pot_d", "clearance": "pot_clear",
           "label": "Inner pot ↔ nursery pot", "per_side": True, "window": [1.0, 8.0]}

    params = [
        Param("pot_d", "Nursery pot diameter", 90, 40, 140, 0.5, "mm", "brief", "pot",
              "Measure across the top rim of the plastic pot the plant came in. 9 cm and 12 cm are the common sizes. "
              "Planting straight into the inner pot? Use the soil width you want."),
        Param("pot_h", "Nursery pot height", 80, 30, 140, 0.5, "mm", "brief", "pot", "Rim to base of the plastic pot."),
        Param("pot_clear", "Pot clearance / side", 2.0, 0.5, 6, 0.25, "mm", "interface", "pot",
              "Room around the nursery pot so it lifts out with roots and soil on it."),
        Param("taper", "Taper", 6, 0, 12, 0.5, "deg", "form", "pot", "Side angle from vertical. Nursery pots are 5–8°."),
        Param("res_h", "Reservoir depth", 40, 10, 80, 1, "mm", "form", "reservoir", "Water below the inner pot's floor."),
        Param("gap", "Gap between walls", 4, 2.5, 10, 0.5, "mm", "form", "reservoir", "Where water goes down from the fill notch."),
        Param("wall", "Wall", 2.0, 1.2, 4, 0.1, "mm", "form", "pot", "Five 0.4 mm lines."),
        Param("rim_wall", "Reservoir wall", 3.2, 2.4, 6, 0.1, "mm", "form", "reservoir",
              "Thicker than the inner pot: the flange seat is cut into it at the rim."),
        Param("floor", "Floors", 2.0, 1.2, 4, 0.1, "mm", "form", "reservoir"),
        Param("seat", "Flange bite", 1.2, 0.6, 3, 0.1, "mm", "interface", "seat", "How far the flange reaches into the reservoir rim."),
        Param("seat_clear", "Seat clearance", 0.3, 0.1, 0.8, 0.05, "mm", "interface", "seat", "Gap across the conical seat."),
        Param("wick_d", "Wick hole", 8, 4, 16, 0.5, "mm", "interface", "wick",
              "For a cotton rope wick; 6–8 mm rope is common (assumed)."),
        Param("drains", "Drain holes", 8, 0, 24, 1, "", "form", "drain", "Small holes around the wick that let surplus water back down."),
        Param("fill_w", "Fill notch width", 16, 0, 40, 1, "mm", "form", "fill", "0 = no notch (water through the wick hole gap only)."),
        Param("flutes", "Flutes", 24, 0, 60, 1, "", "form", "reservoir", "Soft vertical ribs around the outside. 0 = smooth."),
        Param("flute_depth", "Flute depth", 1.2, 0.4, 3, 0.1, "mm", "form", "reservoir"),
    ]
    features = [
        Feature("reservoir", "Reservoir", "structure", "The outer pot that holds the water."),
        Feature("res_cavity", "Reservoir cavity", "access"),
        Feature("seat", "Flange seat", "interface", "Cone in the reservoir rim the inner pot hangs from."),
        Feature("pot", "Inner pot", "structure"),
        Feature("flange", "Flange", "interface"),
        Feature("pot_cavity", "Pot cavity", "interface", "Takes the nursery pot."),
        Feature("wick", "Wick hole", "interface"),
        Feature("drain", "Drain holes", "access"),
        Feature("fill", "Fill notch", "access", "Pour here: through the flange and rim into the gap."),
    ]

    # ---- geometry -------------------------------------------------------------------------------
    @staticmethod
    def g(v):
        tn = math.tan(math.radians(v["taper"]))
        w, fl = v["wall"], v["floor"]
        hi = v["pot_h"] + fl + 2.0                          # inner pot: the nursery pot plus a floor and 2 mm above its rim
        ri_top = v["pot_d"] / 2 + v["pot_clear"]            # inner pot bore at the top
        ro_top = ri_top + w
        ro_bot = ro_top - hi * tn
        rr_top = ro_top + v["gap"]                          # reservoir bore at the top
        Ho = v["floor"] + v["res_h"] + hi                   # reservoir height: rims flush when assembled
        rr_bot = rr_top - (Ho - fl) * tn
        Ro_top = rr_top + v["rim_wall"]                     # reservoir outside (mean radius when fluted)
        Ro_bot = rr_bot + v["rim_wall"]
        fa = v["flute_depth"] if v["flutes"] >= 1 else 0.0
        # flange: from the pot wall out across the gap into the rim, at 40° from vertical underneath
        rf = rr_top + v["seat"]
        # flange height: its cone (from the tapered wall out to rf) plus a 1.2 mm vertical band; the wall it starts from is
        # itself hf * tan(taper) inside ro_top, hence the division
        hf = ((rf - ro_top) * K + 1.2) / (1 - tn * K)
        return {"tn": tn, "hi": hi, "ri_top": ri_top, "ro_top": ro_top, "ro_bot": ro_bot, "rr_top": rr_top, "rr_bot": rr_bot,
                "Ho": Ho, "Ro_top": Ro_top + fa, "Ro_bot": Ro_bot + fa, "Rm_top": Ro_top, "Rm_bot": Ro_bot, "fa": fa,
                "rf": rf, "hf": hf, "ri_bot": ri_top - (hi - fl) * tn,
                "x_pot": (Ro_top + fa) + GAP + rf}

    def constraints(self, v):
        out = []
        for k in ("drains", "flutes"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        g = self.g(v)
        if g["ri_bot"] < v["wick_d"] / 2 + 8:
            out.append(RecipeError(f"The inner pot narrows to {2 * g['ri_bot']:.0f} mm at its floor", "pot",
                                   "Lower the taper or the height, or use a larger pot diameter.", ["taper", "pot_h", "pot_d"]))
        if v["rim_wall"] - v["seat"] - v["seat_clear"] < 1.2:
            out.append(RecipeError("The flange seat leaves under 1.2 mm of reservoir rim", "seat",
                                   "Thicken the reservoir wall or reduce the flange bite.", ["rim_wall", "seat"]))
        if v["fill_w"] and v["fill_w"] > g["ro_top"]:
            out.append(RecipeError("The fill notch is wider than the pot allows", "fill", "Narrow the notch.", ["fill_w"]))
        n = int(round(v["drains"]))
        if n:
            ring = v["wick_d"] / 2 + 6
            if ring + 3 > g["ri_bot"] - 2:
                out.append(RecipeError("No room for drain holes around the wick", "drain", "Use 0 drain holes or a wider pot.", ["drains"]))
            elif 2 * math.pi * ring / n < 5.5:
                out.append(RecipeError("Drain holes would run into each other", "drain", "Use fewer drain holes.", ["drains"]))
        if g["fa"] and 2 * math.pi * g["Rm_bot"] / v["flutes"] < 4 * g["fa"]:
            out.append(RecipeError("Flutes are packed too tight to print cleanly", "reservoir", "Use fewer or shallower flutes.",
                                   ["flutes", "flute_depth"]))
        return out

    def build(self, v):
        g = self.g(v)
        Ho, fl, fa = g["Ho"], v["floor"], g["fa"]
        n = int(round(v["flutes"]))
        # ---- reservoir: lofted skin, 40° foot chamfer ----
        lift = FOOT * K
        Rb, Rt = g["Ro_bot"], g["Ro_top"]                     # flute crests; the valleys are on the mean wall
        Rl = Rb + (Rt - Rb) * lift / Ho
        res = loft([_section(Rb - FOOT, fa, n, 0), _section(Rl, fa, n, lift), _section(Rt, fa, n, Ho)], ruled=True)
        stages = [Stage("reservoir", res)]
        rr_b, rr_t = g["rr_bot"], g["rr_top"]
        res = res - _lathe([(rr_b, fl), (rr_t, Ho + 1)])
        stages.append(Stage("res_cavity", res))
        # seat: a cone widening upward into the rim, 40° from vertical (it faces up, the flange rests on it)
        # the flange's cone moved down by sc / sin 40°: a gap of sc measured square to the cone
        sc = v["seat_clear"]
        rs = g["rf"] + sc
        ro_cone = g["ro_top"] - g["hf"] * g["tn"]
        za = Ho - g["hf"] - sc / math.sin(math.radians(40))
        seat = _lathe([(ro_cone, za), (rs, za + (rs - ro_cone) * K), (rs, Ho + 1)])
        res = res - seat
        stages.append(Stage("seat", res))
        # ---- inner pot, beside the reservoir ----
        hi, x = g["hi"], g["x_pot"]
        ro_t, ro_b = g["ro_top"], g["ro_bot"]
        h_cone = hi - g["hf"]                                  # where the flange cone starts
        ro_cone = ro_b + (ro_t - ro_b) * h_cone / hi
        pot = _lathe([(ro_b - FOOT, 0), (ro_b + FOOT * K * g["tn"], FOOT * K), (ro_cone, h_cone)])
        P = Pos(x, 0, 0)
        s = res + P * pot
        stages.append(Stage("pot", s))
        rf = g["rf"]
        z0 = h_cone - 0.6 * K                                  # start the cone 0.6 mm inside the wall, on the same line
        flange = _lathe([(ro_cone - 0.6, z0), (rf, h_cone + (rf - ro_cone) * K), (rf, hi - 0.6), (rf - 0.6, hi)])
        s = s + P * flange
        stages.append(Stage("flange", s))
        ri_b, ri_t = g["ri_bot"], g["ri_top"]
        pc = _lathe([(ri_b, fl), (ri_t, hi), (ri_t + 1, hi + 1)])
        s = s - P * pc
        stages.append(Stage("pot_cavity", s))
        s = s - P * Pos(0, 0, -1) * Cylinder(v["wick_d"] / 2, fl + 2, align=A)
        stages.append(Stage("wick", s))
        nd = int(round(v["drains"]))
        if nd:
            ring = v["wick_d"] / 2 + 6
            holes = None
            for i in range(nd):
                a = 2 * math.pi * (i + 0.5) / nd
                h = Pos(x + ring * math.cos(a), ring * math.sin(a), -1) * Cylinder(1.5, fl + 2, align=A)
                holes = h if holes is None else holes + h
            s = s - holes
            stages.append(Stage("drain", s))
        if v["fill_w"] > 0:
            fw, depth = v["fill_w"], g["hf"] + 0.6
            # through the flange of the inner pot, and the rim of the reservoir at the same place when assembled (+Y)
            y0 = ro_t - 0.2                                     # just into the wall top, so the notch opens onto the gap
            notch_pot = Pos(x, (y0 + rf + 1) / 2, hi - depth) * Box(fw, rf + 1 - y0, depth + 1, align=A)
            notch_res = Pos(0, rs + 0.5, Ho - depth - 0.6) * Box(fw, 2 * (g["Ro_top"] - rs + 2), depth + 2, align=A)
            s = s - notch_pot - notch_res
            stages.append(Stage("fill", s))
        return stages

    # ---- interfaces -----------------------------------------------------------------------------
    def reservoir_ml(self, v):
        g = self.g(v)
        h = v["res_h"]
        r1 = g["rr_bot"]
        r2 = r1 + h * g["tn"]
        return math.pi * h * (r1 * r1 + r1 * r2 + r2 * r2) / 3 / 1000

    def derived(self, v):
        g = self.g(v)
        return [
            {"key": "pot_bore", "label": "Inner pot bore", "value": 2 * g["ri_top"], "unit": "mm", "feature": "pot_cavity",
             "formula": "nursery pot + 2 × clearance, at the rim", "interface": True},
            {"key": "seat_d", "label": "Flange diameter", "value": 2 * g["rf"], "unit": "mm", "feature": "flange",
             "formula": "reservoir bore + 2 × flange bite", "interface": True},
            {"key": "reservoir_ml", "label": "Water held", "value": self.reservoir_ml(v), "unit": "mL", "feature": "reservoir",
             "formula": "frustum below the inner pot's floor", "interface": False},
            {"key": "height", "label": "Height", "value": g["Ho"], "unit": "mm", "feature": "reservoir",
             "formula": "floor + reservoir + inner pot", "interface": False},
            {"key": "outer_d", "label": "Outside diameter at the rim", "value": 2 * g["Ro_top"], "unit": "mm", "feature": "reservoir",
             "formula": "", "interface": False},
        ]

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        out = []
        rs = list(_radii(faces_by_feature.get("pot_cavity", []), g["x_pot"], g["hi"]))
        if rs:
            out.append({"key": "pot_bore", "label": "Inner pot bore", "intended": 2 * g["ri_top"], "modelled": 2 * max(rs)})
        rs = list(_radii(faces_by_feature.get("flange", []), g["x_pot"], g["hi"] - 0.6))
        if rs:
            out.append({"key": "seat_d", "label": "Flange diameter", "intended": 2 * g["rf"], "modelled": 2 * max(rs)})
        return out

    def assembly(self, v):
        g = self.g(v)
        z = g["Ho"] - g["hi"]
        return Assembly(
            parts=[Part("reservoir", "Reservoir", 0, note="Thread the wick through the inner pot first; fill the reservoir to below the rim."),
                   Part("pot", "Inner pot", 1, move=(-g["x_pot"], 0, z), explode=(0, 0, g["hi"] * 0.8),
                        note="Lower the inner pot in with the fill notches lined up; the flange seats in the rim.")],
            hardware=[Hardware("Cotton wick", f"Ø{v['wick_d'] - 2:g} mm cotton rope, about {v['res_h'] + 60:.0f} mm", 1,
                               "Cotton or acrylic rope (assumed)",
                               "Push the wick up through the centre hole and coil its top into the soil; let the end touch the reservoir floor.",
                               after="pot")])
