"""Sculptural desk-lamp base: a spiral-ribbed body of revolution whose ribs ease out into a plain foot and a
collar, a ballast cavity under it closed by a cover plate, a lamp-pipe socket with a captured M10 nut, and a cable
channel to the rim.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, RegularPolygon, Rot, extrude

from form import craft
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Spiral lamp base", "Spiral-ribbed weighted lamp base with a pipe socket and a cable channel."
    solids = 2
    params = [
        Param("foot_d", "Foot diameter", 140, 110, 180, 1, "mm", "form", "body"),
        Param("height", "Height", 100, 70, 140, 1, "mm", "form", "body"),
        Param("ribs", "Ribs", 36, 18, 60, 1, "", "form", "body"),
        Param("rib_depth", "Rib depth", 2.2, 1.0, 4.0, 0.1, "mm", "form", "body"),
        Param("twist", "Spiral twist", 150, 0, 360, 5, "deg", "form", "body"),
        Param("pipe_d", "Lamp pipe diameter", 10.0, 8, 13, 0.05, "mm", "brief", "socket", "M10x1 lamp pipe (10 mm OD).", "specified"),
        Param("wall", "Wall", 4.0, 2.5, 8, 0.1, "mm", "form", "cavity"),
        Param("cable_d", "Cable diameter", 6.0, 3, 9, 0.1, "mm", "brief", "channel", "Measure the lamp's cable."),
    ]
    features = [Feature("body", "Spiral-ribbed body", "finish"), Feature("collar", "Collar", "structure"),
                Feature("cavity", "Ballast cavity", "structure"), Feature("socket", "Pipe socket and nut trap", "interface"),
                Feature("channel", "Cable channel", "access"), Feature("cover", "Cover plate", "structure")]

    def constraints(self, v):
        if v["rib_depth"] > 0.4 * math.pi * v["foot_d"] * 0.5 / v["ribs"]:          # where the ribs start to fade at the top
            return [RecipeError("Ribs this deep and this many crowd into each other", "body", "Fewer or shallower ribs.",
                                ["ribs", "rib_depth"])]
        return []

    def _profile(self, v):
        R, H = v["foot_d"] / 2, v["height"]
        # (root radius, z): a soft foot, a waist that leans in, shoulders, and a neck that meets the collar
        return [(R - 3.0, 0.0), (R, H * 0.08), (R * 0.93, H * 0.30), (R * 0.72, H * 0.55), (R * 0.50, H * 0.78),
                (R * 0.36, H * 0.93), (R * 0.33, H)]

    def build(self, v):
        R, H, t = v["foot_d"] / 2, v["height"], v["wall"]
        prof = self._profile(v)
        body = craft.spiral_ribbed_body(prof, ribs=int(v["ribs"]), rib_depth=v["rib_depth"], twist=v["twist"], levels=22,
                                        sharpness=2.2, fade=(0.1, 0.22))
        stages = [Stage("body", body)]
        # collar: a plain turned neck with a rounded top on which the pipe's washer sits
        rc = R * 0.33
        collar = craft.revolve_profile([(rc + 0.6, H - 1.0), (rc + 1.6, H + 4.0), (rc + 0.4, H + 12.0), (rc - 1.6, H + 15.0),
                                        (0.0, H + 15.0)], spline=False)
        collar = craft.safe_fillet(collar, collar.edges().group_by(Axis.Z)[-1], 2.0)
        body = body + collar
        body = craft.safe_fillet(body, [e for e in body.edges() if abs(e.center().Z) < 0.01], 1.2)
        stages.append(Stage("collar", body))
        # ballast cavity: the profile inset by the wall, open at the bottom, with a 3 mm rebate for the cover
        # inset along the slope, not just in radius: where the body leans in, a radial inset of t leaves far less
        # than t of wall (the first version broke through at the shoulder; the section showed it)
        inner, prev = [], None
        for (r0, z0), (r1, z1) in zip(prof, prof[1:]):
            slope = math.atan2(r0 - r1, z1 - z0)                 # how far the wall leans in
            inner.append((r0 - t / max(math.cos(slope), 0.4) - 1.0, z0))
        inner = [(x, z) for x, z in inner if z < H * 0.6]
        inner = [(inner[0][0] - 2.0, -1.0)] + inner[1:] + [(R * 0.45, H * 0.66 - t)]
        cav = craft.revolve_profile(inner, spline=True)
        body = body - cav
        body = body - Pos(0, 0, -0.01) * Cylinder(R - t - 2.0, 3.0, align=BOTTOM)
        stages.append(Stage("cavity", body))
        # socket: pipe bore through the collar and the roof, an M10 nut (ISO 4032: s 16, m 8.4) captured from inside
        body = body - Pos(0, 0, H * 0.5) * Cylinder(v["pipe_d"] / 2 + 0.2, H, align=BOTTOM)
        nut = extrude(RegularPolygon(16.3 / 2, 6, major_radius=False), 8.8)
        body = body - Pos(0, 0, H * 0.66 - t - 8.8 + 0.01) * nut
        stages.append(Stage("socket", body))
        # cable channel: from the cavity out through the foot, rounded, under the cover plate
        ch = Pos(R * 0.5, 0, -0.01) * Box(R, v["cable_d"] + 1.0, v["cable_d"] + 3.0, align=BOTTOM)
        body = body - ch
        stages.append(Stage("channel", body))
        # cover: a plate in the rebate, 0.3 mm clear all round, with a notch over the channel and three screw holes
        cr = R - t - 2.0 - 0.3
        cover = Pos(0, 0, 0.1) * Cylinder(cr, 2.6, align=BOTTOM)
        cover = cover - Pos(cr, 0, 0) * Box(2 * (cr - R * 0.5) + 2, v["cable_d"] + 1.6, 10, align=BOTTOM)
        for i in range(3):
            a = math.radians(90 + 120 * i)
            cover = cover - Pos((cr - 8) * math.cos(a), (cr - 8) * math.sin(a), 0) * Cylinder(1.8, 10, align=BOTTOM)
        cover = craft.safe_fillet(cover, cover.edges().group_by(Axis.Z)[0], 0.8)
        body = body + cover
        stages.append(Stage("cover", body))
        return stages

    def derived(self, v):
        R = v["foot_d"] / 2
        return [{"key": "rib_pitch", "label": "Rib pitch at the foot", "value": round(math.pi * v["foot_d"] / v["ribs"], 2),
                 "unit": "mm", "feature": "body", "formula": "pi d / ribs", "interface": False},
                {"key": "pipe_bore", "label": "Pipe bore", "value": v["pipe_d"] + 0.4, "unit": "mm", "feature": "socket",
                 "formula": "pipe + 2 x 0.2", "interface": True}]

    def assembly(self, v):
        R = v["foot_d"] / 2
        return Assembly(parts=[Part("body", "Body", (0, 0, v["height"] + 8)),
                               Part("cover", "Cover plate", (0, R * 0.3, 1.0), explode=(0, 0, -40),
                                    note="Fill the cavity with steel shot, lay the cable in the channel, screw the cover on.")])
