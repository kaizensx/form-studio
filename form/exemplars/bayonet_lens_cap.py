"""Bayonet lens cap: a front plate with a recessed logo field and a raised aperture mark, a ribbed grip ring, and a
bayonet tube whose lugs come from craft.bayonet, printed with the matching socket ring (the lens side, as a test
coupon) and declared as an assembly that twists to unlock. Form Studio exemplar design."""
import math

from build123d import Align, Box, Cone, Cylinder, Pos, RegularPolygon, Rot, extrude

from form import craft, parts
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Bayonet lens cap",
    "category": "consumer",
    "tags": ["lens cap", "cap", "lid", "bayonet", "twist lock", "camera", "lens", "grip", "ribs", "logo", "emboss",
             "deboss", "consumer", "quarter turn", "socket", "assembly"],
    "techniques": ["craft.bayonet: male lugs and the female cutter in one frame, the male turned twist - 2 deg to lock",
                   "socket ring printed beside the cap as a test coupon", "cap modelled locked, printed face-down "
                   "with Rot(180, 0, 0)", "craft.wrapped_ribs grip trimmed by a chamfered envelope so the ribs fade "
                   "out", "recessed logo field with a raised generic mark (RegularPolygon aperture + ring)",
                   "hinge() for the unlock twist"],
    "lessons": [
        "Use craft.bayonet's shared frame: cut female_cutter from the socket and keep the male with the SAME transform; "
        "turned by twist - 2 deg it sits locked with 2 deg of margin before the end of the slot, and the assembly "
        "hinge back to 0 is the unlock.",
        "Print the socket as a coupon before the cap: the clearance (0.3 mm a side here) and the lug depth decide "
        "whether it turns, and a 5-minute ring tells you before a 40-minute cap does.",
        "A cap is held by its rim, so the grip goes there: fine ribs on the skirt, trimmed by a chamfered envelope so "
        "they fade in and out instead of ending square; the front stays calm with one considered detail.",
        "Put a logo in a recessed field with a raised mark inside it: the field protects the mark from scuffs, and the "
        "mark prints crisp face-down on the bed. Use a generic mark (an aperture here), never someone's trademark.",
        "Print face-down: the front is the bed face (flat and glossy), the skirt and tube rise from it, and the lugs "
        "are short 1.6 mm overhangs.",
    ],
}


