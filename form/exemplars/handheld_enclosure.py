"""Handheld device shell (a remote or small instrument): a soft pebble-like body lofted from superellipse sections,
hollowed along the normal and split into a front and a back half at a parting line with a lap joint and a shadow
reveal, a display window with a lens recess, a navigation and button field, and internal screw bosses (M2 screws
from the back into heat-set inserts in the front). Form Studio exemplar design."""
import math

from build123d import Align, Box, Cylinder, Pos, RectangleRounded, Rot, extrude

from form import craft, parts
from form.recipes.base import (Access, Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError,
                               Stage)

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Handheld device shell with lap joint",
    "category": "enclosure",
    "tags": ["handheld", "remote", "remote control", "controller", "instrument", "device", "enclosure", "shell",
             "housing", "two-part", "parting line", "lap joint", "reveal", "display", "buttons", "bosses", "loft",
             "organic"],
    "techniques": ["craft.checked_body: superellipse sections whose plan insets trace a round-over in elevation",
                   "the same section law offset by wall, wall / 2 and wall / 2 + clearance: one law for the "
                   "shell, the lip and the rebate", "lap joint and shadow reveal from slabs of those bodies",
                   "display window with a lens recess, button holes with rounded mouths",
                   "split bosses: parts.screw_clearance from the back, parts.heat_insert_pocket in the front",
                   "assembly() with hardware and tool access"],
    "lessons": [
        "Round the edges in the sections, not with a fillet: each section's plan is inset by r - sqrt(r^2 - (r - d)^2) "
        "at distance d from a face, so the stack traces a round-over of radius r and the loft is one smooth skin with "
        "flat faces for the display and the buttons. A 7 mm round on a 22 mm body is what makes it read as held, not "
        "machined.",
        "Derive every surface of the joint from the same law: body(d) is the slab shrunk by d with its round shrunk "
        "by d (concentric, so the wall is even through the round). The shell is body(0) - body(wall); the back's lip "
        "is body(wall / 2 + clearance) - body(wall) in a slab above the parting line; the front's rebate removes "
        "body(wall / 2) there. Lip, rebate and clearance follow the curved wall with no extra sketch.",
        "Do not hide a parting line, design it: two moulded or printed halves never meet perfectly, so a 0.4 mm shadow "
        "reveal makes the seam a deliberate dark line and hides any step. The lap behind it stops light leaks and "
        "lets the halves locate each other.",
        "Split bosses: the screw comes from the back (a counterbored clearance hole in a flat part of the back) into a "
        "heat-set insert in the front boss, so the front face carries no screw heads. The bosses stop short of each "
        "other by the same gap as the joint, so the lap, not the bosses, sets the closed height.",
        "Lay the face out on a grid that follows the form: the display near the narrow end, the navigation ring on the "
        "centre line, the buttons in pairs below, all inside the flat zone of the face (plan inset by the round), so "
        "every opening is a clean cut through a flat wall.",
    ],
}


