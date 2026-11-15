"""Device dock — a leaning cradle for a measured handheld object.

Modelled in print orientation: base on the plate, Z up, front at −Y.
The pocket is the fit interface; everything else is styling around it.
"""
from __future__ import annotations

import math

from build123d import (Align, Axis, Box, Cylinder, Plane, Polygon, Pos, Rot,
                       chamfer, extrude, fillet)

from .base import Feature, Param, Recipe, RecipeError, Stage

PLA_DENSITY = 1.24e-3  # g/mm³


class Dock(Recipe):
    id = "dock"
    title = "Device dock"
    summary = "A leaning desk cradle with a cable pass-through, sized to a measured device."
    fit = {"cavity": "pocket_width", "mating": "device_width", "clearance": "clearance",
           "label": "Pocket ↔ device width", "per_side": True}

    params = [
        Param("device_width", "Device width", 71.5, 20, 160, 0.05, "mm", "brief", "pocket",
              "Widest dimension across the device where it enters the pocket."),
        Param("device_thickness", "Device thickness", 7.8, 2, 40, 0.05, "mm", "brief", "pocket",
              "Thickness including any case."),
        Param("device_height", "Device height", 147.0, 30, 260, 0.5, "mm", "brief", "",
              "Used only for the tip-over estimate."),
        Param("device_mass", "Device mass", 170.0, 10, 1500, 1, "g", "brief", "",
              "Used only for the tip-over estimate."),
        Param("clearance", "Clearance / side", 0.25, 0.0, 1.5, 0.01, "mm", "interface", "pocket",
              "Nominal gap added on every side of the device."),
        Param("plug_width", "Plug opening width", 13.0, 0, 40, 0.5, "mm", "interface", "cable",
              "Opening under the device for the connector body. 0 removes it."),
        Param("plug_thickness", "Plug opening depth", 7.0, 0, 20, 0.5, "mm", "interface", "cable"),
        Param("cable_diameter", "Cable channel", 4.5, 0, 12, 0.5, "mm", "interface", "cable",
              "Width of the channel running out the back, bridged in print."),
        Param("lean", "Lean angle", 15.0, 5, 30, 0.5, "deg", "form", "pocket",
              "Tilt back from vertical."),
        Param("floor", "Pocket floor height", 7.0, 2, 30, 0.5, "mm", "form", "pocket",
              "Material under the device."),
        Param("side_wall", "Side wall", 7.0, 2.4, 30, 0.2, "mm", "form", "body"),
        Param("lip", "Front lip", 6.0, 2.4, 30, 0.2, "mm", "form", "body",
              "Material in front of the pocket."),
        Param("front_height", "Front height", 18.0, 6, 80, 0.5, "mm", "form", "body"),
        Param("back_height", "Back height", 36.0, 10, 120, 0.5, "mm", "form", "body"),
        Param("depth", "Base depth", 78.0, 30, 170, 0.5, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 12.0, 1.5, 40, 0.5, "mm", "form", "soften",
              "Plan-view radius of the four vertical corners."),
        Param("edge_r", "Edge radius", 2.5, 0, 6, 0.1, "mm", "form", "soften",
              "Softening of the top perimeter."),
        Param("lead_in", "Pocket lead-in", 0.8, 0, 2, 0.1, "mm", "form", "lead_in",
              "Chamfer at the pocket mouth: guides the device in and hides first-layer flare."),
        Param("relief_width", "Thumb relief width", 30.0, 0, 80, 0.5, "mm", "form", "relief",
              "Scoop in the front lip. 0 removes it."),
        Param("relief_depth", "Thumb relief depth", 6.0, 0, 40, 0.5, "mm", "form", "relief"),
    ]

    features = [
        Feature("body", "Body", "structure", "Wedge block that carries the load to the desk."),
        Feature("soften", "Edge softening", "finish", "Corner and perimeter radii; tactile, no interface role."),
        Feature("pocket", "Pocket", "interface", "The fit interface. Width and thickness follow the measured device plus clearance."),
        Feature("lead_in", "Lead-in", "access", "Chamfered mouth so the device finds the pocket."),
        Feature("cable", "Cable path", "access", "Plug opening and bridged channel to the rear."),
        Feature("relief", "Thumb relief", "access", "Scoop that keeps the bottom of the screen reachable."),
    ]

    # ---- geometry helpers ------------------------------------------------
    @staticmethod
    def g(v: dict) -> dict:
        th = math.radians(v["lean"])
        pw = v["device_width"] + 2 * v["clearance"]
        pt = v["device_thickness"] + 2 * v["clearance"]
        W = pw + 2 * v["side_wall"]
        D = v["depth"]
        front, back = -D / 2, D / 2
        slope = (v["back_height"] - v["front_height"]) / D
        top = lambda y: v["front_height"] + slope * (y - front)
        yc = front + v["lip"] + pt / 2 * math.cos(th)          # pocket axis at floor
        zc = v["floor"] + pt / 2 * math.sin(th)
        # where the pocket's front and back walls meet the sloped top
        def meet(y0, z0):
            # line (y0 + s·sinθ, z0 + s·cosθ) ∩ top(y)
            s = (top(y0) - z0) / (math.cos(th) - slope * math.sin(th))
            return y0 + s * math.sin(th), z0 + s * math.cos(th), s
        yf, zf, sf = meet(yc - pt / 2 * math.cos(th), zc + pt / 2 * math.sin(th))
        yb, zb, sb = meet(yc + pt / 2 * math.cos(th), zc - pt / 2 * math.sin(th))
        return dict(th=th, pw=pw, pt=pt, W=W, D=D, front=front, back=back, slope=slope, top=top,
                    yc=yc, zc=zc, yf=yf, zf=zf, sf=sf, yb=yb, zb=zb, sb=sb)

    def constraints(self, v):
        g, out = self.g(v), []
        def bad(msg, feature, hint, params):
            out.append(RecipeError(msg, feature, hint, params))
        if g["W"] > 176:
            bad(f"Overall width {g['W']:.1f} mm exceeds the 176 mm usable plate width", "body",
                "Reduce the side wall, or this device is too wide for an A1 mini in this orientation.", ["side_wall", "device_width"])
        if v["back_height"] < v["front_height"]:
            bad("Back height is lower than front height", "body", "Raise the back or lower the front.", ["back_height", "front_height"])
        if v["corner_r"] > min(g["W"], g["D"]) / 2 - 1:
            bad("Corner radius consumes the footprint", "soften", "Reduce the corner radius.", ["corner_r"])
        if v["edge_r"] > 0 and v["corner_r"] < v["edge_r"] + 1:
            bad("Edge radius needs a corner radius at least 1 mm larger", "soften",
                "Raise the corner radius or lower the edge radius.", ["edge_r", "corner_r"])
        land = v["edge_r"] + v["lead_in"] + 0.8
        if min(v["side_wall"], v["lip"]) < land:
            bad(f"Walls around the pocket are thinner than edge radius + lead-in + 0.8 = {land:.1f} mm", "lead_in",
                "Thicken the side wall / front lip, or reduce the edge radius or lead-in.", ["side_wall", "lip", "edge_r", "lead_in"])
        cr = v["corner_r"]
        for ycorner, name in ((g["front"] + v["lip"], "front"), (g["yb"], "back")):
            cx, cy = g["W"] / 2 - cr, (g["front"] + cr if name == "front" else g["back"] - cr)
            dx, dy = g["pw"] / 2 - cx, (cy - ycorner if name == "front" else ycorner - cy)
            if dx > 0 and dy > 0 and (dx * dx + dy * dy) ** 0.5 > cr - land:
                bad(f"The pocket's {name} corners run into the rounded body corners", "soften",
                    "Reduce the corner radius, or thicken the side wall.", ["corner_r", "side_wall"])
                break
        if g["yb"] > g["back"] - land:
            bad("The leaning pocket breaks through the back of the body", "pocket",
                "Increase base depth, reduce lean, or lower the back height.", ["depth", "lean", "back_height"])
        if g["sf"] < 4:
            bad(f"The front lip only holds {max(g['sf'],0):.1f} mm of the device", "pocket",
                "Raise the front height or lower the pocket floor.", ["front_height", "floor"])
        if v["plug_width"] > g["pw"] - 6:
            bad("Plug opening leaves no ledge for the device to rest on", "cable",
                "Keep at least 3 mm of floor either side of the plug opening.", ["plug_width"])
        if v["plug_width"] > 0 and v["plug_thickness"] <= 0:
            bad("Plug opening has a width but no depth", "cable", "Give the plug opening a depth, or set its width to 0.", ["plug_thickness"])
        if v["cable_diameter"] > 0 and v["floor"] - (v["cable_diameter"] + 0.6) < 1.2:
            bad("Cable channel leaves under 1.2 mm of bridged roof beneath the pocket", "cable",
                "Raise the pocket floor or use a thinner channel.", ["floor", "cable_diameter"])
        if v["relief_width"] > g["pw"] - 4 and v["relief_width"] > 0:
            bad("Thumb relief is wider than the pocket", "relief", "Narrow the relief.", ["relief_width"])
        if v["relief_width"] > 0 and v["relief_depth"] > g["sf"] - 3:
            bad("Thumb relief removes the front lip that retains the device", "relief",
                f"Keep relief depth under {max(g['sf']-3,0):.1f} mm.", ["relief_depth"])
        return out

    # ---- build -----------------------------------------------------------
    def build(self, v):
        g = self.g(v)
        stages: list[Stage] = []
        profile = Polygon((g["front"], 0), (g["back"], 0), (g["back"], v["back_height"]),
                          (g["front"], v["front_height"]), align=None)
        body = extrude(Plane.YZ * profile, amount=g["W"] / 2, both=True)
        stages.append(Stage("body", body))

        try:
            s = fillet(body.edges().filter_by(Axis.Z), v["corner_r"])
            if v["edge_r"] > 0:
                top = s.faces().sort_by(Axis.Z)[-1]
                s = fillet(top.edges(), v["edge_r"])
            bottom = s.faces().sort_by(Axis.Z)[0]
            s = chamfer(bottom.edges(), 0.5)
        except Exception as e:  # OCCT fillet failures are opaque; say what to do
            raise RecipeError("Edge softening could not be built", "soften",
                              "Reduce the edge radius or corner radius; the radii collide at this size.",
                              ["edge_r", "corner_r"]) from e
        stages.append(Stage("soften", s))

        tool = Box(g["pw"], g["pt"], 400, align=(Align.CENTER, Align.CENTER, Align.MIN))
        r = min(1.0, g["pt"] / 2 - 0.2)
        tool = fillet(tool.edges().filter_by(Axis.Z), r)
        tool = Pos(0, g["yc"], g["zc"]) * Rot(-v["lean"], 0, 0) * tool
        before = s
        s = s - tool
        stages.append(Stage("pocket", s))

        if v["lead_in"] > 0:
            rim = _rim_edges(s, before)
            try:
                s = chamfer(rim, v["lead_in"])
            except Exception as e:
                raise RecipeError("Pocket lead-in could not be built", "lead_in",
                                  "Reduce the lead-in, or widen the wall around the pocket.", ["lead_in", "side_wall", "lip"]) from e
            stages.append(Stage("lead_in", s))

        cut = None
        if v["plug_width"] > 0 and v["plug_thickness"] > 0:
            cut = Pos(0, g["yc"], 0) * Box(v["plug_width"], v["plug_thickness"], g["zc"] + 2,
                                           align=(Align.CENTER, Align.CENTER, Align.MIN))
        if v["cable_diameter"] > 0:
            ch = Pos(0, g["yc"], 0) * Box(v["cable_diameter"], g["back"] - g["yc"] + 1, v["cable_diameter"] + 0.6,
                                          align=(Align.CENTER, Align.MIN, Align.MIN))
            cut = ch if cut is None else cut + ch
        if cut is not None:
            s = s - cut
            stages.append(Stage("cable", s))

        if v["relief_width"] > 0 and v["relief_depth"] > 0:
            R = v["relief_width"] / 2
            zr = g["zf"] + R - v["relief_depth"]
            scoop = Pos(0, g["front"] - 1, zr) * Rot(-90, 0, 0) * Cylinder(
                R, (g["yf"] - g["front"]) + 1 + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
            s = s - scoop
            stages.append(Stage("relief", s))
        return stages

    # ---- derived ---------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        return [
            {"key": "pocket_width", "label": "Pocket width", "value": g["pw"], "unit": "mm", "feature": "pocket",
             "formula": "device width + 2 × clearance", "interface": True},
            {"key": "pocket_thickness", "label": "Pocket thickness", "value": g["pt"], "unit": "mm", "feature": "pocket",
             "formula": "device thickness + 2 × clearance", "interface": True},
            {"key": "overall_width", "label": "Overall width", "value": g["W"], "unit": "mm", "feature": "body",
             "formula": "pocket width + 2 × side wall"},
            {"key": "front_engagement", "label": "Front lip engagement", "value": g["sf"], "unit": "mm", "feature": "pocket",
             "formula": "device length held by the front lip"},
            {"key": "back_engagement", "label": "Back support length", "value": g["sb"], "unit": "mm", "feature": "pocket",
             "formula": "device length resting on the back wall"},
            {"key": "bridge_span", "label": "Cable bridge span", "value": v["cable_diameter"], "unit": "mm", "feature": "cable",
             "formula": "channel width, printed as a bridge"},
        ]

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        n_t = (0.0, math.cos(g["th"]), -math.sin(g["th"]))
        xs, ts = [], []
        for f in faces_by_feature.get("pocket", []):
            if f.geom_type.name != "PLANE":
                continue
            n = f.normal_at(f.center())
            c = f.center()
            if abs(abs(n.X) - 1) < 1e-6:
                xs.append(c.X)
            elif abs(abs(n.X * n_t[0] + n.Y * n_t[1] + n.Z * n_t[2]) - 1) < 1e-6:
                ts.append(c.Y * n_t[1] + c.Z * n_t[2])
        out = []
        if len(xs) >= 2:
            out.append({"key": "pocket_width", "label": "Pocket width", "intended": g["pw"], "modelled": max(xs) - min(xs)})
        if len(ts) >= 2:
            out.append({"key": "pocket_thickness", "label": "Pocket thickness", "intended": g["pt"], "modelled": max(ts) - min(ts)})
        return out

    def statics(self, v, solid_volume_mm3, com, dock_mass_g=None):
        g = self.g(v)
        assumed = dock_mass_g is None
        m_dock = dock_mass_g if dock_mass_g is not None else solid_volume_mm3 * PLA_DENSITY * 0.45
        L = v["device_height"]
        yd = g["yc"] + L / 2 * math.sin(g["th"])
        m = m_dock + v["device_mass"]
        ycom = (m_dock * com[1] + v["device_mass"] * yd) / m
        rear = g["back"] - 0.5
        margin = rear - ycom
        h_top = v["floor"] + L * math.cos(g["th"])
        tip_n = max(margin, 0) * m * 9.81e-3 / h_top
        return {"dock_mass_g": m_dock, "dock_mass_assumed": assumed, "com_y": ycom,
                "margin_back_mm": margin, "margin_front_mm": ycom - g["front"],
                "tip_force_n": tip_n, "push_height_mm": h_top,
                "model": "Rigid bodies, device as a uniform slab, friction and cable drag ignored."}

    def companions(self, v):
        g = self.g(v)
        L = v["device_height"]
        return [{"label": "Device", "size": [v["device_width"], v["device_thickness"], L],
                 "origin": [0, g["yc"], g["zc"]], "rot_x_deg": -v["lean"], "anchor": "bottom"}]

    def test_piece(self, v, shape):
        g = self.g(v)
        h, wall = 6.0, 3.0
        z0 = v["floor"] + 1.5
        if z0 + h > g["zf"] - v["relief_depth"] - 0.5:
            z0 = max(v["floor"] + 0.5, g["zf"] - v["relief_depth"] - 0.5 - h)
        y_lo = g["yc"] - g["pt"] / 2 - wall + (z0 - g["zc"]) * math.tan(g["th"])
        y_hi = g["yc"] + g["pt"] / 2 + wall + (z0 + h - g["zc"]) * math.tan(g["th"])
        slab = Pos(0, (y_lo + y_hi) / 2, z0) * Box(g["pw"] + 2 * wall, y_hi - y_lo, h,
                                                   align=(Align.CENTER, Align.CENTER, Align.MIN))
        piece = Pos(0, 0, -z0) * (shape & slab)
        return piece, {"label": "Pocket ring", "doc": f"A {h:g} mm slice of the real pocket with {wall:g} mm walls. "
                       "Checks width and thickness fit before committing to the full print.", "height": h}


def _on(shape_faces, point, tol=1e-4) -> bool:
    from build123d import Vertex
    return Vertex(*point).distance_to(shape_faces) < tol


def _rim_edges(after, before):
    """Edges created by a cut that lie on the pre-cut outer surface: the mouth of the cut."""
    from build123d import Compound
    skin = Compound(before.faces())
    old = Compound(before.edges())
    rim = []
    for e in after.edges():
        m = e.position_at(0.5)
        p = (m.X, m.Y, m.Z)
        if _on(skin, p) and not _on(old, p, 1e-3):
            rim.append(e)
    return rim
