"""Design refinement, the way a person meets it: the stand-in agent (tests/fixtures/fake_agent.py, "stages") makes a
design through the real create_design tool; its MCP server hands the refinement job to the app's engine (the agent's
process ends with its reply), and the job runs there in the background. The workspace's dock shows the Refinement
panel while it runs, then one row per kept change with its reason; the refined head arrives as one more revision
("Refined: N changes"). Undoing one change makes a new revision without it, and the panel follows. Settings has the
on/off row and the reset of what refinement learned. Run in both appearances (FORM_APPEARANCE=dark, light)."""
DATA = "fresh"
S = {}


def _tag(ui):
    return "light" if ui.js("Theme.dark") is False else "dark"


def journey_a_design_is_refined_in_the_background(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home and its composer")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(400)
    ui.click("startText")
    ui.wait_until(lambda: ui.item("startText").property("activeFocus"), 3, "the composer to take the keyboard")
    ui.type("A block with a bore and a tower, built in stages pause 0.2")
    ui.key("Return")
    ui.wait_until(lambda: ui.js("Store.screen === 'work' && !!Store.pid && !!Store.view"), 240, "the design to open")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 60, "the reply to end")
    pid = S["pid"] = ui.store.get("pid")
    first = ui.api("/projects/" + pid)["project"]["head"]
    # the job: running (the panel says what it tries), then done with the refined head as one more revision
    ui.wait_until(lambda: ui.api("/projects/" + pid + "/refine").get("state") in ("running", "done"), 60,
                  "the refinement job to start in the app's engine")
    if ui.api("/projects/" + pid + "/refine").get("state") == "running":
        ui.wait_until(lambda: ui.exists("refinePanel") and ui.item("refinePanel").property("opacity") > 0.9, 20,
                      "the Refinement panel while it runs")
        ui.shot(f"refine-{_tag(ui)}-1-running")
    ui.wait_until(lambda: ui.api("/projects/" + pid + "/refine").get("state") == "done", 240, "the refinement to end")
    rec = ui.api("/projects/" + pid + "/refine")
    ui.check(rec.get("os_pid") and rec["os_pid"] != 0, f"the job ran in a process: {rec.get('os_pid')}")
    changes = rec.get("changes") or []
    ui.check(len(changes) >= 1, f"refinement kept at least one change: {rec.get('stage')} {rec.get('rejected')}")
    p = ui.api("/projects/" + pid)["project"]
    ui.eq(p["head"], first + 1, "the refinement is one more revision")
    last = p["revisions"][-1]
    ui.eq(last["origin"], "refine", "made by refinement")
    ui.check(last["note"].startswith("Refined: "), f"its note says what it is: {last['note']}")
    ui.wait_until(lambda: ui.js("!!Store.project && Store.project.head === %d" % p["head"]), 20, "the window to show it")
    ui.wait_until(lambda: ui.js("!!Store.refine && (Store.refine.changes || []).length === %d" % len(changes)), 20,
                  "the panel to list the changes")
    ui.wait_until(lambda: ui.item("refinePanel").property("opacity") > 0.9, 5, "the panel to be shown")
    for c in changes:
        ui.check(ui.exists(f"refineChange_{c['id']}"), f"a row for {c['label']}")
        ui.check(ui.exists(f"refineUndo_{c['id']}"), f"with its own undo: {c['label']}")
    ui.check(ui.sees(changes[0]["label"], ui.item("refinePanel")), "the change is named in the panel")
    ui.settle(500)
    ui.shot(f"refine-{_tag(ui)}-2-changes")
    S["head"], S["changes"] = p["head"], changes


def journey_one_change_is_undone(ui):
    pid, c = S["pid"], S["changes"][0]
    ui.click(f"refineUndo_{c['id']}")
    ui.wait_until(lambda: ui.api("/projects/" + pid)["project"]["head"] == S["head"] + 1, 60, "the undo revision")
    rec = ui.api("/projects/" + pid + "/refine")
    ui.check(c["id"] not in [x["id"] for x in rec.get("changes") or []], f"{c['id']} is gone from the head")
    ui.wait_until(lambda: ui.js("!!Store.refine && !(Store.refine.changes || []).some(function (x) { return x.id === %r })"
                                % c["id"]), 20, "the panel to follow")
    p = ui.api("/projects/" + pid)["project"]
    ui.check(p["revisions"][-1]["note"].startswith("Undid refinement"), p["revisions"][-1]["note"])
    ui.settle(1500)
    ui.eq(ui.api("/projects/" + pid)["project"]["head"], S["head"] + 1, "the undo does not start a refinement of its own")
    ui.shot(f"refine-{_tag(ui)}-3-undone")


def journey_settings_turn_it_off_and_reset_what_it_learned(ui):
    ui.run_js("Store.openSettings('general')")
    ui.wait_until(lambda: ui.exists("settingsRefineLedger"), 10, "the reset row in Settings › General")
    ui.check(ui.sees("Refine every design after it builds"), "the on/off row")
    ui.scroll_to(ui.item("settingsRefineLedger"), 0.5)
    ui.settle(300)
    ui.shot(f"refine-{_tag(ui)}-4-settings")
    ui.click("refineLedgerReset")
    ui.wait_until(lambda: any("Refinement starts fresh" in (t.get("msg") or "") for t in ui.js("Store.toasts") or []),
                  10, "the reset to be said")
