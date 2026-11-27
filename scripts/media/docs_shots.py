"""The pictures of the app in the docs (docs/images/*.webp), taken from the real app.

    .venv/bin/python scripts/media/docs_shots.py                 # every scene, then docs/images
    .venv/bin/python scripts/media/docs_shots.py chat settings   # only some scenes
    .venv/bin/python scripts/media/docs_shots.py --keep DIR      # where the full-window PNGs go (default .dev/docs-shots)
    .venv/bin/python scripts/media/docs_shots.py --no-write      # take the pictures, leave docs/images alone
    .venv/bin/python scripts/media/docs_shots.py --write-only    # write docs/images from pictures taken before

Each scene is one run of the app through its own test driver (python -m form.app --uitest), in a ghost window that is
never shown and never takes the keyboard, with a new temporary data folder, its own settings file and no keys: nothing
of the person's own designs or agents is read. The agent is the stand-in of scripts/media/docs_agent.py: it reads the
real design and builds real concepts through the engine; only its sentences are scripted. The designs are built by the
CAD kernel and sliced by the slicer installed on this computer, so the numbers on screen are the engine's.

Lines that only exist because of the run itself (which environment variables set the data folder, the path of the
stand-in's interpreter, the development version) are hidden before a picture is taken; nothing else is changed.

The scenes themselves are the functions named scene_* below; this file is also the journey the app runs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "journeys"))
DATA = "fresh"
SIZE = "1440x900"


# ───────────────────────────────────────── inside the app ─────────────────────────────────────────
def snap(ui, name, target=None, pad=0):
    """The whole window as <name>.png; with a target, its box (points) beside it for the crop."""
    p = ui.shot(name)
    if target is not None:
        it = ui.find(target) if isinstance(target, str) else target
        if it is not None:
            from PySide6.QtCore import QPointF
            a = it.mapToScene(QPointF(0, 0))
            Path(str(p)[:-4] + ".box").write_text(json.dumps([round(a.x()) - pad, round(a.y()) - pad, round(it.width()) + 2 * pad, round(it.height()) + 2 * pad]))
    print("SHOT", name, flush=True)


def hide(ui, *needles):
    """Hide the lines a capture run adds (see the module's words above)."""
    n = 0
    for needle in needles:
        for it in ui.find_all(text=needle, exact=False):
            it.setProperty("opacity", 0)
            n += 1
    return n


def away(ui):
    """The pointer on the empty floor at the foot of the stage: on no part, no button, no tab."""
    vp = ui.find("viewport")
    if vp is None:
        return
    l, b = float(vp.property("insetLeft") or 0), float(vp.property("insetBottom") or 0)
    ui.hover("viewport", (l + 150) / vp.width(), (vp.height() - max(b, 60) - 46) / vp.height())
    ui.settle(500)


def back(ui, k):
    """Step the camera back by k, as a wheel turn does: a tall part is framed for its width and runs under the top row."""
    vp = ui.item("viewport")
    vp.setProperty("dist", float(vp.property("dist")) * k)
    ui.settle(500)


def quiet(ui):
    """No toast, no pointer resting on anything."""
    ui.run_js("Store.toasts = []")
    away(ui)


def send(ui, text, wait=180):
    ui.click("composer")
    ui.type(text)
    ui.key("Return")
    ui.settle(600)


def replied(ui, wait=240):
    ui.wait_until(lambda: ui.js("Store.chatItems.length") > 0 and not ui.store.get("chatBusy"), wait, "the agent's reply")
    ui.settle(1500)


def start_home(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home and its composer")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(800)


def write_home(ui, text):
    ui.click("startText")
    ui.wait_until(lambda: ui.item("startText").property("activeFocus"), 3, "the composer to take the keyboard")
    ui.type(text)
    ui.settle(300)


def scene_chat(ui):
    """A conversation about a design; the command palette; Review."""
    from _lib import phone_dock, toasts_gone
    start_home(ui)
    phone_dock(ui)
    ui.settle(2500)
    send(ui, "Review r01 and tell me what to change before I print it.")
    replied(ui)
    ui.wait_until(lambda: ui.store.get("talkOpen") is True, 5, "the conversation column")
    quiet(ui)
    snap(ui, "app-chat")
    ui.key("Ctrl+J")
    ui.settle(700)
    ui.key("Ctrl+K")
    ui.settle(900)
    snap(ui, "app-palette", "palette", 40)
    ui.key("Escape")
    ui.settle(400)
    ui.click("stage-prove")
    ui.settle(1500)
    quiet(ui)
    snap(ui, "prove")
    ui.run_js("Store.openSheet('variants')")
    ui.settle(1800)
    snap(ui, "app-variants")
    ui.run_js("Store.openSheet(null)")
    try:                                  # the share card: the engine's own picture of the head revision
        from form import share
        pid = ui.store.get("pid")
        share.card(ui.studio, ui.studio.load(pid), str(Path(ui.out) / "share-card.png"), "model")
        print("SHOT share-card", flush=True)
    except Exception as e:
        print("SKIP share card", type(e).__name__, str(e)[:200], flush=True)


def scene_settings(ui):
    """Settings: General, Agents & models, Printing."""
    from _lib import printing_on
    start_home(ui)
    printing_on(ui)
    for tab, name in (("general", "settings-general"), ("chat", "settings-agents"), ("printer", "settings-printing")):
        ui.run_js("Store.openSettings(%r)" % tab)
        ui.settle(1600)
        if tab == "general":
            ui.wait_until(lambda: not ui.sees("Reading what Form Studio is set up for", within=ui.item("sheetCard")), 30, "the Set up for cards")
            ui.settle(600)
        hide(ui, *RUN_LINES)
        ui.settle(300)
        snap(ui, name, "sheetCard")
    ui.key("Escape")


HOOK = '''"""Wall hook with a shelf: a peg, a small shelf on a thin gusset and a cable tab."""
from build123d import Align, Box, Cylinder, Pos, Rot

from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Wall hook with a shelf"
    summary = "A back plate that screws to the wall, a peg, and a small shelf carried by a gusset."
    params = [
        Param("width", "Width", 46, 30, 80, 1, "mm", "form", "plate"),
        Param("plate_t", "Plate thickness", 5, 3, 8, 0.5, "mm", "form", "plate"),
        Param("peg_d", "Peg diameter", 12, 8, 20, 0.5, "mm", "form", "peg"),
        Param("peg_l", "Peg length", 30, 15, 60, 1, "mm", "form", "peg"),
        Param("shelf_d", "Shelf depth", 34, 20, 60, 1, "mm", "form", "shelf"),
        Param("gusset_t", "Gusset thickness", 1.0, 0.6, 5, 0.1, "mm", "form", "gusset", "Thin on purpose in this draft."),
        Param("tab_t", "Cable tab thickness", 0.6, 0.4, 3, 0.1, "mm", "form", "tab"),
    ]
    features = [Feature("plate", "Back plate", "structure"), Feature("holes", "Screw holes", "interface"),
                Feature("peg", "Peg", "interface"), Feature("shelf", "Shelf", "access"),
                Feature("gusset", "Gusset", "structure"), Feature("tab", "Cable tab", "access")]

    def build(self, v):
        w, t = v["width"], v["plate_t"]
        body = Box(w, t, 96, align=A)
        stages = [Stage("plate", body)]
        for z in (9, 88):
            body = body - Pos(w / 2 - 8, 0, z) * Rot(90, 0, 0) * Cylinder(2.2, t + 2)
            body = body - Pos(-w / 2 + 8, 0, z) * Rot(90, 0, 0) * Cylinder(2.2, t + 2)
        stages.append(Stage("holes", body))
        body = body + Pos(0, -t / 2, 26) * Rot(90, 0, 0) * Cylinder(v["peg_d"] / 2, v["peg_l"], align=A)
        body = body + Pos(0, -t / 2 - v["peg_l"], 26) * Rot(90, 0, 0) * Cylinder(v["peg_d"] / 2 + 2.5, 3, align=A)
        stages.append(Stage("peg", body))
        body = body + Pos(0, -t / 2 - v["shelf_d"] / 2, 78) * Box(w, v["shelf_d"], 3, align=A)
        stages.append(Stage("shelf", body))
        body = body + Pos(0, -t / 2 - (v["shelf_d"] - 6) / 2, 52) * Box(v["gusset_t"], v["shelf_d"] - 6, 26, align=A)
        stages.append(Stage("gusset", body))
        body = body + Pos(w / 2 - 6, -t / 2 - 5, 81) * Box(v["tab_t"], 10, 12, align=A)
        stages.append(Stage("tab", body))
        return stages
'''


def scene_maps(ui):
    """Analyze: the wall-thickness and overhang maps, on a design that has thin walls and overhangs to show (a wall hook
    whose gusset and cable tab are drawn thin, with a peg and a shelf that overhang)."""
    from _lib import open_project, printing_on, wait_job
    start_home(ui)
    printing_on(ui)
    d = ui.studio.create_design("Wall hook with a shelf", HOOK, purpose="print")
    pid = d["id"]
    ui.api("/projects/" + pid + "/run", {"nodes": [], "force": False})
    wait_job(ui, pid)
    open_project(ui, pid)
    ui.settle(2000)
    away(ui)
    ui.key("A")
    ui.wait_until(lambda: ui.js("Ws.tool") == "analyze", 3, "Analyze")
    bar = ui.item("analyzeBar")
    for label, mid, view in (("Thickness", "thickness", "1"), ("Overhang", "overhang", "5")):
        ui.click_text(label, within=bar)
        ui.wait_until(lambda: ui.js("!!Store.analysis && Store.analysis.map === %r && !Store.analysisBusy" % mid), 180, "the map")
        ui.wait_until(lambda: ui.item("viewport").property("mapShown") is True, 8, "the map on the part")
        away(ui)
        ui.key(view)
        ui.settle(1800)
        back(ui, 1.5 if mid == "thickness" else 1.15)
        quiet(ui)
        snap(ui, "app-" + mid)
        ui.key("1")
        ui.settle(600)
    ui.key("V")


def scene_concepts(ui):
    """Concepts side by side, built by the kernel."""
    start_home(ui)
    write_home(ui, "Concepts for a phone stand for my desk, with room for the charging cable")
    ui.key("Return")
    ui.wait_until(lambda: ui.exists("conceptsSheet"), 300, "the concepts side by side")
    ui.wait_until(lambda: len(ui.find_all(name="conceptCard")) == 3, 30, "three concept cards")
    ui.wait_until(lambda: not ui.store.get("chatBusy"), 120, "the agent's reply")
    ui.settle(4000)
    snap(ui, "concepts")


def scene_measure(ui):
    """Measure this: the agent asks for one number, with where to measure it."""
    from _lib import DOCK, make
    start_home(ui)
    make(ui, "dock", "Desk phone dock", DOCK)
    ui.settle(2000)
    send(ui, "Measure the phone so the slot fits")
    ui.wait_until(lambda: ui.find("measureCard"), 120, "the measurement card")
    ui.wait_until(lambda: ui.store.get("chatAsking"), 20, "the open question")
    ui.settle(1500)
    quiet(ui)
    snap(ui, "measure-this")
    card = ui.item("measureCard")
    ui.click(ui.item("measureValue", within=card))
    ui.type("9.4")
    ui.click("measureSend")
    replied(ui)


def scene_photo(ui):
    """A photo on Home's composer, ready to send. The photo is one of Form Studio's own renders."""
    from PIL import Image
    start_home(ui)
    photo = Path(ui.files) / "desk-box.jpg"
    Image.open(ROOT / "docs" / "images" / "render-desk-blue.webp").convert("RGB").resize((1200, 800)).save(photo, quality=88)
    ui.pick_file(photo)
    ui.click("startAdd")
    ui.wait_until(lambda: ui.find_all(name="startAttachment"), 30, "the photo on the composer")
    write_home(ui, "A box like this for my desk drawer, 120 mm wide, with a hinged lid")
    ui.settle(800)
    snap(ui, "start-photo")


def scene_inspect(ui):
    """Annotate (a face, an edge and a painted region with their computed numbers), then colours and materials."""
    import inspection as I
    from _lib import make, printing_on, wait_job
    start_home(ui)
    printing_on(ui)
    pid = make(ui, "hinged_box", "Hinged keepsake box", purpose="print")
    ui.settle(2000)
    ui.click_text("Annotate")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.store.get("selecting") is True, 3, "the Annotate tool")
    a, b, pa, pb = I.two_parts(ui)
    ui.click("viewport", *a)
    ui.wait_until(lambda: len((ui.store.get("selection") or {}).get("items", [])) == 1, 60, "a face")
    ui.click_text("Edge", within=ui.item("annotateBar"))
    a, b, pa, pb = I.two_parts(ui)
    ui.click("viewport", *b, mods="shift")
    ui.wait_until(lambda: len((ui.store.get("selection") or {}).get("items", [])) == 2, 60, "an edge")
    ui.click_text("Brush", within=ui.item("annotateBar"))
    a, b, pa, pb = I.two_parts(ui)
    ui.stroke("viewport", [(16, 3), (32, 8), (48, 10)], fx=a[0], fy=a[1], mods="shift")
    ui.wait_until(lambda: [x for x in (ui.store.get("selection") or {}).get("items", []) if x["kind"] == "region"], 60, "a painted region")
    ui.settle(1200)
    quiet(ui)
    snap(ui, "annotate")
    ui.click_text("Clear", within=ui.item("annotateBar"))
    ui.settle(300)
    ui.click_text("Select")
    ui.settle(500)
    # colours and materials
    ui.run_js("Store.setStage('shape')")
    ui.settle(500)
    ui.scroll_to(ui.item("appearance"), 0.1)
    ui.click(ui.item("look-design"), 0.5, 0.1)
    ui.settle(300)
    ui.click(ui.item("swatch-#3f7fbf"))
    ui.wait_until(lambda: (ui.js("Store.appearance.color") or "") == "#3f7fbf", 10, "the design colour")
    ui.click(ui.item("materialPick"))
    ui.settle(300)
    ui.click_text("PETG")
    ui.wait_until(lambda: ui.js("Store.appearance.material") == "PETG", 10, "the material")
    ui.wait_until(lambda: ui.js("Store.activity.length") == 0, 180, "the checks to finish")
    wait_job(ui, pid)
    for _ in range(3):
        ui.settle(300)
        ui.click(ui.item("look-lid"), 0.5, 0.1)
        try:
            ui.wait_until(lambda: ui.item("appearance").property("open") == "lid", 4, "the lid's row to open")
            break
        except Exception:
            continue
    ui.settle(300)
    ui.click(ui.item("swatch-#e08a2c"))
    ui.wait_until(lambda: ((ui.js("Store.appearance.parts") or {}).get("lid") or {}).get("color") == "#e08a2c", 10, "the lid's colour")
    wait_job(ui, pid)
    ui.settle(1500)
    quiet(ui)
    snap(ui, "appearance")


def scene_model(ui):
    """A 3D model (not for printing) in Review, and its release."""
    from _lib import make
    start_home(ui)
    pid = make(ui, "vase", "Fluted vase", purpose="model")
    ui.settle(2000)
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "Review")
    ui.settle(1200)
    back(ui, 1.4)
    quiet(ui)
    snap(ui, "model-prove")
    ui.click("stage-release")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "Make")
    ui.settle(800)
    for c in ui.find_all(name="ackCheck"):
        ui.click(c)
    btn = ui.item(text="Approve and release r%02d" % ui.api("/projects/" + pid)["project"]["head"])
    ui.wait_until(lambda: btn.property("enabled") is True, 5, "Approve to be enabled")
    ui.click(btn)
    ui.wait_until(lambda: ui.api("/projects/" + pid)["approval"]["state"] == "approved", 120, "the release")
    ui.settle(3500)
    quiet(ui)
    snap(ui, "model-release")


