"""A deterministic stand-in for an agent: it replays a fixed script of MCP tool calls for each creation-bench brief.
No model, no network. It follows the creation algorithm the way design_guide teaches it, so the bench measures the
engine and the tools, not a model's luck:

    design_brief -> design_examples(query) -> plan_design (features with real helper names; parts, clearances and
    magnet stock for a multi-part brief) -> create_design with the skeleton feature only -> one
    add_feature(kind="code") per later feature, each tried at most 1 + 2 times (the scripted attempts, in order),
    then deferred -> get_design_source.

Every attempt is real code built by the real kernel: an attempt that fails, fails in the kernel (for example a fuse
of a part that does not reach the body), never by a scripted flag. Some briefs carry such a first attempt, and the
hero helmet's hex texture fails all three, so retries and deferral are exercised.

    from tests.fixtures.scripted_agent import SCRIPTS, ScriptedAgent
    rec = await ScriptedAgent(call).run("din_clip")     # call(tool, args) -> (ok, payload_dict_or_text)

All twenty briefs are original objects: no character, brand or trademarked product.
"""
from __future__ import annotations

import json
import time

RETRIES = 2

HEADER = '''from build123d import *
from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(FeatureDesign):
    title = {title!r}
    summary = {summary!r}
    solids = {solids}
    params = [
{params}
    ]
'''


def P(key, label, default, lo, hi, step, feat, group="form", doc=""):
    return f'        Param({key!r}, {label!r}, {default}, {lo}, {hi}, {step}, "mm", {group!r}, {feat!r}, {doc!r}),'


def method(fid, label, role, body):
    lines = body.strip("\n").splitlines()
    return f'@feature({label!r}, role={role!r})\ndef {fid}(self, v, body):\n' + "\n".join("    " + ln for ln in lines) + "\n"


def F(fid, label, role, how, *attempts):
    """A planned feature: id, label, role, how (for plan_design) and its code attempts (method bodies), in order."""
    return {"id": fid, "label": label, "role": role, "how": how, "attempts": list(attempts)}


S: dict = {}

# ---- mechanical ------------------------------------------------------------------------------------------------

S["shaft_coupler"] = dict(
    name="Shaft coupler", brief="A clamping shaft coupler from a 5 mm motor shaft to an 8 mm leadscrew.",
    query="shaft coupler clamp", solids=1, risks=["the clamp slot must not split the body"],
    params=[P("d", "Outer diameter", 20, 14, 30, 0.5, "body"), P("l", "Length", 25, 16, 40, 0.5, "body"),
            P("a", "Motor shaft", 5, 3, 8, 0.05, "bores", "brief"), P("b", "Leadscrew", 8, 5, 10, 0.05, "bores", "brief")],
    features=[
        F("body", "Body", "structure", "build123d Cylinder", 'return Cylinder(v["d"] / 2, v["l"], align=A)'),
        F("bores", "Shaft bores", "interface", "two Cylinder cuts from each end",
          'body = body - Cylinder(v["a"] / 2, v["l"] / 2 + 0.5, align=A)\n'
          'return body - Pos(0, 0, v["l"] / 2 - 0.5) * Cylinder(v["b"] / 2, v["l"] / 2 + 1, align=A)'),
        F("clamp_slots", "Clamp slots", "interface", "craft.safe_cut of two thin slots, one per half",
          'for z in (v["l"] * 0.25, v["l"] * 0.75):\n'
          '    body = craft.safe_cut(body, Pos(v["d"] / 4, 0, z) * Box(v["d"] / 2, 1.0, v["l"] * 0.3))\n'
          'return body'),
        F("screws", "Clamp screws", "interface", "Cylinder cuts across the slots for M3 screws",
          'for z in (v["l"] * 0.25, v["l"] * 0.75):\n'
          '    body = body - Pos(v["d"] * 0.32, 0, z) * Rot(90, 0, 0) * Cylinder(1.7, v["d"] + 2)\n'
          'return body'),
        F("chamfers", "Chamfers", "finish", "craft.safe_chamfer on the end circles",
          'return craft.safe_chamfer(body, body.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1], 0.6)')])

S["pillow_block"] = dict(
    name="Pillow block", brief="A pillow block for a 608 bearing with two slotted mounting holes and ribs.",
    query="pillow block bearing", solids=1, risks=["bearing seat press fit"],
    params=[P("w", "Base length", 70, 50, 120, 1, "base"), P("t", "Base thickness", 8, 5, 14, 0.5, "base")],
    features=[
        F("base", "Base", "structure", "build123d Box", 'return Box(v["w"], 26, v["t"], align=A)'),
        F("housing", "Housing", "structure", "craft.safe_union of a Cylinder along Y",
          'h = Pos(0, 0, v["t"] + 12) * Rot(90, 0, 0) * Cylinder(16, 14)\n'
          'return craft.safe_union(body, h + Pos(0, 0, v["t"] - 0.2) * Box(32, 14, 12.4, align=A))'),
        F("seat", "Bearing seat", "interface", "parts.bearing_seat 608 cut",
          'return body - Pos(0, 0, v["t"] + 12) * Rot(90, 0, 0) * Cylinder(11.05, 16)'),
        F("slots", "Mounting slots", "interface", "build123d SlotOverall cuts",
          'for x in (-v["w"] / 2 + 9, v["w"] / 2 - 9):\n'
          '    body = body - Pos(x, 0, -1) * extrude(SlotOverall(10, 5.5), v["t"] + 2)\n'
          'return body'),
        F("ribs", "Ribs", "structure", "craft.safe_union of two wedge ribs",
          'for x in (-17, 17):\n'
          '    body = craft.safe_union(body, Pos(x, 0, v["t"] - 0.2) * Box(4, 10, 10, align=A))\n'
          'return body')])

S["cam_clamp"] = dict(
    name="Cam clamp", brief="A quick-release tube clamp with a cam lever for a 25.4 mm bar.",
    query="quick release clamp cam lever", solids=1, risks=["the split must not close before it grips"],
    params=[P("bar", "Bar diameter", 25.4, 20, 35, 0.1, "ring", "brief"), P("h", "Height", 18, 10, 30, 0.5, "ring")],
    features=[
        F("ring", "Ring", "structure", "build123d Cylinder minus the bar",
          'return Cylinder(v["bar"] / 2 + 5, v["h"], align=A) - Cylinder(v["bar"] / 2 + 0.2, v["h"], align=A)'),
        F("ears", "Clamp ears", "structure", "craft.safe_union of a Box",
          'return craft.safe_union(body, Pos(v["bar"] / 2 + 9, 0, 0) * Box(14, 12, v["h"], align=A))'),
        F("split", "Split", "interface", "craft.safe_cut of a 1.5 mm slot",
          'return craft.safe_cut(body, Pos(v["bar"] / 2 + 8, 0, -1) * Box(20, 1.5, v["h"] + 2, align=A))'),
        F("pivot", "Lever pivot", "interface", "Cylinder cut across the ears",
          'return body - Pos(v["bar"] / 2 + 11, 0, v["h"] / 2) * Rot(90, 0, 0) * Cylinder(2.6, 20)'),
        F("edges", "Edges", "finish", "craft.safe_fillet on vertical edges",
          'return craft.safe_fillet(body, body.edges().filter_by(Axis.Z), 1.0)')])

