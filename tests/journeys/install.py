"""Hands-free first start: setup starts by itself, every command is in the log, it stops only for what the person must
do (here: sign in), and Skip lets it go on.

Environment the test suite sets (test_install_flow): FORM_INSTALL_FAKE (every command is a stand-in; sign-in ends by
itself after that many seconds), FORM_SETUP_PRETEND_MISSING=parts,claude.signin and auto setup allowed."""
DATA = "empty"


def run(ui):
    ui.wait_until(lambda: ui.store.get("welcome") is True, 30, "the first-run screen")
    job = ui.wait_until(lambda: ui.js("Store.installJob && Store.installJob.kind === 'auto' ? Store.installJob : null"), 60,
                        "the hands-free setup to start by itself")
    ids = [s["id"] for s in job["steps"]]
    ui.check("claude" not in ids, f"no agent is installed by itself; choosing one is the last step: {ids}")
    if (ui.js("Store.softwareItem('claude')") or {}).get("status") != "ok":
        ui.check("parts" in ids and "claude.signin" not in ids, f"what it sets up without Claude Code here: {ids}")
        return                                       # the sign-in pause below needs an installed Claude Code
    ui.check("parts" in ids and "claude.signin" in ids, f"what it sets up: {ids}")
    ui.check(not any(i.startswith("agent.") and i != "agent.claude" for i in ids), "other agents are never edited by itself")
    ui.expect("Setting up", timeout=20)
    # it stops for the sign-in and says so
    ui.wait_until(lambda: ui.find(name="installYourTurn") is not None, 60, "the sign-in pause")
    ui.expect("Sign in to continue")
    ui.expect("Waiting for you")
    ui.shot("install-your-turn")
    w = ui.js("Store.installJob.waiting_for_you")
    ui.eq((w["id"], w["action"]["kind"]), ("claude.signin", "signin"), "waiting for the sign-in")
    ui.click_text("Skip this")
    ui.wait_until(lambda: ui.js("Store.installJob.state") != "running", 60, "the setup to finish")
    steps = {s["id"]: s["state"] for s in ui.js("Store.installJob.steps")}
    ui.eq(steps.get("parts"), "done", "the libraries were (simulated) installed without a question")
    ui.eq(steps.get("claude.signin"), "skipped", "the sign-in was skipped")
    ui.eq(ui.js("Store.installJob.state"), "done", "skipping is not a failure")
    log = " ".join(l["text"] for l in ui.js("Store.installLog"))
    ui.check("FORM_INSTALL_FAKE" in log, "the log says the commands were stand-ins")
    ui.settle(400)
    ui.shot("install-done")
