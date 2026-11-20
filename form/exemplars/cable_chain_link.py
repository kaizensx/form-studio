"""Cable drag-chain link: joggled side plates with a snap pin at one end and a socket at the other, and crossbars top
and bottom. Links snap into each other. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Cable-chain link",
    "tags": ["cable chain", "drag chain", "chain", "link", "snap", "pin", "joint", "3d printer", "mechanism"],
    "techniques": ["joggled side plates (inner at the pin end, outer at the socket end)", "snap pin with a lead-in",
                   "socket with clearance", "joggle sized to clear the next link", "crossbars"],
    "lessons": [
        "Design the joint first: pin, socket, clearance, and what the next link sweeps when it turns. Here the joggle "
        "is sized from that sweep (it ends before the next link's round end), and the clearance is in derived().",
        "The inner plates (pin end) sit one plate thickness inside the outer plates (socket end), so each link nests in "
        "the next and the pins point outward into the next link's sockets.",
        "A production chain adds bend stops (shoulders that meet at the cables' bend radius) and a relief slit in the "
        "pin; add them as features of their own, each checked against the next link in assembly().",
        "Crossbars carry the cables: keep them inside the plate outline so nothing snags.",
    ],
}


class Design(Recipe):
    title, summary = "Cable chain link", "Drag-chain link with joggled plates, snap pins, sockets and crossbars."
    solids = 1
    params = [
        Param("inner_w", "Inside width", 18, 8, 60, 0.5, "mm", "brief", "crossbars", "Cable bundle width + 2 mm."),
        Param("inner_h", "Inside height", 12, 6, 40, 0.5, "mm", "brief", "plates", "Cable bundle height + 2 mm."),
        Param("pitch", "Pitch", 22, 14, 60, 0.5, "mm", "form", "plates"),
        Param("plate_t", "Plate thickness", 2.0, 1.4, 3.5, 0.1, "mm", "form", "plates"),
        Param("pin_d", "Pin diameter", 5.0, 3, 8, 0.1, "mm", "interface", "pins"),
        Param("clearance", "Pin clearance / side", 0.2, 0.1, 0.4, 0.05, "mm", "interface", "pins"),
    ]
    features = [Feature("plates", "Side plates", "structure"), Feature("pins", "Snap pins", "interface"),
                Feature("sockets", "Sockets", "interface"), Feature("crossbars", "Crossbars", "structure")]

    def constraints(self, v):
        if v["pitch"] < v["inner_h"] + 6 + 3:
            return [RecipeError("The pitch is too short: neighbouring links would touch", "plates",
                                "Make the pitch at least the plate height + 3 mm.", ["pitch", "inner_h"])]
        if v["pin_d"] + 3 > v["inner_h"] + 6:
            return [RecipeError("The pin is too large for the plate height", "pins", "Use a smaller pin.", ["pin_d"])]
        return []

    def _joggle_w(self, v):
        P, r = v["pitch"], (v["inner_h"] + 6) / 2
        return min(P * 0.3, P - 2 * r - 1.0)

    def build(self, v):
        P, t, Hh, W = v["pitch"], v["plate_t"], v["inner_h"] + 6, v["inner_w"]
        r = Hh / 2
        yo = W / 2 + t * 1.5                       # outer plates at the socket end
        yi = W / 2 + t * 0.5                       # inner plates at the pin end, one plate thickness inward

        def half(xc, y):
            """Half a side plate: a round end at x = xc, running to the middle of the link."""
            end = Pos(xc, y, r) * Rot(90, 0, 0) * Cylinder(r, t)
            mid = Pos((xc + P / 2) / 2, y, r) * Box(abs(P / 2 - xc), t, Hh)
            return end + mid

        body = None
        jw = self._joggle_w(v)
        for sy in (-1, 1):
            side = half(0, sy * yi) + half(P, sy * yo)
            # the joggle joins the halves; it ends before the next link's round end (x < P - r)
            side = side + Pos(P / 2, sy * (yi + yo) / 2, r) * Box(jw, yo - yi + t, Hh)
            body = side if body is None else body + side
        body = craft.safe_fillet(body, [e for e in body.edges().filter_by(Axis.Y)], 0.6)
        stages = [Stage("plates", body)]
        pd, c = v["pin_d"], v["clearance"]
        for sy in (-1, 1):                         # snap pins on the inner plates, pointing outward, with a lead-in
            pin = Pos(0, sy * (yi + t / 2), r) * Rot(-90 * sy, 0, 0) * (Cylinder(pd / 2, t + 0.4, align=BOTTOM) +
                                                                        Pos(0, 0, t + 0.4) * Cylinder(pd / 2 - 0.3, 0.8, align=BOTTOM))
            body = body + pin
        stages.append(Stage("pins", body))
        for sy in (-1, 1):
            body = body - Pos(P, sy * yo, r) * Rot(90, 0, 0) * Cylinder(pd / 2 + c, t + 1)
        stages.append(Stage("sockets", body))
        for z in (t / 2 + 0.6, Hh - t / 2 - 0.6):  # crossbars top and bottom, between the outer plates
            body = body + Pos(P * 0.5, 0, z) * Box(P * 0.42, 2 * yo, t + 0.4)
        stages.append(Stage("crossbars", body))
        return parts.checked(stages)

    def derived(self, v):
        P, r = v["pitch"], (v["inner_h"] + 6) / 2
        return [{"key": "socket_d", "label": "Socket diameter", "value": v["pin_d"] + 2 * v["clearance"], "unit": "mm",
                 "feature": "sockets", "formula": "pin + 2 x clearance", "interface": True},
                {"key": "link_gap", "label": "Clearance to the next link's round end",
                 "value": (P - r) - (P / 2 + self._joggle_w(v) / 2), "unit": "mm", "feature": "plates",
                 "formula": "(P - r) - (P / 2 + joggle / 2)", "interface": True}]
