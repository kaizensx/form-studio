"""A design in eight separate parts (a toy figure: stand, legs, torso, arms, head, hat), assembled, stays calm while a
parameter's slider is dragged and the view is orbited with the mouse, with its pipeline running at the same time (as
after a commit): no frame where the middle of the view is the clear colour, and no frame where the part (nearly)
disappears between two that show it. A draft keeps every part node and makes again only the meshes of the parts whose
geometry changed: before, every draft destroyed and re-made all eight part nodes, their edge lines and every mesh
(some of them twice), on the GUI thread, for each step of the slider.

The owner saw a multi-part character flicker and sometimes go black while sliding a parameter or orbiting. A sampler
grabs the window on every turn of the event loop while the gestures run (viewport_calm.py's Sampler)."""
import time

from _lib import open_project, wait_job
from viewport_calm import Sampler, measure

DATA = "fresh"
S = {}

SOURCE = '''
"""Toy figure in eight separate parts: a test of drawing many rounded parts while a slider moves."""
from build123d import Align, Box, Cylinder, Pos, Sphere
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Toy figure", "A stand, two legs, a torso, two arms, a head and a hat, each its own part."
    solids = 8
    params = [Param("head_d", "Head size", 34, 22, 48, 0.5, "mm", "form", "head"),
              Param("limb", "Limb length", 30, 18, 44, 0.5, "mm", "form", "arms")]
    features = [Feature("stand", "Stand", "structure"), Feature("legs", "Legs", "structure"),
                Feature("torso", "Torso", "structure"), Feature("arms", "Arms", "structure"),
                Feature("head", "Head", "structure"), Feature("hat", "Hat", "finish")]

    def build(self, v):
        h, L = v["head_d"], v["limb"]
        s = Box(70, 40, 4, align=A)
        st = [Stage("stand", s)]
        for x in (-9, 9):
            s = s + Pos(x, 0, 6) * Cylinder(6, L, align=A)
        st.append(Stage("legs", s))
        s = s + Pos(0, 0, L + 23) * Sphere(15)
        st.append(Stage("torso", s))
        for x in (-22.5, 22.5):
            s = s + Pos(x, 0, L + 12) * Cylinder(4.5, L, align=A)
        st.append(Stage("arms", s))
        s = s + Pos(0, 0, L + 40 + h / 2) * Sphere(h / 2)
        st.append(Stage("head", s))
        s = s + Pos(0, 0, L + 42 + h) * Cylinder(h * 0.3, 8, align=A)
        st.append(Stage("hat", s))
        return st

    def assembly(self, v):
        h, L = v["head_d"], v["limb"]
        return Assembly(parts=[Part("stand", "Stand", (30, 15, 2)),
                               Part("leg_l", "Left leg", (-9, 0, 6 + L / 2)), Part("leg_r", "Right leg", (9, 0, 6 + L / 2)),
                               Part("torso", "Torso", (0, 0, L + 23)),
                               Part("arm_l", "Left arm", (-22.5, 0, L + 12 + L / 2)), Part("arm_r", "Right arm", (22.5, 0, L + 12 + L / 2)),
                               Part("head", "Head", (0, 0, L + 40 + h / 2)), Part("hat", "Hat", (0, 0, L + 46 + h))])
'''

# the draft is what the viewport draws (the same meshes), and no newer one is on its way
DRAWN = ("(function () { var p = Store.preview, m = Store.viewer.model; return !!p && !!m && m.mesh.length === p.mesh.length"
         " && m.mesh.every(function (x, i) { return x.positions === p.mesh[i].positions }) && !Store._pvBusy })()")


def made(ui):
    """Part nodes and part meshes the viewport has created so far (Viewport._nodesMade, _meshesMade)."""
    return ui.js("[Store.viewer._nodesMade, Store.viewer._meshesMade]")


