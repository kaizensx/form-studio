"""Drinks bottle and screw cap, modelled screwed together: a revolved PET-style bottle sized from its volume
(craft.bottle_profile) with a PCO 1881-style neck (three-start thread, tamper bead, support ring), and a ribbed cap
with matching internal threads, a seal plug and a tamper band, clear of the neck everywhere. Form Studio exemplar
design (a 3D model and form study)."""
import math

from build123d import Align, Axis, Cylinder, Helix, Pos, Rot, Torus, Vector, Wire, make_face, sweep

from form import craft, parts
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Bottle with screw cap",
    "category": "assembly",
    "tags": ["bottle", "cap", "screw cap", "closure", "thread", "multi-start thread", "pco 1881", "neck finish",
             "water bottle", "drinks", "revolve", "assembly", "grip ribs", "tamper band", "pet"],
    "techniques": ["craft.bottle_profile (volume -> height, PCO 1881 neck) and craft.revolve_profile(spline=True)",
                   "craft.shell open at the neck, grip rings cut before shelling so the wall follows them",
                   "three-start thread: a trapezoid swept along a build123d Helix (is_frenet), copied at 120 deg",
                   "internal cap thread on the same helix, half a pitch up, with radial and axial clearance",
                   "craft.wrapped_ribs for the cap's grip", "craft.fuse(min_solids=2) proves the cap never touches",
                   "assembly() with a thread Mate on the axis"],
    "product_class": "bottle",
    "lessons": [
        "Size a bottle from its volume, not by eye: pick the slenderness (height / diameter, 2.4-4.2 for drinks "
        "bottles), solve the diameter from the capacity, and craft.bottle_profile solves the height; a 500 ml bottle "
        "comes out near 63 x 197 mm like the real ones. Two free parameters that must agree (volume and diameter) "
        "make half the range unbuildable; one law and one free ratio never do.",
        "The neck is a standard (PCO 1881: 27.4 mm over the thread, 21.7 mm bore, 33 mm support ring, 17 mm tall); "
        "draw it from the table and let the body flow into it. The thread is three-start (3 x 2.7 mm), so a cap "
        "seals in about one turn.",
        "A thread is a profile swept along a helix with a Frenet frame; overlap its root 0.3 mm into the neck so the "
        "fuse is a clean volume, never a face-to-face touch. The cap's thread is the same helix moved up half a "
        "pitch, so the two profiles interleave.",
        "Clearance is designed, then proven: 0.4 mm radially at the crests, about 0.4 mm on each flank, and the seal "
        "plug 0.3 mm inside the bore. craft.fuse(bottle, cap, 2, 2) refuses any contact, so the model cannot hide an "
        "interference. (A real olive seal interferes by ~0.2 mm; a model shows it at the line.)",
        "Grip rings are cut into the solid body BEFORE it is shelled, so the wall stays even through them; cutting "
        "them into a 1 mm wall afterwards would punch through.",
        "A cap reads as a cap from its details: a domed top edge, fine vertical ribs, and a tamper band split off "
        "by a thin groove at the bottom.",
    ],
}


