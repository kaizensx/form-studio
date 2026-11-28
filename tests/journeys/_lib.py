"""Shared steps for the UI journeys (tests/journeys/*.py). Setup goes through the engine API; the thing under
test goes through the window."""
import sys


def wait_job(ui, pid, timeout=300):
    """Until the project's pipeline is current (solid, exports, checks; slice when a slicer is installed and slicing is on)."""
    def done():
        d = ui.api("/projects/" + pid)
        return isinstance(d, dict) and d.get("status") and not d.get("job") and all(
            v["state"] in ("current", "blocked", "failed", "off") or v.get("unavailable") for v in d["status"].values())
    try:
        ui.wait_until(done, timeout, f"the pipeline of {pid}")
    except Exception as e:                 # say where it stopped: a timeout alone explains nothing on a remote runner
        d = ui.api("/projects/" + pid)
        st = {k: {x: v.get(x) for x in ("state", "blocked", "unavailable", "error") if v.get(x)} for k, v in (d.get("status") or {}).items()} if isinstance(d, dict) else d
        jobs = getattr(ui.studio, "jobs", {})
        last = [{"state": j.get("state"), "steps": [(s.get("node"), s.get("state"), str(s.get("error"))[:300]) for s in j.get("steps", [])]} for j in list(jobs.values())[-2:]]
        err = {k: d.get(k) for k in ("error", "hint", "detail") if k in d} if isinstance(d, dict) else {}
        raise type(e)(f"{e}; job={d.get('job') if isinstance(d, dict) else None} status={st} answer={err or str(d)[:300]} "
                      f"last jobs={last}") from None


def make(ui, recipe, name, values=None, open=True, purpose=None):
    """Create a project from a recipe through the engine, wait for its pipeline, open it in the window."""
    r = ui.api("/projects", {"name": name, "recipe": recipe, "brief": "", "values": values, "purpose": purpose})
    pid = r["id"]
    wait_job(ui, pid)
    if open:
        open_project(ui, pid)
    return pid


def printing_on(ui):
    """Turn the 3D printing capability on (Settings › Set up for), as someone who prints would; nothing is installed."""
    ui.api("/capabilities", {"id": "print", "on": True})
    ui.run_js("Store.reloadStudio(); Store.loadCaps()")
    ui.wait_until(lambda: ui.js("Store.printOn") is True, 10, "printing to be on")


# A phone dock for the hallway, built from the dock recipe with the values the journeys measure against
DOCK = {"device_width": 71.5, "device_thickness": 7.8, "device_height": 147.0, "device_mass": 170.0, "clearance": 0.3,
        "plug_width": 13.0, "plug_thickness": 7.0, "cable_diameter": 4.5, "lean": 15.0, "floor": 7.0, "side_wall": 7.0,
        "lip": 6.0, "front_height": 18.0, "back_height": 36.0, "depth": 92.0, "corner_r": 12.0, "edge_r": 2.5,
        "lead_in": 0.8, "relief_width": 30.0, "relief_depth": 7.0}


def phone_dock(ui, open=True):
    """A design made for 3D printing (its fit, checks and slice), from a recipe: printing is turned on first."""
    printing_on(ui)
    return make(ui, "dock", "Hallway phone dock", DOCK, open=open, purpose="print")


def open_project(ui, pid):
    # from another design the old model stays in Store.view until the new one arrives: drop it first (Home does the
    # same), so "loaded" below means this design's model and not the previous one's
    ui.run_js("if (Store.pid !== %r) Store.view = null; Store.reloadStudio().then(function () { Store.open(%r) })" % (pid, pid))
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pid, 60, f"{pid} to open")
    ui.wait_until(lambda: ui.js("!!Store.view && !!Store.viewer && !!Store.data && Store.data.project.id === %r" % pid), 60,
                  "the model to load")
    ui.idle(300)
    ui.settle(700)


def sheet(ui):
    s = ui.store.get("sheet")
    return s["kind"] if s else None


def open_sheet_wait(ui, kind):
    ui.wait_until(lambda: sheet(ui) == kind, 6, f"the {kind} sheet")
    ui.settle(300)


def close_sheet_esc(ui):
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close on Esc")
    ui.settle(200)


def head(ui, pid=None):
    return ui.api("/projects/" + (pid or ui.store.get("pid")))["project"]["head"]


def fold(ui, title):
    """Open or close a folding section of the inspector by clicking its header."""
    f = ui.item(text=title)
    ui.scroll_to(f, 0.0)
    ui.click(f, 0.5, 20.0 / max(40.0, f.height()))
    ui.settle(250)


def toasts_gone(ui):
    """Toasts sit over the bottom right corner and wait while the pointer rests on them: move away, let them leave."""
    ui.hover("viewport", 0.5, 0.3)
    ui.wait_until(lambda: ui.store.get("toasts") == [], 15, "the toasts to leave")
    ui.settle(200)


def has_slicer(ui):
    return bool(ui.js("Store.slicer.available"))


def click_stage(ui):
    """Put the keyboard on the part: a click on the empty room at the top left of the stage, right of the tool dock.
    (The corner of the window is not the stage: the conversation column may stand there.)"""
    vp = ui.item("viewport")
    ui.click("viewport", (float(vp.property("insetLeft")) + 44) / vp.width(), (float(vp.property("insetTop")) + 2) / vp.height())


