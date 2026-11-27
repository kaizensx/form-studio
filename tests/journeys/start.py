"""How a design starts, on Home: a blank design with no agent; a photo dropped in reaches the agent; a sketch drawn on
the pad reaches it as structured geometry; the workspace opens at once while it designs; concepts side by side and a
pick; a guided measurement updates the design. The stand-in agent (tests/fixtures/fake_agent.py) plays the agent: it
reports what it received, builds three tiny concepts, and asks for a measurement through the same files as the real
MCP tools. No model is called."""
import json
import shutil
from pathlib import Path

from _lib import make, printing_on, wait_job

DATA = "fresh"
ROOT = Path(__file__).resolve().parents[2]


def home(ui):
    if ui.store.get("screen") != "home" or ui.js("Store.chatItems.length") > 0:
        ui.run_js("Store.startNew()")             # a new design: Home with an empty composer and a fresh conversation
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home and its composer")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(500)


def conv_events(ui):
    cid = ui.store.get("convId")
    return ui.api("/conversations/" + cid)["items"] if cid else []


def write(ui, text):
    ui.settle(400)                         # the shelf above the words has finished arriving
    ui.click("startText")
    ui.wait_until(lambda: ui.item("startText").property("activeFocus"), 3, "the composer to take the keyboard")
    ui.type(text)


def reply(ui, timeout=60):
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and any(e.get("t") == "text" for e in conv_events(ui)), timeout, "the agent's reply")
    return "\n".join(e["text"] for e in conv_events(ui) if e.get("t") == "text")


def journey_blank(ui):
    home(ui)
    ui.shot("start-home-empty")
    # printing is opt-in: a new person's next design is a 3D model and Home says nothing about printers
    ui.eq(ui.js("Store.newPurposeEffective"), "model", "a new design is a 3D model")
    # "Make it for" always offers Anything and Game asset; My printer only once printing is on
    ui.check(ui.sees("Anything", "startPurpose") and ui.sees("Game asset", "startPurpose"), "Make it for: Anything / Game asset")
    ui.check(not ui.sees("My printer", "startPurpose"), "no print choice while printing is off")
    ui.check(not ui.sees("not for printing", "topBar") and ui.find(name="printerChip") is None, "no printer talk in the top bar")
    # the agent and model are chosen in the composer, beside Design it; the printer right under it
    ui.check(ui.exists("startModel") and ui.find(name="startModel", within=ui.item("startComposer")) is not None, "the agent and model chip is in the composer")
    ui.check(not ui.exists("startPrinter"), "no printer chip for a 3D model")
    n_before = len(ui.api("/studio")["projects"])
    ui.click("startBlank")
    # Start blank is really blank: an empty plate, the conversation open, no design made
    ui.wait_until(lambda: ui.store.get("screen") == "designing" and ui.js("Store.blankCanvas"), 10, "the blank canvas")
    ui.wait_until(lambda: ui.exists("blankCanvas"), 5, "the blank canvas's ways to start")
    ui.eq(ui.store.get("pid"), "", "no design is open")
    ui.eq(len(ui.api("/studio")["projects"]), n_before, "no design was created")
    ui.settle(400)
    ui.shot("start-blank-canvas")
    # a block to shape with sliders, no agent
    ui.click("blankBlock")
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid"), 120, "the block to open in the workspace")
    pid = ui.store.get("pid")
    p = ui.api("/projects/" + pid)["project"]
    ui.eq(p.get("purpose"), "model", "the blank design is just a 3D model")
    ui.eq(ui.api("/projects/" + pid)["status"]["slice"]["off"]["why"], "purpose", "so it is not sliced")
    ui.eq(ui.store.get("chatBusy"), False, "no agent was started")
    wait_job(ui, pid)
    ui.settle(600)
    ui.shot("start-blank-workspace")



def journey_photo_reaches_the_agent(ui):
    home(ui)
    printing_on(ui)                                  # someone who prints: Home offers the purpose
    ui.click_text("My printer", within=ui.item("startPurpose"))
    ui.wait_until(lambda: ui.js("Store.newPurposeEffective") == "print", 5, "the purpose back to printing")
    photo = Path(ui.files) / "desk-clip.png"
    shutil.copyfile(ROOT / "form" / "app" / "assets" / "icon-256.png", photo)
    ui.pick_file(photo)
    ui.click("startAdd")
    shelf = ui.wait_until(lambda: ui.find_all(name="startAttachment"), 20, "the photo on the composer")
    ui.eq(len(shelf), 1)
    ui.eq(ui.js("Store.chatAttach[0].kind"), "image", "attached as an image")
    write(ui, "A clip like the one in my photo")
    ui.shot("start-photo-attached")
    ui.key("Return")
    # the workspace opens at once, in its "being designed" state, before any design exists
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the workspace to open at once")
    ui.check(ui.exists("designingView"), "the being-designed view")
    text = reply(ui)
    ui.check("I received: desk-clip.png (image)" in text, f"the agent received the photo: {text!r}")
    ui.check("Purpose: for 3D printing" in text, f"and the purpose: {text!r}")
    user = [e for e in conv_events(ui) if e.get("t") == "user"][-1]
    ui.eq([a["kind"] for a in user.get("attachments", [])], ["image"], "the message carries the photo")
    ui.settle(400)
    ui.shot("start-designing-done")
    ui.click("designingHome")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "back on Home")