def scene_assembly(ui):
    """An assembly with its joint slider, and its exploded view."""
    from _lib import make, printing_on
    start_home(ui)
    printing_on(ui)
    make(ui, "hinged_box", "Hinged keepsake box", purpose="print")
    ui.settle(2000)
    away(ui)
    ui.key("E")
    ui.wait_until(lambda: ui.js("Ws.tool") == "assembly", 3, "Assembly")
    bar = ui.item("asmBar")
    ui.click_text("Assembled", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "assembled", 3, "assembled mode")
    j = ui.js("Store.assembly.joints")[0]
    slider = [h for h in ui.find_all(text=j["label"], within=bar) if h.property("from") is not None][0]
    beam = [b for b in ui.find_all(within=slider) if b.metaObject().className().startswith("Beam")][0]
    ui.click(beam, 0.45, 0.5)
    ui.wait_until(lambda: abs((ui.store.get("pose") or {}).get(j["id"], 0)) > 1, 3, "the joint to move")
    ui.settle(1500)
    away(ui)
    ui.key("F")
    ui.settle(1200)
    back(ui, 1.5)
    quiet(ui)
    snap(ui, "assembly")
    ui.click_text("Exploded", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "exploded", 3, "exploded mode")
    ui.settle(1800)
    away(ui)
    ui.key("F")
    ui.settle(1200)
    back(ui, 1.7)
    quiet(ui)
    snap(ui, "assembly-exploded")


