"""Connector panel for an enclosure or a rack: a plate with D-sub cutouts (DE-9, DA-15, DB-25) and their jack-screw
holes, a round 4-screw connector, corner mounting holes and a stiffening return flange along both long edges. Ported
from the "Panel With Various Connector Holes" seed in CADEvolve's hand-written CadQuery examples (kulibinai/CADEvolve,
Apache-2.0) and modified: rewritten for build123d and Form Studio's FeatureDesign, the cutouts made a table and laid
out in one row. Form Studio exemplar design."""
from build123d import Align, Box, Circle, Polygon, Pos, Rectangle, extrude, fillet

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Connector panel with D-sub cutouts",
    "category": "enclosure",
    "tags": ["connector panel", "panel", "front panel", "rear panel", "d-sub", "dsub", "db9", "de9", "db25", "da15",
             "serial port", "connector", "cutout", "jack screw", "rack", "enclosure", "faceplate", "sheet",
             "mounting holes", "flange", "electronics"],
    "techniques": ["a cutout table (D-sub shell size -> screw pitch, trapezoid widths) instead of numbers in the code",
                   "D-sub cutout as a 10 deg trapezoid Polygon with 2-D fillets on its corners (fillet on vertices)",
                   "every cutout in one row, laid out from a list, the fit checked before anything is cut",
                   "a round connector with four screws on a square",
                   "return flanges along the long edges for stiffness", "corner holes kept clear of the flanges"],
    "lessons": [
        "Connector cutouts come from a table of real sizes, not from the drawing: a D-sub is named by its shell "
        "(E = DE-9, A = DA-15, B = DB-25), and the shell fixes the jack-screw pitch (25.0, 33.3, 47.0 mm) and the "
        "trapezoid. Put the table at the top of the file and let a parameter pick how many of each.",
        "Lay cutouts out from a list and check the row fits before cutting: a panel too short for its connectors "
        "should be a clear error naming the counts and the width, not overlapping holes.",
        "A D-sub opening is a trapezoid with 10 deg sides and rounded corners: draw the polygon, round its vertices in "
        "2-D (fillet(face.vertices(), r)) and extrude the face; that is cheaper and safer than filleting a 3-D cut.",
        "A thin panel flexes when a plug is pushed in: a return flange along each long edge stiffens it for almost no "
        "material. Keep the mounting holes clear of the flanges.",
        "Jack-screw holes are 3.2 mm (4-40 UNC clearance); the panel is the same whichever connector is fitted.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "Panel With Various Connector Holes",
               "licence": "Apache-2.0", "modified": "modified (ported to build123d / Form Studio)"},
}

# D-sub shells: half the jack-screw pitch, half width of the trapezoid at its wide side (mm). Half height 5.7 mm.
DSUB = {"DE-9": (12.5, 10.85), "DA-15": (16.65, 15.0), "DB-25": (23.5, 21.85)}
ROUND = (14.0, 24.75)            # round connector: radius of the opening, side of the square its four screws sit on
GAP = 10.0                       # between neighbouring cutouts (mm)


def _through(face, x, y, t):
    """A cutter through the plate from a face drawn in XY."""
    return Pos(x, y, -1) * extrude(face, t + 2)