class Design(Recipe):
    title, summary = "Handheld shell", ("Lofted handheld housing split at a lap joint with a reveal: display window, "
                                        "buttons and split screw bosses.")
    solids = 2
    params = [
        Param("length", "Length", 150, 140, 190, 1, "mm", "form", "shell"),
        Param("width", "Width", 56, 53, 70, 1, "mm", "form", "shell"),
        Param("thick", "Thickness", 22, 19, 30, 0.5, "mm", "form", "shell"),
        Param("round_r", "Edge round", 6.5, 4, 8, 0.5, "mm", "form", "shell", "Round-over of the faces into the sides."),
        Param("taper", "Front taper", 0.08, 0.0, 0.15, 0.01, "", "form", "shell", "Narrows the display end (+X)."),
        Param("wall", "Wall", 2.0, 1.6, 2.6, 0.1, "mm", "form", "shell"),
        Param("part_z", "Parting line height", 9, 7, 12, 0.5, "mm", "form", "parting", "From the back face."),
        Param("lap_clearance", "Lap clearance / side", 0.3, 0.3, 0.5, 0.05, "mm", "interface", "parting",
              "Also the gap at the top of the lip: the halves stay separate bodies."),
        Param("display_w", "Display window length", 30, 22, 40, 1, "mm", "brief", "window", "Along X."),
        Param("display_h", "Display window width", 22, 16, 24, 1, "mm", "brief", "window"),
    ]
    features = [Feature("shell", "Lofted shell", "structure"), Feature("parting", "Lap joint and reveal", "interface"),
                Feature("window", "Display window", "access"), Feature("buttons", "Button holes", "access"),
                Feature("bosses", "Screw bosses", "interface")]
    N = 3.2                                             # plan squareness: a soft rectangle

    def constraints(self, v):
        T, r, zp = v["thick"], v["round_r"], v["part_z"]
        if zp - 0.2 < r or zp + 2.6 + v["lap_clearance"] > T - r:
            return [RecipeError("The lap joint must sit on the straight part of the side wall, between the rounds",
                                "parting", "Move the parting line, use a smaller round or a thicker body.",
                                ["part_z", "round_r", "thick"])]
        lay = self._layout(v)
        xr = lay["xd"] + (v["display_w"] + 5) / 2
        if (v["display_h"] + 5) / 2 + 0.5 > self._flat(v, xr):
            return [RecipeError("The display recess runs off the flat of the face", "window", "Shorten or narrow the "
                                "display, or widen the body.", ["display_w", "display_h", "width"])]
        if any(abs(y) + 2.8 > self._flat(v, x) for x, y in lay["bosses"]):
            return [RecipeError("A screw boss falls off the flat of the back", "bosses", "Narrow the display (the "
                                "front bosses stand beside it) or widen the body.", ["display_h", "width"])]
        if lay["holes"][-1][0] - 4 < -v["length"] / 2 + 22:
            return [RecipeError("The buttons run into the end", "buttons", "Lengthen the body or shorten the display.",
                                ["length", "display_w"])]
        return []

    def _flat(self, v, x):
        """Half-width of the flat face at x (the plan outline inset by the round)."""
        a, b, s = v["length"] / 2, v["width"] / 2, v["taper"]
        u = min(abs(x) / a, 0.999)
        y = b * (1 - u ** self.N) ** (1 / self.N) * (1 - s * u * u if x > 0 else 1)
        return y - v["round_r"]

    def _layout(self, v):
        """The face on a grid along the centre line: display near the narrow end, navigation ring, three button pairs;
        bosses beside the display's inner end and at the far end."""
        L, dw, dh = v["length"], v["display_w"], v["display_h"]
        xd = 0.78 * L / 2 - (dw + 5) / 2              # the recess ends at 78 % of the half-length, where the face is wide
        xn = xd - dw / 2 - 16
        holes = [(xn, 0.0, 8.5)] + [(xn - 21 - 13 * k, sy * 9.0, 4.0) for k in range(3) for sy in (-1, 1)]
        bosses = [(xd - dw / 2 - 7.5, sy * (dh / 2 + 4.0)) for sy in (-1, 1)] + \
                 [(-L / 2 + 24, sy * 10.0) for sy in (-1, 1)]
        return {"xd": xd, "xn": xn, "holes": holes, "bosses": bosses}

    def _sections(self, v, d=0.0):
        """The body's sections, or (d > 0) those of the body offset inward by d: the slab shrinks by d on every side
        and the round's radius by d, so the round-over stays concentric and the wall is d thick everywhere."""
        L, W, T, r = v["length"] - 2 * d, v["width"] - 2 * d, v["thick"] - 2 * d, v["round_r"] - d

        def inset(z):                                   # plan inset at height z: a quarter round near each face
            dz = min(z, T - z)
            return r - math.sqrt(max(r * r - (r - dz) ** 2, 0.0)) if dz < r else 0.0
        # the first step is 0.2 r high: steep enough to read as a round, gentle enough not to fold the loft
        zs = [0, 0.2 * r, 0.4 * r, 0.65 * r, r] + ([T / 2] if T - 2 * r > 3 else [])
        zs = sorted({round(z, 4) for z in zs + [T - z for z in zs]})
        return [{"z": z + d, "a": L / 2 - inset(z), "b": W / 2 - inset(z), "n": self.N, "squash": v["taper"],
                 "seam": 180} for z in zs]

    def _wall_prism(self, v, d, z0, z1):
        """The body offset by d, only where the side wall is straight (between the rounds): a prism of the plan."""
        f = craft.superellipse_face(v["length"] / 2 - d, v["width"] / 2 - d, self.N, squash_front=v["taper"], seam=180)
        return Pos(0, 0, z0) * extrude(f, z1 - z0)

    def build(self, v):
        T, t, zp, c = v["thick"], v["wall"], v["part_z"], v["lap_clearance"]
        L, W = v["length"], v["width"]
        outer = craft.checked_body(self._sections(v), label="handheld shell")
        inner = craft.section_body(self._sections(v, t))
        shell = craft.cut(outer, inner)
        stages = [Stage("shell", shell)]

        # --- snippet: lap joint with a shadow reveal, every surface an offset of the same plan
        lap, g = 2.6, 0.4                                       # lip height; reveal at the parting line
        slab = lambda z0, z1: Pos(0, 0, z0) * Box(2 * L, 2 * W, z1 - z0, align=BOTTOM)
        back = shell & slab(-1, zp)
        lip = self._wall_prism(v, t / 2 + c, zp - 0.2, zp + lap) - inner      # inner half of the wall, c inside the mid
        back = craft.fuse(back, lip)
        front = shell & slab(zp + g, T + 1)
        front = craft.cut(front, self._wall_prism(v, t / 2, zp, zp + lap + c))  # rebate: the front's inner half
        body = craft.fuse(back, front, max_solids=2, min_solids=2)
        # --- end snippet
        stages.append(Stage("parting", body))

        lay = self._layout(v)
        xd, dw, dh = lay["xd"], v["display_w"], v["display_h"]
        recess = Pos(xd, 0, T - 1.2) * extrude(RectangleRounded(dw + 5, dh + 5, 3.0), 3)
        window = Pos(xd, 0, T - t - 1) * extrude(RectangleRounded(dw, dh, 2.0), t + 3)
        front = craft.cut(craft.cut(front, recess), window)
        body = craft.fuse(back, front, max_solids=2, min_solids=2)
        stages.append(Stage("window", body))

        for x, y, r in lay["holes"]:
            front = craft.cut(front, Pos(x, y, T - t - 1) * Cylinder(r, t + 3, align=BOTTOM))
        mouths = [e for e in front.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - T) < 0.01]
        front = craft.safe_fillet(front, mouths, 0.6)
        body = craft.fuse(back, front, max_solids=2, min_solids=2)
        stages.append(Stage("buttons", body))

        # split bosses: M2 from the back (counterbored in the flat of the back) into inserts in the front bosses
        ins = parts.heat_insert_pocket("M2")
        cs = parts.screw_clearance("M2", zp + 1.0, head="socket")
        bd = max(6.4, ins["boss_min_d"] + 0.6)
        zm = zp + 1.0                                           # the bosses meet here, 2 x 0.15 mm apart
        for x, y in lay["bosses"]:
            back = back + Pos(x, y, t - 0.3) * Cylinder(bd / 2, zm - 0.15 - (t - 0.3), align=BOTTOM)
            back = back - Rot(180, 0, 0) * Pos(x, -y, 0) * cs.shape          # head recess opens on the back face
            front = front + Pos(x, y, zm + 0.15) * Cylinder(bd / 2, T - t + 0.3 - (zm + 0.15), align=BOTTOM)
            front = front - Pos(x, y, zm + 0.15) * Rot(180, 0, 0) * ins.shape
        body = craft.fuse(back, front, max_solids=2, min_solids=2)
        stages.append(Stage("bosses", body))
        return parts.checked(stages)

    def derived(self, v):
        return parts.heat_insert_pocket("M2").derived("bosses", "insert.") + [
            {"key": "lap_clearance", "label": "Lap clearance per side", "value": v["lap_clearance"], "unit": "mm",
             "feature": "parting", "formula": "assumed; also the gap over the lip", "interface": True},
            {"key": "reveal", "label": "Parting-line reveal", "value": 0.4, "unit": "mm", "feature": "parting",
             "formula": "shadow gap between the halves", "interface": False},
            {"key": "flat_face", "label": "Flat of the face at the display", "unit": "mm", "feature": "window",
             "value": round(2 * self._flat(v, self._layout(v)["xd"]), 1),
             "formula": "plan width - 2 x edge round", "interface": False}]

    def assembly(self, v):
        T, zp = v["thick"], v["part_z"]
        xd = self._layout(v)["xd"]
        return Assembly(
            parts=[Part("back", "Back half", (0, 0, v["wall"] / 2), note="Lay the board in the back half."),
                   Part("front", "Front half", (xd, v["display_h"] / 2 + 3.0, T - 0.5), explode=(0, 0, 25),
                        note="Press the four M2 inserts into the front bosses, close the halves (lip into rebate).")],
            mates=[Mate("front", "back", "slip", v["lap_clearance"], "Lap joint")],
            hardware=[Hardware("M2 heat-set insert", "M2 x 3", 4, "CNC Kitchen", "Press into the front bosses.",
                               after="front"),
                      Hardware("M2 socket screw", f"M2 x {int(round(zp + 4))}", 4, "ISO 4762", "From the back.",
                               after="front",
                               access=tuple(Access((x, y, 0.0), (0, 0, 1), 4.0, 40) for x, y in self._layout(v)["bosses"]))])

    def appearance(self, v):
        return [{"features": ["window", "buttons"], "finish": "matte", "color": "#25282c"},
                {"features": ["shell", "parting", "bosses"], "finish": "matte", "color": "#c9ccd0"}]
