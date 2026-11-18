"""A kinematic chain in the window: an arm hinged on a base, a cup hinged on the arm, a pin fixed in the cup.

Moving the arm's slider swings the arm, the cup and the pin together; moving the cup's slider turns the cup and the pin
about an axis that rides with the arm. Exploded separates each part from its parent. Positions are read from what the
viewport draws and compared with the chain computed from the joints the engine sent."""
import math

import numpy as np

from _lib import open_project, wait_job

DATA = "fresh"
S = {}

SOURCE = '''
"""Arm with a tilting cup: a test of kinematic chains."""
from build123d import Align, Box, Cylinder, Pos
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage, hinge

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Chained arm", "A base, an arm hinged on it, a cup hinged on the arm and a pin in the cup."
    solids = 4
    params = [Param("arm_l", "Arm length", 60, 60, 60, 1, "mm", "form", "arm")]
    features = [Feature("base", "Base", "structure"), Feature("arm", "Arm", "structure"),
                Feature("cup", "Cup", "structure"), Feature("pin", "Pin", "interface")]

    def build(self, v):
        s = Box(40, 40, 6, align=A)
        st = [Stage("base", s)]
        s = s + Pos(40, 0, 0) * Box(10, 60, 6, align=A)
        st.append(Stage("arm", s))
        s = s + Pos(70, 0, 0) * Box(16, 16, 10, align=A)
        st.append(Stage("cup", s))
        s = s + Pos(95, 0, 0) * Cylinder(2, 20, align=A)
        st.append(Stage("pin", s))
        return st

    def assembly(self, v):
        return Assembly(
            parts=[Part("base", "Base", 0),
                   Part("arm", "Arm", 1, move=(-40, 30, 6), explode=(0, 0, 20)),
                   Part("cup", "Cup", 2, move=(-70, 68, 6), explode=(0, 15, 0)),
                   Part("pin", "Pin", 3, move=(-95, 68, 16), attach="cup", explode=(0, 0, 25))],
            joints=[hinge("arm", (1, 0, 0), (0, 0, 9), (0, 60), parent="base", id="arm_tilt", label="Arm tilt"),
                    hinge("cup", (1, 0, 0), (0, 60, 9), (-45, 45), parent="arm", id="cup_tilt", label="Cup tilt")],
            mates=[Mate("pin", "cup", "contact")])
'''


def drawn(ui, pid):
    """Where the viewport draws a part's print-frame origin right now (the transform its scene node binds to)."""
    return np.array(ui.js("(function(){ var p = Store.viewer.partXf(Store.viewer.partById(%r)).pos; return [p.x, p.y, p.z] })()" % pid))


def rot(axis, origin, deg):
    from form.recipes.assembly import Joint, joint_matrix
    return joint_matrix(Joint("j", "", "x", "hinge", tuple(axis), tuple(origin)), deg)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    d = ui.studio.create_design("Chained arm", SOURCE)
    S["pid"] = d["id"]
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])


def journey_chain_moves_together(ui):
    ui.check(ui.store.get("assembly") is not None, "the chained arm is an assembly")
    a = ui.js("Store.assembly")
    by = {p["id"]: p for p in a["parts"]}
    ui.eq(by["pin"]["chain"], ["arm_tilt", "cup_tilt"], "the pin is moved by both joints")
    ui.eq(by["pin"]["parent"], "cup", "the pin is fixed to the cup")
    joints = {j["id"]: j for j in a["joints"]}
    ui.eq(joints["arm_tilt"]["moves"], ["arm", "cup", "pin"], "the arm carries the cup and the pin")

    ui.click("viewport", 0.05, 0.95)          # the viewport has the keys
    ui.key("E")
    ui.wait_until(lambda: ui.js("Ws.tool") == "assembly", 5, "E to open Assembly")
    bar = ui.item("asmBar")
    ui.click_text("Assembled", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "assembled", 3, "assembled mode")
    ui.settle(600)
    rest = {k: drawn(ui, k) for k in ("base", "arm", "cup", "pin")}
    ui.shot("chain-assembled")

    # the arm's slider, with the mouse: everything below the arm moves with it
    slider = ui.item("jointSlider_arm_tilt")
    beam = [b for b in ui.find_all(within=slider) if b.metaObject().className().startswith("Beam")][0]
    ui.click(beam, 0.75, 0.5)
    ui.wait_until(lambda: (ui.store.get("pose") or {}).get("arm_tilt", 0) > 5, 3, "the Arm tilt slider to move the arm")
    ui.settle(600)
    v = ui.store.get("pose")["arm_tilt"]
    R = rot(joints["arm_tilt"]["axis"], joints["arm_tilt"]["origin"], v)
    for k in ("arm", "cup", "pin"):
        want = R[:3, :3] @ rest[k] + R[:3, 3]
        ui.check(np.allclose(drawn(ui, k), want, atol=1e-3), f"{k} swung {v:g}° with the arm: {drawn(ui, k)} vs {want}")
    ui.check(np.allclose(drawn(ui, "base"), rest["base"], atol=1e-6), "the base stays")
    ui.shot("chain-arm-tilted")

    # then the cup's slider: the cup and its pin turn about the cup axis, wherever the arm put it
    slider = ui.item("jointSlider_cup_tilt")
    beam = [b for b in ui.find_all(within=slider) if b.metaObject().className().startswith("Beam")][0]
    ui.click(beam, 0.9, 0.5)
    ui.wait_until(lambda: (ui.store.get("pose") or {}).get("cup_tilt", 0) > 5, 3, "the Cup tilt slider to turn the cup")
    ui.settle(600)
    w = ui.store.get("pose")["cup_tilt"]
    C = rot(joints["cup_tilt"]["axis"], joints["cup_tilt"]["origin"], w)
    M = R @ C                                   # outer joint after inner: the cup axis rides with the arm
    for k in ("cup", "pin"):
        want = M[:3, :3] @ rest[k] + M[:3, 3]
        ui.check(np.allclose(drawn(ui, k), want, atol=1e-3), f"{k} turned {w:g}° on the tilted arm: {drawn(ui, k)} vs {want}")
    want_arm = R[:3, :3] @ rest["arm"] + R[:3, 3]
    ui.check(np.allclose(drawn(ui, "arm"), want_arm, atol=1e-3), "the arm does not move with the cup")
    ui.shot("chain-cup-turned")

    # exploded: each part separates from its parent, offsets add up the chain
    ui.click_text("Exploded", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "exploded", 3, "exploded mode")
    ui.settle(800)
    f = ui.store.get("explode")
    for k, tot in (("arm", (0, 0, 20)), ("cup", (0, 15, 20)), ("pin", (0, 15, 45))):
        ui.eq([round(x, 6) for x in by[k]["explode_total"]], list(map(float, tot)), f"{k} explodes with its parents")
    want = M[:3, :3] @ rest["pin"] + M[:3, 3] + f * np.array([0, 15, 45])
    ui.check(np.allclose(drawn(ui, "pin"), want, atol=1e-3), f"the pin's exploded place follows the chain: {drawn(ui, 'pin')} vs {want}")
    ui.shot("chain-exploded")
    ui.click_text("Print layout", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "print", 3, "print layout")
