"""Under-desk headphone hook: a soft-cornered plate screwed to the underside of the desk, and one lofted arm that drops,
turns forward and becomes a wide, crowned cradle with a raised lip, so a headband rests on a broad curve instead of an
edge. Form Studio exemplar design."""
import math

from build123d import Axis, Edge, Plane, Pos, Rot, Vector, Vertex, Wire, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

META = {
    "title": "Under-desk headphone hook",
    "category": "consumer",
    "tags": ["headphone", "headphones", "hook", "hanger", "holder", "under desk", "desk", "mount", "cradle", "loft",
             "sweep", "path loft", "consumer", "accessory", "countersunk", "screw"],
    "techniques": ["sections lofted along a G1 line-and-arc path (craft.superellipse_face on planes normal to the path)",
                   "section size as a law along the path (flared root, wide cradle, rounded nose)",
                   "craft.loft_sections for one continuous skin from plate to lip",
                   "pad that follows the surface: grown loft & window - core loft",
                   "parts.screw_clearance countersunk holes opening on the visible face",
                   "craft.safe_fillet on the root where the arm meets the plate"],
    "lessons": [
        "A headband is an arch about 30-40 mm wide; resting it on a narrow bar or a crisp edge creases the padding. "
        "The cradle is 1.2-1.5 x the band's width, crowned across (superellipse n ~ 2.4) and straight along its "
        "length, so the band's arch meets a broad, soft surface and the load spreads.",
        "One skin, not a stack of parts: the arm is lofted through sections placed normal to a single path "
        "(lines and tangent arcs: down, a 20+ mm bend, forward, up into the lip) and their size follows a law along "
        "the path; the end closes with sections shrinking as a quarter ellipse to a point, a rounded nose. Joining "
        "separately lofted pieces leaves creases exactly where the eye follows the line.",
        "Keep every bend radius larger than the section's half-thickness, or sections on the inside of the bend cross "
        "each other and the loft folds; about 18 sections do, spaced closer where the size changes fast (the root).",
        "Flare the root (wider and thicker where the arm meets the plate): the bending moment of the hanging load is "
        "largest there, and a trumpet-shaped root reads as one designed object instead of a bar stuck on a plate.",
        "Screws go in from below, so the countersinks open on the plate's visible underside, behind the arm where a "
        "screwdriver can reach them; 4 mm wood screws take an M4 countersunk clearance (ISO 273 / ISO 10642 head).",
        "A soft pad in a second material on the cradle (grown loft intersected with a window, minus the core) is "
        "what a real product does; it is a separate feature so appearance() can make it rubber.",
    ],
}