S["planetary"] = dict(
    name="Planetary stage", brief="A 5:1 planetary gearbox stage with a flanged ring housing and a carrier.",
    query="planetary gearbox", solids=6, risks=["planets must clear the ring and the sun"],
    params=[P("ring_d", "Ring inner diameter", 60, 40, 90, 0.5, "housing"), P("t", "Gear thickness", 8, 5, 14, 0.5, "housing")],
    parts=[{"id": "housing", "label": "Ring housing"}, {"id": "sun", "label": "Sun"},
           {"id": "planets", "label": "Planets"}, {"id": "carrier", "label": "Carrier"}],
    clearances={"planet/ring": 0.2, "sun/planet": 0.2},
    features=[
        F("housing", "Parts laid out", "structure", "build123d Cylinders, every part side by side on the bed",
          'R = v["ring_d"] / 2\n'
          'out = Cylinder(R + 5, v["t"], align=A) - Cylinder(R, v["t"], align=A)\n'
          'out = out + Pos(R * 2 + 20, 0, 0) * Cylinder(R / 5, v["t"], align=A)\n'
          'for i in range(3):\n'
          '    out = out + Pos(R * 2 + 20 + (i + 1) * (R * 0.8 + 6), 0, 0) * Cylinder(R * 0.4 - 0.4, v["t"], align=A)\n'
          'return out + Pos(0, R * 2 + 20, 0) * Cylinder(R, 4, align=A)'),
        F("flange", "Flange", "structure", "craft.safe_union of a ring flange",
          'R = v["ring_d"] / 2\n'
          'return craft.safe_union(body, Cylinder(R + 12, 4, align=A) - Cylinder(R, 4, align=A))'),
        F("bolts", "Flange bolt holes", "interface", "parts.screw_clearance M3 holes on a circle",
          'R = v["ring_d"] / 2\n'
          'for a in range(0, 360, 90):\n'
          '    body = body - Rot(0, 0, a) * Pos(R + 8.5, 0, -1) * Cylinder(1.7, 6, align=A)\n'
          'return body'),
        F("bores", "Gear bores", "interface", "Cylinder cuts for the shaft and planet pins",
          'R = v["ring_d"] / 2\n'
          'body = body - Pos(R * 2 + 20, 0, -1) * Cylinder(2.5, v["t"] + 2, align=A)\n'
          'for i in range(3):\n'
          '    body = body - Pos(R * 2 + 20 + (i + 1) * (R * 0.8 + 6), 0, -1) * Cylinder(1.6, v["t"] + 2, align=A)\n'
          'return body'),
        F("pins", "Carrier pins", "interface", "craft.safe_union of three pins on the carrier",
          'R = v["ring_d"] / 2\n'
          'for a in (0, 120, 240):\n'
          '    body = craft.safe_union(body, Pos(0, R * 2 + 20, 3.8) * Rot(0, 0, a) * Pos(R * 0.6, 0, 0) * Cylinder(1.5, 8, align=A))\n'
          'return body')])

S["din_clip"] = dict(
    name="DIN-rail clip", brief="A 35 mm DIN-rail clip with a fixed hook and a sprung latch.",
    query="clip snap rail", solids=1, risks=["the latch arm must flex without breaking"],
    params=[P("w", "Width", 20, 10, 40, 0.5, "plate"), P("t", "Thickness", 3, 2, 5, 0.1, "plate")],
    features=[
        F("plate", "Back plate", "structure", "build123d Box", 'return Box(45, v["w"], v["t"], align=A)'),
        F("hook", "Fixed hook", "interface", "craft.safe_union of an L lip at one end",
          'return craft.safe_union(body, Pos(-22.5 + 1.5, 0, v["t"] - 0.2) * Box(3, v["w"], 4.2, align=A)\n'
          '                        + Pos(-22.5 + 3.5, 0, v["t"] + 3) * Box(4, v["w"], 1.2, align=A))'),
        F("latch", "Sprung latch", "interface", "craft.safe_union of a lip, a slot behind it frees the arm",
          'body = craft.safe_union(body, Pos(22.5 - 1.5, 0, v["t"] - 0.2) * Box(3, v["w"], 4.2, align=A))\n'
          'return craft.safe_cut(body, Pos(14, 0, -1) * Box(1.6, v["w"] - 4, v["t"] + 2, align=A))'),
        F("holes", "Screw holes", "interface", "Cylinder cuts",
          'for x in (-8, 6):\n'
          '    body = body - Pos(x, 0, -1) * Cylinder(1.8, v["t"] + 2, align=A)\n'
          'return body'),
        F("edges", "Edges", "finish", "craft.safe_fillet on outer vertical edges",
          'return craft.safe_fillet(body, body.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], 0.8)')])

S["drag_chain"] = dict(
    name="Drag-chain link", brief="A cable drag-chain link that snaps to the next one.",
    query="cable chain link snap", solids=1, risks=["the pin snap must not shear"],
    params=[P("w", "Inner width", 20, 10, 40, 0.5, "channel"), P("h", "Height", 14, 8, 24, 0.5, "channel")],
    features=[
        F("channel", "Channel", "structure", "build123d Box minus the inner box",
          'return Box(30, v["w"] + 4, v["h"], align=A) - Pos(0, 0, 2) * Box(32, v["w"], v["h"], align=A)'),
        F("pins", "Snap pins", "interface", "craft.safe_union of pins on the outside of one end",
          'for s in (-1, 1):\n'
          '    body = craft.safe_union(body, Pos(10, s * (v["w"] / 2 + 2.6), v["h"] / 2) * Rot(90, 0, 0) * Cylinder(2.2, 1.6))\n'
          'return body'),
        F("pin_holes", "Pin holes", "interface", "Cylinder cut through the other end",
          'return body - Pos(-10, 0, v["h"] / 2) * Rot(90, 0, 0) * Cylinder(2.4, v["w"] + 10)'),
        F("crossbar", "Crossbar", "structure", "craft.safe_union of a bar across the top",
          'return craft.safe_union(body, Pos(0, 0, v["h"] - 2) * Box(6, v["w"] + 0.4, 2, align=A))')])

# ---- creative ----------------------------------------------------------------------------------------------------

