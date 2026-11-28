"""Results drawn on the part (direction I, decision 7): a strength field, a manufacturability overlay, a CNC setup, a
sheet-metal flat pattern, a motion study and the drawing sheet, each from a real small study run by its own engine in
this journey's data folder (tests/journeys/_results.py). The window is asked for what a person sees; the numbers it
shows are compared with the engine's.

Strength needs the FEA engine ($FORM_FEA_PYTHON or installed). Without it the journey checks the honest state
instead: the row says what it needs and nothing is drawn.

FORM_RESULT_CROPS=<dir> also saves 200 % crops of the stage, the strip and the card for each result.
"""
import os
from pathlib import Path

import _results as R
from _lib import open_project

DATA = "fresh"
S = {}


def res(ui, expr="Results.kind"):
    return ui.js(expr)


def crop(ui, name, what=("legendStrip", "benchCard")):
    shot = ui.shot(name)
    out = os.environ.get("FORM_RESULT_CROPS")
    if not out:
        return
    from PIL import Image
    from PySide6.QtCore import QPointF
    img = Image.open(shot)
    k = img.width / ui.win.width()
    tag = "%s-%d" % (os.environ.get("FORM_APPEARANCE", "dark"), ui.win.width())
    Path(out).mkdir(parents=True, exist_ok=True)
    img.save(str(Path(out) / f"{name}-{tag}.png"))
    for nm in what + ("viewport",):
        it = ui.find(name=nm)
        if it is None or it.width() < 4:
            continue
        p = it.mapToItem(ui.win.contentItem(), QPointF(0, 0))
        box = [int(p.x() * k), int(p.y() * k), int((p.x() + it.width()) * k), int((p.y() + it.height()) * k)]
        if nm == "viewport":                           # the stage between the panes, around the part
            box = [int(ui.win.width() * 0.26 * k), int(90 * k), int(ui.win.width() * 0.76 * k), int(ui.win.height() * 0.84 * k)]
        c = img.crop(box)
        c = c.resize((int(c.width * 2 / k), int(c.height * 2 / k)), Image.LANCZOS)
        c.save(str(Path(out) / f"{name}-{nm}-{tag}.png"))


def show(ui, pid, mode_key, row, kind):
    """Open a design, go to a mode and select a row of its chapter; wait for its result to be on the part."""
    if ui.store.get("pid") != pid:
        open_project(ui, pid)
    ui.key(mode_key)
    ui.wait_until(lambda: ui.find(name="bench-" + row), 15, f"the row {row}")
    ui.scroll_to(ui.item("bench-" + row), 0.4)
    ui.click("bench-" + row, 0.3, 0.5)
    ui.wait_until(lambda: res(ui, "Results.id") == row and res(ui, "!!Results.r && !Results.busy"), 20, f"the result of {row}")
    if kind:
        ui.wait_until(lambda: res(ui) == kind, 10, f"{row} drawn as {kind}")
        ui.wait_until(lambda: not res(ui, "Results.developing"), 5, "the result to have developed")
    ui.settle(500)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S.update(R.seed(ui.studio))
    S["fea"] = "static" in S


