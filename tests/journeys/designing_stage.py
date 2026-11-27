"""While a design is being made (the Designing screen), with a conversation shaped like a real one: a statue scan
that takes a preflight, guides, two refused conversions, a long question with four choices, and four failed builds
(tests/fixtures/fake_agent.py, "statue").

- What the agent is doing ("Being designed", the line, the numbered steps) stands in the middle of the free stage,
  under the key light, at every window size; its running dot belongs to the block.
- The conversation starts as the compact panel at the foot of the window. Once it holds more than that panel shows,
  it becomes the conversation column on the left (the one a workspace has): it glides there, the stage keeps the
  rest, and the block moves to the middle of what is left.
- A question from the agent is readable in full, with every reply chip inside the window.
"""
import os

from PySide6.QtCore import QPointF

DATA = "fresh"
LAX = os.environ.get("FORM_DZ_PROBE") == "1"        # measuring only (before/after pictures): report, never fail


def rect(it):
    p = it.mapToScene(QPointF(0, 0))
    return [p.x(), p.y(), p.x() + it.width(), p.y() + it.height()]


def union(rs):
    return [min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)]


def block(ui):
    """The words on the stage: the caption, the line, the steps and (at the end) the buttons, as one box in window pixels."""
    rs = [rect(ui.item(n)) for n in ("designingCaption", "designingLine", "designingLedger", "designingEnds") if ui.find(n) is not None]
    return union(rs)


def stage(ui):
    """The free stage: left of it the conversation column (when there is one), in window pixels."""
    v = ui.item("designingView")
    return [float(v.property("stageL")), float(v.property("stageR"))]


def say(ui, ok, msg):
    print(("ok   " if ok else "FAIL ") + msg, flush=True)
    if not ok and not LAX:
        ui.check(False, msg)