def scene_history(ui):
    """The revision timeline, and several plates in Review."""
    from _lib import has_slicer, head, make, printing_on, wait_job
    start_home(ui)
    printing_on(ui)
    pid = make(ui, "enclosure", "Sensor case", purpose="print")
    spec = [p for p in ui.api("/projects/" + pid)["recipe"]["params"] if p["key"] == "wall"][0]
    for dv, note in ((0.4, "Thicker wall for the screws"), (0.8, "Stiffer still")):
        ui.api("/projects/" + pid + "/commit", {"values": {"wall": spec["default"] + dv}, "provenance": {}, "note": note, "origin": "user"})
        wait_job(ui, pid)
    from _lib import open_project
    open_project(ui, pid)
    ui.settle(1500)
    away(ui)
    ui.key("T")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is True, 3, "the timeline")
    ui.settle(500)
    ui.click(ui.item("timelineTrack"), 0.02, 0.5)
    ui.wait_until(lambda: (ui.store.get("scrub") or {}).get("rev") is not None, 20, "an earlier revision shown")
    ui.settle(1500)
    quiet(ui)
    snap(ui, "app-timeline")
    ui.click_text("Back to head")
    ui.settle(600)
    away(ui)
    ui.key("T")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is False, 5, "the timeline to close")
    if has_slicer(ui):
        make(ui, "hinged_box", "Wide keepsake box", {"inner_w": 110, "inner_d": 80}, purpose="print")
        ui.click("stage-prove")
        ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "Review")
        seg = ui.item("provePlates")
        ui.scroll_to(seg, 0.35)
        ui.click_text("Plate 2", within=seg)
        ui.wait_until(lambda: ui.js("Store.plateShown") == 2, 3, "plate 2")
        ui.settle(1500)
        quiet(ui)
        snap(ui, "plates")