def journey_strength(ui):
    if not S["fea"]:
        show(ui, S["bracket"], "Ctrl+2", "strength", "")
        ui.eq(res(ui), "", "without the engine nothing is drawn on the part")
        ui.check(ui.find(name="legendStrip") is None or not ui.find(name="legendStrip").isVisible(), "and there is no legend")
        return
    from form.fea import study
    p = ui.studio.load(S["bracket"])
    want = study.result(ui.studio, p, S["static"])["result"]
    show(ui, S["bracket"], "Ctrl+2", "strength", "field")
    ui.eq(res(ui, "Results.r.study"), S["static"], "the static study is the one drawn")
    ui.eq(res(ui, "Results.developed"), 1, "the result developed on the part, once")
    ui.check(res(ui, "Results.develop") == 1 and res(ui, "Results.settle") == 1, "and the moment has ended")
    ui.check(res(ui, "Results.r.converged") is True, "it converged")
    ui.check(abs(res(ui, "Results.r.peak.value") - want["peak_von_mises_MPa"]) < 1e-9, "the peak is the engine's")
    lay = "Store.viewer.resultLayer"
    ui.check(res(ui, lay + ".isField && " + lay + ".covers"), "the field stands in for the clay part")
    ui.check(res(ui, lay + ".fieldGeo.triangles") > 1000, "with the field's own surface mesh")
    strip = ui.item("legendStrip")
    ui.check(ui.sees("Von Mises stress", within=strip), "the strip names the quantity")
    ui.check("MPa" in str(ui.item("legendSub").property("text")), "its unit")
    ev = str(ui.item("legendEvidence").property("text")).lower()
    ui.check("simulated" in ev and "linear static" in ev, f"how it is known: {ev!r}")
    lim = str(ui.item("legendLimits").property("text"))
    pct = "%.1f" % (100 * want["discretisation_error"]["stress"])
    ui.check(("± " + pct.rstrip("0").rstrip(".") + " %") in lim, f"the stated error: {lim[:120]!r}")
    ui.check("Not told here" in lim and "fatigue" in lim, "and what it does not tell")
    ui.check("singular zone" in lim, "the singular zone left out is said")
    ui.check(ui.find(name="peakLabel") is not None and any(("%.1f" % want["peak_von_mises_MPa"]) in t for t in ui.texts(ui.item("peakLabel"))), "the peak carries its number on the part")
    ui.check(len(ui.find_all(name="fixtureGlyph")) == 2, "each held face has its lock")
    ui.check(any("361" in t for t in ui.texts(ui.item("loadLabel"))), "the load arrow says 361 N (300, 0, -200)")
    ui.check(ui.find(name="singularLabel") is not None, "the singular zone is marked as left out")
    # the card: per-result lines and the convergence plot
    card = ui.item("benchCard")
    ui.scroll_to(card, 0.2)
    ui.check(ui.sees("Safety factor", within=card) and ui.sees("%.2f" % want["safety_factor"]["value"], within=card), "the safety factor line")
    ui.check(ui.sees("Largest displacement", within=card), "the displacement line")
    ui.check(ui.find(name="convergence", within=card) is not None and len(res(ui, "Results.r.convergence.points")) == len(want["convergence"]["levels"]),
             "the convergence plot has one point per mesh")
    crop(ui, "strength-static")
    # the many-colour scale, and back
    ui.click_text("Many colours", within=strip)
    ui.eq(res(ui, "Results.scale"), "many", "the many-colour scale is an option")
    ui.settle(300)
    crop(ui, "strength-many")
    ui.click_text("One hue", within=strip)
    # the deformed shape
    ui.click(ui.item(text="Deformed", within=strip, exact=False))
    ui.check(res(ui, "Results.deformed") and res(ui, "Results.deformShown") > 1, "the deformed shape, scaled by a round factor")
    ui.wait_until(lambda: abs(res(ui, lay + ".deformNow") - res(ui, "Results.deformShown")) < 1e-6, 3, "the shape to arrive")
    ui.check(ui.find(name="peakRing") is None or not ui.item("peakRing", timeout=0.2).isVisible(), "markers of the undeformed shape step back")
    crop(ui, "strength-deformed")
    ui.click_text("As built", within=strip)
    # the modal study: its shapes swing
    ui.click_text("Modes", within=card)
    ui.wait_until(lambda: res(ui, "Results.r.study") == S["modal"] and res(ui, "!!Results.r.modes"), 15, "the modal study")
    ui.settle(700)
    f1 = study.result(ui.studio, p, S["modal"])["result"]["frequencies_Hz"][0]
    ui.check(abs(res(ui, "Results.r.modes[0].value") - f1) < 1e-9, "its first frequency is the engine's")
    ui.click("modePlay")
    ui.check(res(ui, "Results.playing"), "a mode shape swings")
    a = res(ui, "Results.phase")
    ui.settle(200)
    ui.check(res(ui, "Results.phase") != a, "over time")
    crop(ui, "strength-mode")
    ui.click("modePlay")
    ui.check(not res(ui, "Results.playing"), "and stops")
    ui.click_text("Shelf load", within=card)
    ui.wait_until(lambda: res(ui, "Results.r.study") == S["static"], 15, "the static study again")
    ui.settle(700)
    ui.eq(res(ui, "Results.developed"), 2, "each study developed once; coming back to one does not play it again")
    # a study that did not converge never plays the moment: it shows its reason
    ui.click_text("Rough", within=card)
    ui.wait_until(lambda: res(ui, "Results.r.study") == S["rough"] and not res(ui, "Results.busy"), 15, "the study that did not converge")
    ui.check(res(ui, "Results.r.converged") is False, "the engine says it did not converge")
    ui.check(not res(ui, "Results.developing") and res(ui, "Results.developed") == 2, "the moment is not played for it")
    ui.check("Did not converge" in str(ui.item("legendLimits").property("text")), "the strip says so, in place of an error it cannot state")
    ui.check(ui.find(name="notConverged", within=card) is not None, "and the card gives the reason")
    ui.settle(300)
    crop(ui, "strength-not-converged")
    ui.click_text("Shelf load", within=card)
    ui.wait_until(lambda: res(ui, "Results.r.study") == S["static"], 15, "the static study again")


