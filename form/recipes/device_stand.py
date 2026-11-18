"""Device stand: a desk stand for a phone, tablet or e-reader, with a charging cut-out.

One continuous side profile, extruded across the width: a front lip, a seat the device's lower edge rests on, and a
backrest the device leans against, braced by a long rear foot. Modelled in print orientation (base on the plate,
front at -Y). The seat is perpendicular to the leaning device, so its lower edge sits square in the channel.

The charging cut-out is a slot through the middle of the lip, seat and base: the plug goes straight down out of the
device and the cable leaves forward along the desk, so the stand stays flat on the desk. The seat is then raised so
the plug's length fits under the device.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Plane, Polygon, Pos, Rot, extrude, fillet

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import FOOT, foot_chamfer

PLA_DENSITY = 1.24e-3     # g/mm³
INFILL = 0.45             # share of the solid volume a 15 % infill print weighs (assumed until sliced)


class DeviceStand(Recipe):
    id = "device_stand"
    title = "Phone and tablet stand"
    summary = ("A leaning desk stand for a phone, tablet or e-reader, sized to the device's thickness with its case, "
               "with a charging cut-out and a tip-over estimate.")
    category = "Desk"
    tags = ("phone", "tablet", "e-reader", "stand", "desk", "charging", "video calls")
    fit = {"cavity": "slot_width", "mating": "device_thickness", "clearance": "clearance",
           "label": "Seat channel ↔ device thickness", "per_side": True, "window": [0.6, 3.5]}

    params = [
        Param("device_thickness", "Device thickness", 9.5, 5, 25, 0.05, "mm", "brief", "slot",
              "Thickness with the case you use, measured with calipers at the bottom edge."),
        Param("device_height", "Device height along the lean", 160, 90, 300, 1, "mm", "brief", "",
              "The edge that stands up: a phone's length, or a tablet's short side in landscape. Used for the tip-over estimate."),
        Param("device_width", "Device width on the seat", 78, 50, 300, 1, "mm", "brief", "",
              "The edge resting on the seat. Shown as the device ghost; the stand can be narrower than the device."),
        Param("device_mass", "Device mass", 220, 50, 1500, 5, "g", "brief", "", "With its case. A phone is about 200 g, an 11\" tablet about 500 g."),
        Param("clearance", "Clearance / side", 0.75, 0.2, 2.0, 0.05, "mm", "interface", "slot",
              "Gap on each side of the device in the channel. A stand wants a loose fit: the device drops in."),
        Param("lean", "Lean angle", 20, 8, 35, 0.5, "deg", "form", "body",
              "Tilt back from vertical. About 15° for video calls, 20–25° for reading and watching."),
        Param("width", "Stand width", 70, 40, 170, 1, "mm", "form", "body", "Across the desk. 70 mm suits phones; 120 mm or more for tablets."),
        Param("depth", "Base depth", 116, 50, 170, 1, "mm", "form", "body", "Front to back on the desk. Longer resists tipping."),
        Param("seat_h", "Seat height", 26, 6, 60, 0.5, "mm", "form", "body",
              "Height of the device's lower edge above the desk. With the charging cut-out it must clear the plug."),
        Param("lip_h", "Lip height", 9, 4, 25, 0.5, "mm", "form", "body", "How far the front lip rises above the seat, measured along the device."),
        Param("lip_t", "Lip thickness", 5, 3, 12, 0.1, "mm", "form", "body"),
        Param("back_h", "Backrest height", 72, 30, 140, 1, "mm", "form", "body", "Along the device, from the seat. Half the device height or a little less."),
        Param("back_t", "Backrest thickness", 7, 4, 15, 0.1, "mm", "form", "body"),
        Param("base_t", "Base thickness", 5, 3, 12, 0.1, "mm", "form", "body", "Under the open window behind the backrest."),
        Param("strut_t", "Rear strut thickness", 6, 3, 15, 0.1, "mm", "form", "body", "The leg from the backrest down to the rear foot."),
        Param("edge_r", "Edge radius", 1.5, 0.6, 3, 0.1, "mm", "form", "soften", "Rounds the two side faces' outlines (at most 0.3 × the thinnest member)."),
        Param("charge", "Charging cut-out", 1, 0, 1, 1, "", "form", "cable", "1 = a slot through the lip and base for the charging plug."),
        Param("plug_w", "Plug width", 13, 8, 30, 0.5, "mm", "brief", "cable",
              "Widest part of the plug's overmold, plus a little. USB-C cables are usually 11–13 mm."),
        Param("plug_len", "Plug length", 24, 10, 50, 0.5, "mm", "brief", "cable",
              "From the device edge to where the cable can bend: plug, overmold and strain relief."),
    ]
    features = [
        Feature("body", "Body", "structure", "One side profile: front lip, base, backrest and rear foot."),
        Feature("slot", "Seat channel", "interface", "Where the device's lower edge sits, square to the device."),
        Feature("cable", "Charging cut-out", "access", "Slot for the plug, open to the front."),
        Feature("soften", "Edge softening", "finish"),
    ]

    # ---- geometry -----------------------------------------------------------------------------------------------
    @staticmethod
    def g(v):
        th = math.radians(v["lean"])
        u = (math.sin(th), math.cos(th))           # up along the device (leans back towards +Y)
        n = (math.cos(th), -math.sin(th))          # across the device, from its front face to its back
        t = v["device_thickness"] + 2 * v["clearance"]
        front = -v["depth"] / 2
        add = lambda p, q, k=1.0: (p[0] + k * q[0], p[1] + k * q[1])
        # S: where the device's front face meets the seat. The lip's front face runs parallel to the device and
        # meets the desk at the front of the base.
        sz = v["seat_h"]
        s_y = front + v["lip_t"] * n[0] + sz * u[0] / u[1] - (v["lip_t"] * n[1]) * u[0] / u[1]
        S = (s_y, sz)
        L1 = add(add(S, n, -v["lip_t"]), u, v["lip_h"])          # lip top, front
        B0 = add(L1, u, -L1[1] / u[1])                            # lip front face meets the desk
        S2 = add(S, n, t)                                         # back corner of the seat
        Q = add(S2, u, v["lip_h"])                                # backrest face at lip-top level (cut away later)
        R1 = add(S2, u, v["back_h"])                              # backrest top, front
        R2 = add(R1, n, v["back_t"])                              # backrest top, back
        rear = (v["depth"] / 2, 0.0)
        return {"th": th, "u": u, "n": n, "t": t, "S": S, "S2": S2, "L1": L1, "B0": B0, "Q": Q, "R1": R1, "R2": R2,
                "rear": rear, "front": B0[0]}

    def constraints(self, v):
        g, out = self.g(v), []
        if abs(v["charge"] - round(v["charge"])) > 1e-9:
            out.append(RecipeError("Charging cut-out is 0 or 1", "cable", "Use 0 (none) or 1.", ["charge"]))
        if g["R2"][0] > g["rear"][0] - 12:
            out.append(RecipeError(f"The backrest leans {g['R2'][0] - g['rear'][0] + 12:.0f} mm past the rear foot", "body",
                                   "Deepen the base, lower the backrest or reduce the lean.", ["depth", "back_h", "lean"]))
        if g["R1"][1] + v["back_t"] > 170:
            out.append(RecipeError(f"The stand is {g['R1'][1]:.0f} mm tall; the smallest common printer is 180 mm", "body",
                                   "Lower the backrest or the seat.", ["back_h", "seat_h"]))
        if v["charge"] >= 0.5:
            need = v["plug_len"] * math.cos(g["th"]) + 2
            if v["seat_h"] < need:
                out.append(RecipeError(f"The plug needs the seat {need:.0f} mm above the desk; it is {v['seat_h']:g} mm",
                                       "cable", "Raise the seat, or measure a shorter plug (right-angle cables need about 12 mm).",
                                       ["seat_h", "plug_len"]))
            if v["plug_w"] > v["width"] - 24:
                out.append(RecipeError("The charging slot leaves under 12 mm of seat on each side", "cable",
                                       "Widen the stand or narrow the slot.", ["width", "plug_w"]))
        if v["lip_h"] > v["back_h"] - 10:
            out.append(RecipeError("The lip is nearly as tall as the backrest", "body", "Lower the lip or raise the backrest.", ["lip_h", "back_h"]))
        return out

    @staticmethod
    def _meet(p, d, q, e):
        """Intersection of the lines p + a·d and q + b·e (2D)."""
        den = d[0] * e[1] - d[1] * e[0]
        a = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
        return (p[0] + a * d[0], p[1] + a * d[1])

    def window(self, v):
        """The open triangle under the backrest: between the base, the backrest's back face and the rear strut.
        Its two upper sides lean at most the lean angle and the strut angle from vertical, so it prints without
        support; its top corner stays sharp (a round there would face down)."""
        g = self.g(v)
        u, n = g["u"], g["n"]
        pb = (g["S2"][0] + v["back_t"] * n[0], g["S2"][1] + v["back_t"] * n[1])
        d = (g["rear"][0] - g["R2"][0], g["rear"][1] - g["R2"][1])
        k = math.hypot(*d)
        d = (d[0] / k, d[1] / k)
        inward = (d[1], -d[0])
        pi = (g["R2"][0] + v["strut_t"] * inward[0], g["R2"][1] + v["strut_t"] * inward[1])
        zb = v["base_t"]
        A = self._meet(pb, u, (0, zb), (1, 0))
        B = self._meet(pi, d, (0, zb), (1, 0))
        C = self._meet(pb, u, pi, d)
        if B[0] - A[0] < 16 or C[1] - zb < 16 or C[1] > g["R1"][1] - 6:
            return None
        return [A, B, C]

    def _profile(self, pts, plane=Plane.YZ):
        return plane * Polygon(*pts, align=None)

    def build(self, v):
        g, W = self.g(v), v["width"]
        u, n = g["u"], g["n"]
        # body: the profile with the channel still filled; its top runs straight from the lip to the backrest
        prof = self._profile([g["B0"], g["L1"], g["Q"], g["R1"], g["R2"], g["rear"]])
        rl = min(2.0, v["lip_t"] * 0.4)
        rb = v["back_t"] * 0.48
        try:
            prof = fillet(prof.vertices().filter_by(lambda p: abs(p.Y - g["L1"][0]) < 1e-3 and abs(p.Z - g["L1"][1]) < 1e-3), rl)
        except Exception:
            pass
        try:
            prof = fillet(prof.vertices().filter_by(lambda p: (abs(p.Y - g["R1"][0]) < 1e-3 and abs(p.Z - g["R1"][1]) < 1e-3)
                                                    or (abs(p.Y - g["R2"][0]) < 1e-3 and abs(p.Z - g["R2"][1]) < 1e-3)), rb)
        except Exception:
            pass
        win = self.window(v)
        if win is not None:
            wf = self._profile(win)
            try:
                wf = fillet(wf.vertices().filter_by(lambda p: p.Z < v["base_t"] + 1e-3), min(4.0, v["base_t"]))
            except Exception:
                pass
            prof = prof - wf
        body = extrude(prof, W / 2, both=True)
        stages = [Stage("body", body)]

        # seat channel: a box in the device's frame, from the seat up past the lip top
        t = g["t"]
        deep = v["lip_h"] + 30
        # Rot(-lean) about X turns the box's Z onto the device's up (u) and its Y onto n
        chan = Pos(0, g["S"][0], g["S"][1]) * Rot(-v["lean"], 0, 0) * Box(W + 2, t, deep, align=(Align.CENTER, Align.MIN, Align.MIN))
        s = body - chan
        stages.append(Stage("slot", s))

        if v["charge"] >= 0.5:
            # a slot whose back wall leans with the device: the backrest keeps its full thickness below the seat
            top = g["L1"][1] + 10
            on = lambda z: g["S2"][0] + 0.01 + (z - g["S2"][1]) * u[0] / u[1]
            sz = g["S2"][1]
            P = (g["S"][0] + (top - g["S"][1]) * u[0] / u[1], top)      # on the lip's back face, above the lip
            cp = self._profile([(g["B0"][0] - 5, -1), (on(-1), -1), (on(sz), sz), P, (g["B0"][0] - 5, top)])
            cut = extrude(cp, v["plug_w"] / 2, both=True)
            s = s - cut
            stages.append(Stage("cable", s))

        # soften: round the outline of both side faces (not the edges on the desk), then a 45° foot chamfer
        r = min(v["edge_r"], 0.3 * min(v["lip_t"], v["base_t"], v["strut_t"], v["back_t"]))
        s2 = s
        side = [e for e in s2.edges() if abs(abs(e.center().X) - W / 2) < 1e-3
                and min(p.Z for p in e.vertices()) > 1e-3]
        for rr in (r, r * 0.5):
            try:
                s2 = fillet(side, rr)
                break
            except Exception:
                pass
        if v["charge"] >= 0.5:                    # the slot's own vertical edges, softer
            es = [e for e in s2.edges() if abs(abs(e.center().X) - v["plug_w"] / 2) < 1e-3 and e.center().Z > 0.05
                  and e.center().Y < g["S2"][0] - 0.1 and abs(e.bounding_box().size.X) < 1e-3]
            for rr in (min(1.0, r), 0.5):
                try:
                    s2 = fillet(es, rr)
                    break
                except Exception:
                    pass
        s2 = foot_chamfer(s2, FOOT)
        stages.append(Stage("soften", s2))
        return stages

    # ---- interfaces ---------------------------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        out = [{"key": "slot_width", "label": "Seat channel width", "value": g["t"], "unit": "mm", "feature": "slot",
                "formula": "device thickness + 2 × clearance, square to the device", "interface": True},
               {"key": "stand_height", "label": "Stand height", "value": g["R1"][1] + v["back_t"] * math.sin(g["th"]),
                "unit": "mm", "feature": "body", "formula": "seat + backrest along the lean", "interface": False}]
        if v["charge"] >= 0.5:
            out.append({"key": "plug_slot", "label": "Charging slot width", "value": v["plug_w"], "unit": "mm",
                        "feature": "cable", "formula": "plug width", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        n = g["n"]
        # the channel walls are planes with normals ±n: the lip's back face and the backrest's front face (which
        # continues the channel wall above it, so OCCT keeps it as one face of the body)
        s0 = g["S"][0] * n[0] + g["S"][1] * n[1]
        offs = []
        for f in faces_by_feature.get("slot", []) + faces_by_feature.get("body", []):
            if f.geom_type.name != "PLANE":
                continue
            nm = f.normal_at(f.center())
            if abs(abs(nm.Y * n[0] + nm.Z * n[1]) - 1) < 1e-4:
                c = f.center()
                offs.append(c.Y * n[0] + c.Z * n[1] - s0)
        front = [o for o in offs if abs(o) < 0.5]
        back = [o for o in offs if abs(o - g["t"]) < 0.5]
        out = []
        if front and back:
            out.append({"key": "slot_width", "label": "Seat channel width", "intended": g["t"], "modelled": back[0] - front[0]})
        if v["charge"] >= 0.5:
            xs = [f.center().X for f in faces_by_feature.get("cable", []) if f.geom_type.name == "PLANE"
                  and abs(abs(f.normal_at(f.center()).X) - 1) < 1e-6]
            if len(xs) >= 2:
                out.append({"key": "plug_slot", "label": "Charging slot width", "intended": v["plug_w"], "modelled": max(xs) - min(xs)})
        return out

    # ---- tip-over -------------------------------------------------------------------------------------------------
    def statics(self, v, solid_volume_mm3, com, dock_mass_g=None):
        g = self.g(v)
        assumed = dock_mass_g is None
        m_st = dock_mass_g if dock_mass_g is not None else solid_volume_mm3 * PLA_DENSITY * INFILL
        L = v["device_height"]
        u, n = g["u"], g["n"]
        c_dev = (g["S"][0] + n[0] * g["t"] / 2 + u[0] * L / 2, g["S"][1] + n[1] * g["t"] / 2 + u[1] * L / 2)
        m = m_st + v["device_mass"]
        ycom = (m_st * com[1] + v["device_mass"] * c_dev[0]) / m
        rear = g["rear"][0] - FOOT
        margin = rear - ycom
        top = (g["S"][1] + u[1] * L)
        tip_n = max(margin, 0) * m * 9.81e-3 / top
        return {"dock_mass_g": m_st, "dock_mass_assumed": assumed, "com_y": ycom,
                "margin_back_mm": margin, "margin_front_mm": ycom - g["front"],
                "tip_force_n": tip_n, "push_height_mm": top,
                "model": "Rigid bodies, device as a uniform slab leaning on the backrest, friction and cable drag ignored."}

    def companions(self, v):
        g = self.g(v)
        u, n = g["u"], g["n"]
        o = (g["S"][0] + n[0] * g["t"] / 2, g["S"][1] + n[1] * g["t"] / 2)
        return [{"label": "Device", "size": [v["device_width"], v["device_thickness"], v["device_height"]],
                 "origin": [0, o[0], o[1]], "rot_x_deg": -v["lean"], "anchor": "bottom"}]

    def test_piece(self, v, shape):
        # a 12 mm wide slice of the whole profile at one side: the channel, lip and backrest root
        w = 12.0
        x0 = v["width"] / 2 - w
        slab = Pos(x0 + w / 2, 0, 0) * Box(w, v["depth"] + 10, 300, align=(Align.CENTER, Align.CENTER, Align.MIN))
        piece = shape & slab
        return Pos(-(x0 + w / 2), 0, 0) * piece, {"label": "Side slice", "doc": "A 12 mm slice through the seat channel, "
                                                  "lip and backrest. Drop the device's edge in to check the fit.", "height": None}