def scene_sketch(ui):
    """The sketch pad: a rectangle, a circle and a stated dimension."""
    start_home(ui)
    ui.click("startSketch")
    pad = ui.wait_until(lambda: ui.find("sketchPad"), 10, "the sketch pad")
    ui.settle(400)
    ui.click("sketchTool-rect")
    ui.drag(pad, (256, -144), fx=0.3, fy=0.66, steps=10)                     # 80 x 45 mm at 3.2 px/mm
    ui.settle(300)
    try:
        ui.click("sketchTool-circle")
        ui.drag(pad, (32, 0), fx=0.3 + 128 / pad.width(), fy=0.66 - 72 / pad.height(), steps=8)
        ui.settle(300)
    except Exception as e:
        print("SKIP circle", str(e)[:120], flush=True)
    ui.click("sketchTool-dim")
    ui.drag(pad, (256, 0), fx=0.3, fy=0.8, steps=10)
    ui.wait_until(lambda: ui.exists("sketchDimValue"), 3, "the dimension's value field")
    ui.type("70")
    ui.key("Return")
    ui.settle(600)
    ui.hover(pad, 0.85, 0.2)
    ui.settle(300)
    snap(ui, "sketch", "sheetCard")


RUN_LINES = ("Set outside the file for this run", "for this run by", "-dev", "/bin/python", "form-ui-", "/var/folders", "/tmp/")