def journey_dfm(ui):
    from form import dfm
    show(ui, S["bracket"], "Ctrl+2", "dfm_injection", "dfm")
    want = dfm.check(ui.studio, ui.studio.load(S["bracket"]), "injection", {})
    lay = "Store.viewer.resultLayer"
    ui.eq(res(ui, "Results.r.verdict"), want["verdict"], "the verdict is the engine's")
    ui.eq(len(res(ui, "Results.r.rows")), len(want["rows"]), "one row per rule")
    ui.check(res(ui, lay + ".isDfm && " + lay + ".covers"), "the overlay stands in for the clay part")
    strip = ui.item("legendStrip")
    lim = str(ui.item("legendLimits").property("text"))
    ui.check("Not told here" in lim, "the strip says what the check does not judge")
    ui.check(ui.sees("parting line", within=strip) if want["data"].get("parting_line") else True, "the parting line is in the legend")
    ui.check(ui.find(name="pullLabel") is not None and any("+Z" in t for t in ui.texts(ui.item("pullLabel"))), "the pull is drawn and named")
    ui.check(len(ui.find_all(name="dfmMarker")) >= 1, "findings are marked where they are")
    card = ui.item("benchCard")
    row = ui.item("rule-injection.draft")
    ui.scroll_to(row, 0.5)
    ui.hover(row, 0.3, 0.5)
    ui.wait_until(lambda: res(ui, "Results.litRule") == "injection.draft", 3, "the rule under the pointer to light")
    faces = sorted({fc for f in want["findings"] if f["rule"] == "injection.draft" for fc in f.get("faces") or []})
    ui.eq(sorted(res(ui, lay + ".litFaces")), faces, "its faces are the ones the engine found")
    ui.settle(300)
    crop(ui, "dfm-injection-lit")
    ui.hover(strip, 0.5, 0.2)
    ui.wait_until(lambda: res(ui, "Results.litRule") == "", 3, "the light to go with the pointer")
    crop(ui, "dfm-injection")
    show(ui, S["bracket"], "Ctrl+2", "dfm_cnc", "dfm")
    ui.eq(res(ui, "Results.r.process"), "cnc", "the CNC check draws its own overlay")
    crop(ui, "dfm-cnc")


    # the bracket's draft fix does not pass in its preview: the window says why, and nothing is saved
    show(ui, S["bracket"], "Ctrl+2", "dfm_injection", "dfm")
    head = ui.studio.load(S["bracket"])["head"]
    row = ui.item("rule-injection.draft")
    ui.scroll_to(row, 0.5)
    ui.hover(row, 0.3, 0.5)
    ui.click("fix-injection.draft")
    ui.wait_until(lambda: res(ui, "!!Results.fix && !Results.fix.busy"), 120, "the fix to be tried")
    ui.check(res(ui, "Results.fix.ok") is not True and ui.find(name="fixApply") is None, "a fix that does not pass cannot be applied")
    ui.eq(ui.studio.load(S["bracket"])["head"], head, "and nothing was saved")
    ui.click("fixCancel")


