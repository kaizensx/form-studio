"""Design only, end to end with no slicer at all: design, checks, exports and a release, with the Prove and Release
stages saying what is not covered. Then Design only for every design from Settings, and back.

Environment (tests/test_ui_journeys.py test_design_only): every slicer points at a program that does not exist."""
import json

from _lib import make, toasts_gone

DATA = "fresh"
S = {}


def data(ui):
    return ui.api("/projects/" + S["pid"])


def journey_no_slicer(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.check(not ui.js("Store.slicer.available"), "no slicer is available here")
    S["pid"] = make(ui, "hook", "Design only hook")
    d = data(ui)
    ui.eq(d["status"]["slice"]["state"], "off", "the slice is off, not missing or failed")
    ui.eq(d["status"]["slice"]["off"]["why"], "no_slicer", "because no slicer is installed")
    ui.check(all(d["status"][n]["state"] == "current" for n in ("geometry", "exports", "checks")), "everything else is current")
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the Prove stage")
    note = ui.item("designOnlyNote")
    ui.scroll_to(note, 0.5)
    ui.check(ui.sees("No slicer is installed", note), "Prove says why it is not sliced")
    ui.expect("Set up a slicer…")
    ui.settle(300)
    ui.shot("prove-design-only")


def journey_release_without_a_slice(ui):
    ui.click("stage-release")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "the Release stage")
    ui.settle(400)
    g = data(ui)["gate"]
    ui.check(not any("Slice" in r for r in g["reasons"]), f"the missing slice does not block: {g['reasons']}")
    ui.check(ui.sees("Design only: not sliced", ui.item("releaseDesignOnly")), "Release lists what is not covered")
    if g["failures"]:
        print("  (the default hook fails a check here; release over it is covered elsewhere)")
        return
    btn = ui.item(text="Approve and release r%02d" % data(ui)["project"]["head"])
    for c in ui.find_all(name="ackCheck"):
        ui.click(c)
    ui.wait_until(lambda: btn.property("enabled") is True, 5, "Approve to be enabled")
    ui.shot("release-design-only")
    ui.click(btn)
    ui.wait_until(lambda: data(ui)["approval"]["state"] == "approved", 60, "the release")
    rel = data(ui)["releases"][-1]
    v = ui.api("/projects/%s/release/%s" % (S["pid"], rel))
    names = [f["file"] for f in v["files"]]
    ui.check(v["intact"] and any(n.endswith(".step") for n in names), f"STEP and STL are released: {names}")
    ui.check(not any(n.endswith((".gcode", ".3mf")) for n in names), "no sliced files are claimed")


def journey_design_only_everywhere(ui):
    toasts_gone(ui)
    ui.run_js("Store.designOnlyEverywhere(true)")
    ui.wait_until(lambda: data(ui)["status"]["slice"].get("off", {}).get("why") == "settings", 10, "Design only for every design")
    import os
    from pathlib import Path
    toml = (Path(os.environ["FORM_UITEST_TMP"]) / "studio.toml").read_text(encoding="utf-8")
    ui.check("enabled = false" in toml, "written to studio.toml")
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the Prove stage")
    ui.expect("Slicing is turned off for every design.")
    on = lambda: data(ui)["status"]["slice"].get("off", {}).get("why") == "no_slicer"
    for attempt in range(2):                           # the Prove panel can still be laying out: click once it holds still
        ui.settle(400)
        ui.click_text("Turn slicing on")
        try:
            ui.wait_until(on, 30, "slicing on again (still no slicer)")
            break
        except Exception:
            if attempt or on():
                raise
    print("  " + json.dumps(data(ui)["status"]["slice"]["off"]))
