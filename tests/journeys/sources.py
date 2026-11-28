"""A conversation that proves itself, with the stand-in agent (tests/fixtures/fake_agent.py; no model is called):
Sources built from the turn's tool log with their evidence words, the reply's numbers marked with a source's index,
the plan card and its approval, the live status line, the note of what was changed by hand, a saved prompt in the
palette."""

DATA = "fresh"


def send(ui, text):
    ui.click("composer")
    ui.type(text)
    ui.key("Return")


def reply(ui, words, timeout=30):
    ui.wait_until(lambda: not ui.store.get("chatBusy") and any(words in t for t in ui.texts(within="talkFeed")), timeout, f"the reply “{words}”")


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chat.available && Store.chatReady"), 20, "the stand-in agent to be connected")

    # ---- Sources: three tool calls are sources; the guide (no evidence class) and the failed study are not ----
    send(ui, "cite the strength")
    reply(ui, "Peak stress")
    card = ui.item("sourcesCard", timeout=10)
    rows = ui.find_all("sourceRow", within=card)
    ui.eq(len(rows), 3, "one row per tool call that is a source")
    ui.eq([r.property("how") for r in rows], ["simulated", "specified", "opened"], "the evidence class of each result")
    said = ui.texts(within=card)
    for want in ("Sources", "3 · from the tool log", "Strength, static on r07", "6061-T6 yield, material library", "nema-ics16.pdf, page 4"):
        ui.check(any(want.lower() == t.lower() or want in t for t in said), f"the Sources block says “{want}”: {said}")
    ui.check(not any("guide" in t.lower() or "converge" in t.lower() for t in said), f"nothing without an evidence class, nothing that failed: {said}")
    # the reply's numbers: 14.2 and 19.4 stand in the study's result (1), 276.0 in the material's (2); 250 stands in none
    html = ui.item("replyText").property("text")
    ui.check("14.2&nbsp;MPa&nbsp;</span><sup>" in html and "276.0&nbsp;MPa&nbsp;</span><sup>" in html and "19.4&nbsp;</span><sup>" in html, f"the numbers that stand in a result carry its index: {html[-600:]}")
    ui.check("250<sup>" not in html and "250 N<sup>" not in html, "a number no result holds is not marked")
    ui.eq(html.count("<sup>"), 3, "three marks, one per number")
    saved = ui.api("/conversations/" + ui.store.get("convId"))
    srcs = [e["source"] for e in saved["items"] if e.get("t") == "result" and e.get("source")]
    ui.eq([s["how"] for s in srcs], ["simulated", "specified", "opened"], "the sources are saved with the tool results they came from")
    ui.shot("sources")

    # a reply that states a figure with no tool result behind it says so: model knowledge, without a number
    send(ui, "the yield is 276.5 MPa")
    reply(ui, "You said: the yield is 276.5 MPa")
    card = ui.find_all("sourcesCard")[-1]
    rows = ui.find_all("sourceRow", within=card)
    ui.eq([r.property("how") for r in rows], ["model knowledge"], "the one row says where the figure comes from")
    ui.check(ui.sees("0 · from the tool log", within=card), f"nothing from the tool log is counted: {ui.texts(within=card)}")

    # ---- the plan card: the steps of plan_design; the approval the agent asks for is answered on it ----
    send(ui, "plan card for the mount")
    plan = ui.item("planCard", timeout=15)
    ui.wait_until(lambda: plan.property("waiting"), 15, "the plan to wait for an answer")
    ui.eq(len(ui.find_all("planStep", within=plan)), 4, "the four steps of the plan")
    ui.check(ui.sees("Base plate with two M5 slots for the rail", within=plan) and ui.sees("waits for you", within=plan))
    ui.check(not ui.exists("askCard"), "the approval is on the plan card, not a second card")
    ui.shot("plan-waits")
    ui.click("planApprove")
    reply(ui, "You answered: Approve")
    plan = ui.find_all("planCard")[-1]
    ui.check(ui.sees("approved by you", within=plan), f"the card says who approved: {ui.texts(within=plan)}")
    ui.check(not ui.exists("planApprove"), "an answered plan has no buttons")

    # a plan nobody was asked about is the plan and nothing more
    send(ui, "plan card quiet mount")
    reply(ui, "You said: plan card quiet mount")
    plan = ui.find_all("planCard")[-1]
    ui.check(ui.sees("4 steps", within=plan) and not ui.sees("approved by you", within=plan), f"no claim of approval: {ui.texts(within=plan)}")

    # ---- the live status line: the dot, what happens, the step ----
    send(ui, "slow one")
    ui.item("liveStatus", timeout=10)
    ui.wait_until(lambda: ui.item("liveSay").property("text") != "", 10, "the status to say something")
    ui.shot("live")
    ui.click("sendBtn")
    ui.wait_until(lambda: not ui.store.get("chatBusy"), 20, "the reply to stop")

    # ---- by hand since the last reply: one note in the column, and the agent reads it with the next message ----
    cid = ui.store.get("convId")
    for n, text in ((2, "Added Fillet 1: 2 edges, r 2 mm"), (3, "Added Edge chamfers: 0.8 mm on 2 edges")):
        ui.studio.chat.store.append(cid, {"t": "act", "by": "You", "text": text, "change": {"project": "by-hand", "from": n - 1, "to": n}})
    ui.run_js("Store._chatTick()")
    note = ui.item("handNoteText", timeout=10)
    ui.check("By hand since the last reply:" in note.property("text") and "Edge chamfers" in note.property("text") and "(r03)" in note.property("text"), note.property("text"))
    ui.eq(len(ui.find_all("handNote")), 1, "the edits of one stretch are one note")
    ui.shot("hand-note")
    send(ui, "carry on")
    reply(ui, "I read: Added Fillet 1: 2 edges, r 2 mm (")          # (r02 and r03 are links to the revisions)
    ui.check(any("Added Edge chamfers: 0.8 mm on 2 edges (" in t for t in ui.texts(within="talkFeed")), "both edits reached the agent")

    # ---- a saved prompt: the bookmark on a message of yours; the palette lists it and sends it again ----
    ui.run_js("Store.togglePrompt('cite the strength')")
    ui.eq(ui.js("Store.savedPrompts.length"), 1)
    ui.key("Ctrl+K")
    pal = ui.item("palette", timeout=5)
    ui.check(ui.sees("Saved prompts", within=pal, ) or ui.sees("SAVED PROMPTS", within=pal), f"the palette has the group: {ui.texts(within=pal)[:12]}")
    ui.type("cite the")
    ui.wait_until(lambda: pal.property("selText") == "cite the strength", 5, "the saved prompt to be the best match")
    ui.shot("palette-saved")
    n0 = len(ui.find_all("sourcesCard"))
    ui.key("Return")
    ui.wait_until(lambda: not ui.store.get("chatBusy") and len(ui.find_all("sourcesCard", shown=False)) > n0, 30, "the saved prompt to run again")
    ui.no_warnings()
