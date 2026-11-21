"""Braille door sign: a plate with grade 1 braille dots as true spherical caps (cell spacing from the published sign
standards), sized from its text, with two countersunk screw holes and rounded edges. Ported from the "Braille
Example" seed in CADEvolve's hand-written CadQuery examples (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten
for build123d and Form Studio's FeatureDesign, letters and digits translated in the file, dots made as sphere caps.
Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cone, Cylinder, Pos, Sphere

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Braille door sign",
    "category": "consumer",
    "tags": ["braille", "sign", "door sign", "room sign", "tactile", "accessibility", "accessible", "plate", "label",
             "dots", "spherical cap", "countersunk", "screw holes", "wayfinding", "ada"],
    "techniques": ["text -> braille cells -> dot centres, all in plain Python before any geometry",
                   "each dot a Sphere whose centre sits below the face so only a cap of the given height shows",
                   "the plate sized from the number of cells and lines", "all dots fused in one union",
                   "countersunk holes from a Cylinder and a Cone", "edges rounded last with craft.safe_fillet"],
    "lessons": [
        "A dot is a spherical cap, not a cylinder with a fillet: for a base diameter d and a height h the sphere's "
        "radius is (d^2/4 + h^2) / 2h, and its centre sits h - r under the face. One Sphere per dot, fused once.",
        "Work out the layout as numbers first (cells, dot positions, plate size), then build: the geometry then has "
        "no logic in it and a wrong letter is a wrong list entry, easy to test without the kernel.",
        "Use the published cell geometry: about 1.5 mm dots, 0.6 mm high, 2.5 mm between dots in a cell, about 6.1 "
        "mm cell to cell and 10 mm line to line. Smaller or flatter dots are hard to read by touch.",
        "Size the plate from its content, so a longer text makes a longer sign instead of dots running off the edge.",
        "Digits in grade 1 braille are the letters a to j after a number sign (dots 3-4-5-6).",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "Braille Example", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}

TEXT = ["room 12"]                         # the sign's lines (lower case letters, digits and spaces)
LETTERS = {"a": "1", "b": "12", "c": "14", "d": "145", "e": "15", "f": "124", "g": "1245", "h": "125", "i": "24",
           "j": "245", "k": "13", "l": "123", "m": "134", "n": "1345", "o": "135", "p": "1234", "q": "12345",
           "r": "1235", "s": "234", "t": "2345", "u": "136", "v": "1236", "w": "2456", "x": "1346", "y": "13456",
           "z": "1356", " ": ""}
DIGITS = dict(zip("1234567890", "abcdefghij"))
NUMBER = "3456"
DOT_XY = {"1": (0, 2), "2": (0, 1), "3": (0, 0), "4": (1, 2), "5": (1, 1), "6": (1, 0)}   # (column, row) in a cell


def cells(line: str) -> list[str]:
    """One line of text as braille cells, each a string of dot numbers."""
    out, digits = [], False
    for ch in line.lower():
        if ch.isdigit():
            if not digits:
                out.append(NUMBER)
                digits = True
            out.append(LETTERS[DIGITS[ch]])
            continue
        digits = False
        if ch not in LETTERS:
            raise RecipeError(f"No braille cell for {ch!r} in the sign text", "dots",
                              "Use letters a-z, digits and spaces.", [])
        out.append(LETTERS[ch])
    return out


class Design(FeatureDesign):
    title, summary = "Braille sign", ("A door sign with grade 1 braille dots as spherical caps, sized from its "
                                      "text, with two countersunk screw holes.")
    params = [
        Param("dot_d", "Dot base diameter", 1.5, 1.2, 2.0, 0.05, "mm", "interface", "dots"),
        Param("dot_h", "Dot height", 0.6, 0.4, 0.9, 0.05, "mm", "interface", "dots"),
        Param("pitch", "Dot spacing in a cell", 2.5, 2.2, 2.8, 0.05, "mm", "interface", "dots"),
        Param("cell", "Cell to cell", 6.2, 5.5, 7.6, 0.05, "mm", "interface", "dots"),
        Param("line", "Line to line", 10.0, 9.0, 12.0, 0.1, "mm", "interface", "dots"),
        Param("t", "Plate thickness", 3.0, 2.0, 6.0, 0.1, "mm", "form", "plate"),
        Param("margin", "Margin", 8.0, 5.0, 20.0, 0.5, "mm", "form", "plate"),
        Param("screw_d", "Screw hole", 3.5, 2.5, 5.0, 0.1, "mm", "interface", "screws", "Countersunk wood screw."),
    ]

    def setup(self, v):
        dots, rows = [], [cells(t) for t in TEXT]
        for li, row in enumerate(rows):
            y0 = -li * v["line"]
            for ci, c in enumerate(row):
                for d in c:
                    col, r = DOT_XY[d]
                    dots.append((ci * v["cell"] + col * v["pitch"], y0 + r * v["pitch"]))
        n = max(len(r) for r in rows)
        text_w = (n - 1) * v["cell"] + v["pitch"]
        text_h = (len(rows) - 1) * v["line"] + 2 * v["pitch"]
        screws = 2 * v["screw_d"] + 6                       # room for a countersunk head at each end
        w, h = text_w + 2 * (v["margin"] + screws), text_h + 2 * v["margin"]
        yc = (2 * v["pitch"] - (len(rows) - 1) * v["line"]) / 2      # the text block's centre
        return {"dots": [(x - text_w / 2, y - yc) for x, y in dots], "w": w, "h": h,
                "screw_x": w / 2 - v["margin"] / 2 - screws / 2}

    @feature("Plate")                                       # the skeleton: a plate face up, its top at z = t
    def plate(self, v, body):
        return Box(self.ctx["w"], self.ctx["h"], v["t"], align=(Align.CENTER, Align.CENTER, Align.MIN))

    @feature("Braille dots", role="interface")
    def dots(self, v, body):
        a, h = v["dot_d"] / 2, v["dot_h"]
        r = (a * a + h * h) / (2 * h)                        # sphere radius of a cap a wide and h high
        z = v["t"] + h - r
        caps = [Pos(x, y, z) * Sphere(r) for x, y in self.ctx["dots"]]
        return craft.safe_union(body, *caps)

    @feature("Screw holes", role="interface")
    def screws(self, v, body):
        d = v["screw_d"]
        for sx in (1, -1):
            at = Pos(sx * self.ctx["screw_x"], 0, 0)
            body = body - at * Cylinder(d / 2, v["t"] * 3)
            sink = Cone(d / 2, d + 0.02, d / 2 + 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))   # 90 deg
            body = body - at * Pos(0, 0, v["t"] - d / 2) * sink
        return body

    @feature("Rounded edges", role="finish")
    def edges(self, v, body):
        corners = [e for e in body.edges().filter_by(Axis.Z) if e.length > v["t"] * 0.9]
        body = craft.safe_fillet(body, corners, 3.0)
        top = [e for e in body.edges() if abs(e.center().Z - v["t"]) < 0.01 and
               (abs(e.center().X) > self.ctx["w"] / 2 - 3.5 or abs(e.center().Y) > self.ctx["h"] / 2 - 3.5)]
        return craft.safe_fillet(body, top, 0.8)
