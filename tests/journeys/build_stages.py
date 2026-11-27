"""A design streams in while the agent builds it: each stage the kernel makes is drawn in the viewport before the
project is saved, growing in over the one before with a quiet caption ("Building Bore (2 of 4)"), and when the
project is saved its head takes over in place, with no blink, no screen fade and no second build-up. A feature the
partial build left out is one calm line in the conversation with the reason the build measured.

The stand-in agent (tests/fixtures/fake_agent.py, "stages") calls Form Studio's real create_design MCP tool with a
FeatureDesign whose features take a second each; its third feature (a 40 mm fillet on a 12 mm body) fails and is
left out. While it runs, the window is grabbed over and over and the clay pixels of the part counted in the free
area of whichever viewport is on screen (the Designing screen's, then the workspace's)."""
import time

DATA = "fresh"
CLEAR = (0x0e, 0x11, 0x13)          # Theme.plate: the View3D's clear colour
S = {}


def _viewport(ui):
    for name in ("viewport", "designingViewport"):
        v = ui.find(name=name)
        if v is not None:
            return name, v
    return "", None


def measure(ui):
    """(viewport name, clay pixels on a 48x32 grid over its free area, clear-colour pixels in its middle 40%)"""
    from PySide6.QtCore import QPointF
    name, v = _viewport(ui)
    if v is None:
        return "", 0, 0
    img = ui.win.grabWindow()
    k = img.width() / max(1, ui.win.width())
    p = v.mapToScene(QPointF(0, 0))
    l, t = p.x() + float(v.property("insetLeft")), p.y() + float(v.property("insetTop"))
    r, b = p.x() + v.width() - float(v.property("insetRight")), p.y() + v.height() - float(v.property("insetBottom"))
    r, b = max(l + 40, r), max(t + 40, b)
    clay = 0
    for i in range(48):
        for j in range(32):
            c = img.pixelColor(int((l + (r - l) * (i + 0.5) / 48) * k), int((t + (b - t) * (j + 0.5) / 32) * k))
            if min(c.red(), c.green(), c.blue()) > 110 and abs(c.red() - c.blue()) < 60:
                clay += 1
    cx, cy, w, h = (l + r) / 2, (t + b) / 2, (r - l) * 0.4, (b - t) * 0.4
    clear = 0
    for i in range(17):
        for j in range(17):
            c = img.pixelColor(int((cx - w / 2 + w * i / 16) * k), int((cy - h / 2 + h * j / 16) * k))
            if max(abs(c.red() - CLEAR[0]), abs(c.green() - CLEAR[1]), abs(c.blue() - CLEAR[2])) <= 6:
                clear += 1
    return name, clay, clear


STATE = """(function () { var v = Store.screen === 'designing' ? Store.stageViewer : Store.viewer, m = v ? v.model : null
    return [Store.screen, Store.building ? Store.building.feature : '', Store.buildingText, Store.pid,
            !!(m && m.stage), v ? v.revealing : false] })()"""


HEAD = """(function () { if (!Store.view || !Store.viewer || !Store.viewer.model) return false
    var a = Store.viewer._mesh, b = Store.view.mesh
    return !Store.viewer.model.stage && Store.viewer.model.rev === Store.view.rev && a.length === b.length
        && a.every(function (m, i) { return m.positions === b[i].positions && m.indices === b[i].indices }) })()"""



def _light(ui):
    return ui.js("Theme.dark") is False