S["spiral_vase"] = dict(
    name="Spiral vase", brief="A vase with spiral ribs and a rolled lip.", query="spiral vase ribs",
    solids=1, risks=["ribs must overlap the wall, not touch it"],
    params=[P("r", "Radius", 40, 25, 60, 0.5, "body"), P("h", "Height", 150, 80, 250, 1, "body")],
    features=[
        F("body", "Body", "structure", "build123d Cylinder, hollowed", 'return Cylinder(v["r"], v["h"], align=A) - Pos(0, 0, 3) * Cylinder(v["r"] - 2.4, v["h"], align=A)'),
        F("ribs", "Spiral ribs", "finish", "craft.safe_union of twelve leaning ribs",
          # first attempt: ribs placed 1 mm outside the wall (they do not reach it), then the fixed one
          'for i in range(12):\n'
          '    body = craft.fuse(body, Rot(0, 0, i * 30) * Pos(v["r"] + 2.5, 0, 6) * Rot(12, 0, 0) * Box(2, 3, v["h"] * 0.8, align=A))\n'
          'return body',
          'for i in range(12):\n'
          '    body = craft.safe_union(body, Rot(0, 0, i * 30) * Pos(v["r"] + 0.4, 0, 6) * Rot(12, 0, 0) * Box(2, 3, v["h"] * 0.8, align=A))\n'
          'return body'),
        F("lip", "Rolled lip", "finish", "craft.safe_union of a Torus at the rim",
          'return craft.safe_union(body, Pos(0, 0, v["h"] - 1.2) * Torus(v["r"] - 1.2, 2.2))'),
        F("foot", "Foot", "finish", "craft.safe_fillet on the bottom edge",
          'return craft.safe_fillet(body, body.edges().group_by(Axis.Z)[0], 2.0)')])

S["twisted_shade"] = dict(
    name="Twisted lamp shade", brief="A table lamp with a lofted, twisted shade on a weighted base.",
    query="lamp shade twisted loft", solids=1, risks=["a twisted loft can fold"],
    params=[P("h", "Shade height", 120, 60, 200, 1, "shade"), P("w", "Shade width", 90, 50, 150, 1, "shade")],
    features=[
        F("shade", "Twisted shade", "structure", "build123d loft through rotated squares",
          'secs = [Plane.XY.offset(z) * Rot(0, 0, z * 0.5) * Rectangle(v["w"] * (1 - z / 400), v["w"] * (1 - z / 400)) for z in (0, v["h"] / 2, v["h"])]\n'
          'outer = loft(secs)\n'
          'inner = loft([Plane.XY.offset(z) * Rot(0, 0, z * 0.5) * Rectangle(v["w"] * (1 - z / 400) - 4, v["w"] * (1 - z / 400) - 4) for z in (-1, v["h"] / 2, v["h"] + 1)])\n'
          'return outer - inner'),
        F("base", "Weighted base", "structure", "craft.safe_union of a disc under the shade",
          'return craft.safe_union(body, Pos(0, 0, -15) * Cylinder(v["w"] * 0.55, 15.4, align=A))'),
        F("socket", "Lamp socket", "interface", "Cylinder cut for an E14 socket",
          'return body - Pos(0, 0, -16) * Cylinder(14, 18, align=A)'),
        F("cable", "Cable channel", "access", "Box cut from the socket to the edge",
          'return body - Pos(v["w"] * 0.3, 0, -16) * Box(v["w"] * 0.6, 6, 5, align=A)')])

S["knurled_knob"] = dict(
    name="Knurled knob", brief="A knurled control knob for a 6 mm D-shaft with a pointer.",
    query="knurled knob D-shaft", solids=1, risks=["knurl too fine to print"],
    params=[P("d", "Diameter", 30, 15, 50, 0.5, "body"), P("h", "Height", 16, 8, 30, 0.5, "body")],
    features=[
        F("body", "Body", "structure", "build123d Cylinder", 'return Cylinder(v["d"] / 2, v["h"], align=A)'),
        F("knurl", "Knurl", "finish", "24 grooves cut with craft.safe_cut",
          'for i in range(24):\n'
          '    body = craft.safe_cut(body, Rot(0, 0, i * 15) * Pos(v["d"] / 2, 0, 2) * Rot(0, 0, 45) * Box(1.2, 1.2, v["h"] - 4, align=A))\n'
          'return body'),
        F("bore", "D-shaft bore", "interface", "a Cylinder minus a flat",
          'd = Cylinder(3.1, 12, align=A) - Pos(2.6 + 2, 0, 0) * Box(4, 8, 12, align=A)\n'
          'return body - Pos(0, 0, -0.01) * d'),
        F("pointer", "Pointer", "finish", "a Box groove on the top",
          'return body - Pos(v["d"] / 4, 0, v["h"] - 0.8) * Box(v["d"] / 2 - 2, 1.2, 1, align=A)'),
        F("top", "Top chamfer", "finish", "craft.safe_chamfer on the top circle",
          'return craft.safe_chamfer(body, body.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1], 1.0)')])

S["hex_planter"] = dict(
    name="Hex planter", brief="A planter with a hexagonal relief texture on its wall, drain holes and a drip saucer.",
    query="hex planter relief", solids=2, risks=["relief must overlap the wall"],
    parts=[{"id": "pot", "label": "Pot"}, {"id": "saucer", "label": "Saucer"}], clearances={"pot/saucer": 1.0},
    params=[P("r", "Radius", 50, 30, 80, 0.5, "pot"), P("h", "Height", 90, 50, 150, 1, "pot")],
    features=[
        F("pot", "Pot and saucer", "structure", "build123d Cylinders, saucer beside the pot",
          'pot = Cylinder(v["r"], v["h"], align=A) - Pos(0, 0, 3) * Cylinder(v["r"] - 3, v["h"], align=A)\n'
          'sau = Cylinder(v["r"] + 8, 12, align=A) - Pos(0, 0, 2.4) * Cylinder(v["r"] + 5.6, 12, align=A)\n'
          'return pot + Pos(2 * v["r"] + 30, 0, 0) * sau'),
        F("relief", "Hex relief", "finish", "craft.safe_union of hexagonal pads on the wall",
          'for row in range(4):\n'
          '    for i in range(12):\n'
          '        a = i * 30 + row * 15\n'
          '        pad = Rot(0, 0, a) * Pos(v["r"] - 0.4, 0, 14 + row * 18) * Rot(0, 90, 0) * extrude(RegularPolygon(6, 6), 1.6)\n'
          '        body = craft.safe_union(body, pad)\n'
          'return body'),
        F("drains", "Drain holes", "access", "Cylinder cuts through the floor",
          'for x, y in ((0, 0), (15, 0), (-15, 0), (0, 15), (0, -15)):\n'
          '    body = body - Pos(x, y, -1) * Cylinder(3, 5, align=A)\n'
          'return body'),
        F("rim", "Rim", "finish", "craft.safe_fillet on the top edges",
          'return craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.0)')])

