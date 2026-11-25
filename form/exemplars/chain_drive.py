"""Roller-chain drive: two printed 06B sprockets with hubs and grub screws, and a side plate with 608 bearing bosses
set at the exact centre distance for an even number of chain links, plus a tension slot for the frame screws. The
sprocket-and-chain exemplar. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Cylinder, Pos, Rot, SlotOverall, extrude

from form import craft, parts
from form.recipes.base import Assembly, Feature, Hardware, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Roller-chain drive with sprockets and bearing plate",
    "category": "mechanical",
    "tags": ["chain", "roller chain", "sprocket", "06b", "08b", "ansi 25", "ansi 35", "ansi 40", "chain drive",
             "reduction", "transmission", "608", "bearing", "grub screw", "set screw", "hub", "tensioner", "mechanism"],
    "techniques": ["parts.chain_drive(chain, z1, z2, centre): even link count and the exact centre distance for it",
                   "parts.sprocket(teeth, chain, bore): ISO 606 tooth width, pitch diameter p / sin(180/z)",
                   "parts.bearing_seat('608') in bosses on a stadium plate, joined by a web",
                   "a radial grub-screw pilot (parts.self_tap_pilot turned onto X) through the hub",
                   "slotted frame holes for chain tension (SlotOverall) with socket-screw counterbores from parts"],
    "lessons": [
        "Never type a chain drive's centre distance: a chain is a whole, even number of links, so pick the wanted "
        "distance, let chain_drive round the links up and give back the distance that chain needs, and put the "
        "axles there. Slot one mounting for tension and wear.",
        "Sprocket teeth are as wide as the chain lets them be: ISO 606 says 0.93 x the chain's inner width for "
        "simple chain, so sprocket() takes the chain size, not a thickness.",
        "A printed sprocket needs a hub: the toothed disc is thin, so a hub carries the bore and a grub screw, and "
        "the hub sits on the side away from the chain line.",
        "Hardware objects carry their own BOM rows: bearing('608').bom() and a chain row whose length is the link "
        "count times the pitch.",
    ],
}


class Design(Recipe):
    title, summary = "Chain drive", "Two 06B sprockets and a 608 bearing plate at the exact chain centre distance."
    solids = 3
    params = [
        Param("teeth_a", "Driver sprocket teeth", 12, 10, 30, 1, "", "brief", "sprocket_a"),
        Param("teeth_b", "Driven sprocket teeth", 24, 10, 45, 1, "", "brief", "sprocket_b"),
        Param("centre", "Wanted centre distance", 90, 50, 250, 1, "mm", "brief", "plate",
              "The plate uses the distance an even number of links gives, at or just above this."),
        Param("plate_t", "Plate thickness", 6, 4, 10, 0.5, "mm", "form", "plate"),
        Param("hub_len", "Hub length", 7, 5, 15, 0.5, "mm", "form", "hubs"),
    ]
    features = [Feature("plate", "Side plate", "structure"), Feature("bosses", "Bearing bosses", "structure"),
                Feature("seats", "608 seats", "interface"), Feature("slots", "Tension slots", "interface"),
                Feature("sprocket_a", "Driver sprocket", "interface"), Feature("sprocket_b", "Driven sprocket", "interface"),
                Feature("hubs", "Hubs and grub screws", "interface")]

    CHAIN = "06B"
    BOSS_H = 9.0

    def _drive(self, v):
        return parts.chain_drive(self.CHAIN, int(v["teeth_a"]), int(v["teeth_b"]), v["centre"])

    def constraints(self, v):
        pa = parts.sprocket_pitch_d(int(v["teeth_a"]), 9.525)
        pb = parts.sprocket_pitch_d(int(v["teeth_b"]), 9.525)
        if v["centre"] < (pa + pb) / 2 + 12:
            return [RecipeError("The sprockets would touch at this centre distance", "plate",
                                "Increase the centre distance or use fewer teeth.", ["centre", "teeth_a", "teeth_b"])]
        return []

    def _sprocket(self, z, hub_len):
        sp = parts.sprocket(int(z), self.CHAIN, bore=8.0 + 0.2)             # 0.2 mm printed allowance on the 8 mm shaft
        t = sp["thickness"]
        hub_r = min(9.0, sp["root_d"] / 2 - 3.0)
        body = craft.fuse(sp.shape, Pos(0, 0, t - 0.2) * (Cylinder(hub_r, hub_len + 0.2, align=BOTTOM)
                                                       - Cylinder(4.1, hub_len + 0.2, align=BOTTOM)))
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 0.6)
        # --- snippet: a radial grub-screw pilot through the hub, from parts, turned to point along X
        pilot = parts.self_tap_pilot("M3", hub_r - 3.9)
        body = body - Pos(hub_r, 0, t + hub_len / 2) * Rot(0, -90, 0) * pilot.shape
        # --- end snippet
        return body, sp

    def build(self, v):
        dr = self._drive(v)
        C, T, Hb = dr["centre_distance"], v["plate_t"], self.BOSS_H
        # plate: a stadium web between two bosses, slotted mounting ears off the long sides
        web = extrude(SlotOverall(C, 26), T)                 # its round ends sit inside the bosses
        web = Pos(C / 2, 0, 0) * web
        stages = [Stage("plate", web)]
        boss = Cylinder(17.0, Hb, align=BOTTOM)
        plate = craft.fuse(web, boss + Pos(C, 0, 0) * boss)
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.Z)[-1], 1.0)
        stages.append(Stage("bosses", plate))
        seat = parts.bearing_seat("608", fit=0.05, through=Hb - 7 + 0.5)
        for x in (0, C):
            plate = plate - Pos(x, 0, Hb) * seat.shape
        stages.append(Stage("seats", plate))
        # --- snippet: tension slots for the frame screws, counterbored from the screw standard
        cb = parts.screw_clearance("M4", T, head="socket")
        for x in (C / 2 - 12, C / 2 + 12):
            plate = plate - Pos(x, 0, -0.1) * extrude(SlotOverall(10 + cb["hole_d"], cb["hole_d"]), T + 0.2)
            plate = plate - Pos(x, 0, T - cb["recess_depth"]) * extrude(SlotOverall(10 + cb["counterbore_d"], cb["counterbore_d"]),
                                                                       cb["recess_depth"] + 0.1)
        # --- end snippet
        stages.append(Stage("slots", plate))
        # sprockets printed in front of the plate, hub up
        ya = -(26 / 2 + 6 + parts.sprocket_pitch_d(int(v["teeth_b"]), 9.525) / 2 + 6)
        sa, spa = self._sprocket(v["teeth_a"], v["hub_len"])
        sb, spb = self._sprocket(v["teeth_b"], v["hub_len"])
        xa = 0.0
        xb = spa["tip_d"] / 2 + 6 + spb["tip_d"] / 2
        stages.append(Stage("sprocket_a", plate + Pos(xa, ya, 0) * spa.shape))
        stages.append(Stage("sprocket_b", plate + Pos(xa, ya, 0) * spa.shape + Pos(xb, ya, 0) * spb.shape))
        stages.append(Stage("hubs", plate + Pos(xa, ya, 0) * sa + Pos(xb, ya, 0) * sb))
        return parts.checked(stages)

    def _layout(self, v):
        spa = parts.sprocket(int(v["teeth_a"]), self.CHAIN, bore=8.2)
        spb = parts.sprocket(int(v["teeth_b"]), self.CHAIN, bore=8.2)
        ya = -(26 / 2 + 6 + parts.sprocket_pitch_d(int(v["teeth_b"]), 9.525) / 2 + 6)
        return ya, spa["tip_d"] / 2 + 6 + spb["tip_d"] / 2, spa, spb

    def derived(self, v):
        dr = self._drive(v)
        return [{"key": "links", "label": "Chain links (06B)", "value": dr["links"], "unit": "", "feature": "plate",
                 "formula": dr["source"], "interface": True},
                {"key": "centre_distance", "label": "Axle centre distance", "value": dr["centre_distance"], "unit": "mm",
                 "feature": "plate", "formula": "exact for that many links (parts.chain_drive)", "interface": True},
                {"key": "ratio", "label": "Ratio", "value": round(dr["ratio"], 3), "unit": "", "feature": "sprocket_b",
                 "formula": "z2 / z1", "interface": False}]

    def assembly(self, v):
        dr = self._drive(v)
        C = dr["centre_distance"]
        ya, xb, spa, spb = self._layout(v)
        z = self.BOSS_H + 4.0                                     # sprockets ride a 4 mm spacer above the bosses
        b608 = parts.bearing("608")
        return Assembly(
            parts=[Part("plate", "Side plate", (C / 2, 8, 2.0), note="Screw the plate to the frame through the slots."),
                   Part("driver", "Driver sprocket", (spa["root_d"] / 2 - 1.0, ya, 1.0), move=(0, -ya, z), explode=(0, 0, 25),
                        note="Slide the driver onto its shaft and tighten the grub screw."),
                   Part("driven", "Driven sprocket", (xb + spb["root_d"] / 2 - 1.0, ya, 1.0), move=(C - xb, -ya, z),
                        explode=(0, 0, 25), note="Slide the driven sprocket on, in line with the driver.")],
            joints=[hinge("driver", (0, 0, 1), (0, 0, 0), (0, 360), 9, id="drive", label="Driver"),
                    hinge("driven", (0, 0, 1), (C, 0, 0), (0, 360 * v["teeth_a"] / v["teeth_b"]), 9, id="driven",
                          label="Driven (turns at the ratio)")],
            hardware=[b608.bom(2, "Press a 608 into each boss.", "plate"),
                      Hardware("8 mm shaft", "Ø8 x 40 mm", 2, "h6 ground shaft", "Through each bearing.", after="plate"),
                      Hardware(f"{dr['chain']} roller chain", f"{dr['links']} links ({dr['chain_length']:g} mm)", 1,
                               "ISO 606", "Wrap it over both sprockets and join it with a connecting link.", after="driven"),
                      Hardware("M3 grub screw", "M3 x 4", 2, "ISO 4026", "Into each hub, onto the shaft's flat.", after="driven")]
            # the frame screws: the joint picks a stock M4 length for the slotted plate into a tapped frame
            + parts.bolted_joint("M4", v["plate_t"], into="tap").hardware(2, after="plate",
                                                                          note="Screw the plate on with the chain taut."))

    def appearance(self, v):
        return [{"features": ["sprocket_a", "sprocket_b", "hubs"], "finish": "matte", "color": "#2f3338"},
                {"features": ["plate", "bosses", "seats", "slots"], "finish": "petg", "color": "#3f7fbf"}]
