"""Threaded jar, made by Form Studio's threaded_jar generator: a jar and its screw lid, printed side by side (the jar
upright, the lid on its top), with a single-start thread swept along a helix.

Two thread forms:
  iso = 0  a printing thread: 45-degree flanks (no flank steeper than 45 degrees from vertical) at any pitch, depth
           0.35 P, crest 0.15 P.
  iso = 1  ISO metric: the ISO 68-1 basic profile (60-degree thread, depth H1 = 0.541266 P, crest P/8, root P/4) at
           the ISO 261 coarse pitch of the nearest standard size; the jar's outside at the thread is that size's
           major diameter less two thread depths, so the wall follows from it.
The lid's thread is the same profile, its bore larger by the clearance and its teeth narrower by it, so the two never
touch when screwed together."""
from build123d import Align, Axis, Cylinder, Helix, Pos, Vector, Wire, make_face, sweep

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
ISO261_COARSE = {20: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0, 39: 4.0, 42: 4.5, 45: 4.5, 48: 5.0, 52: 5.0,
                 56: 5.5, 60: 5.5, 64: 6.0, 68: 6.0}       # ISO 261, coarse series (first and second choice), mm
GAP = 6.0                                                  # between jar and lid on the plate

MAKE = {
    "generator": "threaded_jar",
}