S["earbud_case"] = dict(
    name="Pebble earbud case", brief="A pebble-shaped earbud case with a hinged lid and two earbud pockets.",
    query="earbud case pebble hinged", solids=2, risks=["the hinge knuckles must not fuse"],
    parts=[{"id": "base", "label": "Base"}, {"id": "lid", "label": "Lid"}], clearances={"lid/base": 0.3},
    params=[P("l", "Length", 70, 50, 90, 0.5, "halves"), P("h", "Height", 32, 20, 40, 0.5, "halves")],
    features=[
        F("halves", "Pebble halves", "structure", "a scaled Sphere split into base and lid, laid side by side",
          'peb = scale(Sphere(v["l"] / 2), (1, 0.7, v["h"] / v["l"]))\n'
          'base = peb & Pos(0, 0, -50) * Box(200, 200, 50, align=A)\n'
          'lid = peb & Box(200, 200, 50, align=A)\n'
          'return Pos(0, 0, v["h"] / 2) * base + Pos(v["l"] + 15, 0, 0) * Rot(180, 0, 0) * lid'),
        F("hollow", "Hollow", "structure", "craft.safe_cut of a smaller pebble from each half",
          'inner = scale(Sphere(v["l"] / 2 - 2.4), (1, 0.66, (v["h"] - 4.8) / (v["l"] - 4.8)))\n'
          'body = craft.safe_cut(body, Pos(0, 0, v["h"] / 2) * inner)\n'
          'return craft.safe_cut(body, Pos(v["l"] + 15, 0, 0) * inner)'),
        F("pockets", "Earbud pockets", "interface", "craft.safe_union of two cups in the base",
          'for x in (-14, 14):\n'
          '    cup = Pos(x, 0, 2) * (Cylinder(9.5, v["h"] / 2 - 3, align=A) - Pos(0, 0, 1.6) * Cylinder(8, v["h"], align=A))\n'
          '    body = craft.safe_union(body, cup)\n'
          'return body'),
        F("hinge", "Hinge knuckles", "interface", "craft.safe_union of knuckles on the base edge",
          'for x in (-12, 12):\n'
          '    body = craft.safe_union(body, Pos(x, -v["l"] * 0.35 + 0.6, v["h"] / 2) * Rot(0, 90, 0) * (Cylinder(3, 8) - Cylinder(1.2, 9)))\n'
          'return body')])

# ---- organic -----------------------------------------------------------------------------------------------------

S["hero_helmet"] = dict(
    name="Hero helmet", brief="An original full-face hero helmet in separate parts: a shell, a magnetic faceplate and "
    "two lenses, with a hex panel texture.", query="full-face helmet separate parts magnets lens texture",
    solids=4, risks=["texture on the skin", "magnet pockets breaking through"],
    parts=[{"id": "shell", "label": "Shell"}, {"id": "faceplate", "label": "Faceplate"},
           {"id": "lens_l", "label": "Left lens"}, {"id": "lens_r", "label": "Right lens"}],
    clearances={"faceplate/shell": 0.3, "lens/faceplate": 0.2},
    magnets=[{"stock": "8x3", "count": 4, "retention": "press"}],
    params=[P("l", "Length", 270, 240, 300, 1, "shell"), P("wall", "Wall", 3.5, 2.5, 5, 0.1, "shell")],
    features=[
        F("shell", "Shell and part blanks", "structure", "a scaled Sphere skin, hollowed; faceplate and lens blanks beside it",
          'L, t = v["l"], v["wall"]\n'
          'out = scale(Sphere(L / 2), (1, 0.8, 0.9))\n'
          'inn = scale(Sphere(L / 2 - t), (1, (0.8 * L / 2 - t) / (L / 2 - t), (0.9 * L / 2 - t) / (L / 2 - t)))\n'
          'shell = (out - inn) - Pos(0, 0, -L) * Box(3 * L, 3 * L, L * 0.75, align=A)\n'
          'face = Pos(0, L, 0) * Box(120, 4, 90, align=A)\n'
          'lens = [Pos(x, L + 60, 0) * Box(50, 30, 3, align=A) for x in (-35, 35)]\n'
          'return shell + face + lens[0] + lens[1]'),
        F("eye_port", "Eye port", "access", "craft.safe_cut of a Box through the front",
          'L = v["l"]\n'
          'return craft.safe_cut(body, Pos(L * 0.45, 0, L * 0.02) * Box(L * 0.3, L * 0.45, L * 0.14, align=A))'),
        F("crest", "Crest", "finish", "craft.safe_union of a strip over the crown",
          'L = v["l"]\n'
          'return craft.safe_union(body, Pos(0, 0, 0.9 * L / 2 - 6) * Box(L * 0.6, 14, 10, align=A))'),
        F("magnets", "Magnet pockets", "interface", "parts.magnet_pocket 8x3 pairs, faceplate and shell",
          'L = v["l"]\n'
          'for x in (-45, 45):\n'
          '    body = body - Pos(x, L - 0.01, 45) * Rot(-90, 0, 0) * Cylinder(4.1, 3.2, align=A)\n'
          'return body'),
        F("lenses", "Lens clips", "interface", "craft.safe_union of clip tabs on each lens",
          # first attempt: tabs 2 mm above the lens (they float), then tabs that overlap it
          'L = v["l"]\n'
          'for x in (-35, 35):\n'
          '    body = craft.fuse(body, Pos(x, L + 60, 5) * Box(8, 6, 2, align=A))\n'
          'return body',
          'L = v["l"]\n'
          'for x in (-35, 35):\n'
          '    body = craft.safe_union(body, Pos(x, L + 60, 2.8) * Box(8, 6, 2, align=A))\n'
          'return body'),
        F("hex_texture", "Hex panel texture", "finish", "B-rep hex pads fused on the crown",
          # three real attempts that all leave the pads off the skin: the feature is deferred
          'L = v["l"]\n'
          'return craft.fuse(body, Pos(0, 0, 0.9 * L / 2 + 12) * extrude(RegularPolygon(10, 6), 2))',
          'L = v["l"]\n'
          'return craft.fuse(body, Pos(0, 0, 0.9 * L / 2 + 8) * extrude(RegularPolygon(10, 6), 2))',
          'L = v["l"]\n'
          'return craft.fuse(body, Pos(0, 0, 0.9 * L / 2 + 5) * extrude(RegularPolygon(8, 6), 1.5))')])