def _stream(ui, tag, pid_before=""):
    """Sample the window from now until a design other than pid_before is open with its saved head drawn; a picture
    of each stage while it grows in and once it sits. Returns (samples, shots)."""
    samples, shots, seen, t_end = [], [], {}, time.time() + 240
    pre = f"stages-{tag}-" + ("light-" if _light(ui) else "")
    while time.time() < t_end:
        st = ui.js(STATE)
        vp, clay, clear = measure(ui)
        now = time.time()
        samples.append({"t": now, "screen": st[0], "stage": st[1], "caption": st[2], "pid": st[3], "staged": st[4],
                        "revealing": st[5], "vp": vp, "clay": clay, "clear": clear})
        if st[1] and st[1] not in seen:                 # a new stage arrived: a picture while it grows in, one when it sits
            seen[st[1]] = now
            ui.wait(120)
            shots.append(str(ui.shot(f"{pre}{len(seen)}-{st[1]}-growing")))
        for f, t0 in list(seen.items()):
            if t0 and now - t0 > 0.7 and st[1] == f:
                shots.append(str(ui.shot(f"{pre}{list(seen).index(f) + 1}-{f}-in-place")))
                seen[f] = 0
        if st[0] == "work" and st[3] and st[3] != pid_before and not st[1] and not st[4] and not st[5] and ui.js(HEAD):
            break
        ui.wait(30)
    else:
        raise AssertionError(f"the saved design did not take over: {samples[-1]}")
    ui.settle(600)
    shots.append(str(ui.shot(f"{pre}saved-design")))
    return samples, shots


def _check_stream(ui, samples, log, created):
    """Every stage drawn in build order, the last one too; at least two before the save; no blink from the first
    stage to the saved head; the saved head drawn exactly, with no second build-up."""
    feats = [e["feature"] for e in log]
    print(f"  stages drawn: {[(e['feature'], e['at'], e['of'], round(e['t'] / 1000 - created, 2)) for e in log]}", flush=True)
    ui.eq(feats, ["body", "bore", "tower"], "every stage that built is drawn, in build order, the last one too")
    ui.check(len([e for e in log if e["t"] / 1000 < created]) >= 2, f"at least two stages are drawn before the project is saved: {log} (saved at {created})")
    ui.check(all(e["of"] == 4 for e in log), f"each stage knows how many features the design has: {log}")
    captions = sorted({x["caption"] for x in samples if x["caption"]})
    ui.check("Building Tower (4 of 4)" in captions and ("Building Bore (2 of 4)" in captions or "Building Body (1 of 4)" in captions),
             f"a quiet caption names each stage: {captions}")
    drawn = [x for x in samples if x["staged"] and x["screen"] == "designing"]
    ui.check(drawn and (max(x["clay"] for x in drawn) > 40 or _light(ui)), f"the stage is on screen before the design exists")
    last = next((i for i, x in enumerate(samples) if x["stage"] == "tower"), None)
    ui.check(last is not None and any(x["screen"] == "designing" and x["revealing"] for x in samples[last:]),
             "the last stage grows in on the being-designed screen before the saved design takes over")
    first = next(i for i, x in enumerate(samples) if x["staged"])
    run = [x for x in samples[first:] if x["vp"]]
    print(f"  {len(run)} frames from the first stage, clay {min(x['clay'] for x in run)}..{max(x['clay'] for x in run)}, "
          f"screens {sorted({x['screen'] for x in run})}", flush=True)
    if not _light(ui):                                   # the pixel classes are tuned for the dark bench
        for i, x in enumerate(run):
            ui.check(x["clear"] <= 17 * 17 * 0.6, f"the middle of the view is never the clear colour (frame {i}: {x})")
        for i in range(1, len(run) - 1):
            a, x, b = run[i - 1]["clay"], run[i]["clay"], run[i + 1]["clay"]
            ui.check(not (min(a, b) >= 20 and x < 0.4 * min(a, b)), f"no blink: clay pixels {a} -> {x} -> {b} at frame {i} ({run[i]['screen']})")
        ui.check(min(x["clay"] for x in run[3:]) >= 12, f"the part never leaves the view: {[x['clay'] for x in run]}")
    ui.check(ui.js(HEAD) is True, "the head model is drawn")
    ui.check(ui.js("Store.viewer._hold.length === 0 && !Store.viewer.revealing && Store.building === null") is True,
             "nothing is held or still building after the hand-over")
    after = [x for x in samples if x["screen"] == "work" and x["pid"] == samples[-1]["pid"]]
    ui.check(not any(x["revealing"] for x in after), "the saved design is not grown in a second time")
    ui.eq(ui.js("Store.view.mesh.map(function (m) { return m.feature }).filter(function (f, i, a) { return a.indexOf(f) === i })"),
          ["body", "bore", "tower"], "the saved design has the features that built")


