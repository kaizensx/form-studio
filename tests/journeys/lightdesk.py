"""Lightdesk, the workspace as one room: the 3D view edge to edge and every control a pane of glass over it.

What is checked here is what the layout promises: the panes are where they belong and never over each other; the
conversation is one bar under the part whose numbered suggestions answer to the keys 1 to 4, and it opens upward
into the transcript and folds back; while a build plays the cue (the lower third) counts the real steps, the Program
listing ticks the lines that are built and marks the one being built, and the tools step back; the size line under
the part is the one computed from the solid. Pictures of each moment are kept for the design review
(FORM_UI_SHOTS)."""
from _lib import make

DATA = "fresh"


def _rect(ui, name):
    from PySide6.QtCore import QPointF
    it = ui.item(name)
    p = it.mapToScene(QPointF(0, 0))
    return p.x(), p.y(), it.width(), it.height()


def _apart(a, b):
    return a[0] + a[2] <= b[0] + 1 or b[0] + b[2] <= a[0] + 1 or a[1] + a[3] <= b[1] + 1 or b[1] + b[3] <= a[1] + 1


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.settle(900)
    ui.shot("lightdesk-home")
    # the design opens as a new build and plays: the cue counts the real steps, the program runs, the tools step back
    pid = make(ui, "enclosure", "Sensor case", open=False)
    ui.run_js("Store._buildNext = Date.now(); Store.view = null; Store.reloadStudio().then(function () { Store.open(%r) })" % pid)
    ui.wait_until(lambda: ui.store.get("screen") == "work", 30, "the design to open")
    feats = None
    if ui.js("Theme.reduced"):                         # Reduce Motion: the design is simply there, no build-up plays
        ui.wait_until(lambda: ui.js("!!Store.view && !!Store.viewer && !Store.viewer.revealing") is True, 40, "the design to be drawn")
        ui.settle(2200)                                # whatever the cue said about it has left
    else:
        ui.wait_until(lambda: ui.js("Store.buildOf") > 2, 30, "the build-up to start")
        of = ui.js("Store.buildOf")
        half = max(2, of // 2)
        ui.wait_until(lambda: ui.js("Store.buildAt") >= half, 30, "the build to be half-way")
        ui.wait(160)
        at = ui.js("Store.buildAt")
        shot_at = at
        ui.shot("lightdesk-build")
        if ui.js("Store.buildAt") == at and at < of:        # still on the step that was read
            ui.check(ui.exists("buildCaption"), "the cue is up while the build plays")
            ui.eq(ui.item("buildLedgerCount").property("text"), f"{at} of {of}", "the cue counts the step the viewport is on")
            built, now = ui.js("[Store.builtIds.slice(), Store.revealing.slice()]")
            ui.check(len(built) >= 1 and len(now) >= 1 and not set(built) & set(now), f"built lines and the line being built are different lines: {built} {now}")
            feats = ui.js("Store.recipe.features.map(function (f) { return f.id })")
            ui.check(all(feats.index(b) < feats.index(now[0]) for b in built), f"what is built comes before what is being built: {built} {now}")
            ui.check(ui.sees("building", "programPane"), "the line being built says so in the program")
        ui.wait_until(lambda: ui.js("Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 40, "the build-up to finish")
        ui.check(ui.js("Store.builtIds.length === 0 && Store.revealing.length === 0") is True, "nothing is marked as building once it is in")
        ui.settle(1700)
        ui.check(not ui.exists("buildCaption"), "the cue leaves when the build is in")
        print(f"  build pictured at step {shot_at} of {of}", flush=True)

    ui.shot("lightdesk-workspace")

    # the panes: all there, inside the window, none over another
    names = ["titleCapsule", "stageTabs", "toolsCapsule", "toolDock", "viewsCapsule", "programPane", "pipelineCapsule", "talk"]
    rects = {n: _rect(ui, n) for n in names}
    w, h = ui.win.width(), ui.win.height()
    for n, r in rects.items():
        ui.check(r[0] >= 0 and r[1] >= 0 and r[0] + r[2] <= w + 1 and r[1] + r[3] <= h + 1, f"{n} is inside the window: {r}")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ui.check(_apart(rects[a], rects[b]), f"{a} and {b} do not overlap: {rects[a]} {rects[b]}")
    vp = _rect(ui, "viewport")
    ui.check(vp[0] <= 1 and vp[1] <= 1 and vp[2] >= w - 2 and vp[3] >= h - 2, f"the 3D view fills the window: {vp}")

    # the program: one line per feature, in build order, numbered
    feats = ui.js("Store.recipe.features.map(function (f) { return f.id })")
    ui.check(len(feats) >= 6 and all(ui.exists("feature-" + f) for f in feats), f"every feature is a line of the program: {feats}")
    ui.expect("Program", "programPane")
    ui.expect("build order", "programPane")

    # the size line is the solid's own bounding box and volume
    bb = ui.js("Store.shown.bbox")
    says = " ".join(ui.texts("readout"))
    for a in range(3):
        ui.check(("%.1f" % (bb[1][a] - bb[0][a])) in says, f"the size line carries {bb[1][a] - bb[0][a]:.1f}: {says}")
    ui.check("cm³" in says, f"and the volume: {says}")

    # the bar: folded, with numbered suggestions; a number key picks one while the prompt is empty
    ui.check(ui.js("Store.chatItems.length") == 0 and rects["talk"][3] < 330, f"the conversation is a bar under the part: {rects['talk']}")
    ui.expect("Ask about this design, or describe a change.", "talk")
    sugg = ui.find_all(name="talkSuggestion")
    ui.check(len(sugg) >= 2, f"numbered suggestions from the design's real state: {len(sugg)}")
    ui.click("composer")
    ui.key("2")                                        # "Make it lighter without failing a check" opens its sheet
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "lighter", 6, "key 2 to pick the second suggestion")
    ui.eq(ui.item("composer").property("text"), "", "the key picked the suggestion and typed nothing")
    ui.settle(300)
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("sheet") is None, 4, "the sheet to close")
    ui.settle(600)

    # the conversation opens upward into the transcript, and folds back
    ui.click("composer")
    ui.type("hello there")
    ui.eq(ui.item("composer").property("text"), "hello there", "typing reaches the prompt")
    ui.key("Return")
    ui.wait_until(lambda: ui.js("Store.chatItems.length") > 0 and not ui.store.get("chatBusy"), 30, "the agent's reply")
    ui.settle(900)
    open_h = _rect(ui, "talk")[3]
    ui.check(ui.store.get("talkOpen") is True and open_h > 250, f"the transcript is open above the prompt: {open_h}")
    ui.check(ui.exists("talkFeed") and ui.exists("convSwitch"), "with its messages and the conversation switcher")
    ui.check(_apart(_rect(ui, "talk"), _rect(ui, "programPane")) and _apart(_rect(ui, "talk"), _rect(ui, "viewsCapsule")), "it stays clear of the other panes")
    ui.shot("lightdesk-conversation")
    ui.key("Ctrl+J")
    ui.wait_until(lambda: ui.store.get("talkOpen") is False, 3, "Ctrl+J to fold it")
    ui.settle(900)
    fold_h = _rect(ui, "talk")[3]
    ui.check(fold_h < open_h - 100 and not ui.exists("talkFeed"), f"folded, it is the prompt alone: {fold_h}")
    ui.shot("lightdesk-conversation-folded")
    ui.click("talkLead")
    ui.wait_until(lambda: ui.store.get("talkOpen") is True, 3, "a click on the status line to open it again")
    ui.settle(700)
    ui.check(ui.exists("talkFeed"), "the messages are back")

    # the stages are in the top bar and the pane follows them
    ui.key("Ctrl+J")
    ui.settle(500)
    for stage in ("brief", "prove", "release", "shape"):
        ui.click("stage-" + stage)
        ui.wait_until(lambda: ui.store.get("stage") == stage, 3, f"the {stage} stage")
        ui.settle(500)
        r = _rect(ui, "programPane")
        ui.check(r[1] + r[3] <= _rect(ui, "pipelineCapsule")[1] + 1, f"{stage}: the pane ends above the pipeline: {r}")
        if stage in ("brief", "release"):
            ui.shot("lightdesk-stage-" + stage)

    # Settings wears the same material
    ui.key("Ctrl+,")
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "settings", 5, "Settings")
    ui.settle(700)
    ui.shot("lightdesk-settings")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("sheet") is None, 4, "Settings to close")