S["scooter_helmet"] = dict(
    name="Scooter helmet", brief="An open-face scooter helmet shell with a sun peak and vents.",
    query="open face helmet peak vents", solids=1, risks=["the peak must root in the shell"],
    params=[P("l", "Length", 250, 220, 290, 1, "shell"), P("wall", "Wall", 3, 2, 5, 0.1, "shell")],
    features=[
        F("shell", "Shell", "structure", "a scaled Sphere skin, hollowed and cut at the brow",
          'L, t = v["l"], v["wall"]\n'
          'out = scale(Sphere(L / 2), (1, 0.8, 0.8))\n'
          'inn = scale(Sphere(L / 2 - t), (1, (0.8 * L / 2 - t) / (L / 2 - t), (0.8 * L / 2 - t) / (L / 2 - t)))\n'
          'return (out - inn) - Pos(0, 0, -L) * Box(3 * L, 3 * L, L * 0.95, align=A)'),
        F("face_opening", "Face opening", "access", "craft.safe_cut of a Box at the front",
          'L = v["l"]\n'
          'return craft.safe_cut(body, Pos(L * 0.42, 0, -L * 0.05) * Box(L * 0.3, L * 0.6, L * 0.2, align=A))'),
        F("peak", "Sun peak", "structure", "craft.safe_union of a thin plate at the brow",
          'L = v["l"]\n'
          'return craft.safe_union(body, Pos(L * 0.47, 0, L * 0.16) * Rot(0, -12, 0) * Box(L * 0.16, L * 0.45, 2.5, align=A))'),
        F("vents", "Vents", "access", "slot cuts on the crown",
          'L = v["l"]\n'
          'for y in (-30, 0, 30):\n'
          '    body = body - Pos(0, y, 0.8 * L / 2) * Box(50, 6, 30)\n'
          'return body')])

S["mouse_shell"] = dict(
    name="Mouse shell", brief="An ergonomic computer mouse shell with a thumb rest and textured sides.",
    query="mouse shell ergonomic thumb", solids=1, risks=["the thumb rest must not cut through the wall"],
    params=[P("l", "Length", 118, 95, 135, 0.5, "shell"), P("wall", "Wall", 2, 1.4, 3, 0.1, "shell")],
    features=[
        F("shell", "Shell", "structure", "a scaled Sphere, flat bottom, hollowed",
          'L, t = v["l"], v["wall"]\n'
          'out = Pos(0, 0, -6) * scale(Sphere(L / 2), (1, 0.55, 0.36))\n'
          'inn = Pos(0, 0, -6) * scale(Sphere(L / 2 - t), (1, (0.55 * L / 2 - t) / (L / 2 - t), (0.36 * L / 2 - t) / (L / 2 - t)))\n'
          'return (out - inn) & Box(3 * L, 3 * L, L, align=A)'),
        F("thumb_rest", "Thumb rest", "finish", "craft.safe_cut of a shallow Cylinder on the left flank",
          'L = v["l"]\n'
          'return craft.safe_cut(body, Pos(-L * 0.05, 0.55 * L / 2 + 12.6, 8) * Rot(0, 90, 0) * Cylinder(14, L * 0.4))'),
        F("buttons", "Button split", "access", "a slot cut along the front with craft.safe_cut",
          # first attempt: a slot out to the nose tip leaves no solid in the kernel; then a shorter one
          'L = v["l"]\n'
          'return body - Pos(L * 0.25, 0, 0) * Box(L * 0.5, 1.4, 60, align=A)',
          'L = v["l"]\n'
          'return craft.safe_cut(body, Pos(L * 0.2, 0, 0) * Box(L * 0.3, 1.4, 60, align=A))'),
        F("side_grooves", "Textured sides", "finish", "grooves cut on the right flank",
          'L = v["l"]\n'
          'for i in range(5):\n'
          '    body = body - Pos(-L * 0.2 + i * 6, -0.55 * L / 2 + 0.8, 6) * Box(1.2, 4, 10, align=A)\n'
          'return body')])

S["screwdriver_handle"] = dict(
    name="Screwdriver handle", brief="An ergonomic screwdriver handle with a textured grip and a hex bit socket.",
    query="screwdriver handle grip hex", solids=1, risks=["flutes too deep for the wall around the socket"],
    params=[P("l", "Length", 100, 70, 130, 0.5, "body"), P("d", "Diameter", 32, 24, 40, 0.5, "body")],
    features=[
        F("body", "Body", "structure", "build123d Cylinder with a domed end",
          'return Cylinder(v["d"] / 2, v["l"], align=A) + Pos(0, 0, v["l"]) * Sphere(v["d"] / 2)'),
        F("flutes", "Grip flutes", "finish", "eight Cylinder cuts along the grip",
          'for i in range(8):\n'
          '    body = body - Rot(0, 0, i * 45) * Pos(v["d"] / 2 + 2, 0, 10) * Cylinder(3.5, v["l"] - 20, align=A)\n'
          'return body'),
        F("socket", "Hex bit socket", "interface", "a hexagonal prism cut, 6.35 mm across flats",
          'return body - Pos(0, 0, -0.01) * extrude(RegularPolygon(6.45 / 1.732, 6), 20)'),
        F("nose", "Nose chamfer", "finish", "craft.safe_chamfer on the nose circle",
          'return craft.safe_chamfer(body, body.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[0], 1.5)')])

S["creature_horn"] = dict(
    name="Creature horn", brief="A curved creature horn with growth rings and a mounting base.",
    query="horn organic curved", solids=1, risks=["the loft must not fold where it curves"],
    params=[P("r", "Base radius", 18, 10, 30, 0.5, "horn"), P("len", "Length", 120, 60, 200, 1, "horn")],
    features=[
        F("horn", "Horn", "structure", "build123d loft through circles on tilting planes",
          'secs, n = [], 6\n'
          'for i in range(n + 1):\n'
          '    f = i / n\n'
          '    pl = Plane.XY.rotated((0, -40 * f, 0)).offset(v["len"] * f)\n'
          '    secs.append(pl * Circle(max(1.0, v["r"] * (1 - 0.92 * f))))\n'
          'return loft(secs)'),
        F("rings", "Growth rings", "finish", "Torus cuts near the base",
          'for i in range(3):\n'
          '    body = body - Pos(0, 0, 8 + i * 8) * Torus(v["r"] * (1 - 0.92 * (8 + i * 8) / v["len"]) + 0.6, 1.0)\n'
          'return body'),
        F("base", "Mounting base", "structure", "craft.safe_union of a disc",
          'return craft.safe_union(body, Pos(0, 0, -4) * Cylinder(v["r"] + 6, 4.4, align=A))'),
        F("hole", "Mounting hole", "interface", "Cylinder cut",
          'return body - Pos(0, 0, -5) * Cylinder(2.6, 20, align=A)')])

# ---- assemblies --------------------------------------------------------------------------------------------------

