"""First run on an empty data folder: the launcher (what do you want to make, your agent, set up), then the empty Home
whose composer is the way to start; a first design is made from a recipe and opens. No examples ship with Form Studio.

Nothing is installed: the journeys run with FORM_NO_AUTO_SETUP=1, and the last step is left with "Open"."""
DATA = "empty"


def run(ui):
    ui.wait_until(lambda: ui.store.get("welcome") is True, 30, "the first-run screen")
    ui.eq(ui.api("/studio")["projects"], [], "a new data folder starts with no projects")
    # step 1: what do you want to make? capability cards with a live download total
    ui.expect("Step 1 of 3")
    ui.expect("What do you want to make?")
    ui.wait_until(lambda: ui.store.get("software") is not None and ui.js("!!Store.caps"), 90, "the software check")
    cards = [c["id"] for c in ui.js("Store.caps.capabilities")]
    ui.eq(cards[-1], "print", "3D printing is the last card")
    chosen = ui.js("Store.caps.chosen")
    ui.check("print" not in chosen and "core" in chosen and "parts" in chosen, f"printing is opt-in: {chosen}")
    total = ui.item("welcomeDownloadTotal")
    before = ui.js("Store.caps.capabilities.filter(function (c) { return c.id === 'render' })[0].size_mb")
    ui.settle(400)
    ui.shot("first-run-step1-make")
    if before:                                         # Blender is not here: ticking renders adds it to the total at once
        ui.click("capCard_render")
        ui.wait_until(lambda: ui.sees("MB", total) or ui.sees("GB", total), 3, "the download total to count Blender")
        ui.settle(300)
        ui.shot("first-run-step1-total")
        ui.click("capCard_render")                     # and off again: nothing optional for this run
        ui.settle(200)
    ui.click_text("Continue")
    ui.wait_until(lambda: ui.api("/capabilities")["decided"] is True, 10, "the choice to be written")
    ui.check("print" not in ui.api("/capabilities")["chosen"], "printing stays off")
    # step 2: your agent
    ui.expect("Step 2 of 3")
    ui.expect("Your agent")
    ui.run_js("var p = {}; Store.software.software.forEach(function (r) { p[r.id] = false }); Store.installPick = p")   # nothing is installed in a test
    ui.settle(300)
    ui.shot("first-run-step2-agent")
    ui.click_text("Continue")
    # step 3: only what was chosen
    ui.expect("Step 3 of 3")
    ui.wait_until(lambda: ui.find(name="welcomeInstallList") is not None, 10, "the install list")
    ui.settle(400)
    ui.shot("first-run-step3-setup")
    ids = ui.api("/capabilities")["install"]
    ui.check(not any(i.startswith("slicer.") for i in ids), f"no slicer is installed for someone who did not choose printing: {ids}")
    ui.eq(ui.store.get("onboardStep"), 2, "the step reached is remembered")
    ui.wait_until(lambda: ui.api("/setup/state")["onboarding"]["step"] == 2, 5, "the engine to save the step")
    ui.click_text("Back")
    ui.settle()
    ui.expect("Step 2 of 3")
    ui.click_text("Continue")
    ui.settle()
    if ui.find(name="welcomeOpenWithout") is not None:
        ui.click("welcomeOpenWithout")
    else:
        ui.click_text("Open Form Studio")
    ui.wait_until(lambda: ui.store.get("welcome") is False, 5, "the first-run screen to close")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.wait_until(lambda: ui.api("/setup/state")["first_run"] is False, 5, "the engine to remember that setup was seen")
    ui.settle(400)
    ui.shot("first-run-home-empty")
    ui.check(ui.exists("startComposer"), "the empty Home is the composer")
    ui.expect("What do you want to make?")
    ui.check(ui.find(name="printerChip") is None and not ui.sees("not for printing", "topBar"), "no printer talk in the top bar")
    # no examples: Import brings in only work made elsewhere
    ui.click_text("Import…")
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "import", 5, "the Import sheet")
    ui.settle()
    ui.check(not ui.exists(text="Examples that ship with Form Studio", exact=False), "no examples ship with Form Studio")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("sheet") is None, 4, "the sheet to close")
    # a first design, built from a recipe, opens as a 3D model
    r = ui.api("/projects", {"name": "Desk stand", "recipe": "device_stand", "brief": "", "values": None})
    pid = r["id"]
    ui.wait_until(lambda: all(v["state"] in ("current", "failed", "off") or v.get("unavailable")
                              for v in ui.api("/projects/" + pid)["status"].values()), 300, "the design's pipeline")
    ui.run_js("Store.reloadStudio().then(function () { Store.open(%r) })" % pid)
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pid, 60, "the design to open")
    d = ui.api("/projects/" + pid)
    ui.eq(d["purpose"]["purpose"], "model", "a new design is a 3D model")
    st = d["status"]
    ui.check(all(v["state"] in ("current", "off") or v.get("unavailable") for v in st.values()), f"the pipeline finished: {st}")
    ui.check("fit" not in [s["id"] for s in ui.js("Store.stages")], "no Fit stage while printing is off")
    ui.idle(300)
    ui.settle(600)
    ui.shot("first-run-design-open")
