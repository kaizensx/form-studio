"""One conversation at a time on screen. While conversation B's design is open, conversation A's agent builds a new
design stage by stage and saves it: nothing of A is drawn in B's view, the open design and the screen stay as they
are, and a calm note says that A is working, with Show to open A. Concepts the agent proposes are shown in the
conversation as a card with a picture of each and Pick, and the agent rendering one of them a moment later never
takes the concepts sheet away or opens that concept. A design made for printing names its printer in the top bar and
stands on its build plate from Describe on; a 3D model shows neither.

The stand-in agent (tests/fixtures/fake_agent.py) plays both conversations: "stages" calls Form Studio's real
create_design MCP tool, so its activity carries the conversation the way a real run does ($FORM_CONVERSATION)."""
import time

from _lib import DOCK, goto, make, plate_toggle, printing_on, toasts_gone

DATA = "fresh"
S = {}


def conv(ui, title, designs, project):
    m = ui.api("/conversations", {"project": project, "agent": "fake"})
    store = ui.studio.chat.store
    store.append(m["id"], {"t": "user", "text": title})
    store.append(m["id"], {"t": "end", "steps": 1, "seconds": 1})
    store.update(m["id"], title=title, title_auto=False, messages=1, events=2, project=project,
                 designs=[{"project": p, "role": "made", "ts": time.time(), "state": "live"} for p in designs])
    return m["id"]


def both_looks(ui, name):
    """A picture in the dark bench and one in the light bench."""
    ui.settle(500)
    ui.shot(name + "-dark")
    ui.run_js("Theme.setAppearance('light')")
    ui.wait_until(lambda: ui.js("Theme.dark") is False, 3, "the light appearance")
    ui.settle(700)
    ui.shot(name + "-light")
    ui.run_js("Theme.setAppearance('dark')")
    ui.wait_until(lambda: ui.js("Theme.dark") is True, 3, "the dark appearance")
    ui.settle(400)


STATE = "[Store.pid, Store.screen, Store.convId, !!Store.building, Store.stageLog.length, Store.agentElsewhere]"