def journey_sketch_is_structured(ui):
    home(ui)
    ui.click("startSketch")
    pad = ui.wait_until(lambda: ui.find("sketchPad"), 10, "the sketch pad")
    ui.settle(300)
    ui.click("sketchTool-rect")
    ui.drag(pad, (192, -128), fx=0.3, fy=0.7, steps=10)                      # 60 × 40 mm at 3.2 px/mm
    ui.wait_until(lambda: ui.exists(text="Rectangle", exact=False, within=ui.item("sketchSheet")) and not ui.exists(text="Rectangle 0", exact=False), 3, "the rectangle in the list of shapes")
    ui.click("sketchTool-dim")
    ui.drag(pad, (192, 0), fx=0.3, fy=0.85, steps=10)
    ui.wait_until(lambda: ui.exists("sketchDimValue"), 3, "the dimension's value field")
    ui.type("62")
    ui.key("Return")
    ui.settle(300)
    ui.shot("start-sketch")
    ui.click("sketchDone")
    ui.wait_until(lambda: ui.js("Store.chatAttach.filter(function (a) { return a.kind === 'sketch' }).length") == 1, 20, "the sketch on the composer")
    ui.wait_until(lambda: ui.js("Store.chatAttach.filter(function (a) { return a.kind === 'image' }).length") == 1, 20, "and its picture")
    sk = ui.js("Store.chatAttach.filter(function (a) { return a.kind === 'sketch' })[0]")
    data = ui.api("/conversations/" + ui.store.get("convId") + "/file/" + sk["file"])
    ui.eq(data["units"], "mm")
    kinds = [p["type"] for p in data["primitives"]]
    ui.eq(kinds, ["rect", "dim"], "the shapes, in order")
    r = data["primitives"][0]
    w, h = abs(r["b"][0] - r["a"][0]), abs(r["b"][1] - r["a"][1])
    ui.check(50 <= w <= 65 and 30 <= h <= 45 and w % 5 == 0 and h % 5 == 0, f"the rectangle in millimetres, snapped to the 5 mm grid: {w} × {h}")
    ui.eq(data["primitives"][1]["value"], 62, "the stated dimension")
    write(ui, "Make this from my sketch")
    ui.key("Return")
    text = reply(ui)
    ui.check("Sketch: 2 primitives" in text, f"the agent read the structured sketch: {text!r}")
    # the way back is offered once the run has ended on the stage: a click before that lands on nothing
    ui.wait_until(lambda: ui._shown(ui.item("designingHome")), 10, "Back to Home on the stage")
    ui.settle(400)
    ui.click("designingHome")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "back on Home")


def journey_concepts_pick(ui):
    home(ui)
    write(ui, "concepts for a phone stand")
    ui.key("Return")
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the workspace to open at once")
    ui.settle(800)
    ui.shot("start-designing")
    ui.wait_until(lambda: ui.exists("conceptsSheet"), 240, "the concepts to open side by side")
    cards = ui.wait_until(lambda: len(ui.find_all(name="conceptCard")) == 3 and ui.find_all(name="conceptCard"), 20, "three concept cards")
    ui.settle(2500)
    ui.shot("start-concepts")
    gid = ui.js("Store.sheet.props.group")
    board = ui.api("/concepts/" + gid)
    ui.eq([m["letter"] for m in board["members"]], ["A", "B", "C"])
    ui.check(all(m.get("numbers", {}).get("size_mm") for m in board["members"]), "each concept has computed sizes")
    pick = board["members"][1]["project"]
    ui.click(ui.find_all(name="conceptPick", within=cards[1])[0])
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pick, 60, "the picked concept to open in the workspace")
    after = ui.api("/concepts/" + gid)
    ui.eq(after["state"], "picked")
    ids = [p["id"] for p in ui.api("/studio")["projects"]]
    ui.check(pick in ids and not any(m["project"] in ids for m in board["members"] if m["project"] != pick), "the others went to the trash")
    ui.settle(1500)
    ui.shot("start-concept-picked")