def scene_providers(ui):
    """Add a provider by its address, and the model menu searching its models. The provider is a stand-in gateway on
    this computer (tests/fixtures/fake_provider.py) that lists 240 models of invented vendors; no model is called."""
    import providers as P
    sys.path.insert(0, str(ROOT))
    from tests.fixtures.fake_provider import FakeProvider
    srv = FakeProvider(models=P.models(), key="sk-gateway-test", strict=True, script=[{"text": "Hello."}])
    try:
        os.environ["PYTHONPATH"] = str(ROOT)
        start_home(ui)
        ui.run_js('Store.openSettings("chat")')
        ui.click(ui.item("addProvider", timeout=10))
        ui.fill("providerUrl", srv.root)
        ui.fill("providerKey", "sk-gateway-test")
        ui.fill("providerName", "Studio gateway")
        ui.click("providerCheck")
        ui.wait_until(lambda: ui.sees("Connected: OpenAI-compatible"), 30, "the detection")
        ui.scroll_to(ui.item("providerCheck"), 0.8)
        ui.settle(500)
        hide(ui, *RUN_LINES)
        snap(ui, "provider-added", "sheetCard")
        ui.click("providerSave")
        ui.wait_until(lambda: ui.find(name="providerRow") is not None, 20, "the saved provider")
        ui.wait_until(lambda: ui.js("(Store.agentInfo('custom-studio-gateway') || {}).available === true"), 20, "the agent")
        ui.key("Escape")
        ui.settle(400)
        ui.run_js("Store.toasts = []")
        ui.click("modelChip")
        ui.expect("Your providers", timeout=5)
        ui.click(ui.item("pickAgent_custom-studio-gateway", timeout=5))
        ui.wait_until(lambda: ui.store.get("chatAgent") == "custom-studio-gateway", 5, "the provider to be chosen")
        ui.click("modelSearch")
        ui.type("vision")
        ui.wait_until(lambda: ui.find(name="modelRow_acme/vision-1") is not None, 5, "the search to narrow the list")
        ui.settle(600)
        snap(ui, "model-picker")
        ui.key("Escape")
    finally:
        srv.close()


