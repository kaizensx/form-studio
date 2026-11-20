"""Gasketed enclosure for a Raspberry Pi 5: base with standoffs and two cable-gland bosses, a lid with a gasket
groove that closes on a tongue around the base rim, a pin hinge along the back and a cantilever snap latch at the
front. Modelled closed (as used); the lid swings open on its hinge joint.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Access, Assembly, Feature, Hardware, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def rrect(w, d, h, r):
    """A rounded-rectangle prism standing on z = 0."""
    b = Box(w, d, h, align=BOTTOM)
    return craft.safe_fillet(b, b.edges().filter_by(Axis.Z), min(r, w / 2 - 0.05, d / 2 - 0.05))


class Design(Recipe):
    title, summary = "Pi 5 sealed enclosure", "Hinged, gasketed enclosure for a Raspberry Pi 5 with a snap latch."
    solids = 2
    params = [
        Param("board_w", "Board length", 85.0, 85, 90, 0.1, "mm", "brief", "standoffs", "Raspberry Pi 5 mechanical drawing.", "specified"),
        Param("board_d", "Board width", 56.0, 56, 60, 0.1, "mm", "brief", "standoffs", "Raspberry Pi 5 mechanical drawing.", "specified"),
        Param("hole_x", "Hole pitch along the board", 58.0, 58, 58, 0.1, "mm", "brief", "standoffs", "Pi 5 drawing: 58 x 49.", "specified"),
        Param("hole_y", "Hole pitch across the board", 49.0, 49, 49, 0.1, "mm", "brief", "standoffs", "Pi 5 drawing: 58 x 49.", "specified"),
        Param("headroom", "Height above the board", 24, 18, 40, 0.5, "mm", "brief", "base", "Tallest part + active cooler; measure yours."),
        Param("wall", "Base wall", 3.2, 2.8, 4, 0.1, "mm", "form", "base"),
        Param("corner_r", "Plan corner radius", 7, 3, 12, 0.5, "mm", "form", "base"),
        Param("gasket_d", "Gasket cord diameter", 1.5, 1.0, 3.0, 0.1, "mm", "brief", "gasket", "Silicone cord; measure it."),
        Param("hinge_clear", "Hinge clearance / side", 0.35, 0.2, 0.6, 0.05, "mm", "interface", "hinge"),
        Param("gland_d", "Cable gland hole", 12.7, 10, 20.5, 0.1, "mm", "brief", "glands", "PG7 / M12 gland: 12.5-12.7 mm hole.", "specified"),
    ]
    features = [Feature("base", "Base", "structure"), Feature("tongue", "Rim tongue", "interface"),
                Feature("standoffs", "Pi standoffs with M2.5 inserts", "interface"), Feature("glands", "Cable-gland bosses", "access"),
                Feature("lid", "Lid", "structure"), Feature("gasket", "Gasket groove", "interface"),
                Feature("hinge", "Pin hinge", "interface"), Feature("latch", "Snap latch and ledge", "interface")]

    def constraints(self, v):
        out = []
        if v["gasket_d"] + 0.6 > 3.6 - 1.4:
            out.append(RecipeError("The gasket groove leaves the lid wall too thin", "gasket", "Use a thinner cord.", ["gasket_d"]))
        return out

    def _dims(self, v):
        inner_w, inner_d = v["board_w"] + 2 * 3.5, v["board_d"] + 2 * 3.5
        t = v["wall"]
        lid_t = 4.0
        W, D = inner_w + 2 * t, inner_d + 2 * t
        Hb = 3.0 + 5.0 + 1.6 + v["headroom"] * 0.7          # floor + standoff + board + most of the headroom
        Hl = 3.0 + v["headroom"] * 0.3 + 1.0                # the rest of the headroom is in the lid
        return W, D, Hb, Hl, t, lid_t, 0.4

    def build(self, v):
        W, D, Hb, Hl, t, lt, g = self._dims(v)
        r = v["corner_r"]
        # base: a rounded tub, softened outside, crisp rim
        base = rrect(W, D, Hb, r)
        base = craft.safe_fillet(base, base.edges().group_by(Axis.Z)[0], 2.0)
        base = base - Pos(0, 0, 3.0) * rrect(W - 2 * t, D - 2 * t, Hb, r - t)
        stages = [Stage("base", base)]
        # tongue: 1.2 mm wide, 2 mm tall, centred on the rim, presses the cord into the lid's groove
        tw, th = 1.2, 2.0
        mid = 1.9                                              # seal line: 1.9 mm in from the outside
        tongue = rrect(W - 2 * mid + tw, D - 2 * mid + tw, th + 0.1, r - mid + tw / 2) - rrect(W - 2 * mid - tw, D - 2 * mid - tw, th + 0.1, r - mid - tw / 2)
        base = base + Pos(0, 0, Hb - 0.1) * tongue
        stages.append(Stage("tongue", base))
        # standoffs: M2.5 heat-set inserts (CNC Kitchen hole), board 5 mm above the floor
        ins = parts.heat_insert_pocket("M2.5")
        bx = -(W / 2 - t) + 3.5 + 3.5                          # board's left hole: 3.5 mm from its edge
        for dx in (0, v["hole_x"]):
            for sy in (-1, 1):
                x, y = bx + dx, sy * v["hole_y"] / 2
                post = Pos(x, y, 2.9) * Cylinder(ins["boss_min_d"] / 2 + 0.6, 5.1, align=BOTTOM)
                base = base + post
                base = base - Pos(x, y, 8.0) * ins.shape
        stages.append(Stage("standoffs", base))
        # glands: two raised spot faces on the +X end wall, through holes for PG7 glands
        zc = 3.0 + Hb * 0.42
        for y in (-D * 0.22, D * 0.22):
            boss = Pos(W / 2 - 0.5, y, zc) * Rot(0, 90, 0) * Cylinder(v["gland_d"] / 2 + 4.0, 2.0, align=BOTTOM)
            base = base + boss
            base = base - Pos(W / 2 - t - 1, y, zc) * Rot(0, 90, 0) * Cylinder(v["gland_d"] / 2, t + 5, align=BOTTOM)
        stages.append(Stage("glands", base))
        # lid: same plan, thicker wall that carries the gasket groove, domed slightly by a big top fillet
        z0 = Hb + g
        lid = Pos(0, 0, z0) * rrect(W, D, Hl, r)
        lid = craft.safe_fillet(lid, lid.edges().group_by(Axis.Z)[-1], 3.0)
        lid = lid - Pos(0, 0, z0 - 0.1) * rrect(W - 2 * lt, D - 2 * lt, Hl - 2.5 + 0.1, r - lt)
        body = base + lid
        stages.append(Stage("lid", body))
        gw = v["gasket_d"] + 0.5
        gr = rrect(W - 2 * mid + gw, D - 2 * mid + gw, 3.0, r - mid + gw / 2) - rrect(W - 2 * mid - gw, D - 2 * mid - gw, 3.0, r - mid - gw / 2)
        body = body - Pos(0, 0, z0 - 0.01) * gr
        stages.append(Stage("gasket", body))
        # hinge along the back (-Y): knuckles outside the wall, leaves half sunk into the back walls
        R = 4.5
        lw, HL = 10.5, W * 0.62
        h = craft.pin_hinge(length=HL, outer_d=2 * R, pin_d=3.0, knuckles=5, clearance=v["hinge_clear"],
                            leaf_w=lw, leaf_t=2.4)
        yh, zh = -D / 2 - R - 0.4, Hb + g / 2                     # axis just outside the back: knuckles clear both walls
        place = Pos(0, yh, zh) * Rot(90, 0, 0) * Pos(0, 0, -R)
        a, b = place * h["leaf_a"], place * h["leaf_b"]
        body = body - place * h.info["relief_a"] - place * h.info["relief_b"]
        # webs from each leaf into its wall, above and below the knuckles (never in the knuckle zone)
        kz = R + v["hinge_clear"] + 0.4
        web_a = Pos(0, yh + R - 2.4, zh - lw) * Box(HL, 2.4 + 0.4 + 0.8, lw - kz, align=(Align.CENTER, Align.MIN, Align.MIN))
        web_b = Pos(0, yh + R - 2.4, zh + kz) * Box(HL, 2.4 + 0.4 + 0.8, lw - kz, align=(Align.CENTER, Align.MIN, Align.MIN))
        web_a = craft.safe_fillet(web_a, web_a.edges().filter_by(Axis.Y), 1.0)
        web_b = craft.safe_fillet(web_b, web_b.edges().filter_by(Axis.Y), 1.0)
        body = body + a + b + web_a + web_b
        stages.append(Stage("hinge", body))
        # latch: a hook hanging from a lug on the lid front, catching under a ramped ledge on the base front
        L, ht, hw, u = 11.0, 1.8, 10.0, 0.8
        snap = craft.cantilever_snap(length=L, thickness=ht, width=hw, undercut=u, lead_angle=35)
        self._snap = snap
        p, c = 1.6, 0.3                                          # ledge proud of the wall; clearance beam to ledge
        zr = z0 + 2.0
        ybeam = D / 2 + p + c + ht
        hook = Pos(0, ybeam, zr) * Rot(0, 0, -90) * Rot(180, 0, 0) * snap["hook"]
        lug = Pos(0, D / 2 - 0.5, zr - 0.01) * Box(hw, ybeam - D / 2 + 0.5, Hl - 3.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        lug = craft.safe_fillet(lug, lug.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], 1.5)
        body = body + lug + hook
        zl = zr - L + 0.25
        ledge = Pos(0, D / 2 - 0.5, zl) * Box(hw + 6, p + 0.5, 3.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        ledge = ledge.chamfer(1.4, 1.2, ledge.edges().group_by(Axis.Z)[-1].group_by(Axis.Y)[-1])   # ramp on top
        body = body + ledge
        stages.append(Stage("latch", body))
        return parts.checked(stages)

    def derived(self, v):
        W, D, Hb, Hl, t, lt, g = self._dims(v)
        e = 1.5 * 1.8 * 0.8 / 11.0 ** 2
        return [{"key": "outer", "label": "Outside size", "value": round(W, 1), "unit": "mm", "feature": "base",
                 "formula": f"{W:.1f} x {D:.1f} x {Hb + g + Hl:.1f}", "interface": False},
                {"key": "snap_strain", "label": "Latch hook strain", "value": round(e * 100, 2), "unit": "%", "feature": "latch",
                 "formula": "1.5 t y / L^2 (computed)", "interface": False},
                {"key": "gasket_squeeze", "label": "Gasket squeeze", "value": round(2.0 - (3.0 - v["gasket_d"]) + g, 2) if False else
                 round((v["gasket_d"] - (3.0 - (2.0 - g))) / v["gasket_d"] * 100, 0), "unit": "%", "feature": "gasket",
                 "formula": "(cord - (groove depth - tongue engagement)) / cord", "interface": True}]

    def assembly(self, v):
        W, D, Hb, Hl, t, lt, g = self._dims(v)
        yh, zh = -D / 2 - 4.5 - 0.4, Hb + g / 2
        return Assembly(
            parts=[Part("base", "Base", (W / 2 - 1.0, 0, 5.0), note="Screw the Pi onto the standoffs (M2.5 x 6)."),
                   Part("lid", "Lid", (0, 0, Hb + g + Hl - 1.0), explode=(0, 0, 30),
                        note="Lay the gasket cord in the lid groove, close the lid and press until the latch clicks.")],
            joints=[hinge("lid", (1, 0, 0), (0, yh, zh), (0, 110), 12, parent="base", id="lid_open", label="Lid")],
            hardware=[Hardware("Heat-set insert", "M2.5", 4, "CNC Kitchen", "In the standoffs", after="base"),
                      Hardware("Screw", "M2.5 x 6", 4, "ISO 7380", "Pi to standoffs", after="base"),
                      Hardware("Cable gland", "PG7", 2, "IP68", "In the end wall", after="base"),
                      Hardware("Silicone cord", f"{v['gasket_d']:g} mm", 1, "", "Gasket, about "
                               f"{2 * (W + D) * 0.95:.0f} mm", after="base")])