class Design(Recipe):
    title, summary = "Bayonet lens cap", "Twist-lock lens cap with a ribbed grip, logo field and a matching socket ring."
    solids = 2
    params = [
        Param("tube_d", "Bayonet tube diameter", 50, 36, 72, 0.5, "mm", "brief", "bayonet",
              "Lens side: measure the socket bore and subtract twice the clearance."),
        Param("lugs", "Lugs", 3, 2, 4, 1, "", "form", "bayonet"),
        Param("twist", "Twist to lock", 30, 20, 45, 1, "deg", "form", "bayonet"),
        Param("clearance", "Bayonet clearance / side", 0.3, 0.15, 0.5, 0.05, "mm", "interface", "bayonet"),
        Param("grip_ribs", "Grip ribs", 60, 24, 90, 1, "", "form", "grip"),
        Param("logo_d", "Logo field diameter", 26, 14, 40, 0.5, "mm", "form", "logo"),
    ]
    features = [Feature("socket", "Socket ring (coupon)", "interface"), Feature("plate", "Front plate", "structure"),
                Feature("bayonet", "Bayonet tube and lugs", "interface"), Feature("grip", "Grip ring", "finish"),
                Feature("logo", "Logo field", "finish")]

    H, PLATE_T, SKIRT_H, LUG_W, LUG_H, LUG_D, RING_WALL, EXT = 8.0, 2.4, 6.0, 8.0, 2.4, 1.6, 2.4, 2.0

    def constraints(self, v):
        r = v["tube_d"] / 2
        if int(v["lugs"]) * (math.degrees(self.LUG_W / r) + v["twist"]) >= 330:
            return [RecipeError("The lugs and their twist do not fit round the tube", "bayonet",
                                "Use fewer lugs or less twist.", ["lugs", "twist"])]
        if v["logo_d"] > v["tube_d"] - 6:
            return [RecipeError("The logo field is wider than the front's flat", "logo", "Make it smaller.", ["logo_d"])]
        return []

    def _bay(self, v):
        return craft.bayonet(d=v["tube_d"], height=self.H, lugs=int(v["lugs"]), lug_w=self.LUG_W, lug_h=self.LUG_H,
                             lug_depth=self.LUG_D, twist=v["twist"], clearance=v["clearance"], wall=2.0)

    def _radii(self, v):
        r, c = v["tube_d"] / 2, v["clearance"]
        R2 = math.hypot(r + self.LUG_D, self.LUG_W / 2) + c            # the lock slot's outer radius
        ring_o = R2 + self.RING_WALL
        skirt_i = ring_o + 0.6
        skirt_o = skirt_i + 2.4
        return r, R2, ring_o, skirt_i, skirt_o

    def build(self, v):
        bay = self._bay(v)
        r, R2, ring_o, skirt_i, skirt_o = self._radii(v)
        H, tp, ext, c = self.H, self.PLATE_T, self.EXT, v["clearance"]
        n = int(v["lugs"])
        # socket ring (the lens side as a coupon): a tube with the bayonet's female cutter, chamfered outside.
        # craft.bayonet puts the lugs 1 mm below the male's top, so a socket that ends at `height` keeps under 1 mm of
        # lip over the lock slots; extend the socket (and its bore and entry slots) by ext - 0.5 for a real lip, and
        # the male tube by ext.
        Hr = H + ext - 0.5
        ring = Cylinder(ring_o, Hr, align=BOTTOM)
        ring = craft.attempt("ring chamfer", [("0.8 mm", lambda: ring.chamfer(0.8, None, ring.edges())),
                                              ("sharp", lambda: ring)], "", ["tube_d"])
        ring = ring - bay.shapes["female_cutter"]
        more = Pos(0, 0, H - 0.1) * Cylinder(r + c, ext + 0.2, align=BOTTOM)
        for i in range(n):
            more = more + Rot(0, 0, i * 360 / n) * Pos((r + R2) / 2, 0, H - 0.1) * Box(R2 - r + 0.4, self.LUG_W + 2 * c,
                                                                                    ext + 0.2, align=BOTTOM)
        ring = ring - more
        lay = Pos(skirt_o + ring_o + 12, 0, 0)
        stages = [Stage("socket", lay * ring)]
        # the cap, modelled in the socket's frame and locked: male tube turned twist - 2, plate on top of it
        # --- snippet: one frame for both halves; the male turned twist - 2 deg is the locked pose
        male = Rot(0, 0, v["twist"] - 2) * bay.shapes["male"]
        male = male + Pos(0, 0, H - 0.2) * (Cylinder(r, ext + 0.4, align=BOTTOM) - Cylinder(r - 2.0, ext + 1, align=BOTTOM))
        plate = Pos(0, 0, H + ext - 0.2) * Cylinder(skirt_o, tp + 0.2, align=BOTTOM)
        cap = craft.fuse(plate, male)
        # --- end snippet
        top = H + ext + tp
        flip = lambda s: Pos(0, 0, top) * Rot(180, 0, 0) * s          # printed face-down
        stages.append(Stage("plate", lay * ring + flip(plate)))
        stages.append(Stage("bayonet", lay * ring + flip(cap)))
        # grip ring: a skirt round the socket, with ribs that fade in and out (trimmed by a chamfered envelope)
        zs = H + ext - self.SKIRT_H
        skirt = Pos(0, 0, zs) * (Cylinder(skirt_o, self.SKIRT_H + 0.2, align=BOTTOM)
                                 - Pos(0, 0, -1) * Cylinder(skirt_i, self.SKIRT_H + 2, align=BOTTOM))
        cap = craft.fuse(cap, skirt)
        # --- snippet: grip ribs that fade out: wrapped_ribs intersected with a double-chamfered envelope
        rib_h = 0.8
        ribs = craft.wrapped_ribs(skirt_o, self.SKIRT_H + tp - 1.0, count=int(v["grip_ribs"]), rib_w=1.4, rib_h=rib_h,
                                  z0=zs + 0.5, core=False)
        env = Pos(0, 0, zs + 0.5) * (Cone(skirt_o - 0.3, skirt_o + rib_h, 1.6, align=BOTTOM)
                                     + Pos(0, 0, 1.6) * Cylinder(skirt_o + rib_h, self.SKIRT_H + tp - 1.0 - 3.2, align=BOTTOM)
                                     + Pos(0, 0, self.SKIRT_H + tp - 1.0 - 1.6) * Cone(skirt_o + rib_h, skirt_o - 0.3, 1.6,
                                                                                   align=BOTTOM))
        cap = craft.fuse(cap, ribs & env)
        # --- end snippet
        rim = [e for e in cap.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - skirt_o) < 1e-3
               and abs(e.center().Z - top) < 1e-3]
        cap = craft.safe_fillet(cap, rim, 0.9)
        stages.append(Stage("grip", lay * ring + flip(cap)))
        # logo field: a 0.5 mm recess in the front with a raised aperture mark (hexagon + ring), 0.3 below the face
        zf = top
        L = v["logo_d"]
        cap = cap - Pos(0, 0, zf - 0.5) * Cylinder(L / 2, 1.0, align=BOTTOM)
        mark = (Cylinder(L * 0.36, 0.2, align=BOTTOM) - Pos(0, 0, -0.1) * Cylinder(L * 0.36 - 1.0, 0.4, align=BOTTOM)
                + extrude(RegularPolygon(L * 0.2, 6), 0.2) - Pos(0, 0, -0.1) * extrude(RegularPolygon(L * 0.2 - 0.9, 6), 0.4))
        cap = craft.fuse(cap, Pos(0, 0, zf - 0.5 - 0.01) * mark)
        stages.append(Stage("logo", lay * ring + flip(cap)))
        return parts.checked(stages)

    def derived(self, v):
        bay = self._bay(v)
        r, R2, ring_o, skirt_i, skirt_o = self._radii(v)
        return bay.derived("bayonet", "bayonet.") + [
            {"key": "cap_d", "label": "Cap outside diameter", "value": round(2 * skirt_o, 2), "unit": "mm",
             "feature": "grip", "formula": "socket ring + 0.6 gap + 2.4 skirt, each side", "interface": False},
            {"key": "lock_margin", "label": "Lock margin before the slot end", "value": 2, "unit": "deg",
             "feature": "bayonet", "formula": "locked at twist - 2 deg", "interface": True}]

    def assembly(self, v):
        r, R2, ring_o, skirt_i, skirt_o = self._radii(v)
        lx = skirt_o + ring_o + 12
        top = self.H + self.EXT + self.PLATE_T
        return Assembly(
            parts=[Part("socket", "Socket ring (lens side)", (lx + (r + v["clearance"] + ring_o) / 2, 0, 1.0),
                        move=(-lx, 0, 0), note="The lens side: here the printed test ring."),
                   Part("cap", "Cap", (skirt_o - 1.2, 0, 1.0), move=(0, 0, top), rotate=(180, 0, 0), explode=(0, 0, 25),
                        note="Lugs into the entry slots, push, turn clockwise to lock.")],
            joints=[hinge("cap", (0, 0, 1), (0, 0, 0), (-(v["twist"] - 2), 0), 9, parent="socket", id="twist",
                          label="Unlock twist")])

    def appearance(self, v):
        return [{"features": ["plate", "bayonet", "logo"], "finish": "matte", "color": "#16181b"},
                {"features": ["grip"], "finish": "rubber", "color": "#101113"},
                {"features": ["socket"], "finish": "petg", "color": "#7a8088"}]