def centred(ui, tag):
    b, s = block(ui), stage(ui)
    mid, want = (b[0] + b[2]) / 2, (s[0] + s[1]) / 2
    say(ui, abs(mid - want) <= 1.0, f"{tag}: the block's middle {mid:.1f} is the free stage's {want:.1f} (block {b[0]:.0f}..{b[2]:.0f}, stage {s[0]:.0f}..{s[1]:.0f})")
    light = ui.find("designingLight")
    if light is not None:
        lx = float(light.property("poolX")) * light.width()
        say(ui, abs(lx - want) <= 1.0, f"{tag}: the key light {lx:.1f} falls on the same middle")
    dot = ui.find("designingDot")
    if dot is not None:
        d = rect(dot)
        say(ui, b[0] - 0.5 <= d[0] and d[2] <= b[2] + 0.5, f"{tag}: the running dot {d[0]:.0f}..{d[2]:.0f} is inside the block")
    return mid, want


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(500)
    W, H = ui.win.width(), ui.win.height()
    ui.click("startText")
    ui.type("Turn this statue scan into editable CAD")
    ui.key("Return")
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the Designing screen")
    talk = ui.item("talk")

    # ── the first steps: the compact panel at the foot, the block in the middle of the stage ──
    ui.wait_until(lambda: ui.find("designingLedger") is not None and ui.js("Store.chatItems.filter(function (e) { return e.t === 'tool' }).length") >= 1, 20, "the first step")
    t = rect(talk)                                   # measured at once: in a small window it outgrows the panel within a few steps
    say(ui, bool(talk.property("bar")), "the conversation starts as the panel at the foot")
    say(ui, abs((t[0] + t[2]) / 2 - W / 2) <= 1.0 or W < 1200, f"the panel stands on the window's centre line ({t[0]:.0f}..{t[2]:.0f} of {W})")
    centred(ui, "early")
    ui.settle(150)
    ui.shot("dz-early")

    # ── it grows: the question arrives; the conversation is now the column on the left ──
    track = []

    def sample():
        r = rect(talk)
        track.append((r[0], r[1], r[2] - r[0], r[3] - r[1], float(talk.property("opacity"))))
        return bool(ui.store.get("chatAsking")) and not bool(talk.property("bar")) and not bool(talk.property("gliding"))
    try:
        ui.wait_until(sample, 30, "the question, and the conversation in its column")
    except Exception as e:                           # noqa: BLE001
        why = {k: talk.property(k) for k in ("grown", "outgrown", "wantCol", "col", "bar", "gliding", "barHeight", "bodyWant", "sheetMax")}
        say(ui, False, f"the conversation moved to the side once it grew ({e}; {why}; talkOpen {ui.store.get('talkOpen')}, focusView {ui.store.get('focusView')})")
        ui.wait_until(lambda: bool(ui.store.get("chatAsking")), 30, "the question")
    ui.settle(900)
    t = rect(talk)
    s = stage(ui)
    docked = not bool(talk.property("bar"))
    say(ui, docked and t[0] <= 20 and t[3] >= H - 20 and (t[2] - t[0]) <= 480, f"the column is on the left, to the foot of the window ({[round(x) for x in t]})")
    say(ui, t[2] <= s[0] + 0.5, f"the stage begins right of the column ({t[2]:.0f} <= {s[0]:.0f})")
    b = block(ui)
    say(ui, b[0] >= t[2] and b[2] <= W, f"the block is clear of the column ({b[0]:.0f} >= {t[2]:.0f})")
    centred(ui, "docked")
    # the glide: every step goes one way (no jump back, no overshoot)
    for k, name in ((0, "left edge"), (2, "width"), (3, "height")):
        vals = [p[k] for p in track]
        d = [b2 - a for a, b2 in zip(vals, vals[1:]) if abs(b2 - a) > 0.5]
        mono = all(x > 0 for x in d) or all(x < 0 for x in d)
        # the height: the panel may still be opening when the glide starts; one turn at most
        turns = sum(1 for a, b2 in zip(d, d[1:]) if (a > 0) != (b2 > 0))
        say(ui, mono or (k == 3 and turns <= 1), f"the {name} glides one way ({len(d)} steps, {vals[0]:.0f} to {vals[-1]:.0f})")
    # the question: all of it, and its replies, inside the window and inside the column
    card = ui.wait_until(lambda: ui.find("askCard"), 5, "the question card")
    feed = ui.item("talkFeed")
    c, f = rect(card), rect(feed)
    q = ui.find(name="askQuestion", within=card)
    say(ui, q is not None and not q.property("truncated"), "the question is written in full")
    chips = ui.find_all(name="askChoice", within=card)
    say(ui, len(chips) == 4, f"four reply chips ({len(chips)})")
    for ch in chips:
        r = rect(ch)
        label = [x for x in ui.texts(within=ch)][:1]
        lab = ui.find(name="askChoiceLabel", within=ch)
        say(ui, lab is not None and not lab.property("truncated"), f"reply {label} is written in full")
        say(ui, r[0] >= c[0] and r[2] <= c[2] + 0.5 and r[1] >= f[1] - 0.5 and r[3] <= min(f[3], H) + 0.5, f"reply {label} is in view ({[round(x) for x in r]} in feed {[round(x) for x in f]})")
    if c[3] - c[1] <= f[3] - f[1] - 28:              # (the feed's own margins)
        say(ui, c[1] >= f[1] - 0.5 and c[3] <= f[3] + 0.5, f"the whole card is in view ({c[1]:.0f}..{c[3]:.0f} in {f[1]:.0f}..{f[3]:.0f})")
    else:
        # a long question in a low window is taller than the column: its replies and answer field stay in view, and
        # the top of the question is one scroll away (the feed is pinned to its end)
        print(f"note the card ({c[3] - c[1]:.0f} px) is taller than the column's feed ({f[3] - f[1]:.0f} px) at {W}x{H}: {f[1] - c[1]:.0f} px of its top are a scroll away", flush=True)
        say(ui, c[3] <= f[3] + 0.5 and bool(feed.property("stick")), f"the card's foot (replies, answer field) is in view ({c[1]:.0f}..{c[3]:.0f} in {f[1]:.0f}..{f[3]:.0f}, atYEnd {feed.property('atYEnd')}, stick {feed.property('stick')})")
        say(ui, f[1] - c[1] <= 130, f"the question still reads from near its start ({f[1] - c[1]:.0f} px)")
    ui.shot("dz-ask")

    # ── answered: the run goes on (failed builds), the column stays, the block stays in the middle ──
    if chips:                                        # where it stands (it is in view: no scrolling first)
        r = rect(chips[-1])
        ui.click((round((r[0] + r[2]) / 2), round((r[1] + r[3]) / 2)))
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 60, "the end of the run")
    ui.settle(900)
    say(ui, not bool(talk.property("bar")), "the column stays to the end of the run")
    centred(ui, "done")
    ui.shot("dz-done")
    # folded by hand (Ctrl+J) it is the panel again, and the block is back on the window's middle
    ui.run_js("Store.toggleTalk()")
    ui.wait_until(lambda: bool(talk.property("bar")) and not bool(talk.property("gliding")), 5, "the panel again")
    ui.settle(900)
    centred(ui, "folded")
    ui.shot("dz-folded")
    ui.run_js("Store.toggleTalk()")
    ui.settle(900)
    ui.no_warnings()