class Design(Recipe):
    title, summary = "Under-desk headphone hook", ("Screw-on plate and one lofted arm ending in a wide crowned cradle "
                                                   "with a lip and a soft pad.")
    params = [
        Param("drop", "Drop below the desk", 62, 45, 110, 1, "mm", "form", "arm",
              "From the desk underside to the bottom of the arm; leave room for the ear cups to hang free."),
        Param("cradle_len", "Cradle length", 64, 48, 95, 1, "mm", "form", "arm", "Along X, from the bend to the lip."),
        Param("cradle_w", "Cradle width", 46, 34, 60, 1, "mm", "brief", "arm",
              "Headbands are about 30-40 mm wide; 1.2-1.5 x the band."),
        Param("thick", "Arm thickness", 10, 8, 14, 0.5, "mm", "form", "arm", "PLA/PETG: 10 mm carries ~1 kg at the lip."),
        Param("lip", "Lip height", 14, 8, 24, 0.5, "mm", "form", "arm", "How far the end turns up above the cradle."),
        Param("plate_t", "Plate thickness", 6, 4, 10, 0.5, "mm", "form", "plate"),
        Param("pad", "Pad thickness", 1.2, 0.6, 2.0, 0.1, "mm", "form", "pad", "Soft pad on the cradle."),
    ]
    features = [Feature("plate", "Mounting plate", "structure"), Feature("holes", "Countersunk screw holes", "interface"),
                Feature("arm", "Lofted arm and cradle", "structure"), Feature("root", "Root blend", "finish"),
                Feature("pad", "Cradle pad", "finish")]

    def constraints(self, v):
        if v["drop"] < 2.5 * v["thick"] + v["plate_t"] + 12:
            return [RecipeError("The drop is too short for the bend at this thickness", "arm",
                                "Increase the drop or make the arm thinner.", ["drop", "thick"])]
        return []

    def _path(self, v):
        """The arm's centreline in XZ, tangent-continuous: a line straight down from inside the plate, a quarter arc of
        radius R turning forward, the straight cradle, and an arc of radius Rl turning up 80 deg into the lip. Lines and
        arcs (not a spline through points) cannot overshoot, so the cradle stays straight where the band rests."""
        H, t, L, lip = v["drop"], v["thick"], v["cradle_len"], v["lip"]
        R = max(2.2 * t, 20.0)                       # bend radius: well above the half-thickness, no fold
        zc = t / 2                                    # centreline at the bottom of the bend
        phi = math.radians(80)
        Rl = lip / (1 - math.cos(phi))                # the lip rises `lip` over its arc
        c45 = math.cos(math.radians(45))
        P = lambda x, z: Vector(x, 0, z)
        segs = [Edge.make_line(P(0, H - v["plate_t"] / 2), P(0, zc + R)),
                Edge.make_three_point_arc(P(0, zc + R), P(R - R * c45, zc + R - R * c45), P(R, zc)),
                Edge.make_line(P(R, zc), P(R + L, zc)),
                Edge.make_three_point_arc(P(R + L, zc), P(R + L + Rl * math.sin(phi / 2), zc + Rl * (1 - math.cos(phi / 2))),
                                          P(R + L + Rl * math.sin(phi), zc + lip))]
        return Wire(segs), R, (segs[0].length + segs[1].length)

    def _sections(self, v, grow=0.0, count=18):
        """Faces normal to the path. Half-width (Y) and half-thickness follow laws of the path fraction s: a flared root,
        the stem, a wide cradle after the bend and a slightly narrower lip, closed by a rounded nose (sections that
        shrink as a quarter ellipse past the end of the path, then a point)."""
        path, R, l_bend = self._path(v)
        t, W = v["thick"], v["cradle_w"]
        Ltot = path.length
        s_bend = l_bend / Ltot                                         # where the cradle starts
        stem_w = max(0.5 * W, 18.0)
        out = []

        def size(s):
            root = max(0.0, 1 - s / 0.14) ** 2                         # flare over the first 14 %
            k = min(1.0, max(0.0, (s - s_bend * 0.55) / (s_bend * 0.5)))   # stem -> cradle width through the bend
            k = k * k * (3 - 2 * k)
            tip = max(0.0, (s - 0.85) / 0.15)
            hw = (stem_w + (W - stem_w) * k) / 2 * (1 - 0.1 * tip) + root * 7
            ht = t / 2 * (1 + 0.5 * root) * (1 - 0.1 * tip)
            return hw, ht

        for i in range(count):
            s = (i / (count - 1)) ** 1.35                              # denser at the flared root
            hw, ht = size(s)
            pl = Plane(origin=path.position_at(s), x_dir=(0, 1, 0), z_dir=path.tangent_at(s))
            out.append(craft.superellipse_face(hw + grow, ht + grow, 2.4, plane=pl, count=64))
        hw, ht = size(1.0)
        end, d = path.position_at(1.0), path.tangent_at(1.0)
        nose = ht + grow
        for u in (0.5, 0.8, 0.95):
            k = math.sqrt(1 - u * u)
            pl = Plane(origin=end + d * (nose * u), x_dir=(0, 1, 0), z_dir=d)
            out.append(craft.superellipse_face((hw + grow) * k, (ht + grow) * k, 2.4, plane=pl, count=64))
        out.append(Vertex(*(end + d * nose)))
        return out

    def build(self, v):
        H, pt = v["drop"], v["plate_t"]
        # plate: a soft-square slab whose top is the desk face (z = drop), arm root near its front end
        plate = Pos(-14, 0, H - pt) * extrude(craft.superellipse_face(42, 24, 4.0, count=72), pt)
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.Z)[0], min(2.5, pt * 0.45))
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.Z)[-1], 0.8)
        stages = [Stage("plate", plate)]
        # holes: 4 mm wood screws from below; the countersink opens on the plate's underside, behind the arm
        cs = parts.screw_clearance("M4", pt, head="countersunk")
        body = plate
        for y in (-13, 13):
            body = craft.cut(body, Pos(-34, y, H - pt) * Rot(180, 0, 0) * cs.shape)
        stages.append(Stage("holes", body))
        # --- snippet: loft sections along a path, sized by a law
        secs = self._sections(v)
        arm = craft.loft_sections(secs)
        body = craft.fuse(body, arm)
        # --- end snippet
        stages.append(Stage("arm", body))
        # root: blend the concave edge where the arm leaves the plate's underside
        def flat_at(e, z):
            bb = e.bounding_box()
            return abs(bb.min.Z - z) < 0.05 and abs(bb.max.Z - z) < 0.05
        # the arm's intersection loop: lies in the plate's underside, near the arm, not the plate outline or a hole
        root = [e for e in body.edges() if flat_at(e, H - pt) and e.geom_type.name == "BSPLINE"
                and e.bounding_box().size.X < 50]
        body = craft.safe_fillet(body, root, 3.0)
        stages.append(Stage("root", body))
        # --- snippet: a pad that follows a lofted surface (grown skin & window - core)
        grown = craft.loft_sections(self._sections(v, grow=v["pad"]))
        path, R, _ = self._path(v)
        x0, x1 = R + 4, R + v["cradle_len"] - 4
        window = Pos((x0 + x1) / 2, 0, v["thick"] * 0.72) * extrude(
            craft.superellipse_face((x1 - x0) / 2, v["cradle_w"], 6.0, count=48), v["thick"] * 2)
        pad = craft.cut(grown & window, craft.loft_sections(self._sections(v, grow=-0.2)))
        body = craft.fuse(body, pad)
        # --- end snippet
        stages.append(Stage("pad", body))
        return parts.checked(stages)

    def appearance(self, v):
        return [{"features": ["pad"], "finish": "rubber", "color": "#2a2c2e"},
                {"features": ["plate", "holes", "arm", "root"], "finish": "satin", "color": "#c9c4ba"}]

    def derived(self, v):
        path, R, _ = self._path(v)
        return [{"key": "bend_r", "label": "Bend radius (centreline)", "value": round(R, 1), "unit": "mm",
                 "feature": "arm", "formula": "max(2.2 x thickness, 20 mm): no fold on the inside of the bend",
                 "interface": False},
                {"key": "screw", "label": "Screw", "value": parts.clearance_d("M4")[0], "unit": "mm",
                 "feature": "holes", "formula": "4 mm wood screw, M4 normal clearance (ISO 273), 90 deg countersink",
                 "interface": True}]
