"""Several plates: a hinged box too wide for the plate is laid out on two plates, each sliced; Prove and the print
simulation switch between plates. Then Design only for this design, and slicing on again from Prove.

Runs with whatever slicer the test gives it (tests/test_ui_journeys.py): a stand-in OrcaSlicer on every machine, and
the slicer installed here when there is one (test_plates_real_slicer)."""
from _lib import has_slicer, make, toasts_gone, wait_job, printing_on

DATA = "fresh"
S = {}


def data(ui):
    return ui.api("/projects/" + S["pid"])


def journey_two_plates(ui):
    printing_on(ui)                      # this journey is about printing: turn it on as someone who prints would
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.check(has_slicer(ui), "a slicer is set up for this journey")
    S["pid"] = make(ui, "hinged_box", "Wide box", {"inner_w": 110, "inner_d": 80})
    d = data(ui)
    ui.eq(d["status"]["slice"]["state"], "current", "sliced")
    env = next(c for c in d["checks"]["checks"] if c["id"] == "envelope")
    ui.eq((env["status"], env["value"]), ("PASS", "2 plates"), "the build-volume check counts plates")
    sl = d["slice"]
    ui.eq(len(sl["plates"]), 2, "two plates sliced")
    ui.eq(sl["time_s"], sum(x["time_s"] for x in sl["plates"]), "the time is the sum of the plates")
    print(f"  sliced with {sl['slicer_name']} {sl['slicer_version']}: " + ", ".join(
        f"plate {x['n']} {x['time_s']:.0f} s {x['filament_g']} g" for x in sl["plates"]))
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the Prove stage")
    seg = ui.item("provePlates")
    ui.scroll_to(seg, 0.5)
    ui.expect("Slice of r01 · 2 plates")
    ui.click_text("Plate 2", within=seg)
    ui.wait_until(lambda: ui.js("Store.plateShown") == 2, 3, "plate 2 on screen")
    ui.expect("Lid")
    ui.settle(300)
    ui.shot("prove-plate-2")


def journey_simulate_a_plate(ui):
    ui.click_text("Inspect layers")
    ui.wait_until(lambda: ui.find(name="printSim") is not None, 10, "the print simulation")
    sim = ui.item("printSim")
    ui.wait_until(lambda: sim.property("count") > 0, 60, "the toolpaths of plate 2")
    n2 = sim.property("count")
    ui.eq(n2, data(ui)["slice"]["plates"][1]["layers"], "the simulation shows plate 2's layers")
    seg = ui.item("simPlates")
    ui.click_text("Plate 1", within=seg)
    ui.wait_until(lambda: ui.js("Store.plateShown") == 1, 3, "plate 1 chosen")
    ui.wait_until(lambda: sim.property("count") == data(ui)["slice"]["plates"][0]["layers"], 60, "plate 1's toolpaths")
    ui.settle(500)
    ui.shot("simulation-plate-1")
    ui.click_text("Back to the design")
    ui.wait_until(lambda: ui.find(name="printSim") is None, 5, "back to the design")


def journey_design_only_and_back(ui):
    toasts_gone(ui)
    ui.api("/projects/" + S["pid"] + "/settings", {"design_only": True})
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: ui.find(name="sliceOn") is not None, 10, "the Design only note in Prove")
    ui.eq(data(ui)["status"]["slice"]["state"], "off", "the slice is off for this design")
    ui.scroll_to(ui.item("sliceOn"), 0.5)
    ui.click("sliceOn")
    ui.wait_until(lambda: not data(ui)["project"].get("design_only"), 10, "slicing on for this design")
    wait_job(ui, S["pid"])
    ui.eq(data(ui)["status"]["slice"]["state"], "current", "the earlier slice is current again (same inputs, same key)")