class Design(Recipe):
    title, summary = "Threaded jar", "A jar and a screw lid with a printing thread or an ISO metric thread."
    category, tags = "Makers", ("jar", "thread", "lid")
    solids = 2
    params = [
        Param("inner_d", "Inside diameter", 50, 15, 120, 0.5, "mm", "brief", "jar"),
        Param("height", "Jar height", 60, 20, 150, 0.5, "mm", "brief", "jar", "Outside, floor to rim."),
        Param("wall", "Wall", 2.4, 1.2, 5, 0.1, "mm", "form", "jar", "With iso = 1 the wall follows from the ISO size."),
        Param("floor", "Floor", 2, 1, 5, 0.1, "mm", "form", "jar"),
        Param("iso", "ISO metric", 0, 0, 1, 1, "", "interface", "thread",
              "0 = printing thread at the pitch below; 1 = ISO 68-1 profile at the ISO 261 coarse pitch."),
        Param("pitch", "Pitch", 4, 1.5, 8, 0.1, "mm", "interface", "thread", "The printing thread's pitch (iso = 0)."),
        Param("turns", "Turns", 2.5, 1.25, 5, 0.25, "", "interface", "thread"),
        Param("clearance", "Thread clearance", 0.35, 0.1, 0.8, 0.05, "mm", "interface", "lid_thread",
              "Radial room between the threads, and axial room on the flanks (assumed for FDM)."),
        Param("lid_wall", "Lid wall", 2.4, 1.6, 5, 0.1, "mm", "form", "lid"),
        Param("lid_top", "Lid top", 2.4, 1.2, 5, 0.1, "mm", "form", "lid"),
    ]
    features = [Feature("jar", "Jar", "structure"), Feature("thread", "Jar thread", "interface"),
                Feature("lid", "Lid", "structure"), Feature("lid_thread", "Lid thread", "interface")]

    def thread_form(self, v):
        """(pitch, depth, root width, crest width, root radius of the jar thread, standard major d or None)."""
        if v["iso"] >= 0.5:
            want = v["inner_d"] + 2 * v["wall"] + 2 * 0.541266 * 4
            major = min(ISO261_COARSE, key=lambda m: abs(m - want))
            P = ISO261_COARSE[major]
            h = 0.541266 * P
            return P, h, 0.75 * P, P / 8, major / 2 - h, major
        P = v["pitch"]
        h = 0.35 * P
        return P, h, 0.15 * P + 2 * h, 0.15 * P, v["inner_d"] / 2 + v["wall"], None

    def _neck(self, v):
        P, h, wb = self.thread_form(v)[:3]
        return v["turns"] * P + wb + 1.2          # the thread's run, its own width, and 0.6 mm above and below

    def constraints(self, v):
        P, h, wb, wt, r_root, major = self.thread_form(v)
        if v["iso"] >= 0.5:
            want = v["inner_d"] + 2 * v["wall"] + 2 * h
            if want > 70 or want < 18:
                return [RecipeError("ISO 261 coarse threads are tabulated here from M20 to M68", "thread",
                                    "Use iso = 0 (a printing thread) for this size.", ["iso", "inner_d"])]
            if r_root - v["inner_d"] / 2 < 1.2:
                return [RecipeError(f"The nearest ISO size, M{major}, leaves under 1.2 mm of wall", "thread",
                                    "Change the inside diameter a little, or use iso = 0.", ["inner_d", "iso"])]
        if self._neck(v) > v["height"] - v["floor"] - 4:
            return [RecipeError("The thread is taller than the jar", "thread", "Use fewer turns or a taller jar.",
                                ["turns", "height"])]
        R = r_root + h + v["clearance"] + v["lid_wall"]
        if 2 * (r_root + 0.0) + 2 * R + GAP > 175:
            return [RecipeError("The jar and lid do not fit a 175 mm bed side by side", "jar", "Make the jar narrower.",
                                ["inner_d"])]
        return []

    @staticmethod
    def _tooth(r_base, depth, w_base, w_tip, lead, length, inward=False):
        """One thread: a trapezoid in the XZ plane (base w_base wide on radius r_base, sunk 0.3 mm into its wall; tip
        w_tip wide, depth away from it) swept along a helix of the given lead and length."""
        s = -1 if inward else 1
        pts = [(r_base - s * 0.3, -w_base / 2), (r_base + s * depth, -w_tip / 2), (r_base + s * depth, w_tip / 2),
               (r_base - s * 0.3, w_base / 2)]
        face = make_face(Wire.make_polygon([Vector(x, 0, z) for x, z in pts], close=True))
        return sweep(face, Helix(lead, length, r_base), is_frenet=True)

    def _layout(self, v):
        P, h, wb, wt, r_root, major = self.thread_form(v)
        R_lid = r_root + h + v["clearance"] + v["lid_wall"]
        return -(R_lid + GAP / 2), r_root + GAP / 2, R_lid

    def build(self, v):
        P, h, wb, wt, r_root, major = self.thread_form(v)
        H, neck = v["height"], self._neck(v)
        xj, xl, R_lid = self._layout(v)
        jar = Cylinder(r_root, H, align=BOTTOM) - Pos(0, 0, v["floor"]) * Cylinder(v["inner_d"] / 2, H, align=BOTTOM)
        jar = craft.safe_fillet(jar, jar.edges().group_by(Axis.Z)[0], min(2.0, v["floor"]))
        stages = [Stage("jar", Pos(xj, 0, 0) * jar)]
        run = v["turns"] * P
        th = Pos(0, 0, H - neck + 0.6 + wb / 2) * self._tooth(r_root, h, wb, wt, P, run)
        jar = craft.fuse(jar, th)
        stages.append(Stage("thread", Pos(xj, 0, 0) * jar))
        Rb = r_root + h + v["clearance"]                   # the lid's bore: the jar's major diameter + clearance
        top, skirt = v["lid_top"], neck + 0.6
        lid = Cylinder(R_lid, top + skirt, align=BOTTOM) - Pos(0, 0, top) * Cylinder(Rb, skirt + 1, align=BOTTOM)
        lid = craft.safe_fillet(lid, lid.edges().group_by(Axis.Z)[0], min(1.5, top * 0.6))
        both = Pos(xj, 0, 0) * jar + Pos(xl, 0, 0) * lid
        stages.append(Stage("lid", both))
        c = v["clearance"]
        lt = self._tooth(Rb, h, max(wb - c, 2 * wt), max(wt - c * 0.5, 0.1 * P), P, run, inward=True)
        lid = craft.fuse(lid, Pos(0, 0, top + 0.6 + wb / 2) * lt)
        both = Pos(xj, 0, 0) * jar + Pos(xl, 0, 0) * lid
        stages.append(Stage("lid_thread", both))
        return stages

    def derived(self, v):
        P, h, wb, wt, r_root, major = self.thread_form(v)
        out = [{"key": "pitch_used", "label": "Thread pitch", "value": P, "unit": "mm", "feature": "thread",
                "formula": "ISO 261 coarse pitch of the size" if major else "the pitch parameter", "interface": True},
               {"key": "major_d", "label": "Jar thread major diameter", "value": round(2 * (r_root + h), 3), "unit": "mm",
                "feature": "thread", "formula": (f"M{major} (ISO 261)" if major else "jar outside + 2 x 0.35 P"),
                "interface": True},
               {"key": "thread_depth", "label": "Thread depth", "value": round(h, 3), "unit": "mm", "feature": "thread",
                "formula": "0.541266 P (ISO 68-1 H1)" if major else "0.35 P (45-degree printing profile)", "interface": False},
               {"key": "flank_deg", "label": "Flank angle from the radial plane", "value": 30 if major else 45, "unit": "deg",
                "feature": "thread", "formula": "half the thread angle", "interface": False},
               {"key": "jar_wall", "label": "Jar wall", "value": round(r_root - v["inner_d"] / 2, 3), "unit": "mm",
                "feature": "jar", "formula": "root radius - inside radius", "interface": False}]
        out[0]["value"] = round(P, 3)
        return out
