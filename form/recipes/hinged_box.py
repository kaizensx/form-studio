"""Hinged box: a box and a lid printed side by side, joined by a pin through three knuckles.

The lid has a lip that drops into the box. When the lid opens, the front edge of that lip swings on an arc
about the hinge axis and can dig into the box's front wall; ``front_relief`` sets how far the lip front is
held back. The assembly checks sweep the hinge and report the angle where that happens.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot, fillet

from .. import marks
from .assembly import Access, Assembly, Hardware, Part, hinge
from .base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)
GAP = 8.0          # mm between box and lid on the plate


class HingedBox(Recipe):
    id = "hinged_box"
    legacy = True          # retired from the library: still opens and builds for designs that use it
    title = "Hinged box"
    summary = "A box and a lid joined by a pin hinge, printed side by side; the lid's lip is checked through its swing."
    solids = 2
    params = [
        Param("inner_w", "Inner width", 60, 30, 120, 0.5, "mm", "brief", "body", "What it must hold."),
        Param("inner_d", "Inner depth", 40, 20, 100, 0.5, "mm", "brief", "body"),
        Param("inner_h", "Inner height", 30, 12, 80, 0.5, "mm", "brief", "body"),
        Param("wall", "Wall", 2.0, 1.2, 4, 0.1, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 3, 0.5, 8, 0.5, "mm", "form", "body"),
        Param("lid_t", "Lid thickness", 2.4, 1.6, 4, 0.1, "mm", "form", "lid"),
        Param("knuckle_r", "Knuckle radius", 3.5, 2.5, 6, 0.1, "mm", "form", "knuckles"),
        Param("hinge_gap", "Hinge gap", 0.4, 0.2, 1.0, 0.05, "mm", "interface", "knuckles",
              "Between neighbouring knuckles, and between the knuckles and the wall or lid."),
        Param("pin_d", "Pin diameter", 1.75, 1.0, 3.0, 0.05, "mm", "brief", "pin_hole",
              "A length of 1.75 mm filament works as the pin.", "specified"),
        Param("pin_clear", "Pin clearance / side", 0.15, 0.0, 0.5, 0.05, "mm", "interface", "pin_hole"),
        Param("lip_h", "Lip depth", 6, 2, 15, 0.5, "mm", "form", "lip"),
        Param("lip_clear", "Lip clearance / side", 0.15, 0.0, 0.6, 0.05, "mm", "interface", "lip"),
        Param("front_relief", "Lip front relief", 0.6, 0.0, 3.0, 0.05, "mm", "interface", "lip",
              "Gap between the lip's front face and the front wall. The lip front swings on an arc as the lid opens."),
        Param("open_deg", "Opening angle", 110, 30, 170, 1, "deg", "form", "lid_knuckle", "How far the hinge is checked to open."),
        Param("mount", "Mounting holes", 1, 0, 1, 1, "", "form", "mount", "1 = two screw holes in the floor."),
        # ---- marks (form.marks) ----
        Param("label", "Label", 0, 0, 2, 1, "", "form", "mark",
              "The project's label text on the front wall of the box. 0 = none, 1 = raised, 2 = sunk."),
        Param("label_h", "Label height", 6, 3, 20, 0.5, "mm", "form", "mark", "Height of the capitals."),
        Param("stamp", "Revision stamp", 0, 0, 1, 1, "", "form", "mark",
              "1 = the revision and a short hash (\"r04 a3f1\") sunk 0.4 mm into the underside."),
    ]
    wall_exempt = ("mark",)                   # letter corners are not walls; marks.checks() measures the strokes instead
    mark_params = ("label", "stamp")          # these values make the geometry depend on the project's label and revision
    features = [Feature("body", "Box", "structure"), Feature("mount", "Mounting holes", "access"),
                Feature("knuckles", "Box knuckles", "interface"), Feature("lid", "Lid", "structure"),
                Feature("lip", "Lid lip", "interface"), Feature("lid_knuckle", "Lid knuckle", "interface"),
                Feature("pin_hole", "Pin hole", "interface"),
                Feature("mark", "Label and stamp", "finish", "Lettering on the front wall; revision stamp under the floor.")]

    # ---- geometry helpers --------------------------------------------------------------------------
    @staticmethod
    def dims(v):
        W, D = v["inner_w"] + 2 * v["wall"], v["inner_d"] + 2 * v["wall"]
        H, t, R, g = v["inner_h"] + v["wall"], v["lid_t"], v["knuckle_r"], v["hinge_gap"]
        ya, za = D / 2 + R + g, H + t - R              # hinge axis: behind the back wall, knuckle tops flush with the lid
        L = W - 2 * max(v["corner_r"], 3)              # hinge length
        k = (L - 2 * g) / 3                            # three knuckles: box, lid, box
        return W, D, H, t, R, g, ya, za, L, k

    def constraints(self, v):
        W, D, H, t, R, g, ya, za, L, k = self.dims(v)
        out = []
        if v["corner_r"] >= min(W, D) / 2 - 1:
            out.append(RecipeError("Corner radius is larger than the box", "body", "Reduce the corner radius.", ["corner_r"]))
        if k < 4:
            out.append(RecipeError("Knuckles are too short", "knuckles", "Widen the box or reduce the corner radius.", ["inner_w", "corner_r"]))
        if R - (v["pin_d"] / 2 + v["pin_clear"]) < 1.2:
            out.append(RecipeError("Knuckle wall around the pin is under 1.2 mm", "knuckles", "Raise the knuckle radius or use a thinner pin.",
                                   ["knuckle_r", "pin_d"]))
        if R < t:
            out.append(RecipeError("Knuckle radius is smaller than the lid thickness", "lid_knuckle", "Raise the knuckle radius.", ["knuckle_r", "lid_t"]))
        if v["lip_h"] > v["inner_h"] - 2:
            out.append(RecipeError("Lip is deeper than the box", "lip", "Shorten the lip.", ["lip_h"]))
        if za - R < v["wall"]:
            out.append(RecipeError("Knuckles reach below the floor", "knuckles", "Make the box taller or the knuckles smaller.", ["inner_h", "knuckle_r"]))
        for k in ("label", "stamp"):
            if abs(v.get(k, 0) - round(v.get(k, 0))) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", "mark", "Use whole numbers.", [k]))
        if abs(v["mount"] - round(v["mount"])) > 1e-9 or abs(v["open_deg"] - round(v["open_deg"])) > 1e-9:
            out.append(RecipeError("Mounting holes and opening angle are whole numbers", "mount", "Use 0 or 1, and whole degrees.", ["mount", "open_deg"]))
        return out

    def back_setback(self, v):
        """Gap behind the lip. Near the hinge the lip's back face swings past the box's inner top edge, which sits
        sqrt(a² + b²) from the axis; the face must start at least that far out, plus the lip clearance."""
        W, D, H, t, R, g = self.dims(v)[:6]
        a, b = R + g + v["wall"], R - t
        return v["lip_clear"] + (math.hypot(a, b) - a) + 0.15

    def lid_to_print(self, v):
        """Lid as printed = this location * lid as assembled (flipped, top face on the bed, beside the box)."""
        W, D, H, t = self.dims(v)[:4]
        return Pos(W + GAP, 0, 0) * Rot(180, 0, 0) * Pos(0, 0, -(H + t))

    def build(self, v):
        W, D, H, t, R, g, ya, za, L, k = self.dims(v)
        w = v["wall"]
        outer = fillet(Box(W, D, H, align=A).edges().filter_by(Axis.Z), v["corner_r"])
        body = outer - Pos(0, 0, w) * Box(v["inner_w"], v["inner_d"], H, align=A)
        stages = [Stage("body", body)]
        if v["mount"] >= 0.5:
            for x in (-(v["inner_w"] / 2 - 8), v["inner_w"] / 2 - 8):
                body = body - Pos(x, 0, -1) * Cylinder(1.7, w + 2, align=A)
            stages.append(Stage("mount", body))
        along = Rot(0, 90, 0)                                   # cylinder along X
        for x0 in (-L / 2, L / 2 - k):                          # the box's two outer knuckles
            xc = x0 + k / 2
            body = body + Pos(xc, ya, za) * along * Cylinder(R, k)
            body = body + Pos(xc, (D / 2 - w / 2 + ya) / 2, za - R) * Box(k, ya - (D / 2 - w / 2), R, align=A)
        stages.append(Stage("knuckles", body))

        T = self.lid_to_print(v)
        plate = Pos(0, 0, H) * fillet(Box(W, D, t, align=A).edges().filter_by(Axis.Z), v["corner_r"])
        s = body + T * plate
        stages.append(Stage("lid", s))
        c, r = v["lip_clear"], v["front_relief"]
        ld = v["inner_d"] - self.back_setback(v) - r
        lip = Pos(0, -v["inner_d"] / 2 + r + ld / 2, H - v["lip_h"]) * Box(v["inner_w"] - 2 * c, ld, v["lip_h"], align=A)
        s = s + T * lip
        stages.append(Stage("lip", s))
        kn = Pos(0, ya, za) * along * Cylinder(R, k) + Pos(0, (D / 2 - 1 + ya) / 2, H) * Box(k, ya - (D / 2 - 1), t, align=A)
        s = s + T * kn
        stages.append(Stage("lid_knuckle", s))
        hole = Pos(0, ya, za) * along * Cylinder(v["pin_d"] / 2 + v["pin_clear"], L + 2)
        s = s - hole - T * hole
        stages.append(Stage("pin_hole", s))
        if v.get("label") or v.get("stamp"):
            if v.get("label"):
                text = marks.context().get("text") or "FORM"
                info = marks.analyse(text, v["label_h"])
                room_w, room_h = W - 2 * v["corner_r"] - 4, H - 4
                if info["width_mm"] > room_w or v["label_h"] > room_h:
                    raise RecipeError(f"The label “{info['text']}” is {info['width_mm']:.0f} × {v['label_h']:g} mm; the front wall has "
                                      f"{max(room_w, 0):.0f} × {max(room_h, 0):.0f} mm", "mark",
                                      "Lower the label height or shorten the label text.", ["label_h"])
                if v["label"] > 1.5 and w < 1.6:
                    raise RecipeError("A sunk label needs a wall of at least 1.6 mm", "mark", "Thicken the wall, or raise the label instead.",
                                      ["wall", "label"])
                fn = marks.emboss_text if v["label"] < 1.5 else marks.deboss_text
                s = fn(s, text, on=(0, -D / 2, H / 2), normal=(0, -1, 0), height=v["label_h"], depth=0.6)
            if v.get("stamp"):
                # between the two mounting holes (they sit 8 mm in from the side walls, on y = 0)
                s = marks.revision_stamp(s, at=(0, 0), height=6, depth=min(0.4, w / 3))
            stages.append(Stage("mark", s))
        return stages

    def _mark_checks(self, v):
        ctx = marks.context()
        out = []
        if v.get("label") and ctx:                # the label text is only known while FORM builds for a project
            out += marks.checks(marks.analyse(ctx.get("text") or "FORM", v["label_h"]), raised=v["label"] < 1.5)
        if v.get("stamp") and ctx:
            out += marks.checks(marks.analyse(marks.stamp_text(), 6, 0.4), raised=False, id="stamp", label="Revision stamp")
        return out

    def statics(self, v, solid_volume_mm3, com):
        checks = self._mark_checks(v)
        return {"checks": checks} if checks else None

    def derived(self, v):
        W, D, H, t, R, g, ya, za, L, k = self.dims(v)
        return [{"key": "pin_len", "label": "Pin length", "value": L, "unit": "mm", "feature": "pin_hole",
                 "formula": "outer width - 2 x max(corner radius, 3)", "interface": False},
                {"key": "hole_d", "label": "Pin hole", "value": v["pin_d"] + 2 * v["pin_clear"], "unit": "mm", "feature": "pin_hole",
                 "formula": "pin + 2 x clearance", "interface": True},
                {"key": "knuckle_len", "label": "Knuckle length", "value": k, "unit": "mm", "feature": "knuckles",
                 "formula": "(pin length - 2 x hinge gap) / 3", "interface": False},
                {"key": "lip_back", "label": "Lip back setback", "value": self.back_setback(v), "unit": "mm", "feature": "lip",
                 "formula": "lip clearance + swing past the back wall's inner edge + 0.15", "interface": True}]

    def assembly(self, v):
        W, D, H, t, R, g, ya, za, L, k = self.dims(v)
        n = int(round(v["open_deg"] / 5)) + 1                   # one sample every 5 degrees or less
        hw = [Hardware("Hinge pin", f"Ø{v['pin_d']:g} × {L:.0f} mm", 1, "1.75 mm filament offcut, or steel rod of the same diameter",
                       "Push the pin through the three knuckles from the left and trim it flush.", after="lid",
                       access=(Access(at=(-L / 2, ya, za), axis=(1, 0, 0), tool_d=v["pin_d"], length=L),))]
        if v["mount"] >= 0.5:
            xs = (-(v["inner_w"] / 2 - 8), v["inner_w"] / 2 - 8)
            hw.insert(0, Hardware("Mounting screw", "M3 × 12 pan head", 2, "ISO 7045, or a #4 wood screw",
                                  "Screw the box down through the two holes in its floor.", after="body",
                                  access=tuple(Access(at=(x, 0, v["wall"]), axis=(0, 0, -1), tool_d=6, length=80) for x in xs)))
        return Assembly(
            parts=[Part("body", "Box", 0, note="Set the box on the bench, open side up."),
                   Part("lid", "Lid", 1, move=(-(W + GAP), 0, H + t), rotate=(180, 0, 0), explode=(0, 0, v["lip_h"] + 22),
                        note="Lower the lid on: the lip goes into the box, the lid knuckle between the two box knuckles.")],
            joints=[hinge("lid", (-1, 0, 0), (0, ya, za), (0, v["open_deg"]), samples=n, label="Lid hinge")],
            hardware=hw)
