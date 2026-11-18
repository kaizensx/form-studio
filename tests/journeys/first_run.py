"""First run on an empty data folder: onboarding, the empty Home, an example opens."""
DATA = "empty"


def run(ui):
    ui.wait_until(lambda: ui.store.get("welcome") is True, 30, "the first-run screen")
    ui.expect("Three short steps")
    ui.eq(ui.api("/studio")["projects"], [], "a new data folder starts with no projects")
    for n, step in enumerate(("Step 1 of 3", "Step 2 of 3", "Step 3 of 3")):
        ui.expect(step)
        # the primary button reads Checking… until the software list has loaded
        ui.wait_until(lambda: ui.store.get("software") is not None, 90, "the software check")
        if n == 0:
            ui.shot("first-run-step1")
        # nothing is installed in a test: untick whatever the step pre-selected
        ui.run_js("Store.installPick = ({})")
        ui.wait(120)
        if n < 2:
            ui.click_text("Continue")
            ui.settle()
    ui.eq(ui.store.get("onboardStep"), 2, "the step reached is remembered")
    ui.wait_until(lambda: ui.api("/setup/state")["onboarding"]["step"] == 2, 5, "the engine to save the step")
    ui.click_text("Back")
    ui.settle()
    ui.expect("Step 2 of 3")
    ui.click_text("Continue")
    ui.settle()
    ui.click_text("Open Form Studio")
    ui.wait_until(lambda: ui.store.get("welcome") is False, 5, "the first-run screen to close")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.api("/setup/state")["first_run"] is False, 5, "the engine to remember that setup was seen")
    ui.settle(400)
    ui.shot("first-run-home-empty")
    ui.check(ui.exists("startComposer"), "the empty Home is the composer")
    ui.click_text("Import…")
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "import", 5, "the Import sheet")
    ui.settle()
    ex = ui.wait_until(lambda: ui.find_all(name="exampleAdd"), 10, "the example list")
    ui.shot("first-run-examples")
    ui.click(ex[0])
    ui.wait_until(lambda: ui.store.get("screen") == "work", 120, "the example project to open")
    pid = ui.store.get("pid")
    ui.check(pid and any(p["id"] == pid for p in ui.api("/studio")["projects"]), "the example exists in the engine")
    # the pipeline starts a moment after the design opens: wait for it to finish, not for "nothing running yet"
    ui.wait_until(lambda: all(v["state"] in ("current", "failed") or v.get("unavailable")
                              for v in ui.api("/projects/" + pid)["status"].values()), 300, "the example's pipeline")
    ui.idle(300)
    st = ui.api("/projects/" + pid)["status"]
    ui.check(all(v["state"] == "current" or v.get("unavailable") for v in st.values()), f"the pipeline finished: {st}")
    ui.eq(ui.store.get("sheet"), None, "the sheet closed")
    ui.settle(600)
    ui.shot("first-run-example-open")