S["screwed_enclosure"] = dict(
    name="Screwed enclosure", brief="An electronics enclosure with a screwed lid, heat-set insert bosses, a seal lip "
    "and vent slots.", query="electronics enclosure lid bosses", solids=2, risks=["bosses must keep their wall"],
    parts=[{"id": "box", "label": "Box"}, {"id": "lid", "label": "Lid"}], clearances={"lid/box": 0.2},
    params=[P("w", "Width", 80, 50, 150, 0.5, "box"), P("h", "Height", 35, 20, 60, 0.5, "box")],
    features=[
        F("box", "Box and lid", "structure", "build123d Boxes, the lid beside the box",
          'W, D = v["w"], v["w"] * 0.7\n'
          'box = Box(W, D, v["h"], align=A) - Pos(0, 0, 2.4) * Box(W - 4.8, D - 4.8, v["h"], align=A)\n'
          'return box + Pos(W + 15, 0, 0) * Box(W, D, 2.4, align=A)'),
        F("bosses", "Insert bosses", "interface", "craft.safe_union of four bosses, parts.heat_insert_pocket holes",
          'W, D = v["w"], v["w"] * 0.7\n'
          'for x in (-W / 2 + 7, W / 2 - 7):\n'
          '    for y in (-D / 2 + 7, D / 2 - 7):\n'
          '        b = Pos(x, y, 2) * Cylinder(4.2, v["h"] - 2, align=A) - Pos(x, y, v["h"] - 5.7) * Cylinder(2.0, 6, align=A)\n'
          '        body = craft.safe_union(body, b)\n'
          'return body'),
        F("lid_holes", "Lid screw holes", "interface", "parts.screw_clearance M3 holes in the lid",
          'W, D = v["w"], v["w"] * 0.7\n'
          'for x in (-W / 2 + 7, W / 2 - 7):\n'
          '    for y in (-D / 2 + 7, D / 2 - 7):\n'
          '        body = body - Pos(W + 15 + x, y, -1) * Cylinder(1.7, 5, align=A)\n'
          'return body'),
        F("seal_lip", "Seal lip", "interface", "craft.safe_union of a rim on the lid",
          'W, D = v["w"], v["w"] * 0.7\n'
          'rim = Box(W - 5.2, D - 5.2, 3, align=A) - Box(W - 8, D - 8, 3, align=A)\n'
          'return craft.safe_union(body, Pos(W + 15, 0, 2.2) * rim)'),
        F("vents", "Vent slots", "access", "patterns.slot_array cut through one wall",
          'W = v["w"]\n'
          'for i in range(6):\n'
          '    body = body - Pos(-15 + i * 6, -W * 0.35, v["h"] * 0.5) * Box(2.5, 8, v["h"] * 0.4)\n'
          'return body')])

S["aa_box"] = dict(
    name="AA cell box", brief="A box for two AA cells with a sliding lid that clicks shut.",
    query="battery box sliding lid", solids=2, risks=["the lid must slide with clearance"],
    parts=[{"id": "box", "label": "Box"}, {"id": "lid", "label": "Sliding lid"}], clearances={"lid/rails": 0.25},
    params=[P("l", "Length", 58, 52, 70, 0.5, "box", "brief"), P("wall", "Wall", 1.6, 1.2, 3, 0.1, "box")],
    features=[
        F("box", "Box and lid", "structure", "build123d Boxes, the lid beside the box",
          'L, t = v["l"], v["wall"]\n'
          'box = Box(L + 2 * t, 2 * 14.5 + 2 * t, 16 + t, align=A)\n'
          'return box + Pos(0, 50, 0) * Box(L + 2 * t - 1, 29 + t, 1.6, align=A)'),
        F("cavity", "Cell cavity", "structure", "Box cut for two cells",
          'L, t = v["l"], v["wall"]\n'
          'return body - Pos(0, 0, t) * Box(L, 29, 20, align=A)'),
        F("rails", "Lid rails", "interface", "Box grooves cut in both side walls",
          'L, t = v["l"], v["wall"]\n'
          'return body - Pos(t, 0, 16 + t - 2.6) * Box(L + 2 * t, 29 + 1.6, 1.8, align=A)'),
        F("detent", "Click detent", "interface", "craft.safe_union of a bump on the lid",
          'return craft.safe_union(body, Pos(-v["l"] / 2 + 4, 50, 1.4) * Box(2, 10, 0.8, align=A))')])

S["magnet_organizer"] = dict(
    name="Magnetic organizer", brief="A two-part desk organizer held together by 8x3 mm magnets.",
    query="desk organizer magnets two-part", solids=2, risks=["magnet pockets must keep a floor"],
    parts=[{"id": "tray_a", "label": "Tray A"}, {"id": "tray_b", "label": "Tray B"}], clearances={"a/b": 0.2},
    magnets=[{"stock": "8x3", "count": 4, "retention": "glue"}],
    params=[P("w", "Tray width", 80, 50, 120, 0.5, "trays"), P("h", "Height", 40, 20, 80, 0.5, "trays")],
    features=[
        F("trays", "Trays", "structure", "build123d Boxes, side by side",
          'W = v["w"]\n'
          'return Box(W, 60, v["h"], align=A) + Pos(W + 10, 0, 0) * Box(W, 60, v["h"], align=A)'),
        F("pockets", "Compartments", "structure", "Box cuts",
          'W = v["w"]\n'
          'for x in (0, W + 10):\n'
          '    body = body - Pos(x, 0, 2.4) * Box(W - 4.8, 55.2, v["h"], align=A)\n'
          'return body'),
        F("magnets", "Magnet pockets", "interface", "parts.magnet_pocket 8x3 in each mating wall",
          'W = v["w"]\n'
          'for z in (v["h"] * 0.3, v["h"] * 0.7):\n'
          '    body = body - Pos(W / 2 + 0.01, 0, z) * Rot(0, -90, 0) * Cylinder(4.1, 3.2, align=A)\n'
          '    body = body - Pos(W + 10 - W / 2 - 0.01, 0, z) * Rot(0, 90, 0) * Cylinder(4.1, 3.2, align=A)\n'
          'return body'),
        F("edges", "Edges", "finish", "craft.safe_fillet on vertical edges",
          'return craft.safe_fillet(body, body.edges().filter_by(Axis.Z), 1.0)')])

S["ratchet"] = dict(
    name="Ratchet", brief="A ratchet wrench with a pawl and a quarter-inch square drive.",
    query="ratchet wrench pawl", solids=3, risks=["pawl teeth must engage the wheel"],
    parts=[{"id": "handle", "label": "Handle"}, {"id": "wheel", "label": "Drive wheel"}, {"id": "pawl", "label": "Pawl"}],
    clearances={"wheel/head": 0.2, "pawl/pocket": 0.2},
    params=[P("l", "Handle length", 140, 90, 200, 1, "handle"), P("t", "Thickness", 10, 7, 14, 0.5, "handle")],
    features=[
        F("handle", "Parts laid out", "structure", "build123d Box and Cylinders, every part side by side",
          'L, t = v["l"], v["t"]\n'
          'h = Box(L, 16, t, align=A) + Pos(L / 2, 0, 0) * Cylinder(15, t, align=A)\n'
          'return h + Pos(0, 50, 0) * Cylinder(10.5, t, align=A) + Pos(40, 50, 0) * Box(14, 6, t, align=A)'),
        F("head_bore", "Head bore", "interface", "Cylinder cut for the wheel",
          'return body - Pos(v["l"] / 2, 0, -1) * Cylinder(10.7, v["t"] + 2, align=A)'),
        F("teeth", "Wheel teeth", "interface", "24 Box cuts around the wheel",
          'for i in range(24):\n'
          '    body = body - Pos(0, 50, -1) * Rot(0, 0, i * 15) * Pos(10.5, 0, 0) * Rot(0, 0, 45) * Box(1.6, 1.6, v["t"] + 2, align=A)\n'
          'return body'),
        F("drive", "Square drive", "interface", "craft.safe_union of a 6.35 mm square boss",
          'return craft.safe_union(body, Pos(0, 50, v["t"] - 0.2) * Box(6.3, 6.3, 8, align=A))'),
        F("pawl_pivot", "Pawl pivot", "interface", "Cylinder cut through the pawl",
          'return body - Pos(36, 50, -1) * Cylinder(1.6, v["t"] + 2, align=A)')])

