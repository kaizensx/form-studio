"""Synthetic parts for the remodel tests (form/remodel): a small mechanism built in build123d and exported as STL.

    tray     a base plate with chamfered bottom edges, two side rails, a rounded slot pocket, a through hole and a pivot pin
    slider   a block that runs between the rails along Y, with a ramp on top
    disc     a thin stepped disc turning on the pin (a cascade)

All three are modelled in place (assembled coordinates), like meshes exported from one CAD assembly.
"""
from __future__ import annotations

from pathlib import Path

A = None


def _a():
    from build123d import Align
    return (Align.CENTER, Align.CENTER, Align.MIN)


TRAY = {"w": 60.0, "l": 100.0, "t": 3.0, "chamfer": 1.0, "rail_x": 28.0, "rail_t": 2.0, "rail_h": 8.0, "hole_d": 4.0,
        "hole_at": (0.0, 40.0), "slot": (20.0, 6.0, 1.5), "slot_at": (0.0, -30.0), "pin_d": 6.0, "pin_h": 5.0,
        "pin_at": (-12.0, -36.0)}


def tray_code() -> str:
    """The tray as a Form Studio design (the source a remodel would write), used to compare against its own mesh."""
    return '''
from build123d import *
from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Tray"
    summary = "Remodel test tray"
    params = [Param("hole_d", "Hole diameter", 4.0, 1, 10, 0.1, "mm", "form", "hole", "through hole")]
    features = [Feature("plate", "Base plate", "structure"), Feature("rails", "Side rails", "structure"),
                Feature("slot", "Slot pocket", "structure"), Feature("hole", "Through hole", "interface"),
                Feature("pin", "Pivot pin", "interface")]

    def build(self, v):
        return [Stage(k, s) for k, s in build_tray(v["hole_d"])]


def build_tray(hole_d):
    plate = Box(60, 100, 3, align=A)
    plate = chamfer(plate.edges().group_by(Axis.Z)[0], 1.0)
    out = [("plate", plate)]
    body = plate
    for x in (-28.0, 28.0):
        body = body + Pos(x, 0, 3) * Box(2, 100, 8, align=A)
    out.append(("rails", body))
    body = body - Pos(0, -30, 1.5) * extrude(SlotOverall(20, 6), 2)
    out.append(("slot", body))
    body = body - Pos(0, 40, -1) * Cylinder(hole_d / 2, 5, align=A)
    out.append(("hole", body))
    body = body + Pos(-12, -36, 3) * Cylinder(3, 5, align=A)
    out.append(("pin", body))
    return out
'''


def tray():
    ns = {}
    exec(tray_code(), ns)
    return ns["build_tray"](4.0)[-1][1]


def slider():
    from build123d import Box, Plane, Polyline, Pos, extrude, make_face
    body = Pos(0, 10, 3.2) * Box(53.6, 30, 4, align=_a())          # 0.2 mm clear of each rail (rails' inner faces at x = +/-27)
    ramp = make_face(Plane.YZ * Polyline((-5, 7.2), (25, 7.2), (25, 10.2), close=True))
    return body + extrude(ramp, 20, both=True)


def disc():
    from build123d import Cylinder, Pos
    x, y = TRAY["pin_at"]
    body = Pos(x, y, 3.0) * Cylinder(10, 1.0, align=_a())
    body = body + Pos(x, y, 4.0) * Cylinder(7, 1.0, align=_a())
    return body - Pos(x, y, 2) * Cylinder(3.3, 4, align=_a())         # Ø6.6 bore on the Ø6 pin


PARTS = {"tray": tray, "slider": slider, "disc": disc}


def export(name: str, folder) -> Path:
    from build123d import export_stl
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}.stl"
    if not f.exists():
        export_stl(PARTS[name](), str(f), tolerance=0.005, angular_tolerance=0.1)
    return f