def journey_fix(ui):
    show(ui, S["cup"], "Ctrl+2", "dfm_injection", "dfm")
    card = ui.item("benchCard")
    row = ui.item("rule-injection.draft")
    ui.scroll_to(row, 0.5)
    ui.hover(row, 0.3, 0.5)
    # a fix, previewed as a ghost: built and checked, nothing saved
    head = ui.studio.load(S["cup"])["head"]
    ui.click("fix-injection.draft")
    ui.wait_until(lambda: res(ui, "!!Results.fix && !Results.fix.busy"), 120, "the fix to be built without saving")
    ui.check(res(ui, "Results.fix.ok") is True, "the candidate passes its rule in the preview: " + str(res(ui, "Results.fix.why")))
    ui.check(res(ui, "!!Store.viewer.ghost"), "the candidate is drawn as a ghost over the part")
    ui.eq(ui.studio.load(S["cup"])["head"], head, "and nothing was saved")
    ui.settle(300)
    crop(ui, "dfm-fix-after")
    ui.click_text("Before", within=card)
    ui.check(not res(ui, "!!Store.viewer.ghost"), "Before shows the part alone")
    ui.click_text("After", within=card)
    ui.click("fixApply")
    ui.wait_until(lambda: ui.studio.load(S["cup"])["head"] == head + 1, 120, "the fix to be applied as a revision")
    ui.wait_until(lambda: res(ui, "Results.fix") is None, 30, "the preview to go")
    from form import dfm
    after = dfm.check(ui.studio, ui.studio.load(S["cup"]), "injection", {"resin": "abs"})
    ui.eq({r["id"]: r["status"] for r in after["rows"]}["injection.draft"], "pass", "checked again on the new revision, the rule passes")


def journey_cam(ui):
    show(ui, S["pocket"], "Ctrl+3", "cam_3axis", "cam")
    lay = "Store.viewer.resultLayer"
    dur = res(ui, "Results.duration")
    ui.check(dur > 1 and abs(dur - res(ui, "Results.r.summary.cycle_time_s")) < 1.0, f"the timeline is the program's cycle time ({dur})")
    ui.check(res(ui, lay + ".pathGeo.segments") > 50, "the toolpaths are drawn")
    ui.check(res(ui, "Results.t") == dur and res(ui, lay + ".stockOn"), "it opens at the end of the setup, with the simulated stock")
    marks = res(ui, "Results.r.setups[0].marks.length")
    ui.eq(len(ui.find_all(name="camMark")), min(12, marks), "what the simulation marked is on the stock")
    strip = ui.item("legendStrip")
    ev = str(ui.item("legendEvidence").property("text")).lower()
    ui.check("simulated" in ev and "not proven on a machine" in ev, f"the evidence: {ev!r}")
    crop(ui, "cam-end")
    # scrub: the paths up to that second, the tool where the program is
    area = ui.item("scrubArea")
    ui.click(area, 0.4, 0.5)
    ui.check(abs(res(ui, "Results.t") - 0.4 * dur) < 0.03 * dur, "a click on the timeline goes to that second")
    ui.check(not res(ui, lay + ".stockOn"), "the stock, which is the end of the setup, steps back")
    ui.settle(300)
    crop(ui, "cam-scrub")
    ui.drag(area, (60, 0), 0.4, 0.5)
    ui.check(res(ui, "Results.t") > 0.4 * dur, "dragging scrubs")
    t0 = res(ui, "Results.t")
    ui.click("playButton")
    ui.settle(400)
    ui.check(res(ui, "Results.playing") and res(ui, "Results.t") > t0, "play runs the program in time")
    ui.click("playButton")
    ui.check(not res(ui, "Results.playing"), "and pauses")
    card = ui.item("benchCard")
    ui.check(len(ui.find_all(name="camOp", within=card, shown=False)) >= 2, "the card lists the operations")


