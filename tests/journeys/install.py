"""The launcher's install run: nothing starts by itself; the last step installs only what was chosen, every command is
in the log, it stops only for what the person must do (here: sign in), and Skip lets it go on.

Environment the test suite sets (test_install_flow): FORM_INSTALL_FAKE (every command is a stand-in; sign-in ends by
itself after that many seconds), FORM_SETUP_PRETEND_MISSING=parts,claude.signin and setup runs allowed."""
DATA = "empty"


def run(ui):
    ui.wait_until(lambda: ui.store.get("welcome") is True, 30, "the first-run screen")
    ui.wait_until(lambda: ui.store.get("software") is not None and ui.js("!!Store.caps"), 90, "the software check")
    ui.idle(1500)
    ui.check(not ui.js("Store.installJob"), "nothing is installed before the person chose what to set up")
    # 1 what to make: the defaults (parametric CAD, mechanical parts, mesh to CAD; no printing)
    ui.click_text("Continue")
    ui.expect("Step 2 of 3")
    ui.check(not any(ui.js("Store.installPick[%r]" % i) for i in ("agent.codex", "agent.gemini", "agent.cursor", "agent.desktop")),
             "other agents' settings start unticked")
    ui.click_text("Continue")
    ui.expect("Step 3 of 3")
    ids = ui.api("/capabilities")["install"]
    ui.check("parts" in ids, f"the parts libraries the person chose are in the run: {ids}")
    ui.check("claude" not in ids and not any(i.startswith("slicer.") for i in ids), f"no agent app and no slicer: {ids}")
    ticked = ui.js("Store.installChosen")             # agent apps and integrations ticked in step 2 are listed too
    ui.settle(300)
    ui.shot("install-step3-list")
    ui.click("welcomePrimary")
    job = ui.wait_until(lambda: ui.js("Store.installJob && Store.installJob.kind === 'auto' ? Store.installJob : null"), 30,
                        "the setup run to start")
    steps = [s["id"] for s in job["steps"]]
    ui.check(set(ids) <= set(steps) and set(steps) <= set(ids) | set(ticked), f"exactly what the list showed: {steps}")
    ui.expect("Setting up", timeout=20)
    if "claude.signin" not in steps:                 # the sign-in pause below needs an installed Claude Code
        ui.wait_until(lambda: ui.js("Store.installJob.state") != "running", 60, "the setup to finish")
        ui.eq({s["id"]: s["state"] for s in ui.js("Store.installJob.steps")}.get("parts"), "done", "the libraries were (simulated) installed")
        ui.settle(400)
        ui.shot("install-done")
        return
    ui.check(all(i in ids or i in ticked for i in steps), "nothing that was not listed")
    # it stops for the sign-in and says so
    ui.wait_until(lambda: ui.find(name="installYourTurn") is not None, 60, "the sign-in pause")
    ui.expect("Sign in to continue")
    ui.expect("Waiting for you")
    ui.shot("install-your-turn")
    w = ui.js("Store.installJob.waiting_for_you")
    ui.eq((w["id"], w["action"]["kind"]), ("claude.signin", "signin"), "waiting for the sign-in")
    ui.click_text("Skip this")
    ui.wait_until(lambda: ui.js("Store.installJob.state") != "running", 60, "the setup to finish")
    states = {s["id"]: s["state"] for s in ui.js("Store.installJob.steps")}
    ui.eq(states.get("parts"), "done", "the libraries were (simulated) installed without a question")
    ui.eq(states.get("claude.signin"), "skipped", "the sign-in was skipped")
    ui.eq(ui.js("Store.installJob.state"), "done", "skipping is not a failure")
    log = " ".join(l["text"] for l in ui.js("Store.installLog"))
    ui.check("FORM_INSTALL_FAKE" in log, "the log says the commands were stand-ins")
    ui.settle(400)
    ui.shot("install-done")