# ───────────────────────────────────────── outside: run the scenes, write docs/images ─────────────────────────────────────────
# picture in docs/images -> (scene, shot, crop to the .box beside the shot)
PICTURES = {
    "app-chat": ("chat", "app-chat", False), "app-palette": ("chat", "app-palette", True), "prove": ("chat", "prove", False),
    "app-variants": ("chat", "app-variants", False), "share-card": ("chat", "share-card", False),
    "settings-general": ("settings", "settings-general", True), "settings-agents": ("settings", "settings-agents", True),
    "settings-printing": ("settings", "settings-printing", True),
    "concepts": ("concepts", "concepts", False), "measure-this": ("measure", "measure-this", False),
    "start-photo": ("photo", "start-photo", False),
    "provider-added": ("providers", "provider-added", True), "model-picker": ("providers", "model-picker", False),
    "model-prove": ("model", "model-prove", False), "model-release": ("model", "model-release", False),
    "assembly": ("assembly", "assembly", False), "assembly-exploded": ("assembly", "assembly-exploded", False),
    "app-timeline": ("history", "app-timeline", False), "plates": ("history", "plates", False), "sketch": ("sketch", "sketch", True),
    "app-thickness": ("maps", "app-thickness", False), "app-overhang": ("maps", "app-overhang", False),
    "annotate": ("inspect", "annotate", False), "appearance": ("inspect", "appearance", False),
}


def run_scene(name: str, out: Path) -> int:
    sys.path.insert(0, str(ROOT / "tests"))
    os.environ["FORM_UI_TESTS"] = "1"
    os.environ["FORM_UI_SHOTS"] = str(out)
    import test_ui_journeys as t
    rc, text = t.run_journey(f"{Path(__file__).resolve()}::scene_{name}", size=SIZE, timeout=1500, env_extra={
        "FORM_WINDOW_GHOST": "1", "FORM_UITEST_AGENT": str(Path(__file__).with_name("docs_agent.py")), "FORM_UITEST_LAX": "1",
        "FORM_UITEST_WATCHDOG": "1400", **({"FORM_UITEST_API_AGENTS": "1"} if name in ("providers", "settings") else {})})
    print("\n".join(ln for ln in text.splitlines() if ln.startswith(("SHOT", "SKIP", "PASS", "FAIL")) or "Error" in ln)[-3000:])
    return rc


def write_picture(name: str, src: Path, crop: bool, width: int = 2400) -> None:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    box = src.with_suffix(".box")
    if crop and box.exists():
        k = im.size[0] / int(SIZE.split("x")[0])
        x, y, w, h = json.loads(box.read_text())
        im = im.crop((max(0, round(x * k)), max(0, round(y * k)), min(im.size[0], round((x + w) * k)), min(im.size[1], round((y + h) * k))))
    if im.size[0] > width:
        im = im.resize((width, round(width * im.size[1] / im.size[0])), Image.LANCZOS)
    im.save(ROOT / "docs" / "images" / f"{name}.webp", quality=84, method=6)
    print("docs/images/%s.webp %s" % (name, im.size))


def main() -> int:
    args = sys.argv[1:]
    out = ROOT / ".dev" / "docs-shots"
    if "--keep" in args:
        i = args.index("--keep")
        out = Path(args[i + 1]).resolve()
        del args[i:i + 2]
    write, run = "--no-write" not in args, "--write-only" not in args
    args = [a for a in args if a not in ("--no-write", "--write-only")]
    out.mkdir(parents=True, exist_ok=True)
    scenes = args or sorted({s for s, _, _ in PICTURES.values()})
    for s in scenes if run else []:
        print("== scene", s, flush=True)
        run_scene(s, out)
    if write:
        for name, (scene, shot, crop) in PICTURES.items():
            if scene in scenes and (out / f"{shot}.png").exists():
                write_picture(name, out / f"{shot}.png", crop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
