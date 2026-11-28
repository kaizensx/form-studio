"""Working in a design the way a person does on the first evening: the stage, the two side columns, the prompt.

- The first click into the 3D view after a design opens folds the conversation column (calm); so does Esc.
- The prompt under the part is a place to write: clicking it and typing leaves the column folded and the words in the
  prompt; sending brings the conversation back.
- The caret of the prompts is a thin line of the accent at the cursor: it moves with the words, is lit while they
  change and blinks once they are still.
- Refinement in the dock opens and folds from its header in every stage, and never lies under the pane above it.
- The pane's tab stands on the middle of the pane's outer edge and folds the pane.
- The cue of a build stands on a pane of glass.
- The part is in the middle of the free stage; a view the person panned and zoomed goes back there when a column
  folds or opens, the pane folds, Focus, or the window is resized."""
import json

from _lib import make

DATA = "fresh"
TALK = [{"t": "user", "text": "make the walls a little thicker and add vents to the lid", "local": True},
        {"t": "text", "text": "Done as revision 2. The walls are 2.4 mm and the lid has seven vent slots over the board.", "local": True}]


def _centre(ui):
    """How far the part's middle is from the middle of the free stage, in px (x, y), and the camera's distance."""
    return ui.js("(function(){var v=Store.viewer,c=v._px(v.center(v.bounds));return [c.x-(v.insetLeft+v.width-v.insetRight)/2,c.y-(v.insetTop+v.height-v.insetBottom)/2,v.dist]})()")


def _enter(ui, pid, talk_open=True, build=False):
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 20, "Home")
    ui.settle(400)
    ui.run_js("Store.talkOpen = %s; %s Store.view = null; Store.reloadStudio().then(function () { Store.open(%r) })"
              % ("true" if talk_open else "false", "Store._buildNext = Date.now();" if build else "", pid))
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.js("!!Store.view && !!Store.viewer") is True, 40, "the design to open")
    ui.run_js("Store.chatItems = %s" % json.dumps(TALK))


def _stage_click(ui):
    v = ui.item("viewport")
    ui.click("viewport", (float(v.property("insetLeft")) + 60) / v.width(), (float(v.property("insetTop")) + 20) / v.height())