class Design(Recipe):
    title, summary = "Bottle and cap", ("500 ml bottle with a PCO 1881-style three-start neck and a ribbed screw cap, "
                                        "modelled closed with clearance.")
    solids = 2
    params = [
        Param("volume", "Capacity", 500, 250, 1000, 10, "ml", "brief", "body", "Height is solved from it."),
        Param("slender", "Height / diameter", 2.85, 2.4, 4.2, 0.05, "", "form", "body",
              "PET drinks bottles 330 ml-1.5 l: 2.2-4.2 (diameter 58-90 mm, height 170-320 mm)."),
        Param("wall", "Bottle wall", 1.0, 0.6, 2.0, 0.1, "mm", "form", "body", "Blow-moulded PET is ~0.3 mm; a printed "
              "or display model needs ~1 mm."),
        Param("lead", "Thread lead", 8.1, 7, 9.6, 0.1, "mm", "brief", "neck",
              "3 starts x 2.7 mm pitch (approximate PCO 1881 profile).", "specified"),
        Param("clearance", "Thread clearance", 0.4, 0.25, 0.6, 0.05, "mm", "interface", "cap_thread",
              "Radial, at the crests and the roots."),
        Param("ribs", "Cap grip ribs", 48, 24, 90, 1, "", "form", "cap"),
    ]
    features = [Feature("body", "Bottle body", "structure"), Feature("grip", "Grip rings", "finish"),
                Feature("hollow", "Wall", "structure"),
                Feature("neck", "PCO 1881 neck", "interface"), Feature("thread", "Neck thread", "interface"),
                Feature("cap", "Cap shell", "structure"), Feature("cap_thread", "Cap thread", "interface"),
                Feature("cap_grip", "Cap ribs and tamper band", "finish")]

    N = {"E": 25.1, "T": 27.4, "bore": 21.7, "ring": 33.0, "finish": 17.0, "th_h": 1.15}   # PCO 1881 (mm)

    def _diameter(self, v):
        """The body diameter for the capacity at the chosen slenderness: V = pi D^2 / 4 x H / 1.1 with H = k D."""
        return (4 * v["volume"] * 1000 * 1.1 / (math.pi * v["slender"])) ** (1 / 3)

    def _form(self, v):
        return craft.bottle_profile(v["volume"], diameter=self._diameter(v), neck_d=self.N["E"], shoulder=0.24,
                                    waist=0.05, base_r=7.0)

    def _thread(self, r_root, depth, w_root, w_tip, lead, turns, inward=False):
        """One start of a thread: a trapezoid in the XZ plane (root w_root, tip w_tip wide, depth tall, the root sunk
        0.3 mm into its wall) swept along a helix of radius r_root."""
        s = -1 if inward else 1
        pts = [(r_root - s * 0.3, -w_root / 2), (r_root + s * depth, -w_tip / 2), (r_root + s * depth, w_tip / 2),
               (r_root - s * 0.3, w_root / 2)]
        face = make_face(Wire.make_polygon([Vector(x, 0, z) for x, z in pts], close=True))
        return sweep(face, Helix(lead, lead * turns, r_root), is_frenet=True)

    def build(self, v):
        F = self._form(v)
        H, N, c = F["height"], self.N, v["clearance"]
        rE, rT = N["E"] / 2, N["T"] / 2
        z_top = H
        z_fin = H - N["finish"]                              # bottom of the neck finish
        # the spline runs up to the top of the shoulder; the finish is a true cylinder (a spline through the neck
        # points sags between them, and a thread on a sagging neck is not a thread)
        body = craft.revolve_profile(F["profile"][:-1], spline=True)
        stages = [Stage("body", body)]
        # grip rings: three shallow round grooves at the waist, cut while the body is still solid
        R = self._diameter(v) / 2
        zs = (H - N["finish"]) * 0.76 * 0.5
        for dz in (-9, 0, 9):
            body = craft.cut(body, Pos(0, 0, zs + dz) * Torus(R * (1 - 0.05) + 1.4, 1.6))
        stages.append(Stage("grip", body))
        # --- snippet: hollow a revolved bottle, open at the neck
        body = craft.shell(body, v["wall"], openings=craft.faces_at(body, "top"))
        stages.append(Stage("hollow", body))
        # --- end snippet
        # neck: the finish as a true tube (E 25.1, bore 21.7), a support ring (33 mm) at its foot and a tamper bead
        tube = Pos(0, 0, z_fin - 4) * (Cylinder(rE, N["finish"] + 4, align=BOTTOM) -
                                       Cylinder(N["bore"] / 2, N["finish"] + 4, align=BOTTOM))  # E 25.1, bore 21.7
        body = craft.fuse(body, tube)
        ring = Pos(0, 0, z_fin + 1.0) * Cylinder(N["ring"] / 2, 1.6, align=BOTTOM)
        ring = craft.safe_fillet(ring, [e for e in ring.edges() if e.geom_type.name == "CIRCLE"], 0.6)
        bead = Pos(0, 0, z_fin + 4.2) * Torus(rE + 0.2, 0.9)          # crest 0.45 mm inside the cap
        body = craft.fuse(body, ring)
        body = craft.fuse(body, bead)
        lipr = [e for e in body.edges() if e.bounding_box().min.Z > z_top - 0.01]
        body = craft.safe_fillet(body, lipr, 0.4)                                            # the sealing lip
        stages.append(Stage("neck", body))
        # --- snippet: a three-start thread swept along a helix
        lead = v["lead"]
        z_th = z_top - 3.2 - lead * 0.85                                                     # thread starts here
        p = lead / 3                                                                         # pitch between starts
        one = self._thread(rE, N["th_h"], 0.55 * p, 0.26 * p, lead, 0.85)                   # widths scale with pitch
        starts = [Pos(0, 0, z_th) * Rot(0, 0, 120 * i) * one for i in range(3)]
        for t in starts:
            body = craft.fuse(body, t)
        # --- end snippet
        stages.append(Stage("thread", body))
        # cap: a closed cup over the finish, inside radius = thread crest + clearance, top 1.8 mm, domed edge
        r_in = rT + c
        cap_h = N["finish"] - 1.0
        cap_r = r_in + 1.6
        z_cap = z_top + 0.4 + 1.8 - cap_h                       # top plate 0.4 mm above the lip
        cap = Pos(0, 0, z_cap) * Cylinder(cap_r, cap_h, align=BOTTOM)
        cap = craft.safe_fillet(cap, cap.edges().group_by(Axis.Z)[-1], 1.6)
        cap = craft.cut(cap, Pos(0, 0, z_cap - 1) * Cylinder(r_in, cap_h - 1.8 + 1, align=BOTTOM))
        # seal plug: a ring hanging from the top plate into the bore, 0.3 mm clear of it
        plug = Pos(0, 0, z_top - 2.6) * (Cylinder(N["bore"] / 2 - 0.3, 3.2, align=BOTTOM)
                                         - Cylinder(N["bore"] / 2 - 1.5, 3.2, align=BOTTOM))
        cap = craft.fuse(cap, plug)
        stages.append(Stage("cap", craft.fuse(body, cap, max_solids=2, min_solids=2)))
        # cap thread: the same helix half a pitch up, pointing inward from the cap wall
        # Turning a helix by th degrees moves it down lead * th / 360, so a start turned 60 deg (between the neck's
        # starts) is lifted by that much plus half a pitch: it then sits exactly between two neck threads.
        inner = self._thread(r_in, r_in - (rE + c), 0.48 * p, 0.22 * p, lead, 0.75, inward=True)
        dz = p / 2 + lead * 60 / 360
        for i in range(3):
            cap = craft.fuse(cap, Pos(0, 0, z_th + dz) * Rot(0, 0, 120 * i + 60) * inner)
        stages.append(Stage("cap_thread", craft.fuse(body, cap, max_solids=2, min_solids=2)))
        # --- snippet: grip ribs and a tamper band on the cap
        ribs = craft.wrapped_ribs(cap_r, cap_h - 4.6, count=int(v["ribs"]), rib_w=0.9, rib_h=0.45, z0=z_cap + 3.0,
                                  core=False)
        cap = craft.fuse(cap, ribs)
        cap = craft.cut(cap, Pos(0, 0, z_cap + 2.2) * (Cylinder(cap_r + 2, 0.5, align=BOTTOM)
                                                       - Cylinder(cap_r - 0.6, 0.5, align=BOTTOM)))   # tamper split
        # --- end snippet
        body = craft.fuse(body, cap, max_solids=2, min_solids=2)
        stages.append(Stage("cap_grip", body))
        return parts.checked(stages)

    def assembly(self, v):
        F = self._form(v)
        H = F["height"]
        return Assembly(parts=[Part("bottle", "Bottle", (self.N["ring"] / 2 - 0.5, 0, H - self.N["finish"] + 1.8),
                                    note="Stand the bottle up."),
                               Part("cap", "Cap", (0, 0, H + 1.3), explode=(0, 0, 30),
                                    note="Screw the cap on: about one turn.")],
                        mates=[Mate("bottle", "cap", "thread", v["clearance"], "PCO 1881 thread", axis=(0, 0, 1),
                                    origin=(0, 0, 0))])

    def appearance(self, v):
        return [{"features": ["body", "grip", "hollow", "neck", "thread"], "finish": "smoke", "color": "#cfe3ea"},
                {"features": ["cap", "cap_thread", "cap_grip"], "finish": "gloss", "color": "#1f5fa8"}]

    def derived(self, v):
        F = self._form(v)
        return [{"key": "height", "label": "Bottle height", "value": F["height"], "unit": "mm", "feature": "body",
                 "formula": "craft.bottle_profile: volume / body area x 1.1 + 17 mm finish", "interface": False},
                {"key": "cap_bore", "label": "Cap bore", "value": round(self.N["T"] + 2 * v["clearance"], 2),
                 "unit": "mm", "feature": "cap", "formula": "thread crest 27.4 + 2 x clearance", "interface": True},
                {"key": "pitch", "label": "Thread pitch (between starts)", "value": round(v["lead"] / 3, 2),
                 "unit": "mm", "feature": "thread", "formula": "lead / 3 starts", "interface": True}]