def journey_measure_updates_the_design(ui):
    pid = make(ui, "storage_box", "Drawer box")
    before = ui.api("/projects/" + pid)["project"]
    ui.click("composer")
    ui.type("measure the drawer please")
    ui.key("Return")
    card = ui.wait_until(lambda: ui.find("measureCard"), 30, "the measurement card")
    ask = ui.wait_until(lambda: ui.store.get("chatAsking"), 10, "the open question")
    ui.settle(500)
    ui.shot("start-measure-card")
    ui.click(ui.item("measureValue", within=card))
    ui.type("42.5")
    ui.click("measureSend")
    text = reply(ui)
    ui.check("You measured: 42.5 mm with calipers" in text, f"the agent got the measurement: {text!r}")
    p = ui.api("/projects/" + pid)["project"]
    ui.eq(p["head"], before["head"] + 1, "a new revision")
    head = [r for r in p["revisions"] if r["n"] == p["head"]][0]
    param = [e for e in conv_events(ui) if e.get("t") == "ask"][-1]["param"]
    ui.eq(head["values"][param], 42.5, "with the measured value")
    ui.eq(head["provenance"][param]["source"], "measured", "recorded as measured")
    ui.wait_until(lambda: ui.js("Store.project.head") == p["head"], 20, "the design on screen to update")
    ui.settle(800)
    ui.shot("start-measure-answered")
    ui.no_warnings()


def _group(ui, name):
    """An open concept group with two tiny concepts, made the way propose_concepts makes them."""
    import importlib.util
    from form import concepts
    spec = importlib.util.spec_from_file_location("fake_agent", ROOT / "tests" / "fixtures" / "fake_agent.py")
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    tiny = [{"title": t, "rationale": why, "source": fa._source(t, expr)} for t, (expr, why) in list(fa.TINY.items())[:2]]
    g = concepts.create(ui.studio, name, tiny)
    ui.run_js("Store.loadConcepts()")
    return g


def journey_concepts_dismiss(ui):
    home(ui)
    # a new group opens its sheet on Home; Not now closes it and the group waits on Home
    g = _group(ui, "Shelf peg")
    ui.wait_until(lambda: ui.exists("conceptsSheet") and len(ui.find_all(name="conceptCard")) == 2, 20, "the concepts sheet")
    ui.settle(1500)
    ui.shot("start-concepts-sheet-dismiss")
    ui.click("conceptsNotNow")
    ui.wait_until(lambda: not ui.exists("conceptsSheet"), 4, "Not now to close the sheet")
    ui.eq(ui.api("/concepts/" + g["id"])["state"], "open")
    # Home: close the waiting group from its card, keeping both concepts as designs
    card = ui.wait_until(lambda: next((c for c in ui.find_all(name="conceptGroup") if ui.sees("Shelf peg", within=c)), None), 10, "the group's card")
    ui.scroll_to(card)
    ui.right_click(card, 0.3, 0.5)
    ui.wait_until(lambda: ui.sees("Keep all as designs"), 4, "the group's menu")
    ui.key("Escape")
    ui.wait_until(lambda: not ui.sees("Keep all as designs"), 4, "the menu to close")
    ui.hover(card, 0.5, 0.5)
    ui.click(ui.item("conceptGroupClose", within=card))
    ui.wait_until(lambda: ui.sees("Discard all"), 4, "the close button's menu")
    ui.settle(250)
    ui.shot("start-concepts-close-menu")
    ui.click_text("Keep all as designs")
    ui.wait_until(lambda: ui.api("/concepts/" + g["id"])["state"] == "dismissed", 10, "the group to close")
    ids = [p["id"] for p in ui.api("/studio")["projects"]]
    ui.check(all(m["project"] in ids for m in g["members"]), "both concepts are designs now")
    ui.wait_until(lambda: not any(ui.sees("Shelf peg", within=c) for c in ui.find_all(name="conceptGroup")), 10, "the card to leave Home")
    # the sheet: Discard all moves them to the trash
    g2 = _group(ui, "Cup hook")
    ui.wait_until(lambda: ui.exists("conceptsDiscardAll") and len(ui.find_all(name="conceptCard")) == 2, 20, "the second group's sheet")
    ui.settle(800)
    ui.click("conceptsDiscardAll")
    ui.wait_until(lambda: ui.api("/concepts/" + g2["id"])["state"] == "dismissed", 10, "Discard all")
    ids = [p["id"] for p in ui.api("/studio")["projects"]]
    ui.check(not any(m["project"] in ids for m in g2["members"]), "both concepts went to the trash")
    ui.wait_until(lambda: not ui.exists("conceptsSheet"), 4, "the sheet to close")
    ui.settle(600)
    ui.shot("start-concepts-dismissed")