def journey_flat(ui):
    show(ui, S["tray"], "Ctrl+3", "sheet_flat", "flat")
    lay = "Store.viewer.resultLayer"
    ui.eq(len(res(ui, "Results.r.bends")), 4, "four bends, as the engine unfolded them")
    ui.eq(len(ui.find_all(name="bendNote")), 4, "each bend carries its angle on the part")
    ui.check(all("90° up" in " ".join(ui.texts(n)) for n in ui.find_all(name="bendNote")), "90° up")
    crop(ui, "flat-folded")
    ui.click_text("Flat", within=ui.item("legendStrip"))
    ui.wait_until(lambda: res(ui, lay + ".foldK") == 0, 3, "the part to unfold")
    ui.check(res(ui, lay + ".covers"), "the flat pattern stands in for the folded part")
    ui.settle(300)
    crop(ui, "flat-flat")
    ui.click_text("Folded", within=ui.item("legendStrip"))
    ui.wait_until(lambda: res(ui, lay + ".foldK") == 1, 3, "and to fold back")


def journey_motion(ui):
    show(ui, S["fourbar"], "Ctrl+2", "motion", "motion")
    dur = res(ui, "Results.duration")
    ui.check(dur > 0, "the cycle has a duration")
    ui.wait_until(lambda: ui.find(name="gapLabel") is not None, 5, "the smallest gap of the frame shown, on the part")
    area = ui.item("scrubArea")
    ui.click(area, 0.5, 0.5)
    fr = res(ui, "Results.frame")
    want = res(ui, "Results.r.joints[0].value[%d]" % fr)
    got = res(ui, "Store.pose.crank")
    ui.check(abs(got - want) < 360.0 / 36, f"the mechanism stands at the frame scrubbed to (crank {got:.1f}, frame {want:.1f})")
    ui.eq(ui.store.get("asmMode"), "assembled", "drawn assembled")
    ui.settle(400)
    crop(ui, "motion-mid")
    ui.click("playButton")
    ui.settle(300)
    ui.check(res(ui, "Results.playing"), "the cycle plays")
    ui.click("playButton")
    card = ui.item("benchCard")
    ui.check(len(ui.find_all(name="jointLine", within=card, shown=False)) == 3, "the card lists the joints with their drives")


def journey_drawing(ui):
    show(ui, S["bracket"], "Ctrl+4", "drawing", "drawing")
    pane = ui.item("drawingPane")
    ui.wait_until(lambda: pane.property("k") >= 1, 3, "the sheet to have unfolded")
    ui.check(not res(ui, "Results.onPart"), "the sheet is a pane, not a map on the part")
    ui.check(len(res(ui, "Results.r.dims")) >= 5, "the sheet's dimensions are objects")
    ui.settle(300)
    crop(ui, "drawing-night", what=("drawingPane",))
    ui.click(pane, 0.02, 0.02)
    night = not pane.property("paper")
    ui.eq(night, os.environ.get("FORM_APPEARANCE", "dark") != "light", "a night sheet in the dark room, paper in the light one")
    ui.key("P")
    ui.check(res(ui, "Results.paper") is True and pane.property("paper") is night, "P switches between night and paper")
    ui.settle(300)
    crop(ui, "drawing-paper", what=("drawingPane",))
    ui.key("P")
    # a dimension bound to a parameter: select it, type over it, and the design changes
    dm = next(d for d in res(ui, "Results.r.dims") if d.get("param") == "t")
    z, ox, oy, sh = (float(pane.property(k)) for k in ("zoom", "ox", "oy", "sh"))
    b = dm["bbox"]
    fx = (ox + (b[0] + b[2]) / 2 * z) / pane.width()
    fy = (oy + (sh - (b[1] + b[3]) / 2) * z) / pane.height()
    ui.click(pane, fx, fy)
    ui.eq(res(ui, "Results.selDim"), dm["id"], "a click selects the dimension")
    ui.check(any("parameter t" in t for t in ui.texts(ui.item("sheetFoot"))), "the sheet says which parameter it is")
    ui.wheel(pane, 240, fx, fy)
    ui.check(float(pane.property("zoom")) > z, "the wheel zooms")
    crop(ui, "drawing-zoom", what=("drawingPane",))
    ui.key("0")
    ui.key("Return")
    ui.wait_until(lambda: ui.find(name="dimEditor") is not None, 3, "the dimension to open for typing")
    head = ui.studio.load(S["bracket"])["head"]
    ui.key("Ctrl+A")
    ui.type("7")
    ui.key("Return")
    ui.wait_until(lambda: ui.studio.load(S["bracket"])["head"] == head + 1, 60, "the edit to be committed as a revision")
    p = ui.studio.load(S["bracket"])
    ui.eq(ui.studio.rev(p)["values"]["t"], 7.0, "the parameter took the typed value")
    ui.wait_until(lambda: res(ui) == "drawing" and res(ui, "Results.r.rev") == head + 1, 120, "the sheet to be made again for the new revision")
    crop(ui, "drawing-after-edit", what=("drawingPane",))
    # the strength study now describes the revision before: nothing of it is drawn
    if S["fea"]:
        show(ui, S["bracket"], "Ctrl+2", "strength", "")
        ui.eq(res(ui), "", "a stale field is not drawn")
        ui.check(ui.sees("Stale", within=ui.item("resultNone")) or ui.sees("Not run", within=ui.item("resultNone")), "the card says so")