def journey_stages_stream_then_the_saved_design(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home and its composer")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(400)
    ui.click("startText")
    ui.wait_until(lambda: ui.item("startText").property("activeFocus"), 3, "the composer to take the keyboard")
    # the agent takes 1.6 s per feature on the machine the journey was written on, and as much longer as this one is
    # slower: a stage has to be meshed and drawn before the next arrives, and that takes longer there too
    ui.type("A block with a bore and a tower, built in stages pause %.1f" % (1.6 * ui.slow))
    ui.key("Return")
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the workspace to open in its being-designed state")
    samples, shots = _stream(ui, "new")
    pid = ui.store.get("pid")
    ui.check(pid, "the saved design is open")
    _check_stream(ui, samples, ui.js("Store.stageLog"), ui.api("/projects/" + pid)["project"]["created"])
    # the feature left out is a calm line in the conversation with the measured reason, not an error
    tools = ui.js("Store.chatTools")
    left = [r for r in tools.values() if r.get("left_out")]
    ui.check(left and left[0]["left_out"][0]["feature"] == "rounded_top" and "40 mm" in left[0]["left_out"][0]["reason"]
             and "12 mm" in left[0]["left_out"][0]["reason"], f"the result names what was left out and why: {left}")
    ui.check(all(r.get("ok") for r in tools.values()), "no tool step failed")
    ui.wait_until(lambda: ui.exists("leftOut"), 10, "the left-out line in the conversation")
    ui.check(not any(e.get("t") == "error" for e in ui.js("Store.chatItems")), "no error in the conversation")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 30, "the reply to end")
    shots.append(str(ui.shot("stages-new-" + ("light-" if _light(ui) else "") + "left-out-line")))
    # the saved revision is partial: a calm badge in the header, and the feature list marks the feature left out
    # with the whole measured reason
    ui.wait_until(lambda: ui.exists("partialBadge"), 10, "the partial badge beside the revision in the header")
    why = ui.js("Store.leftOutReason(Store.leftOut('rounded_top'))")
    ui.check(why and "40 mm" in why and not why.endswith("…"), f"the feature list has the whole reason: {why!r}")
    ui.check(ui.js("Store.leftOut('body') === null && Store.leftOut('bore') === null") is True,
             "features that built are not marked left out")
    shots.append(str(ui.shot("stages-new-" + ("light-" if _light(ui) else "") + "partial-badge")))
    S["pid"] = pid
    print("  screenshots: " + ", ".join(shots), flush=True)


def journey_a_new_design_while_one_is_open(ui):
    """The person opened the saved design themselves and asks the agent, in its conversation, for another one: the
    workspace hands over to the being-designed view and the new design's stages are drawn there too."""
    pid = S["pid"]
    ui.run_js("Store.open(%r)" % pid)                   # opened by the person: steered
    ui.wait_until(lambda: ui.js("Store.screen === 'work' && Store.pid === %r && !!Store.view" % pid), 30, "the design to open")
    ui.settle(800)
    ui.check(ui.js("Store.steered") is True, "the person is working on the open design")
    ui.run_js("Store.talkOpen = true")
    n0 = len(ui.js("Store.stageLog"))
    ui.wait_until(lambda: ui.exists("talk"), 5, "the conversation column")
    ui.run_js("Store.send('Make another one built in stages pause %.1f')" % (1.6 * ui.slow))
    samples, shots = _stream(ui, "open", pid_before=pid)
    pid2 = ui.store.get("pid")
    ui.check(pid2 and pid2 != pid, f"the new design is open: {pid2}")
    ui.check(any(x["screen"] == "designing" for x in samples), "the workspace handed over to the being-designed view")
    log = [e for e in ui.js("Store.stageLog")[n0:]]
    _check_stream(ui, samples, log, ui.api("/projects/" + pid2)["project"]["created"])
    print("  screenshots: " + ", ".join(shots), flush=True)