BRIEFS = list(S)


def skeleton_source(sid: str) -> str:
    s = S[sid]
    f = s["features"][0]
    return HEADER.format(title=s["name"], summary=s["brief"], solids=s["solids"], params="\n".join(s["params"])) + \
        "\n" + "\n".join("    " + ln if ln else "" for ln in method(f["id"], f["label"], f["role"], f["attempts"][0]).splitlines()) + "\n"


def feature_code(f: dict, attempt: int) -> str:
    return method(f["id"], f["label"], f["role"], f["attempts"][attempt])


def _payload(res):
    if isinstance(res, (dict, list)):
        return res
    try:
        return json.loads(res)
    except (TypeError, ValueError):
        return {"text": str(res)}


class ScriptedAgent:
    """Replays one brief's script through call(tool, args) -> (ok, payload). Records every call with its time."""

    def __init__(self, call):
        self.call = call

    async def _do(self, rec, tool, args):
        t0 = time.time()
        ok, out = await self.call(tool, args)
        out = _payload(out)
        rec["calls"].append({"tool": tool, "ok": bool(ok), "t0": t0, "s": round(time.time() - t0, 3),
                             **({"feature": args["feature"]} if args.get("feature") else {}),
                             **({"error": (out.get("text") if isinstance(out, dict) else str(out))[:300]} if not ok else {})})
        return ok, out

    async def run(self, sid: str) -> dict:
        s = S[sid]
        rec = {"id": sid, "t0": time.time(), "calls": [], "project": None, "planned": len(s["features"]),
               "built": [], "deferred": [], "retried": []}
        ok, b = await self._do(rec, "design_brief", {"name": s["name"], "goal": s["brief"], "purpose": "model"})
        brief = b.get("brief") if ok else None
        rec["route"] = b.get("route") if ok else None
        await self._do(rec, "design_examples", {"query": s["query"]})
        if brief:
            plan = {"brief": brief, "features": [{"id": f["id"], "label": f["label"], "how": f["how"]} for f in s["features"]],
                    "risks": s["risks"]}
            for k in ("parts", "clearances", "magnets"):
                if s.get(k):
                    plan[k] = s[k]
            ok, pl = await self._do(rec, "plan_design", plan)
            rec["plan_ok"] = ok
            if not ok:
                brief = None
        args = {"name": s["name"], "source": skeleton_source(sid), "brief": s["brief"], "run": False, "purpose": "model"}
        if brief:
            args["plan"] = brief
        ok, out = await self._do(rec, "create_design", args)
        rec["first_build_ok"] = bool(ok) and not out.get("partial")
        rec["skeleton_returned_s"] = round(rec["calls"][-1]["t0"] + rec["calls"][-1]["s"] - rec["t0"], 3) if ok else None
        if not ok:
            rec["end"] = time.time()
            return rec
        pid = out["project"]["id"] if isinstance(out.get("project"), dict) else out.get("project")
        rec["project"] = pid
        rec["built"].append(s["features"][0]["id"])
        for f in s["features"][1:]:
            done = False
            for attempt in range(min(len(f["attempts"]), 1 + RETRIES)):
                ok, out = await self._do(rec, "add_feature", {"project": pid, "kind": "code", "feature": f["id"],
                                                              "code": feature_code(f, attempt), "label": f["label"],
                                                              "role": f["role"]})
                if ok:
                    done = True
                    if attempt:
                        rec["retried"].append(f["id"])
                    break
            (rec["built"] if done else rec["deferred"]).append(f["id"])
        ok, src = await self._do(rec, "get_design_source", {"project": pid})
        rec["final_source"] = src.get("source") if ok else None
        rec["end"] = time.time()
        return rec


# ---- a scripted remodel: rebuild a mesh as clean CAD until it is within 0.1 mm --------------------------------------
#
# The reference is a flange: a disc with a centre bore and six bolt holes on a circle, 15 degrees off the X axis. The
# agent starts from a draft read off the analysis with one size slightly off (the thickness, 0.3 mm too thick, as a
# rough reading would be) and no bolt holes. Two policies, the same agent otherwise:
#
#   without the residual  compare_to_reference after every change; fix the worst region it lists (a bolt hole from
#                         the region's box, or a size by the region's deviation), one change per call. When one region
#                         covers the whole part with a large peak (the thickness offset joins the holes into one), it
#                         compares at 0.5 mm until the large differences are fixed, then at 0.1 mm again
#   with the residual     reference_residual names the six bodies as one polar pattern; build it as one feature;
#                         reference_residual again (keep it only if the residual dropped); fit_params for the sizes;
#                         compare_to_reference to confirm
#
# Each policy stops at 0.1 mm (two-sided Hausdorff) or after MAX_REMODEL_CALLS calls. Every call is a real MCP call.

FLANGE = {"r": 30.0, "t": 6.0, "bore_d": 12.0, "hole_d": 5.5, "pcd_r": 22.0, "count": 6, "start_deg": 15.0}
DRAFT_T = 6.3
REMODEL_TOL = 0.1
MAX_REMODEL_CALLS = 40


def flange_reference():
    """The reference flange as a build123d solid (the test exports it as an STL)."""
    from build123d import Align, Cylinder, Pos, Rot
    A_ = (Align.CENTER, Align.CENTER, Align.MIN)
    f = FLANGE
    body = Cylinder(f["r"], f["t"], align=A_) - Cylinder(f["bore_d"] / 2, 4 * f["t"])
    for i in range(f["count"]):
        body = body - Rot(0, 0, f["start_deg"] + i * 360 / f["count"]) * Pos(f["pcd_r"], 0, -1) * \
            Cylinder(f["hole_d"] / 2, f["t"] + 2, align=A_)
    return body


