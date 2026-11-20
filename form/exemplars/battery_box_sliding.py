"""Battery box for two AA cells in series with a sliding lid: the lid is a dovetail that runs in undercut rails cut
into the box's side walls, a flexible tongue at its trailing end carries a detent bump that drops into a dimple in
the end wall to hold it shut, and the end walls have slots and windows for spring and plate contacts.
Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts, patterns
from form.recipes.base import Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage, slide

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "AA battery box with sliding lid",
    "category": "enclosure",
    "tags": ["battery", "battery box", "battery holder", "aa", "cell", "2xaa", "enclosure", "sliding lid", "slide",
             "slider", "dovetail", "rail", "detent", "latch", "contacts", "assembly"],
    "techniques": ["craft.dovetail: the slot cutter makes the rails, the flipped male is the lid (one named clearance)",
                   "cantilever tongue cut into the lid by two slots", "craft.detent bump on the tongue, dimple in the "
                   "end wall", "contact slots with retaining windows in the end walls", "patterns.grip_ribs as "
                   "grooves on the lid", "assembly() slide joint, companions() ghost cells"],
    "lessons": [
        "Start from the cell: IEC 60086 AA (LR6) is 14.5 mm x 50.5 mm. The pocket is the cell length plus the "
        "contacts (a spring compressed to about 4-5 mm and a 1-2 mm plate: about 7 mm), and cells sit 1.6 mm apart "
        "with a low rib between them.",
        "A sliding lid is a dovetail: craft.dovetail gives the male and a slot cutter grown by the same named clearance. "
        "Cut the cutter from the top of the walls (narrow at the top, undercut below) and flip the male to make the "
        "lid; both come from one call, so they always match.",
        "Hold it shut with a detent that only the latch flexes: two slots free a tongue at the lid's trailing end, its "
        "bump drops into a dimple in the end wall at the last millimetres of travel. The rest of the lid never has "
        "to bend, and the bump is outside the box until then, so it never drags along the rails.",
        "Contacts are bought parts: give them a slot behind a window narrower than the plate, so the plate is "
        "captured but the spring or dimple reaches the cell; route the solder tabs through the floor.",
        "Print the lid top-down (the grip grooves on the bed, the bump on top); its 60 deg flanks then lean 30 deg "
        "from vertical and print without support. assembly() turns it over and slides it in along X.",
    ],
}


class Design(Recipe):
    title, summary = "2xAA battery box", "Box for two AA cells with a dovetail sliding lid, detent latch and contact slots."
    solids = 2
    params = [
        Param("cell_d", "Cell diameter", 14.5, 14.5, 14.5, 0.1, "mm", "brief", "box", "IEC 60086 LR6 (AA).", "specified"),
        Param("cell_l", "Cell length", 50.5, 50.5, 50.5, 0.1, "mm", "brief", "box", "IEC 60086 LR6 (AA).", "specified"),
        Param("contact_allow", "Contact allowance", 7.0, 5.0, 10.0, 0.5, "mm", "brief", "contacts",
              "Spring (compressed) + plate contact, total; check the contacts' datasheet."),
        Param("side_wall", "Side wall", 3.4, 3.0, 4.5, 0.1, "mm", "form", "box",
              "Holds the dovetail undercut: >= 1.2 mm left beside the rail."),
        Param("lid_t", "Lid thickness", 2.0, 1.6, 2.6, 0.1, "mm", "form", "lid"),
        Param("rail_clearance", "Rail clearance / side", 0.25, 0.15, 0.4, 0.05, "mm", "interface", "rails",
              "Sliding fit on FDM: 0.2-0.3 mm per side; tune with a coupon."),
        Param("detent_depth", "Detent depth", 0.6, 0.3, 0.9, 0.05, "mm", "interface", "detent",
              "How far the tongue lifts; deeper holds harder."),
    ]
    features = [Feature("box", "Cell box", "structure"), Feature("contacts", "Contact slots", "interface"),
                Feature("rails", "Dovetail rails", "interface"), Feature("detent", "Detent dimple", "interface"),
                Feature("lid", "Sliding lid", "structure"), Feature("tongue", "Latch tongue and bump", "interface"),
                Feature("grip", "Grip grooves", "finish")]

    def constraints(self, v):
        if v["detent_depth"] > v["lid_t"] * 0.45:
            return [RecipeError("The detent is too deep for the lid tongue to flex over", "detent",
                                "Make it shallower or the lid thicker.", ["detent_depth", "lid_t"])]
        return []

    def _dims(self, v):
        d, sw, lt, c = v["cell_d"], v["side_wall"], v["lid_t"], v["rail_clearance"]
        p = d + 1.6                                       # cell pitch across
        Lp, Wp = v["cell_l"] + v["contact_allow"], 2 * p  # pocket
        ew, fz = 4.0, 1.6                                 # end walls hold the contact slots; floor
        L, W = Lp + 2 * ew, Wp + 2 * sw
        H = fz + d + 1.0 + lt + c                         # the cells, head room, the lid in its rails
        x0 = -Lp / 2 - 2.0                                # the lid's leading end tucks 2 mm into the -X end wall
        xo = -(W + 10)                                    # lid printed beside the box, at this Y
        return d, sw, lt, c, p, Lp, Wp, ew, fz, L, W, H, x0, xo

    def build(self, v):
        d, sw, lt, c, p, Lp, Wp, ew, fz, L, W, H, x0, xo = self._dims(v)
        box = Box(L, W, H, align=BOTTOM)
        box = craft.safe_fillet(box, box.edges().filter_by(Axis.Z), 3.0)
        box = craft.safe_fillet(box, box.edges().group_by(Axis.Z)[0], 1.0)
        cav = Pos(0, 0, fz) * Box(Lp, Wp, H, align=BOTTOM)
        cav = craft.safe_fillet(cav, cav.edges().filter_by(Axis.Z), 1.0)
        box = box - cav
        box = box + Pos(0, 0, fz - 0.2) * Box(Lp - 14, 1.2, d * 0.45 + 0.2, align=BOTTOM)   # rib between the cells
        stages = [Stage("box", box)]

        # contact slots: a 0.9 mm slot 1 mm behind each end wall's inner face, a narrower window in front of it
        def slot(xs, y, w, wins):
            s = Pos(xs, y, fz) * Box(0.9, w, H, align=BOTTOM)
            for yw in wins:                               # windows run into the pocket: no sliver of wall is left
                s = s + Pos(xs - 1.0 * (1 if xs > 0 else -1), yw, fz + 1.5) * Box(2.2, 7.0, d - 1.0, align=BOTTOM)
            return s
        xs = Lp / 2 + 1.0 + 0.45
        for sy in (-1, 1):                                # +X: one plate per cell (+ and -), solder tab through floor
            box = box - slot(xs, sy * p / 2, 10.0, [sy * p / 2])
            box = box - Pos(xs, sy * (p / 2 + 3.5), -1) * Cylinder(1.0, fz + 2, align=BOTTOM)
        box = box - slot(-xs, 0, p + 10.0, [-p / 2, p / 2])   # -X: one bridge joins the cells in series
        for sy, sym in ((1, "+"), (-1, "-")):              # polarity marks in the floor
            mx = Lp / 2 - 6
            mark = Pos(mx, sy * p / 2, fz - 0.4) * Box(4.0, 0.9, 1, align=BOTTOM)
            if sym == "+":
                mark = mark + Pos(mx, sy * p / 2, fz - 0.4) * Box(0.9, 4.0, 1, align=BOTTOM)
            box = box - mark
        stages.append(Stage("contacts", box))

        # --- snippet: dovetail rails cut into the walls and the lid as the flipped male, one clearance
        x1 = L / 2
        cutter = craft.dovetail(length=x1 - x0 + 1, width=Wp + 3.2, height=lt, angle=60, clearance=c)
        rails = Pos((x0 + x1 + 1) / 2, 0, H) * Rot(0, 0, 90) * cutter.shapes["slot_cutter"]
        box = box - rails
        top = [e for e in box.edges() if abs(e.center().Z - H) < 0.01 and
               (abs(abs(e.center().Y) - W / 2) < 0.6 or abs(e.center().X + L / 2) < 0.6 or e.length < 5)]
        box = craft.safe_fillet(box, top, 0.6)            # soften the outer rim where the thumb slides
        stages.append(Stage("rails", box))
        lid_l = x1 - (x0 + 0.3)
        dv = craft.dovetail(length=lid_l, width=Wp + 3.2, height=lt, angle=60, clearance=c)
        # the male is narrow at z = 0 and wide at z = lt: turned over (wide side down) it fills the undercut rails
        lid = Pos((x0 + 0.3 + x1) / 2, 0, H - lt) * Rot(0, 0, 90) * Pos(0, 0, lt) * Rot(0, 180, 0) * dv.shapes["male"]
        # --- end snippet

        det = craft.detent(ball_d=3.0, depth=v["detent_depth"], clearance=c)   # same clearance as the rails
        xb, zl = x1 - 1.4, H - lt                       # over the end wall's outer half; zl = the lid's underside
        box = box - Pos(xb, 0, zl) * det.shapes["dimple_cutter"]
        stages.append(Stage("detent", box))

        place = lambda s: Pos(0, xo, H) * Rot(180, 0, 0) * s          # printed top-down beside the box
        stages.append(Stage("lid", box + place(lid)))
        # tongue: two slots free a 9 mm wide, 16 mm long cantilever at the trailing (+X) end; its bump hangs below
        tl, tw = 16.0, 9.0
        for sy in (-1, 1):
            lid = lid - Pos(x1 - tl / 2 + 0.5, sy * (tw / 2 + 0.6), zl - 1) * Box(tl + 1, 1.2, lt + 3, align=BOTTOM)
        bump = Pos(0, 0, 0.2) * det.shapes["bump"] + Cylinder(det["cap_d"] / 2, 0.21, align=BOTTOM)
        lid = lid + Pos(xb, 0, zl + 0.2) * Rot(180, 0, 0) * bump          # hangs below the tongue tip
        stages.append(Stage("tongue", box + place(lid)))
        g = patterns.grip_ribs(w=10, d=Wp - 4, rib_w=1.2, pitch=2.6, height=0.5)
        lid = lid - Pos(x1 - tl - 8, 0, H + 0.05) * Rot(180, 0, 0) * g.shape     # grooves 0.5 deep in the top
        stages.append(Stage("grip", box + place(lid)))
        self._lid_l = lid_l
        return parts.checked(stages)

    def derived(self, v):
        d, sw, lt, c, p, Lp, Wp, ew, fz, L, W, H, x0, xo = self._dims(v)
        return [{"key": "pocket_l", "label": "Pocket length", "value": Lp, "unit": "mm", "feature": "box",
                 "formula": "cell length + contact allowance", "interface": True},
                {"key": "rail_clearance", "label": "Rail clearance per side", "value": c, "unit": "mm",
                 "feature": "rails", "formula": "assumed sliding fit (craft.dovetail)", "interface": True},
                {"key": "travel", "label": "Lid travel", "value": round(L / 2 - x0 - 0.3, 1), "unit": "mm",
                 "feature": "lid", "formula": "lid length", "interface": False}]

    def companions(self, v):
        d, sw, lt, c, p, Lp, Wp, ew, fz, L, W, H, x0, xo = self._dims(v)
        return [{"label": f"AA cell {i + 1}", "size": [v["cell_l"], d, d], "origin": [0, sy * p / 2, fz],
                 "rot_x_deg": 0, "anchor": "bottom"} for i, sy in enumerate((-1, 1))]

    def assembly(self, v):
        d, sw, lt, c, p, Lp, Wp, ew, fz, L, W, H, x0, xo = self._dims(v)
        travel = L / 2 - x0 - 0.3
        return Assembly(
            parts=[Part("box", "Battery box", (0, 0, fz / 2), note="Push the contacts into their slots, solder the "
                        "leads to the tabs under the floor, put the cells in."),
                   Part("lid", "Sliding lid", (-10, xo, lt / 2), move=(0, xo, H), rotate=(180, 0, 0), explode=(40, 0, 0),
                        note="Slide the lid in from the +X end until the tongue clicks into the end wall.")],
            joints=[slide("lid", (1, 0, 0), (0, round(travel, 1)), 9, id="lid_slide", label="Lid", parent="box")],
            # the detent bump is meant to ride over the end wall: the pair is mated, its gap checked as a slip fit
            mates=[Mate("lid", "box", "slip", c, "Lid in the dovetail rails")],
            hardware=[Hardware("AA battery contact set", "spring + plate + bridge", 1, "e.g. Keystone 209 / 5204 style",
                               "Plates into the end-wall slots, tabs through the floor.", after="box"),
                      Hardware("AA cell", "LR6 14.5 x 50.5", 2, "IEC 60086", "Mind the floor marks.", after="box")])

    def appearance(self, v):
        return [{"features": ["lid", "tongue", "grip"], "finish": "satin", "color": "#2f3439"},
                {"features": ["box", "contacts", "rails", "detent"], "finish": "satin", "color": "#c7ccd1"}]
