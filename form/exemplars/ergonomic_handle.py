"""Ergonomic tool handle: a lofted grip that swells under the palm, with a finger guard, an oval section that does
not turn in the hand, a hex socket for 1/4" bits, a ferrule groove, a lanyard hole and a leather-grain mesh texture.
Form Studio exemplar design."""
import math

from build123d import Align, Axis, Cylinder, Pos, RegularPolygon, Rot, Torus, extrude

from form import craft, parts
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Ergonomic handle",
    "category": "organic",
    "tags": ["handle", "grip", "ergonomic", "tool", "screwdriver", "organic", "texture", "grain", "hand", "loft",
             "mesh texture"],
    "techniques": ["craft.section_body along the axis from a diameter law", "oval sections (n ~ 2.2, a > b)",
                   "palm swell offset (cy) at 40 % of the length", "finger guard section", "hex socket from published "
                   "bit size", "MeshTexture grain on the grip only"],
    "lessons": [
        "Size from the hand: a power grip is 30-38 mm across, 100-120 mm long; the swell sits under the palm at about "
        "40 % of the length from the butt, not in the middle.",
        "An oval section (wider one way) tells the hand where 'up' is and stops the handle turning under torque.",
        "Describe the handle as sections along its axis following a smooth diameter law; then add a guard section "
        "near the working end so fingers do not slide onto the blade.",
        "Functional details are real geometry (hex socket, ferrule groove, lanyard hole); the grip grain is a mesh "
        "texture on the grip feature only, so the socket and the ends stay crisp.",
    ],
}


class Design(Recipe):
    title, summary = "Ergonomic handle", "Lofted oval handle with palm swell, finger guard, 1/4\" hex socket and grain."
    solids = 1
    photo_color = "#3f5f4a"
    params = [
        Param("length", "Length", 115, 80, 160, 1, "mm", "brief", "grip"),
        Param("d_max", "Palm swell diameter", 36, 26, 46, 0.5, "mm", "brief", "grip", "30-38 mm suits most hands."),
        Param("d_end", "End diameter", 28, 20, 40, 0.5, "mm", "form", "grip"),
        Param("oval", "Oval ratio", 0.86, 0.7, 1.0, 0.01, "", "form", "grip", "Thickness / width of the section."),
        Param("guard", "Guard lift", 3.0, 0, 6, 0.5, "mm", "form", "guard"),
        Param("grain", "Grain depth", 0.3, 0, 0.6, 0.05, "mm", "form", "grip", "0 = smooth. Mesh texture."),
    ]
    features = [Feature("grip", "Grip", "structure"), Feature("guard", "Finger guard", "structure"),
                Feature("nose", "Nose and ferrule groove", "finish"), Feature("socket", "Hex bit socket", "interface"),
                Feature("lanyard", "Lanyard hole", "access")]

    def constraints(self, v):
        if v["d_end"] > v["d_max"]:
            return [RecipeError("The ends are wider than the palm swell", "grip", "Make the ends smaller.", ["d_end"])]
        return []

    def _sections(self, v, upto=1.0):
        L, D1, D0, k = v["length"], v["d_max"], v["d_end"], v["oval"]
        K = math.log(0.5) / math.log(0.4)                        # peak of the swell at 40 % of the length
        secs = []
        for i in range(12):
            u = i / 11 * 0.82                                    # the grip runs to 82 % of the length, then the guard
            d = D0 + (D1 - D0) * math.sin(math.pi * min(1.0, u / 0.82) ** K) ** 0.9
            if u < 0.02:
                d *= 0.9                                         # soften the butt
            secs.append({"z": u * L, "a": d / 2, "b": d / 2 * k, "n": 2.25, "cy": 0.0, "cx": 0.0})
        return secs

    def build(self, v):
        L, D0 = v["length"], v["d_end"]
        secs = self._sections(v)
        # the guard: the section lifts by `guard` just past the grip, then necks into the nose
        zg = 0.86 * L
        g = v["guard"]
        guard = [{"z": zg, "a": D0 / 2 + g, "b": (D0 / 2 + g) * v["oval"], "n": 2.2},
                 {"z": zg + 4, "a": D0 / 2 + g * 0.8, "b": (D0 / 2 + g * 0.8) * v["oval"], "n": 2.15}]
        nose = [{"z": L * 0.95, "a": D0 * 0.42, "b": D0 * 0.42, "n": 2.0}, {"z": L, "a": D0 * 0.38, "b": D0 * 0.38, "n": 2.0}]
        grip = craft.section_body(secs, count=64)
        grip = craft.safe_fillet(grip, grip.edges().group_by(Axis.Z)[0], 5.0)
        stages = [Stage("grip", grip)]
        body = grip + craft.section_body([secs[-1]] + guard, count=64)
        stages.append(Stage("guard", body))
        body = body + craft.section_body([guard[-1]] + nose, count=64)
        # ferrule groove: a shallow round groove round the nose
        body = body - Pos(0, 0, L * 0.975) * Torus(D0 * 0.40 + 0.2, 0.9)
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.2)
        stages.append(Stage("nose", body))
        # hex socket for 1/4" bits: 6.35 mm across flats + 0.15 clearance, 25 mm deep, with a magnet pocket below
        hexd = 6.35 + 0.15
        sock = extrude(RegularPolygon(hexd / 2, 6, major_radius=False), 25.2)
        body = body - Pos(0, 0, L - 25) * sock
        mag = parts.magnet_pocket(6, 3)
        body = body - Pos(0, 0, L - 25) * mag.shape
        stages.append(Stage("socket", body))
        # lanyard hole across the butt, along the narrow axis
        body = body - Pos(0, 0, 9) * Rot(90, 0, 0) * Cylinder(2.6, 60)
        stages.append(Stage("lanyard", body))
        return parts.checked(stages)

    def mesh_texture(self, v):
        if v["grain"] <= 0:
            return []
        return [MeshTexture("grain", amplitude=v["grain"], scale=1.6, features=["grip"], edge_falloff=4.0)]

    def derived(self, v):
        return [{"key": "socket_af", "label": "Socket across flats", "value": 6.5, "unit": "mm", "feature": "socket",
                 "formula": "1/4 inch bit (6.35 mm) + 0.15 mm clearance", "interface": True}]