def calm(ui, sm, what):
    """viewport_calm's two rules: the middle of the view is never the clear colour, and the part never blinks."""
    s = sm.samples
    print(f"  {what}: {len(s)} frames, clay pixels {min(x['clay'] for x in s)}..{max(x['clay'] for x in s)}", flush=True)
    ui.check(len(s) >= 6, f"enough frames sampled {what}: {len(s)}")
    for i, x in enumerate(s):
        if x["clear"] > 17 * 17 * 0.6:
            raise AssertionError(f"the middle of the view is the clear colour {what} (sample {i}) ({ui.shot('blink-' + what.replace(' ', '-'))})")
    for i in range(1, len(s) - 1):
        a, x, b = s[i - 1]["clay"], s[i]["clay"], s[i + 1]["clay"]
        if min(a, b) >= 20 and x < 0.4 * min(a, b):
            raise AssertionError(f"the part blinked {what}: clay pixels {a} → {x} → {b} (sample {i} of {len(s)})")


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    d = ui.studio.create_design("Toy figure", SOURCE)
    S["pid"] = d["id"]
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])
    ui.check(ui.js("!!Store.viewer.asm && Store.viewer.asm.parts.length") == 8, "eight parts in an assembly")
    ui.run_js("Store.setAsmMode('assembled')")
    ui.settle(900)
    clay, clear = measure(ui)
    ui.check(clay > 40, f"the figure is on screen: {clay} clay pixels")
    ui.shot("parts-calm-open")


def _drag_slider(ui, frac_from, frac_to, steps=40, pause=60):
    from PySide6.QtCore import QPoint
    row = ui.wait_until(lambda: next((r for r in ui.find_all() if r.objectName() == "param-head_d" and ui._on_screen(r)), None),
                        5, "the Head size slider")
    beam = ui.find(name="paramBeam", within=row)
    a = ui._pt(beam, frac_from, 0.5)
    b = QPoint(a.x() + int((frac_to - frac_from) * beam.width()), a.y())
    ui.T.mouseMove(ui.win, a)
    ui.T.mousePress(ui.win, ui._btn("left"), ui._mods(), a)
    for i in range(1, steps + 1):
        ui.T.mouseMove(ui.win, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y()))
        ui.wait(pause)
    ui.T.mouseRelease(ui.win, ui._btn("left"), ui._mods(), b)


def journey_slider_and_orbit_while_the_pipeline_runs(ui):
    pid = S["pid"]
    ui.run_js("Store.setStage('shape')")
    ui.click("feature-head")
    ui.wait_until(lambda: ui.store.get("feature") == "head", 3, "the Head feature")
    ui.settle(500)
    ui.api("/projects/" + pid + "/run", {"nodes": [], "force": True})       # the pipeline runs under the gestures
    n0 = made(ui)
    with Sampler(ui) as sm:
        _drag_slider(ui, 0.3, 0.75)
        t0 = time.time()
        ui.wait_until(lambda: ui.js(DRAWN), 60, "the draft to be drawn")
        print(f"  draft drawn {time.time() - t0:.2f} s after the pointer stopped", flush=True)
        for dx, dy in ((360, 0), (-240, 90), (0, -120)):
            ui.drag("viewport", (dx, dy), fx=0.45, fy=0.5, steps=30)
        _drag_slider(ui, 0.75, 0.35, steps=30)
        for dx, dy in ((200, 30), (-200, -30)):
            ui.drag("viewport", (dx, dy), fx=0.45, fy=0.5, steps=24)
        ui.wait_until(lambda: ui.js(DRAWN), 60, "the last draft to be drawn")
        ui.settle(400)
    calm(ui, sm, "while sliding and orbiting a figure in eight parts")
    n1 = made(ui)
    ui.eq(n1[0] - n0[0], 0, "no part node was made again while sliding and orbiting")
    print(f"  meshes made again while sliding: {n1[1] - n0[1]}", flush=True)
    ui.shot("parts-calm-after")

    # a draft that changes only the head makes again only the head's and the hat's meshes
    for v in (30, 40):
        a = made(ui)
        ui.run_js("Store.setParam('head_d', %s, true)" % v)
        ui.wait_until(lambda: ui.js(DRAWN) and ui.js("Store.preview.impact.params.some(function (p) { return p.key === 'head_d' && Math.abs(p.to - %s) < 1e-6 })" % v),
                      60, f"the draft at {v} mm")
        ui.settle(300)
        b = made(ui)
        ui.eq(b[0] - a[0], 0, f"a head-size draft ({v} mm) keeps every part node")
        ui.check(b[1] - a[1] <= 2, f"a head-size draft ({v} mm) makes only the head's and the hat's meshes again: {b[1] - a[1]}")
    ui.run_js("Store.discard()")
    ui.settle(300)