def _pan_zoom(ui, dx=70, dy=40):
    v = ui.item("viewport")
    fx = (float(v.property("insetLeft")) + v.width() - float(v.property("insetRight"))) / 2 / v.width()
    ui.drag("viewport", (dx, dy), fx, 0.5, button="right")
    ui.wheel("viewport", 240, fx, 0.5)
    ui.settle(300)


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    wide = ui.win.width() >= 1200

    # ── the caret on Home ──
    ui.click("startText"); ui.settle(200)
    cur = ui.item("startCursor")
    ui.check(cur.isVisible() and cur.width() <= 2.01, "Home's caret is a thin line (%s px)" % cur.width())
    x0 = cur.x()
    ui.type("a wall hook")
    ui.wait_until(lambda: ui.item("startCursor").x() > x0 + 40, 3, "Home's caret to follow the words")
    ui.eq(ui.item("startCursor").property("beat"), 0, "the caret is lit while the words change")
    ui.eq(round(cur.height()), round(ui.item("startText").property("cursorRectangle").height()), "the caret is as tall as the line")
    ui.key("End")                                    # (a key through the window: it is the active one from here on)
    if not ui.js("Theme.reduced"):
        ui.wait_until(lambda: ui.item("startCursor").property("beat") == 1, 3, "the caret to blink once the words are still")
    ui.clear()

    pid = make(ui, "enclosure", "Sensor case", open=False)

    # ── 1: the first click into the view folds the column ──
    for wait in (250, 1500):
        _enter(ui, pid); ui.settle(wait)
        if wide:
            ui.check(ui.js("Store.talkCol") > 0, "the conversation column is open when the design opens")
        _stage_click(ui); ui.settle(700)
        ui.eq(ui.js("Store.talkCol"), 0, "the first click into the view, %d ms after the design opened, folds the column" % wait)
        ui.check(ui.js("Store.talkOpen") is True, "calm: the conversation is still open, only folded")
    ui.run_js("Store.talkCalm = false"); ui.settle(600)
    if wide:
        ui.key("Escape"); ui.settle(600)
        ui.eq(ui.js("Store.talkCol"), 0, "Esc with nothing else to leave folds the column")

    # ── 2 and 3: the prompt under the part is written in; its caret follows ──
    ui.run_js("Store.talkCalm = true"); ui.settle(800)
    ui.click("composer", 0.14, 0.5); ui.settle(300)          # on its words: in a narrow bar the controls stand over its right half
    ui.type("make it 4 mm taller"); ui.settle(500)
    ui.check(ui.js("Store.talkCalm") is True and ui.js("Store.talkCol") == 0, "typing in the prompt under the part leaves the column folded")
    ui.check(ui.focus_item() is ui.item("composer") or ui.focus_item() == ui.item("composer"), "the keyboard is in the prompt that was clicked")
    ui.eq(ui.item("composer").property("text"), "make it 4 mm taller", "the words are in the prompt")
    car = ui.item("composerCaret")
    ui.check(car.isVisible() and car.width() <= 2.01, "the prompt's caret is a thin line")
    ui.check(abs(car.x() - ui.item("composer").property("cursorRectangle").x()) < 1.5, "the caret stands at the cursor")
    xa = car.x(); ui.key("Left", 6); ui.settle(80)
    ui.check(ui.item("composerCaret").x() < xa - 20, "the caret moves with the cursor")
    ui.eq(ui.item("composerCaret").property("beat"), 0, "a caret that has just moved is lit")
    ui.shot("stage-use-bar-typed")
    ui.key("Return")
    ui.wait_until(lambda: ui.js("Store.talkCalm") is False, 5, "sending to bring the conversation back")
    ui.wait_until(lambda: not ui.store.get("chatBusy"), 30, "the agent's reply")
    ui.settle(500)
    ui.run_js("Store.talkOpen = false"); ui.settle(900)

    # ── 4: Refinement opens from its header in every stage ──
    def refine():
        ui.run_js("Store.refine = { state: 'done', changes: [{ id: 'edge_break', kind: 'feature', label: 'Edge break', reason: 'Break the outer edges by 0.6 mm.' }], stage: '' }")
    for st in ("shape", "prove", "release", "document"):
        ui.click("stage-" + st); ui.settle(800); refine(); ui.settle(500)
        rp = ui.item("refinePanel")
        was = rp.height() > 60
        ui.click(rp, 0.5, 18.0 / max(36.0, rp.height())); ui.settle(700)
        ui.check((ui.item("refinePanel").height() > 60) != was, "%s: a click on Refinement's header %s it" % (st, "folds" if was else "opens"))
        if was:
            ui.click(ui.item("refinePanel"), 0.5, 0.5); ui.settle(700)
        ui.check(ui.item("refinePanel").height() > 60, "%s: Refinement is open" % st)
        from PySide6.QtCore import QPointF
        pane = ui.item("programPane")
        top = ui.item("refinePanel").mapToItem(pane.parentItem(), QPointF(0, 0)).y()
        ui.check(pane.y() + pane.height() <= top - 4, "%s: the pane above ends over Refinement (%d, %d)" % (st, pane.y() + pane.height(), top))
        ui.run_js("Ws.refineWant = -1"); ui.settle(300)
    ui.shot("stage-use-refinement")
    ui.run_js("Store.refine = null")
    ui.click("stage-shape"); ui.settle(700)

    # ── 5: the pane's tab ──
    tab, pane = ui.item("paneTab"), ui.item("programPane")
    ui.check(abs(tab.x() + tab.width() / 2 - pane.x()) <= 1, "the tab stands on the pane's outer edge")
    ui.check(abs(tab.y() + tab.height() / 2 - (pane.y() + pane.height() / 2)) <= 1, "the tab stands at the middle of the pane's height")
    ui.click("paneTab"); ui.settle(900)
    ui.check(ui.js("Store.paneFolded") is True and not ui.exists("paneTab"), "the tab folds the pane")
    ui.run_js("Store.paneFolded = false"); ui.settle(900)

    # ── 7: the part is in the middle; a view of one's own goes back there when the layout changes ──
    def centred(what, tol=4):
        ui.settle(1300)
        # the view glides to its framing: it is judged where it comes to rest (two looks 250 ms apart agree), which
        # is later where frames are slow
        seen = {"c": None}

        def rested():
            was, now = seen["c"], _centre(ui)
            seen["c"] = now
            ui.wait(250)
            return was is not None and all(abs(a - b) < 0.5 for a, b in zip(was, now))
        try:
            ui.wait_until(rested, 6, "the view to come to rest")
        except Exception:                              # noqa: BLE001 - the checks below say where it stands
            pass
        c = _centre(ui)
        ui.check(abs(c[0]) <= tol and abs(c[1]) <= tol, "%s: the part is in the middle of the free stage (off by %.0f, %.0f)" % (what, c[0], c[1]))
        return c
    centred("as the design stands")

    def moved_then(what, change):
        _pan_zoom(ui)
        c = _centre(ui)
        ui.check(abs(c[0]) > 30, "a pan moves the part off the middle (%.0f)" % c[0])
        ui.settle(900)
        ui.check(abs(_centre(ui)[0]) > 30, "the view the person chose stays while nothing else changes")
        change()
        c = centred(what)
        # (the whole part, framed for the free stage as it now is: one with more room may stand closer)
        home = ui.js("Store.viewer.homeDist()")
        ui.check(abs(c[2] - home) < 0.02 * home, "%s: the whole part is framed again (%.0f, %.0f)" % (what, c[2], home))
    moved_then("the pane folded", lambda: ui.run_js("Store.paneFolded = true"))
    moved_then("the pane back", lambda: ui.run_js("Store.paneFolded = false"))
    moved_then("Focus", lambda: ui.key("Ctrl+."))
    moved_then("Focus left", lambda: ui.key("Ctrl+."))
    if wide:
        moved_then("the column opened", lambda: ui.run_js("Store.talkOpen = true"))
        ui.run_js("Store.talkOpen = false"); ui.settle(900)
    w, h = ui.win.width(), ui.win.height()
    moved_then("the window resized", lambda: ui.resize(w + 80, h + 40))
    ui.resize(w, h)
    # orbiting alone keeps it in the middle
    ui.drag("viewport", (90, 30), 0.45, 0.5); centred("after an orbit")

    # ── 6: the cue stands on glass ──
    if not ui.js("Theme.reduced"):
        _enter(ui, pid, talk_open=False, build=True)
        ui.wait_until(lambda: ui.js("Store.buildAt") >= 2, 30, "the build-up to start")
        ui.wait(250)
        if ui.exists("buildCaption") and ui.js("Store.buildOf") > 0:
            from PySide6.QtCore import QPointF
            back, cap = ui.item("cueBacking"), ui.item("buildCaption")
            ui.check(back.isVisible() and back.width() >= cap.width() - 1 and back.height() > cap.height() + 20, "the cue has a pane behind its words")
            for name in ("buildLedgerState", "buildLedgerName"):
                it = ui.item(name)
                p, q = it.mapToItem(back, QPointF(0, 0)), it.mapToItem(back, QPointF(it.width(), it.height()))
                ui.check(p.x() >= 8 and p.y() >= 8 and q.x() <= back.width() - 8 and q.y() <= back.height() - 8, name + " lies inside the cue's pane")
            ui.shot("stage-use-cue")
        ui.wait_until(lambda: ui.js("Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to finish")
    ui.no_warnings()
