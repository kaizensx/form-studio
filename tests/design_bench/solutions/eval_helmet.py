"""Full-face motorcycle helmet shell with a carbon-like twill on the outside, an eye port, chin and crown vents, a
rear spoiler, and a visor that rides 1 mm off the shell on two pivot studs. Visual and fit model, not a certified
helmet: no impact liner, no retention system, no standard (ECE 22.06 / DOT) is claimed.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Box, Cylinder, Plane, Pos, Rot, extrude

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Motorcycle helmet shell", "Full-face shell, carbon-like twill, eye port, vents and a pivoting visor."
    solids = 2
    params = [
        Param("head_l", "Head length", 200, 180, 215, 1, "mm", "brief", "shell", "Measure: glabella to back of head."),
        Param("head_w", "Head width", 160, 140, 175, 1, "mm", "brief", "shell"),
        Param("allow", "Liner + shell allowance per side", 35, 25, 45, 1, "mm", "form", "shell", "EPS liner ~25-30 + shell."),
        Param("wall", "Shell wall", 3.5, 2.5, 5, 0.1, "mm", "form", "shell"),
        Param("port_w", "Eye port width", 165, 140, 190, 1, "mm", "form", "eye_port"),
        Param("port_h", "Eye port height", 62, 50, 75, 1, "mm", "form", "eye_port"),
        Param("visor_gap", "Visor gap to shell", 1.2, 0.6, 2.5, 0.1, "mm", "interface", "visor"),
        Param("weave", "Twill depth", 0.25, 0, 0.5, 0.05, "mm", "form", "shell", "Mesh texture; STEP carries the smooth body."),
    ]
    features = [Feature("shell", "Shell (carbon twill)", "structure"), Feature("eye_port", "Eye port", "access"),
                Feature("chin_vent", "Chin vent", "access"), Feature("crown_vents", "Crown vents", "access"),
                Feature("spoiler", "Rear spoiler", "finish"), Feature("pivots", "Visor pivot studs", "interface"),
                Feature("visor", "Visor", "structure")]

    def _geo(self, v):
        L, W = v["head_l"] + 2 * v["allow"], v["head_w"] + 2 * v["allow"]
        H, S = 0.62 * L, 0.36 * L                         # dome height and the skirt below the dome's widest line
        secs, tip = craft.helmet_sections(L, W, H, S, crown_back=0.05 * L, squash_front=0.1)
        # the chin bar juts forward and narrows: shift the low sections toward +X and pinch them
        for s in secs:
            if s["z"] < S:
                u = 1 - s["z"] / S
                s["cx"] = s.get("cx", 0.0) + 0.07 * L * u
                s["b"] *= 1 - 0.08 * u
                s["squash"] = s.get("squash", 0.0) + 0.12 * u
        eye_z = S + 0.12 * H                              # eye line: just above where the dome starts
        piv = (0.04 * L, eye_z + 0.18 * H)                # pivot centre (x, z), each side
        return L, W, H, S, secs, tip, eye_z, piv

    def constraints(self, v):
        if v["port_w"] > v["head_w"] + 2 * v["allow"] - 40:
            return [RecipeError("The eye port is as wide as the helmet", "eye_port", "Narrow the port.", ["port_w"])]
        return []

    def build(self, v):
        L, W, H, S, secs, tip, eye_z, piv = self._geo(v)
        t = v["wall"]
        outer = craft.section_body(secs, tip=tip)
        inner = craft.inset_body(secs, t, tip=tip, open_bottom=True)
        shell = outer - inner
        # the lower edge sweeps up behind the jaw to a neck roll: a side-profile cutter through the whole width
        cut = craft.spline_profile([(-L, -5), (-L, 0.22 * S), (-0.5 * L / 2, 0.20 * S), (0.05 * L, 0.06 * S),
                                    (0.3 * L, -0.02 * S), (L, -5)], plane=Plane.XZ)
        cutter = extrude(cut, W, both=True)
        shell = shell - cutter
        lip = [e for e in shell.edges() if e.center().Z < 0.25 * S]
        shell = craft.safe_fillet(shell, lip, 1.5)
        stages = [Stage("shell", shell)]
        # eye port: a soft-square superellipse driven through the front, its edges rounded inside and out
        pw, ph = v["port_w"] / 2, v["port_h"] / 2
        prof = craft.superellipse_face(pw, ph, 3.2, plane=Plane.YZ, center=(0, eye_z + ph))
        port = extrude(prof, L)
        shell = shell - Pos(L * 0.08, 0, 0) * port
        rim = [e for e in shell.edges() if e.center().X > L * 0.08 and eye_z - 2 < e.center().Z < eye_z + 2 * ph + 2]
        shell = craft.safe_fillet(shell, rim, 1.5)
        stages.append(Stage("eye_port", shell))
        # chin vent: three slots across the chin bar, following its curve
        for i in (-1, 0, 1):
            slot = Pos(L / 2 - 20, i * 16, eye_z - 42) * Box(60, 9, 3.2)
            slot = craft.safe_fillet(slot, slot.edges().filter_by(lambda e: abs(e.tangent_at(0.5).X) > 0.99), 1.4)
            shell = shell - slot
        stages.append(Stage("chin_vent", shell))
        # crown vents: two slots that run fore and aft on top, a raised lip in front of each
        zc = S + H * 0.86
        for sy in (-1, 1):
            vent = Pos(L * 0.12, sy * W * 0.12, zc) * Box(34, 7, 60)
            vent = craft.safe_fillet(vent, vent.edges().filter_by(lambda e: abs(e.tangent_at(0.5).Z) > 0.99), 3.0)
            shell = shell - vent
        stages.append(Stage("crown_vents", shell))
        # rear spoiler: the shell's surface grown 5 mm, kept in a band across the back of the crown
        s5, t5 = craft.inflate(secs, 5.0, tip)
        band = Pos(-L / 2 + 15, 0, S + H * 0.38) * Box(70, W * 0.55, 26)
        spoiler = (craft.section_body(s5, tip=t5) & band) - inner
        spoiler = craft.safe_fillet(spoiler, spoiler.edges(), 2.0)
        shell = shell + spoiler
        stages.append(Stage("spoiler", shell))
        # visor pivots: a stud on each side, clipped to the zone between the inner surface and 6 mm outside
        g = v["visor_gap"]
        lo_s, lo_t = craft.inflate(secs, g, tip)
        hi_s, hi_t = craft.inflate(secs, g + 3.0, tip)
        cap_lo, cap_lt = craft.inflate(secs, g + 3.5, tip)
        cap_hi, cap_ht = craft.inflate(secs, g + 5.5, tip)
        zone = craft.section_body(cap_hi, tip=cap_ht) - inner
        studs = None
        for sy in (-1, 1):
            axis = Pos(piv[0], 0, piv[1]) * Rot(90, 0, 0)
            stud = (axis * Cylinder(4.0, W + 40)) & zone
            cap = (axis * Cylinder(7.0, W + 40)) & (craft.section_body(cap_hi, tip=cap_ht) - craft.section_body(cap_lo, tip=cap_lt))
            part = stud + cap
            part = part & (Pos(0, sy * (W / 2 + 30), 0) * Box(L, 80, 2 * L))
            studs = part if studs is None else studs + part
        shell = shell + studs
        stages.append(Stage("pivots", shell))
        # visor: a 3 mm band g off the shell over the port, widened to discs round the pivots, bored for the studs
        skin = craft.section_body(hi_s, tip=hi_t) - craft.section_body(lo_s, tip=lo_t)
        # the visor wraps from the front back to both pivots, like a real one: everything forward of the pivots
        # side outline of the visor: a curved lower edge that rises to the pivot, a crown edge that sweeps back
        zt, zb = eye_z + 2 * ph + 16, eye_z - 16
        outline = craft.spline_profile([(piv[0] + 6, piv[1] + 16), (L * 0.25, zt), (L * 0.6, zt + 4), (L * 0.6, zb - 8),
                                        (L * 0.3, zb - 6), (piv[0] + 14, piv[1] - 14)], plane=Plane.XZ)
        window = extrude(outline, W, both=True)
        discs = Pos(piv[0], 0, piv[1]) * Rot(90, 0, 0) * Cylinder(18, W + 40)
        visor = skin & (window + discs)
        visor = visor - Pos(piv[0], 0, piv[1]) * Rot(90, 0, 0) * Cylinder(4.4, W + 40)
        visor = craft.safe_fillet(visor, [e for e in visor.edges() if e.length > 20], 1.2)
        body = shell + visor
        stages.append(Stage("visor", body))
        return stages

    def mesh_texture(self, v):
        if v["weave"] <= 0:
            return []
        return [MeshTexture("weave", amplitude=v["weave"], scale=3.0, features=["shell", "spoiler"], facing="out",
                            edge_falloff=2.0)]

    def derived(self, v):
        L, W, H, S, secs, tip, eye_z, piv = self._geo(v)
        return [{"key": "shell_l", "label": "Shell length", "value": round(L, 1), "unit": "mm", "feature": "shell",
                 "formula": "head length + 2 x allowance", "interface": False},
                {"key": "shell_w", "label": "Shell width", "value": round(W, 1), "unit": "mm", "feature": "shell",
                 "formula": "head width + 2 x allowance", "interface": False},
                {"key": "visor_gap", "label": "Visor gap", "value": v["visor_gap"], "unit": "mm", "feature": "visor",
                 "formula": "inflate(sections, gap)", "interface": True}]

    def assembly(self, v):
        L, W, H, S, secs, tip, eye_z, piv = self._geo(v)
        return Assembly(parts=[Part("shell", "Shell", (-L / 2 + 1.5, 0, S + 10), note="The shell."),
                               Part("visor", "Visor", (L / 2 + v["visor_gap"] + 1.0, 0, eye_z + v["port_h"] / 2),
                                    explode=(60, 0, 0), note="Slide the visor over the pivot caps.")],
                        joints=[hinge("visor", (0, 1, 0), (piv[0], 0, piv[1]), (-35, 0), 8, parent="shell",
                                      id="visor_up", label="Visor")])
