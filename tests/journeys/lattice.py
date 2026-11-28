"""A lattice inside the part, drawn on the stage (docs/LATTICES.md), from real builds in this journey's data folder.

A block with an octet strut lattice (exact B-rep) and one with a gyroid sheet (faceted), each in a region with a skin.
Selecting *Lattice infill* in Check draws the lattice alone, clipped to its region inside the skin (the kernel's own
struts or level set, kept where the material is), with the region's box; the strip says the relative density: the
cell's computed value and the value measured on the built solid. A graded one spans its range on the scale.

FORM_RESULT_CROPS=<dir> saves 200 % crops of the stage, the strip and the card.
"""
import os
from pathlib import Path

import _results as R
from _lib import open_project

DATA = "fresh"

BLOCK = '''
from build123d import Box
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Block"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 30, 24)
'''


def res(ui, expr="Results.kind"):
    return ui.js(expr)


def crop(ui, name):
    R.stage_crops(ui, name)


def show(ui, pid):
    if ui.store.get("pid") != pid:
        open_project(ui, pid)
    ui.key("Ctrl+2")
    ui.wait_until(lambda: ui.find(name="bench-lattice"), 15, "the lattice row")
    ui.scroll_to(ui.item("bench-lattice"), 0.4)
    ui.click("bench-lattice", 0.3, 0.5)
    ui.wait_until(lambda: res(ui, "Results.id") == "lattice" and res(ui, "!!Results.r && !Results.busy"), 120, "the lattice's view")
    ui.wait_until(lambda: res(ui) == "lattice", 10, f"the lattice drawn ({res(ui, 'Results.r.state')}: {res(ui, 'Results.r.why')})")
    ui.settle(600)


def one(ui, name, **spec):
    from form.lattice import tools as LT
    st = ui.studio
    pid = R.design(st, name, BLOCK)
    LT.fill(st, pid, by="person", **spec)
    e = R.bench(st, pid, "lattice")
    ui.check(e.get("state") == "current", f"the lattice was read: {e.get('state')} {e.get('why', '')}")
    show(ui, pid)
    d = res(ui, "Results.r")
    lay = "Store.viewer.resultLayer"
    ui.check(res(ui, lay + ".isLattice && " + lay + ".covers"), "the lattice stands in for the clay part")
    ui.check(res(ui, lay + ".latticeGeo.triangles") > 100, "with the lattice's own triangles")
    lo, hi = d["region"]["lo"], d["region"]["hi"]
    ui.check(all(h - l > 1 for l, h in zip(lo, hi)), "inside its region")
    dn = d["density"]
    ui.check(dn["measured"] is not None and abs(dn["drawn"] - dn["measured"]) < 0.08, f"the drawn lattice is as dense as the built one ({dn['drawn']:.3f} against {dn['measured']:.3f})")
    strip = " ".join(ui.texts(ui.item("legendStrip")))
    ui.check("Relative density" in strip and "measured on the built solid" in strip, "the strip names the density and how it is known")
    ui.check("Not told here" in str(ui.item("legendLimits").property("text")), "and what it does not tell")
    ui.check(ui.sees("The built solid", within=ui.item("benchCard")), "the card has the three densities")
    return pid, d


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    _pid, d = one(ui, "Octet block", kind="octet", cell=8, strut_d=1.2, skin=1.5)
    lim = str(ui.item("legendLimits").property("text"))
    ui.check(("a mesh body" if d["output"] == "mesh" else "B-rep") in lim, f"the strip says what was built ({d['output']}): {lim[:80]}")
    ui.check(ui.find(name="latticeValue") is not None and ui.item("latticeValue").isVisible(), "a uniform lattice is one value on the scale")
    crop(ui, "lattice-octet")
    _pid, d = one(ui, "Gyroid block", kind="gyroid", cell=10, skin=1.5,
                  grading={"mode": "distance", "from": "boundary", "density": [0.35, 0.12], "over": 8})
    ui.check(d["grading"] == "distance" and d["density"]["range"] == [0.12, 0.35], "a graded lattice spans its range")
    crop(ui, "lattice-gyroid-graded")