def journey_another_conversation_never_takes_over(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    b = make(ui, "coupon", "Wallet base", open=False)
    cb = conv(ui, "The wallet base", [b], b)
    ui.run_js("Store.reloadStudio().then(function () { Store.loadConvs().then(function () { Store.openConv(%r) }) })" % cb)
    ui.wait_until(lambda: ui.js("Store.screen === 'work' && Store.pid === %r && !!Store.view && Store.convId === %r" % (b, cb)),
                  30, "conversation B's design")
    ui.settle(800)
    ui.check(ui.js("Store.steered") is False, "opened by its conversation: the case where follow used to jump")
    log0 = ui.js("Store.stageLog.length")
    r = ui.api("/conversations/send", {"message": "A block built in stages pause 0.8", "agent": "fake", "model": "default"})
    ca = r["conversation"]
    ui.check(ca and ca != cb, f"conversation A runs beside B: {r}")
    samples, t_end, made = [], time.time() + 180, None
    while time.time() < t_end:
        st = ui.js(STATE)
        samples.append(st)
        ui.eq(st[0], b, "the open design stays B's while A works")
        ui.eq(st[1], "work", "the screen stays the workspace")
        ui.eq(st[2], cb, "conversation B stays open")
        ui.check(st[3] is False and st[4] == log0, f"none of A's stages is drawn in B's view: {st}")
        m = ui.api("/conversations/" + ca)
        if m.get("state") not in ("running", "asking") and m.get("project"):
            made = m["project"]
            break
        ui.wait(100)
    ui.check(made, "conversation A saved its design")
    ui.settle(2500)                                   # the commit and the last stages are polled too
    st = ui.js(STATE)
    ui.eq(st[0], b, "still B's design after A saved its own")
    ui.eq(st[1], "work", "still the workspace")
    ui.check(st[4] == log0, "nothing of A was drawn")
    a = ui.js("Store.agentElsewhere")
    ui.check(a and a.get("conversation") == ca, f"the note names conversation A: {a}")
    ui.wait_until(lambda: ui.exists("agentElsewhere"), 5, "the calm note over the view")
    ui.wait_until(lambda: ui.js("Store.agentElsewhere.name") == "Staged block", 10, "the note names A's saved design")
    a = ui.js("Store.agentElsewhere")
    print(f"  {len(samples)} samples while A worked; note: {a}", flush=True)
    both_looks(ui, "wpA-elsewhere-note")
    ui.click("agentElsewhereShow")
    ui.wait_until(lambda: ui.js("Store.convId === %r && Store.pid === %r && Store.screen === 'work'" % (ca, made)), 20,
                  "Show opens conversation A on its design")
    ui.check(ui.js("Store.agentElsewhere") is None, "the note goes once it is opened")
    S["made"] = made


def journey_concepts_in_the_conversation(ui):
    toasts_gone(ui)
    ui.run_js("Store.startNew()")
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home")
    ui.settle(500)
    ui.run_js("Store.startDesign('concepts for a desk hook, then look at one')")
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the being-designed view")
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "concepts", 240, "the concepts sheet")
    gid = ui.js("Store.sheet.props.group")
    seen = []
    while ui.store.get("chatBusy"):                    # the agent renders concept B a few seconds later
        st = ui.js("[Store.sheet ? Store.sheet.kind : '', Store.screen, Store.pid]")
        seen.append(st)
        ui.eq(st[0], "concepts", "the concepts sheet stays open while the agent looks at a concept")
        ui.eq(st[2], "", "no concept is opened behind it")
        ui.wait(100)
    ui.settle(1500)
    ui.eq(ui.js("Store.sheet ? Store.sheet.kind : ''"), "concepts", "still open after the reply")
    ui.eq(ui.store.get("pid"), "", "no concept workspace")
    looks = [e for e in ui.api("/activity?since=0")["events"] if e.get("kind") == "look" and e.get("conversation") == ui.store.get("convId")]
    ui.check(looks, "the agent did look at a concept (a stamped look event)")
    card = ui.wait_until(lambda: ui.find(name="chatConcepts", within=ui.item("talk")), 10, "the concepts card in the conversation")
    tiles = ui.wait_until(lambda: (lambda x: x if len(x) == 3 else None)(ui.find_all(name="chatConcept", within=card)), 10, "three concepts in the card")
    print(f"  {len(seen)} samples while the agent looked; group {gid}", flush=True)
    ui.click("conceptsNotNow")
    ui.wait_until(lambda: ui.store.get("sheet") is None, 4, "the sheet closed")
    ui.settle(2500)                                    # the pictures arrive
    both_looks(ui, "wpA-concepts-card")
    board = ui.api("/concepts/" + gid)
    pick = board["members"][2]["project"]
    ui.click(ui.find_all(name="chatConceptPick", within=tiles[2])[0])
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pick, 60, "Pick in the card continues with it")
    ui.eq(ui.api("/concepts/" + gid)["state"], "picked")


def journey_print_design_names_its_printer(ui):
    toasts_gone(ui)
    printing_on(ui)
    m = make(ui, "storage_box", "Desk tray")               # a 3D model: no printer, no plate
    goto(ui, "brief")
    ui.settle(500)
    ui.check(ui.find(name="printerChip") is None, "a 3D model names no printer")
    ui.check(ui.js("!!Store.viewer && Store.viewer.plateShown") is False, "a 3D model has no plate")
    ui.click("stage-shape")                            # (as ground.py does: the next design opens from Design)
    ui.wait_until(lambda: ui.store.get("stage") == "shape", 3, "Design")
    p = make(ui, "dock", "Hallway phone dock", DOCK, purpose="print")
    for sid in ("shape", "fit", "prove", "release", "document"):
        goto(ui, sid)
        if sid == "release":                           # the printer is a property of the print route: named in Make only
            ui.wait_until(lambda: ui.find(name="printerChip", within=ui.item("topBar")) is not None, 5, "the printer in the top bar in Make")
        else:
            ui.check(ui.find(name="printerChip") is None, f"no printer in the top bar in {sid}")
        ui.wait_until(lambda: ui.js("!!Store.viewer && Store.viewer.plateShown") is True, 5, f"the build plate in {sid}")
    goto(ui, "shape")
    ui.settle(800)
    both_looks(ui, "wpA-print-brief")
    plate_toggle(ui)                                   # it can still be hidden in Design
    ui.wait_until(lambda: ui.js("Store.viewer.plateShown") is False, 3, "the plate hidden on request")
    plate_toggle(ui)
    ui.wait_until(lambda: ui.js("Store.viewer.plateShown") is True, 3, "and back")
    ui.check(p and m, "both designs exist")
    ui.no_warnings()