def goto(ui, sid):
    """Go where a design's work is done. The four modes are tabs (shape: Design, prove: Check, release: Make,
    document: Document). What used to be two more stages is reached the way a person reaches it now: "brief" is the
    Overview, opened from the design capsule; "fit" is the Fit study, a row of Check."""
    if sid == "brief":
        if ui.js("Store.overview") is not True:
            ui.click("designCapsule")
        ui.wait_until(lambda: ui.js("Store.overview") is True, 3, "the Overview")
        return
    if sid == "fit":
        goto(ui, "prove")
        ui.click("bench-fit", 0.3, 0.5)
    else:
        ui.click("stage-" + sid)
    ui.wait_until(lambda: ui.store.get("stage") == sid and ui.js("Store.overview") is False, 3, sid)


def plate_toggle(ui):
    """The build plate of a design made for printing, shown or hidden from the shading chip under the view cube."""
    ui.settle(350)                                     # a menu that has just closed is gone before the chip is pressed again
    ui.click("shadeChip")
    ui.wait_until(lambda: ui.exists("showPlate"), 3, "the chip's menu")
    ui.settle(200)
    ui.click("showPlate")
    ui.wait_until(lambda: not ui.exists("showPlate"), 3, "the menu to close")


# the four modes answer to Ctrl+1..4 (⌃ on macOS, where ⌘1..9 switch the document tabs: Theme.modeMod, tabMod)
MODE_KEY = "Meta" if sys.platform == "darwin" else "Ctrl"
TAB_KEY = "Ctrl" if sys.platform == "darwin" else "Alt"


def mode_key(n):
    """The key chord that switches to mode n (1 Design, 2 Check, 3 Make, 4 Document)."""
    return f"{MODE_KEY}+{n}"


# the dock holds four tools everywhere; the tools of the mode stand in the ribbon at the head of the stage
# (ToolRibbon.qml, ToolSet.js), or under the four in the dock when the ribbon is hidden
DOCK_MODE = {"Analyze": ("prove", "analyze"), "History": ("prove", "history"), "Assembly": ("prove", "assembly"),
             "Simulate the print": ("release", "slice"), "Photo render": ("release", "render"),
             "Hide overall dimensions": ("document", "dims"), "Show overall dimensions": ("document", "dims")}
# the dock's own buttons for the same tools, when the ribbon is hidden
RAIL = {"sketch": "railSketch", "extrude": "railExtrude", "cut": "railCut", "revolve": "railRevolve", "fillet": "railRound",
        "chamfer": "railChamfer", "hole": "railHole", "pattern": "railPattern", "shell": "railShell", "part": "railPart",
        "analyze": "railAnalyze", "mass": "railMass", "assembly": "railAssembly", "history": "railHistory",
        "slice": "railSimulate", "plates": "railPlates", "game": "railGame", "views": "railViews", "dims": "railDims",
        "select": "railSelect", "measure": "railMeasure", "section": "railSection", "annotate": "railAnnotate"}


def ribbon_on(ui):
    return ui.exists("toolRibbon") and ui._shown(ui.item("toolRibbon"))


def tool(ui, tid):
    """Click a tool of the mode in front by its id (ToolSet.js): in the ribbon, behind its More when the stage is
    narrow, or in the dock when the ribbon is hidden."""
    if ribbon_on(ui):
        name = "ribbon-" + tid
        if ui.exists(name) and ui._shown(ui.item(name)):
            # the pointer arrives first, as a hand does: a mode's tooltip just above the band is gone by the press
            ui.hover(name)
            ui.settle(200)
            ui.click(name)
            return
        ui.hover("ribbonMore")
        ui.settle(200)
        ui.click("ribbonMore")
        ui.wait_until(lambda: ui.exists("ribbonMore-" + tid), 3, f"{tid} in More")
        ui.settle(150)
        ui.click("ribbonMore-" + tid)
        return
    ui.click(RAIL.get(tid, tid))


def tool_item(ui, tid):
    """The button of a tool, where it stands now: the ribbon's, or the dock's."""
    if ribbon_on(ui) and ui.exists("ribbon-" + tid):
        return ui.item("ribbon-" + tid)
    return ui.item(RAIL.get(tid, tid))


def dock(ui, label):
    """Click a tool of the mode by its label, as a person does: in the mode that holds it, then back to the mode the
    journey was in (a tool stays active, a toggle stays set, whatever the mode; a sheet stays open)."""
    was, (mode, tid) = ui.store.get("stage"), DOCK_MODE[label]
    there = ui.js("Store.mode") != mode
    if there:
        ui.click("stage-" + mode)
        ui.wait_until(lambda: ui.js("Store.mode") == mode, 3, mode)
        ui.settle(260)
    tool(ui, tid)
    if there and not ui.store.get("sheet") and not ui.js("!!Store.layers"):      # a sheet or the print simulation is where it leads
        ui.settle(120)
        ui.click("stage-" + ("shape" if was == "brief" else "prove" if was == "fit" else was))
        ui.settle(260)