class Frames:
    """Counts the frames the window swaps (QQuickWindow.frameSwapped) and the time between them."""

    def __init__(self, ui):
        import time
        self.ui, self.t, self.clock = ui, [], time.perf_counter
        ui.win.frameSwapped.connect(self._tick)

    def _tick(self):
        self.t.append(self.clock())

    def idle(self, ms=1200):
        self.ui.settle(400)
        self.t.clear()
        self.ui.wait(ms)
        return len(self.t)

    def orbit(self, steps=90):
        """Turn the view two degrees a frame; the mean and the worst milliseconds between frames."""
        self.ui.settle(300)
        self.t.clear()
        for _ in range(steps):
            n = len(self.t)
            self.ui.run_js("Store.viewer.tween = false; Store.viewer.az += 2")
            self.ui.wait_until(lambda: len(self.t) > n, 2, "a frame")
        d = [1000 * (b - a) for a, b in zip(self.t, self.t[1:])]
        d.sort()
        return sum(d) / len(d), d[int(len(d) * 0.95)]

    def close(self):
        self.ui.win.frameSwapped.disconnect(self._tick)


def journey_perf(ui):
    """A still result is not redrawn, and turning the view with a result on the part costs what the part costs."""
    fr = Frames(ui)
    out = {}
    open_project(ui, S["bracket"])
    ui.key("Ctrl+1")
    ui.settle(600)
    out["part"] = (fr.idle(), *fr.orbit())
    rows = [("dfm", S["bracket"], "Ctrl+2", "dfm_injection", "dfm"), ("cam", S["pocket"], "Ctrl+3", "cam_3axis", "cam"),
            ("flat", S["tray"], "Ctrl+3", "sheet_flat", "flat")]
    if S["fea"] and ui.studio.load(S["bracket"])["head"] == 1:
        rows.insert(0, ("strength", S["bracket"], "Ctrl+2", "strength", "field"))
    for name, pid, key, row, kind in rows:
        show(ui, pid, key, row, kind)
        out[name] = (fr.idle(), *fr.orbit())
    fr.close()
    for k, (idle, mean, p95) in out.items():
        print(f"PERF {k:9s} idle frames in 1.2 s: {idle:3d}   orbit: {mean:5.1f} ms mean, {p95:5.1f} ms 95th")
    base = out["part"]
    for k, (idle, mean, p95) in out.items():
        if k == "part":
            continue
        ui.check(idle <= base[0] + 2, f"{k}: a still result is not redrawn ({idle} frames, the part alone {base[0]})")
        ui.check(mean <= max(base[1] * 1.5, base[1] + 6), f"{k}: turning the view is not slowed ({mean:.1f} ms a frame, the part alone {base[1]:.1f})")


def run(ui):
    journey_setup(ui)
    journey_strength(ui)
    journey_dfm(ui)
    journey_fix(ui)
    journey_cam(ui)
    journey_flat(ui)
    journey_motion(ui)
    journey_perf(ui)
    journey_drawing(ui)
