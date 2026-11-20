"""Disk cam and pivoting roller follower on a NEMA 17 base: a cycloidal plate cam from craft.cam on a hub with a
5 mm D bore and a set screw, a tapered follower arm on a printed pivot post, a roller on an M4 axle and a spring
post. Four printed parts declared as an assembly. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot, extrude

from form import craft, parts
from form.recipes.base import (Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage, hinge)

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Cam and pivoting roller follower",
    "category": "mechanical",
    "tags": ["cam", "follower", "roller", "lever", "rocker", "mechanism", "cycloidal", "d-shaft", "nema17", "stepper",
             "pressure angle", "set screw", "assembly", "motion", "automaton"],
    "techniques": ["craft.cam with follower_r: the plate is the roller's pitch curve offset inward",
                   "cam turned so the base-circle dwell sits under the roller at rest",
                   "D bore (5 mm, 4.5 across the flat) + radial M3 set screw over a square-nut slot",
                   "follower arm long against the lift; its swing and side drift in derived()",
                   "NEMA 17 pattern (22 mm pilot, 31 mm M3 square) in the base",
                   "assembly(): arm hinge with the roller attached, Mate pin and contact; cam motion as data"],
    "lessons": [
        "Draw the motion before the cam: rise, dwell, fall and dwell in degrees, with a cycloidal law (zero "
        "acceleration at both ends) unless speed is trivial. craft.cam builds the pitch curve and reports the worst "
        "pressure angle; above about 30 deg a follower jams, so grow the base circle or lengthen the rise.",
        "With a roller the cam plate is the pitch curve offset inward by the roller radius; the roller's centre rides "
        "the pitch curve. Keep the roller smaller than the cam's tightest concave radius or the offset folds.",
        "A pivoting follower moves on an arc, not a radius. Make the arm several times the lift (here 50 mm for 8 mm) "
        "and level at rest, so the arc is tangent to the radial line there; derived() states the swing and the side "
        "drift that remains.",
        "Interfaces from the motor's drawing: NEMA 17 has a 22 mm pilot, M3 holes on a 31 mm square and a 5 mm shaft "
        "with a 0.5 mm flat. A D bore alone wears loose; a set screw onto the flat, over a captive square nut, holds.",
        "Contact is not a joint: the roller is attached to the arm, the arm hinges on its post, and the cam's lift "
        "curve goes into derived(). A spring keeps the roller on the cam; the rest gap is the declared contact.",
    ],
}


class Design(Recipe):
    title, summary = "Cam and roller follower", "Cycloidal disk cam on a D-shaft hub driving a pivoting roller arm."
    solids = 4
    params = [
        Param("base_r", "Base circle (pitch)", 20, 15, 30, 0.5, "mm", "form", "cam"),
        Param("lift", "Lift", 8, 3, 12, 0.5, "mm", "brief", "cam"),
        Param("rise", "Rise angle", 150, 90, 160, 5, "deg", "brief", "cam"),
        Param("dwell", "Dwell at the top", 30, 0, 35, 5, "deg", "brief", "cam"),
        Param("fall", "Fall angle", 150, 90, 160, 5, "deg", "brief", "cam"),
        Param("roller_d", "Roller diameter", 12, 8, 16, 0.5, "mm", "form", "roller"),
        Param("arm_len", "Follower arm length", 50, 35, 90, 1, "mm", "form", "arm",
              "Pivot to roller; several times the lift keeps the arc close to radial."),
        Param("shaft_d", "Motor shaft", 5, 5, 5, 0.1, "mm", "brief", "hub", "NEMA 17: 5 mm with a 0.5 mm flat.",
              "specified"),
    ]
    features = [Feature("base", "Base and posts", "structure"), Feature("cam", "Cam plate", "structure"),
                Feature("hub", "D-shaft hub", "interface"), Feature("arm", "Follower arm", "structure"),
                Feature("roller", "Roller", "interface")]

    BASE_T, PLATE_T, HUB_H, ROLLER_T, ARM_T, G = 5.0, 6.0, 8.0, 5.0, 4.0, 0.3

    def constraints(self, v):
        if v["rise"] + v["dwell"] + v["fall"] > 345:
            return [RecipeError("Rise, dwell and fall leave no rest dwell for the roller", "cam",
                                "Shorten one of them (the rest dwell must be at least 15 deg).", ["rise", "dwell", "fall"])]
        if v["roller_d"] / 2 > v["base_r"] - 9:
            return [RecipeError("The roller is too large for the base circle around the hub", "roller",
                                "Use a smaller roller or a larger base circle.", ["roller_d", "base_r"])]
        if v["arm_len"] < 4 * v["lift"]:
            return [RecipeError("The arm is short for the lift: its arc drifts far from radial", "arm",
                                "Lengthen the arm or reduce the lift.", ["arm_len", "lift"])]
        return []

    def _z(self):
        z_cam = self.BASE_T + 0.5                                   # cam plate underside
        z_rol = z_cam + (self.PLATE_T - self.ROLLER_T) / 2          # roller centred on the plate
        z_arm = z_cam + self.PLATE_T + 0.5                          # arm underside, clear above the plate
        return z_cam, z_rol, z_arm

    def _cam(self, v):
        return craft.cam(base_r=v["base_r"], lift=v["lift"], rise=v["rise"], dwell_top=v["dwell"], fall=v["fall"],
                         kind="cycloidal", thickness=self.PLATE_T, bore=0, follower_r=v["roller_d"] / 2)

    def _geom(self, v):
        rb, fr, La = v["base_r"], v["roller_d"] / 2, v["arm_len"]
        roller = (0.0, rb + self.G)                                 # roller centre at rest, over the base circle
        pivot = (La, rb + self.G)                                   # arm level at rest: the arc is radial there
        rest = (v["rise"] + v["dwell"] + v["fall"] + 360) / 2       # middle of the rest dwell
        spin = 90 - rest                                            # turn the cam so that dwell faces the roller
        swing = math.degrees(math.asin(min(v["lift"] / La, 0.99)))
        return rb, fr, La, roller, pivot, spin, swing

    def _print_layout(self, v):
        """Where each part prints, clear of the base: cam x, roller (x, y), arm flip offset in y."""
        rb, lift, fr = v["base_r"], v["lift"], v["roller_d"] / 2
        cx = -rb - lift - 6 - (rb + lift) - 8
        return cx, (cx, rb + lift + fr + 8), 2 * rb + 33

    def build(self, v):
        rb, fr, La, roller_c, pivot, spin, swing = self._geom(v)
        cx, (qx, qy), ya = self._print_layout(v)
        z_cam, z_rol, z_arm = self._z()
        # base: NEMA 17 face pattern, pivot post, spring post
        x0, x1, y0, y1 = -rb - v["lift"] - 6, La + 12, -rb - v["lift"] - 6, rb + 14
        base = Pos((x0 + x1) / 2, (y0 + y1) / 2, 0) * Box(x1 - x0, y1 - y0, self.BASE_T, align=BOTTOM)
        base = craft.safe_fillet(base, base.edges().filter_by(Axis.Z), 6.0)
        base = craft.safe_fillet(base, base.edges().group_by(Axis.Z)[-1], 1.0)
        base = base - Pos(0, 0, -1) * Cylinder(22.2 / 2, self.BASE_T + 2, align=BOTTOM)
        for sx in (-1, 1):
            for sy in (-1, 1):
                base = base - Pos(sx * 15.5, sy * 15.5, self.BASE_T) * parts.screw_clearance("M3", self.BASE_T,
                                                                                              head="socket").shape
        post_top = z_arm + self.ARM_T + 0.3
        base = base + Pos(*pivot, self.BASE_T - 0.2) * Cylinder(4.0, post_top - self.BASE_T + 0.2, align=BOTTOM)
        base = base - Pos(*pivot, post_top) * parts.self_tap_pilot("M3", 8).shape
        sp = (La * 0.55, rb + self.G - 20)
        base = base + Pos(*sp, self.BASE_T - 0.2) * Cylinder(3.0, z_arm - 0.5 - self.BASE_T + 0.2, align=BOTTOM)
        base = base - Pos(*sp, z_arm - 2.5) * (Cylinder(3.5, 1.2, align=BOTTOM) - Cylinder(2.2, 1.2, align=BOTTOM))
        stages = [Stage("base", base)]

        # --- snippet: a roller cam: craft.cam gives the plate (pitch curve offset by the roller), turned so the
        # rest dwell faces the roller; its lift law and pressure angle come back as numbers
        cm = self._cam(v)
        plate = Rot(0, 0, spin) * cm.shapes["cam"]
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.Z)[-1], 0.8)
        # --- end snippet
        lay = Pos(cx, 0, 0)                                         # cam printed left of the base
        stages.append(Stage("cam", base + lay * plate))
        # hub with a D bore and a radial M3 set screw onto the flat, over a square nut slot dropped in from the top
        hub = Pos(0, 0, self.PLATE_T - 0.2) * Cylinder(8.0, self.HUB_H + 0.2, align=BOTTOM)
        cam = craft.fuse(plate, hub)
        cam = craft.safe_fillet(cam, cam.edges().group_by(Axis.Z)[-1], 0.8)
        d = v["shaft_d"] + 0.15
        dbore = Pos(0, 0, -1) * Cylinder(d / 2, 30, align=BOTTOM) - Pos(d / 2 - 0.5 + 5, 0, -2) * Box(10, 10, 40, align=BOTTOM)
        cam = cam - dbore
        zs = self.PLATE_T + self.HUB_H / 2
        cam = cam - Pos(0, 0, zs) * Rot(0, 90, 0) * Cylinder(parts.clearance_d("M3")[0] / 2, 10, align=BOTTOM)
        cam = cam - Pos(4.6, 0, zs - 3.1) * Box(2.2, 5.9, 20, align=BOTTOM)
        stages.append(Stage("hub", base + lay * cam))

        # follower arm, modelled in place, printed top-down: a tapered bar, a pivot sleeve, a roller boss, a spring tab
        rx, ry = roller_c
        px, py = pivot
        bar = extrude(craft.polygon_profile([(rx, ry - 5), (px, py - 8), (px, py + 8), (rx, ry + 5)]), self.ARM_T)
        bar = bar + Pos(rx, ry, 0) * Cylinder(6.0, self.ARM_T, align=BOTTOM) + Pos(px, py, 0) * Cylinder(8.0, self.ARM_T, align=BOTTOM)
        tab_x = sp[0]
        bar = bar + extrude(craft.polygon_profile([(tab_x - 5, ry - 1), (tab_x + 5, ry - 1), (tab_x + 4, sp[1] + 9),
                                                   (tab_x - 4, sp[1] + 9)]), self.ARM_T)
        bar = bar + Pos(tab_x, sp[1] + 9, 0) * Cylinder(4.0, self.ARM_T, align=BOTTOM)
        bar = Pos(0, 0, z_arm) * bar
        sleeve = Pos(px, py, z_cam) * Cylinder(7.0, z_arm - z_cam + 0.2, align=BOTTOM)
        boss = Pos(rx, ry, z_rol + self.ROLLER_T + self.G) * Cylinder(4.0, z_arm - (z_rol + self.ROLLER_T + self.G) + 0.2,
                                                                      align=BOTTOM)
        arm = craft.fuse(bar, sleeve + boss)
        arm = craft.safe_fillet(arm, arm.edges().group_by(Axis.Z)[-1], 1.0)
        arm = arm - Pos(px, py, 0) * Cylinder(4.0 + 0.25, 40, align=BOTTOM)
        arm = arm - Pos(rx, ry, 0) * Cylinder(parts.clearance_d("M4")[0] / 2, 40, align=BOTTOM)
        arm = arm - Pos(tab_x, sp[1] + 9, 0) * Cylinder(1.6, 40, align=BOTTOM)
        top = z_arm + self.ARM_T
        flip = lambda s: Pos(0, ya, top) * Rot(180, 0, 0) * s     # printed top-down beside the base
        stages.append(Stage("arm", base + lay * cam + flip(arm)))
        # roller on an M4 axle, its edges chamfered so it rides onto the cam smoothly
        rol = Cylinder(fr, self.ROLLER_T, align=BOTTOM)
        rol = craft.attempt("roller chamfer", [("0.6 mm", lambda: rol.chamfer(0.6, None, rol.edges())),
                                               ("sharp", lambda: rol)], "", ["roller_d"])
        rol = rol - Pos(0, 0, -1) * Cylinder(4.0 / 2 + 0.2, self.ROLLER_T + 2, align=BOTTOM)
        rol_at = Pos(qx, qy, 0)
        body = base + lay * cam + flip(arm) + rol_at * rol
        stages.append(Stage("roller", body))
        self._spin = spin
        return parts.checked(stages)

    def derived(self, v):
        cm = self._cam(v)
        rb, fr, La, roller_c, pivot, spin, swing = self._geom(v)
        return cm.derived("cam", "cam.") + [
            {"key": "arm_swing", "label": "Arm swing at full lift", "value": round(swing, 2), "unit": "deg",
             "feature": "arm", "formula": "asin(lift / arm length)", "interface": False},
            {"key": "side_drift", "label": "Roller side drift at full lift", "value": round(La * (1 - math.cos(math.radians(swing))), 3),
             "unit": "mm", "feature": "arm", "formula": "arm length x (1 - cos swing): the arc's departure from radial",
             "interface": False},
            {"key": "d_flat", "label": "D bore across the flat", "value": v["shaft_d"] + 0.15 - 0.5, "unit": "mm",
             "feature": "hub", "formula": "NEMA 17 shaft 5 mm, flat 0.5 mm deep, + 0.15 clearance", "interface": True}]

    def assembly(self, v):
        rb, fr, La, roller_c, pivot, spin, swing = self._geom(v)
        z_cam, z_rol, z_arm = self._z()
        cx, (qx, qy), ya = self._print_layout(v)
        top = z_arm + self.ARM_T
        rx, ry = roller_c
        # the arm is printed as Pos(0, ya, top) * Rot(180, 0, 0) * arm: turning it back over puts it in place
        return Assembly(
            parts=[Part("base", "Base", (pivot[0], pivot[1], 1.0), note="Bolt the base to the motor face (4 x M3)."),
                   Part("cam", "Cam", (cx, -6.0, 1.0), move=(-cx, 0, z_cam), explode=(0, 0, 25),
                        note="Push the cam onto the D shaft and tighten the set screw onto the flat."),
                   Part("arm", "Follower arm", ((rx + pivot[0]) / 2, ya - ry, 1.0), move=(0, ya, top), rotate=(180, 0, 0),
                        explode=(0, 0, 45), note="Drop the arm's sleeve over the pivot post; screw a washer on top."),
                   Part("roller", "Roller", (qx + fr - 1.0, qy, 1.0), move=(rx - qx, ry - qy, z_rol), attach="arm",
                        explode=(0, 0, -15), note="Fit the roller under the arm on the M4 axle."),
                   ],
            joints=[hinge("arm", (0, 0, 1), (pivot[0], pivot[1], 0), (-(swing + 2), 0), 7, parent="base",
                          id="follower", label="Follower lift")],
            mates=[Mate("arm", "base", "pin", 0.25, "Arm sleeve on the pivot post"),
                   Mate("roller", "cam", "contact", self.G, "Roller on the cam (a spring holds it in use)")],
            hardware=[Hardware("M4 socket screw + nylock nut", "M4 x 16", 1, "ISO 4762 / ISO 7040", "Roller axle.",
                               after="roller"),
                      Hardware("M3 grub screw + square nut", "M3 x 6", 1, "ISO 4027 / DIN 562", "Cam set screw.",
                               after="cam"),
                      Hardware("Extension spring", "5 x 20 mm", 1, "stock", "From the arm's tab to the spring post.",
                               after="roller"),
                      Hardware("M3 screw + 10 mm washer", "M3 x 8", 1, "ISO 4762 / ISO 7089", "Keeps the arm on its post.",
                               after="arm")])

    def appearance(self, v):
        return [{"features": ["cam", "hub"], "finish": "metal", "color": "#b7bcc2"},
                {"features": ["roller"], "finish": "rubber", "color": "#1d1f22"},
                {"features": ["arm"], "finish": "petg", "color": "#2d6cdf"},
                {"features": ["base"], "finish": "matte", "color": "#2f3338"}]
