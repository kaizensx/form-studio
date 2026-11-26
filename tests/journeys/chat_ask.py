"""The agent asks, you answer; it offers follow-ups; a failure goes to the agent with one click; a conversation about
a design opens that design. A stand-in agent CLI (tests/fixtures/fake_agent.py) plays the agent and Form Studio's
ask_user tool through the same files the real tool uses (form/ask.py). No model is called."""
from _lib import make

DATA = "fresh"


def send(ui, text):
    ui.click("composer")
    ui.type(text)
    ui.key("Return")


def idle(ui, what):
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 30, what)
    ui.settle(300)


def asking(ui):
    return ui.wait_until(lambda: ui.store.get("chatAsking"), 20, "the agent's question to arrive")


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    pid = make(ui, "dock", "Desk dock")

    # ── a question with choices: one click answers, and the agent carries on with it ──
    send(ui, "Please ask me about the phone")
    q = asking(ui)
    ui.eq(q["choices"], ["9 mm", "11 mm", "13 mm"])
    card = ui.wait_until(lambda: ui.find("askCard"), 5, "the question card")
    ui.expect("How thick is the phone with its case?")
    ui.expect("Waiting for you")
    ui.settle(400)
    ui.shot("ask-card")
    chips = ui.find_all(name="askChoice", within=card)
    ui.eq(len(chips), 3, "one chip per choice")
    ui.click(chips[1])
    idle(ui, "the reply after the answer")
    ui.expect("You answered: 11 mm")
    ui.check(ui.store.get("chatAsking") is None, "nothing is waiting any more")
    ui.check(ui.exists("askAnswer"), "the card keeps what you answered")
    items = ui.js("Store.chatItems.filter(function (i) { return i.t === 'answer' })")
    ui.eq(items[-1]["choices"], ["11 mm"], "the answer is saved in the conversation")
    ui.shot("ask-answered")

    # ── an open question, answered from the composer ──
    send(ui, "ask me in words")
    asking(ui)
    ui.wait_until(lambda: "Answer the question" in (ui.item("composer").property("placeholder") or ""), 5, "the composer to offer the answer")
    send(ui, "75.6 measured with calipers")
    idle(ui, "the reply after a typed answer")
    ui.expect("You answered: 75.6 measured with calipers")

    # ── an approval card: the first action is the primary one ──
    send(ui, "ask me to approve the replacement")
    asking(ui)
    ui.expect("Needs your approval")
    ui.settle(300)
    ui.shot("ask-approval")
    btn = ui.wait_until(lambda: [b for b in ui.find_all(name="askChoice") if b.property("text") == "Keep the current one"], 5, "the approval buttons")[0]
    ui.click(btn)
    idle(ui, "the reply after the approval")
    ui.expect("You answered: Keep the current one")

    # ── follow-ups offered by the agent: one click sends it ──
    send(ui, "suggest what next")
    idle(ui, "the reply with follow-ups")
    chip = lambda: [c for c in ui.find_all(name="suggestChip") if "Show me the bottom" in " ".join(ui.texts(c))]
    ui.wait_until(chip, 5, "the follow-up chips")
    ui.settle(500)
    ui.shot("chat-suggestions")
    # the last line of the feed sits at its very bottom, where scrolling it "into view" would move it: click it where it is
    from PySide6.QtCore import QPointF
    c = chip()[0]
    p = c.mapToScene(QPointF(c.width() / 2, c.height() / 2))
    ui.click((p.x(), p.y()))
    ui.wait_until(lambda: ui.sees("You said: Show me the bottom"), 30, "the follow-up to be sent")
    idle(ui, "the follow-up reply")
    ui.check(not ui.exists("suggestChip"), "follow-ups go away once you write again")
    conv = ui.store.get("convId")

    # ── Fix with the agent: a draft that does not build ──
    ui.run_js("Store.setParam('cable_diameter', 12, true)")
    ui.wait_until(lambda: ui.store.get("draftError"), 30, "the draft error")
    fix = ui.wait_until(lambda: ui.find("fixBtn"), 5, "the Fix button")
    ui.check("Test agent" in fix.property("text"), "the button names the agent")
    ui.settle(300)
    ui.shot("fix-button")
    n = len(ui.js("Store.chatItems.filter(function (i) { return i.t === 'user' })"))
    ui.click(fix)
    ui.wait_until(lambda: len(ui.js("Store.chatItems.filter(function (i) { return i.t === 'user' })")) == n + 1, 10, "the fix message")
    sent = ui.js("Store.chatItems.filter(function (i) { return i.t === 'user' })")[-1]["text"]
    ui.check("this draft does not build" in sent and "Cable channel" in sent and "cable_diameter" in sent,
             "the message carries the failure word for word: " + sent[:200])
    ui.eq(ui.store.get("convId"), conv, "it goes to this design's conversation")
    idle(ui, "the agent's answer to the fix")
    ui.run_js("Store.discard()")

    # ── what a reply changed: compare it, go back ──
    ui.wait_until(lambda: not ui.store.get("hasDraft"), 10, "the draft to be discarded")
    r = ui.api("/projects/" + pid + "/commit", {"values": {"lean": 18}, "note": "steeper", "origin": "agent:test"})
    ui.wait_until(lambda: ui.api("/projects/" + pid)["project"]["head"] == r["head"], 30, "the commit")
    ui.run_js("Store.refresh(true)")
    # the reply footer the engine writes when a run moved the head (form/chat.py adds `change` to the end event)
    ui.run_js("Store.chatItems = Store.chatItems.concat([{ t: 'end', steps: 2, seconds: 4, cost_usd: 0.1, local: true, "
              "change: { project: %r, from: 1, to: %d } }])" % (pid, r["head"]))
    card = ui.wait_until(lambda: ui.find("changeCard"), 5, "the change card")
    ui.settle(400)
    ui.shot("chat-change")
    ui.click(ui.find("changeCompare", within=card))
    ui.wait_until(lambda: ui.js("!!Store.compare && Store.compare.rev === 1"), 20, "the comparison with r01")
    ui.click(ui.find("changeUndo", within=card))
    for attempt in range(3):              # the confirmation slides in: click once it has settled, again if it missed
        yes = ui.wait_until(lambda: ui.find("changeUndoYes", within=card), 5, "the confirmation")
        ui.settle(350)
        if yes.property("visible"):
            ui.click(yes)
        try:
            ui.wait_until(lambda: ui.api("/projects/" + pid)["project"]["head"] == 1, 8 if attempt < 2 else 20, "the head to go back to r01")
            break
        except Exception:
            if attempt == 2:
                raise
    ui.settle(300)

    # ── opening a conversation opens its design ──
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.store.get("pid") == "", 10, "Home")
    rows = lambda: [r for r in ui.find_all(name="homeConversation") if r.property("modelData")["id"] == conv]
    ui.wait_until(rows, 10, "the conversation on Home")
    ui.settle(1500)                                  # Home lays itself out (its cards arrive one by one)
    ui.click(rows()[0])
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pid, 30, "the design to open with its conversation")
    ui.wait_until(lambda: ui.js("!!Store.view"), 30, "the model")
    ui.eq(ui.store.get("convId"), conv)
    ui.settle(600)
    ui.shot("conversation-opens-design")
    ui.no_warnings()