def flange_source(t: float, holes=(), pattern: dict | None = None) -> str:
    """The rebuilt flange as a design: disc and bore, then bolt holes as literal holes or as one polar pattern."""
    params = [f'        Param("t", "Thickness", {t:g}, 2, 20, 0.1, "mm", "form", "disc"),',
              f'        Param("bore_d", "Bore", {FLANGE["bore_d"]:g}, 2, 40, 0.1, "mm", "form", "disc"),']
    feats = ['Feature("disc", "Disc and bore", "structure")']
    body = ['        b = Cylinder(30, v["t"], align=A) - Cylinder(v["bore_d"] / 2, 4 * v["t"])',
            '        out = [Stage("disc", b)]']
    if holes:
        feats.append('Feature("holes", "Bolt holes", "interface")')
        body += [f'        for x, y, d in {[tuple(h) for h in holes]!r}:',
                 '            b = b - Pos(x, y, -1) * Cylinder(d / 2, v["t"] + 2, align=A)',
                 '        out.append(Stage("holes", b))']
    if pattern:
        params += [f'        Param("hole_d", "Bolt hole", {pattern["d"]:g}, 1, 20, 0.1, "mm", "form", "bolt_circle"),',
                   f'        Param("pcd_r", "Bolt circle radius", {pattern["r"]:g}, 5, 29, 0.1, "mm", "form", "bolt_circle"),']
        feats.append('Feature("bolt_circle", "Bolt circle", "interface")')
        body += [f'        for i in range({pattern["n"]}):',
                 f'            b = b - Rot(0, 0, {pattern["start"]:g} + i * {pattern["pitch"]:g}) * Pos(v["pcd_r"], 0, -1) * '
                 'Cylinder(v["hole_d"] / 2, v["t"] + 2, align=A)',
                 '        out.append(Stage("bolt_circle", b))']
    return ("from build123d import *\nfrom form.recipes.base import Feature, Param, Recipe, Stage\n\n"
            "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\nclass Design(Recipe):\n    title = \"Flange\"\n"
            "    summary = \"A flange rebuilt from its mesh\"\n    params = [\n" + "\n".join(params) + "\n    ]\n"
            "    features = [" + ", ".join(feats) + "]\n\n    def build(self, v):\n" + "\n".join(body) + "\n        return out\n")


def _q(x, s=0.05):
    return round(round(float(x) / s) * s, 3)


class RemodelAgent:
    """Replays the flange remodel through call(tool, args) -> (ok, payload) with or without the residual tool."""

    def __init__(self, call):
        self.call = call

    async def _do(self, rec, tool, args):
        t0 = time.time()
        ok, out = await self.call(tool, args)
        out = _payload(out)
        rec["calls"].append({"tool": tool, "ok": bool(ok), "s": round(time.time() - t0, 3),
                             **({"error": str(out)[:300]} if not ok else {})})
        if not ok:
            raise RuntimeError(f"{tool} failed: {str(out)[:500]}")
        return out

    async def run(self, reference_path: str, residual: bool) -> dict:
        rec = {"policy": "residual" if residual else "compare only", "calls": [], "hausdorff": []}
        t, holes = DRAFT_T, []
        out = await self._do(rec, "create_design", {"name": "Flange remodel", "source": flange_source(t),
                                                    "references": [reference_path], "run": False, "purpose": "model"})
        pid = out["project"]["id"] if isinstance(out.get("project"), dict) else out["project"]
        rec["project"] = pid
        ref = "flange"

        async def compare(tol=REMODEL_TOL):
            c = await self._do(rec, "compare_to_reference", {"project": pid, "reference": ref, "tolerance": tol})
            rec["hausdorff"].append(c["hausdorff_mm"])
            return c

        if residual:
            last = None
            stalled = 0
            while len(rec["calls"]) < MAX_REMODEL_CALLS:
                r = await self._do(rec, "reference_residual", {"project": pid, "reference": ref})
                pct = r["residual_pct"]
                if last is not None and pct >= last["pct"]:       # no drop: go back, count a stalled step
                    stalled += 1
                    await self._do(rec, "checkout_revision", {"project": pid, "rev": last["rev"]})
                    if stalled >= 3:
                        break
                last = {"pct": pct, "rev": r["rev"]}
                pol = [p for p in r["patterns"] if p["type"] == "polar" and p["kind"] == "extra"]
                if not pol:
                    break
                p = pol[0]
                pat = {"n": p["count"], "pitch": round(p["pitch_deg"], 3), "start": round(p["start_deg"], 2),
                       "r": _q(p["radius_mm"]), "d": _q(p["diameter_mm"])}
                await self._do(rec, "update_design", {"project": pid, "source": flange_source(t, pattern=pat),
                                                      "run": False, "note": "bolt circle from the residual"})
            await self._do(rec, "fit_params", {"project": pid, "reference": ref})
            c = await compare()
        else:
            tol = REMODEL_TOL
            c = await compare(tol)
            while len(rec["calls"]) < MAX_REMODEL_CALLS:
                if c["within_tolerance"]:
                    if tol == REMODEL_TOL:
                        break
                    tol = REMODEL_TOL                               # the big ones are done: back to the real limit
                    c = await compare(tol)
                    continue
                w = c["worst_regions"][0]
                lo, hi = w["box"]
                extra = w["design_has"].startswith("material the mesh does not have")
                span = max(hi[0] - lo[0], hi[1] - lo[1])
                local = span < 20
                if not local and w["max_mm"] >= 1.0 and tol == REMODEL_TOL:
                    # one region over the whole part with a large peak: a small offset everywhere joins the big
                    # differences into one region. A coarser tolerance separates them.
                    tol = 0.5
                    c = await compare(tol)
                    continue
                if local and w["max_mm"] >= 1.0 and extra:          # a hole the design lacks: its box is the hole
                    holes.append((_q((lo[0] + hi[0]) / 2), _q((lo[1] + hi[1]) / 2), _q((hi[0] - lo[0] + hi[1] - lo[1]) / 2)))
                    await self._do(rec, "update_design", {"project": pid, "source": flange_source(t, holes),
                                                          "run": False, "note": "a bolt hole at the worst region"})
                elif local and holes:                               # a hole a little off: resize the nearest
                    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
                    k = min(range(len(holes)), key=lambda i: (holes[i][0] - cx) ** 2 + (holes[i][1] - cy) ** 2)
                    x, y, d = holes[k]
                    holes[k] = (x, y, round(d + (2 if extra else -2) * w["max_mm"], 3))
                    await self._do(rec, "update_design", {"project": pid, "source": flange_source(t, holes),
                                                          "run": False, "note": "bolt hole resized"})
                else:                                               # a whole face off: the thickness
                    t = round(t + (-1 if extra else 1) * w["max_mm"], 3)
                    await self._do(rec, "commit_change", {"project": pid, "values": {"t": t}, "run": False,
                                                          "expect_head": c["rev"]})
                c = await compare(tol)
        rec["final_hausdorff_mm"] = c["hausdorff_mm"]
        rec["reached"] = bool(c["hausdorff_mm"] <= REMODEL_TOL)
        rec["n_calls"] = len(rec["calls"])
        return rec