class Design(FeatureDesign):
    title, summary = "Connector panel", ("A flanged panel with a row of D-sub cutouts, a round 4-screw connector and "
                                         "corner mounting holes.")
    params = [
        Param("width", "Panel width", 280, 100, 480, 1, "mm", "brief", "plate"),
        Param("height", "Panel height", 50, 30, 132, 1, "mm", "brief", "plate", "3U rack panels are 132.5 mm."),
        Param("t", "Thickness", 2.5, 1.5, 5, 0.1, "mm", "form", "plate"),
        Param("de9", "DE-9 connectors", 2, 0, 6, 1, "", "interface", "dsub"),
        Param("da15", "DA-15 connectors", 1, 0, 4, 1, "", "interface", "dsub"),
        Param("db25", "DB-25 connectors", 1, 0, 4, 1, "", "interface", "dsub"),
        Param("rounds", "Round connectors", 1, 0, 4, 1, "", "interface", "round_conn"),
        Param("flange", "Return flange depth", 8, 0, 20, 0.5, "mm", "form", "flanges"),
        Param("mount_d", "Mounting hole", 3.4, 2.5, 6.6, 0.1, "mm", "interface", "mounting", "M3 clearance."),
    ]

    def setup(self, v):
        row = (["DB-25"] * int(round(v["db25"])) + ["DA-15"] * int(round(v["da15"])) +
               ["DE-9"] * int(round(v["de9"])) + ["round"] * int(round(v["rounds"])))
        widths = [2 * (DSUB[k][0] + 3.5) if k in DSUB else 2 * ROUND[0] + 6 for k in row]
        need = sum(widths) + GAP * max(0, len(row) - 1)
        room = v["width"] - 8 * v["mount_d"] - 8                  # leave the corner holes clear
        if need > room:
            raise RecipeError(f"{len(row)} connectors need {need:.0f} mm; the panel has {room:.0f} mm between its "
                              "mounting holes", "dsub", "Make the panel wider or use fewer connectors.",
                              ["width", "de9", "da15", "db25", "rounds"])
        x, at = -need / 2, []
        for k, w in zip(row, widths):
            at.append((k, x + w / 2))
            x += w + GAP
        return {"row": at}

    @feature("Plate")                                       # the skeleton: a flat plate in XY, face up
    def plate(self, v, body):
        return extrude(fillet(Rectangle(v["width"], v["height"]).vertices(), 2.0), v["t"])

    @feature("Return flanges")
    def flanges(self, v, body):
        if v["flange"] <= 0:
            return body
        for sy in (1, -1):                                  # hanging under the plate along each long edge
            lip = Pos(0, sy * (v["height"] / 2 - v["t"] / 2), 0.01) * \
                Box(v["width"] - 8, v["t"], v["flange"], align=(Align.CENTER, Align.CENTER, Align.MAX))
            body = craft.safe_union(body, lip)
        return body

    @feature("D-sub cutouts", role="interface")
    def dsub(self, v, body):
        for kind, x in self.ctx["row"]:
            if kind not in DSUB:
                continue
            half_pitch, wide = DSUB[kind]
            narrow = wide - 2 * 5.7 * 0.1763                   # 10 deg sides over the 11.4 mm height
            trap = fillet(Polygon((-narrow, -5.7), (narrow, -5.7), (wide, 5.7), (-wide, 5.7)).vertices(), 2.2)
            body = body - _through(trap, x, 0, v["t"])
            for sx in (1, -1):
                body = body - _through(Circle(1.6), x + sx * half_pitch, 0, v["t"])
        return body

    @feature("Round connectors", role="interface")
    def round_conn(self, v, body):
        r, sq = ROUND
        for kind, x in self.ctx["row"]:
            if kind != "round":
                continue
            body = body - _through(Circle(r), x, 0, v["t"])
            for sx in (1, -1):
                for sy in (1, -1):
                    body = body - _through(Circle(1.6), x + sx * sq / 2, sy * sq / 2, v["t"])
        return body

    @feature("Mounting holes", role="interface")
    def mounting(self, v, body):
        dx = v["width"] / 2 - 2 * v["mount_d"]
        dy = v["height"] / 2 - v["t"] - 1.5 * v["mount_d"]   # clear of the flanges
        for sx in (1, -1):
            for sy in (1, -1):
                body = body - _through(Circle(v["mount_d"] / 2), sx * dx, sy * dy, v["t"])
        return body

    @feature("Edges", role="finish")
    def edges(self, v, body):
        top = [e for e in body.edges() if e.center().Z > v["t"] - 0.01 and abs(e.center().Y) > v["height"] / 2 - 0.01]
        return craft.safe_chamfer(body, top, 0.4) if top else body
