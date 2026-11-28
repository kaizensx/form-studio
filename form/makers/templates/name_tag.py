"""Name tag or keychain, made by Form Studio's name_tag generator: lettering in real font outlines (Form Studio's
bundled font, Instrument Sans 700, SIL OFL 1.1), raised from or engraved into a rounded plate, with an optional
keyring hole. The plate grows with the text. MAKE holds the text the generator was given; change it there or with
the parameters below."""
from build123d import Align, Axis, Box, Cylinder, Pos

from form import craft, marks
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
BED = 175.0

MAKE = {
    "generator": "name_tag",
    "text": "FORM",
}


class Design(Recipe):
    title, summary = "Name tag", "Raised or engraved lettering on a rounded plate, with an optional keyring hole."
    category, tags = "Makers", ("keychain", "name tag", "text")
    params = [
        Param("cap_h", "Letter height", 8, 4, 30, 0.5, "mm", "form", "text",
              "Height of a capital letter. Under 4 mm FDM lettering is hard to read."),
        Param("depth", "Letter depth", 1.0, 0.4, 3, 0.1, "mm", "form", "text",
              "How far the letters stand out (raised) or go in (engraved)."),
        Param("sunk", "Engraved", 0, 0, 1, 1, "", "form", "text", "0 = raised letters, 1 = letters cut into the plate."),
        Param("plate_t", "Plate thickness", 3, 1.6, 8, 0.1, "mm", "form", "plate"),
        Param("margin", "Margin", 4, 2, 15, 0.5, "mm", "form", "plate", "Plate around the lettering."),
        Param("corner_r", "Corner radius", 3, 0.5, 10, 0.5, "mm", "form", "plate"),
        Param("ring", "Keyring hole", 1, 0, 1, 1, "", "form", "ring", "1 = a round tab with a hole on the left."),
        Param("ring_d", "Hole diameter", 4.5, 3, 8, 0.1, "mm", "brief", "ring", "A split ring needs 4 to 5 mm."),
        Param("ring_wall", "Ring wall", 2.6, 1.6, 5, 0.1, "mm", "form", "ring", "Material around the hole: it carries the keys."),
    ]
    features = [Feature("plate", "Plate", "structure"), Feature("ring", "Keyring hole", "structure"),
                Feature("text", "Lettering", "finish")]

    def text(self):
        return marks.clean(MAKE.get("text", ""))

    def constraints(self, v):
        if not self.text():
            return [RecipeError("The text is empty", "text", "Put the letters in MAKE['text'].")]
        if v["sunk"] >= 0.5 and v["depth"] > v["plate_t"] - 1.0:
            return [RecipeError("Engraved letters would leave under 1 mm of plate behind them", "text",
                                "Make the letters shallower or the plate thicker.", ["depth", "plate_t"])]
        if v["corner_r"] > v["margin"] + v["cap_h"] / 2:
            return [RecipeError("The corner radius is larger than half the plate", "plate", "Reduce the corner radius.",
                                ["corner_r"])]
        return []

    def _size(self, v):
        bb = marks.sketch(self.text(), v["cap_h"]).bounding_box()
        w = bb.size.X + 2 * v["margin"]
        h = max(bb.size.Y, v["cap_h"]) + 2 * v["margin"]
        rr = v["ring_d"] / 2 + v["ring_wall"]
        total = w + (2 * rr - v["margin"] * 0.5 if v["ring"] >= 0.5 else 0)
        return w, h, rr, total

    def build(self, v):
        w, h, rr, total = self._size(v)
        if total > BED:
            raise RecipeError(f"The tag is {total:.0f} mm long and does not fit a {BED:g} mm bed", "plate",
                              "Use fewer letters or smaller ones.", ["cap_h", "margin"])
        t = v["plate_t"]
        plate = Box(w, h, t, align=BOTTOM)
        plate = craft.safe_fillet(plate, plate.edges().filter_by(Axis.Z), min(v["corner_r"], h / 2 - 0.1))
        stages = [Stage("plate", plate)]
        body = plate
        if v["ring"] >= 0.5:
            cx = -w / 2 - rr + v["margin"] * 0.5
            x1 = -w / 2 + v["corner_r"] + 0.5                 # the bridge reaches past the plate's rounded corners
            tab = Pos(cx, 0, 0) * Cylinder(rr, t, align=BOTTOM) + Pos((cx + x1) / 2, 0, 0) * Box(
                x1 - cx, min(2 * rr, h), t, align=BOTTOM)
            body = craft.fuse(body, tab)
            body = craft.cut(body, Pos(cx, 0, -0.1) * Cylinder(v["ring_d"] / 2, t + 0.2, align=BOTTOM))
        stages.append(Stage("ring", body))
        put = marks.deboss_text if v["sunk"] >= 0.5 else marks.emboss_text
        body = put(body, self.text(), on=(0, 0, t), normal=(0, 0, 1), height=v["cap_h"], depth=v["depth"])
        stages.append(Stage("text", body))
        return stages

    def derived(self, v):
        w, h, rr, total = self._size(v)
        info = marks.analyse(self.text(), v["cap_h"], v["depth"])
        out = [{"key": "tag_length", "label": "Tag length", "value": round(total, 2), "unit": "mm", "feature": "plate",
                "formula": "text width + 2 x margin (+ ring tab)", "interface": False},
               {"key": "tag_height", "label": "Tag height", "value": round(h, 2), "unit": "mm", "feature": "plate",
                "formula": "text height + 2 x margin", "interface": False}]
        stroke = info.get("min_stroke_mm") or info.get("stroke_mm")
        if isinstance(stroke, (int, float)):
            out.append({"key": "min_stroke", "label": "Thinnest letter stroke (estimate)", "value": round(stroke, 2),
                        "unit": "mm", "feature": "text", "formula": "2 x glyph area / outline length", "interface": False})
        return out
