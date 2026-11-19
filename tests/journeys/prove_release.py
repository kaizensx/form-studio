"""Fit, Prove and Release on the phone dock: tolerance window, a suggested action as a draft, passed checks, a
check's marker, the orientation finder, acknowledging warnings, approving, verifying, saving files."""
import zipfile

from PySide6.QtCore import QPointF

from _lib import fold, head, phone_dock, toasts_gone, wait_job

DATA = "fresh"
S = {}


def data(ui):
    return ui.api("/projects/" + S["pid"])


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = phone_dock(ui)


def journey_companion(ui):
    # the phone is four times taller than the dock: its outline stops a little above the part, with a note
    ui.key("Ctrl+2")
    ui.wait_until(lambda: ui.store.get("stage") == "shape", 3, "the Shape stage")
    vp = ui.item("viewport")
    h = ui.js("Store.values.device_height")
    for key in ("1", "2", "3", "4"):
        ui.key(key)
        ui.settle(700)
        note = ui.wait_until(lambda: ui.find(name="companionNote"), 5, "the note on what the dock holds")
        ui.check(ui.sees("%g mm tall" % h, note), "the note gives the device's real height")
        ui.check(ui.sees("not printed", note), "the note says it is not printed")
        p = note.mapToItem(vp, QPointF(0, 0))
        ui.check(p.x() >= 0 and p.y() >= 0 and p.x() + note.width() <= vp.width() and p.y() + note.height() <= vp.height(), f"the note is inside the view ({key})")
    ui.key("1")
    ui.check(vp.property("compTo") < h, "the outline is cut below the device's full height")
    ui.settle(500)
    ui.shot("companion")
    ui.run_js("Store.toggleCompanions()")                            # hide what the part holds: the note goes with it
    ui.wait_until(lambda: ui.find(name="companionNote") is None, 3, "the note to leave with the outline")
    ui.run_js("Store.toggleCompanions()")
    ui.wait_until(lambda: ui.find(name="companionNote") is not None, 3, "the note to come back")


def journey_fit(ui):
    ui.key("Ctrl+3")
    ui.wait_until(lambda: ui.store.get("stage") == "fit", 3, "the Fit stage with Ctrl+3")
    ui.settle(500)
    f0 = data(ui)["fit"]
    ui.check(f0 and 0 <= f0["yield"] <= 1, "the dock has a fit model")
    lo, hi = f0["window"]
    new_hi = 0.5                     # a narrower window: fewer prints fit, and FORM suggests re-centring the clearance
    ui.fill("fitHi", str(new_hi), enter=True)
    ui.wait_until(lambda: abs(data(ui)["fit"]["window"][1] - new_hi) < 1e-6, 20, "the wider window to reach the engine")
    ui.idle(120)
    f1 = data(ui)["fit"]
    ui.check(f1["yield"] < f0["yield"], f"a narrower window lowers the modelled yield: {f0['yield']} → {f1['yield']}")
    ui.wait_until(lambda: ui.sees(str(round(f1["yield"] * 100)) + "%"), 5, "the new yield on screen")
    ui.settle(300)
    ui.shot("fit-window")
    # a suggested action loads as a draft
    acts = [a for a in data(ui)["actions"] if a.get("change")]
    if acts:
        ui.click_text("Load as draft")
        ui.wait_until(lambda: ui.store.get("hasDraft") is True and ui.store.get("stage") == "shape", 5, "the action to load as a draft on Shape")
        k = list(acts[0]["change"])[0]
        ui.check(abs(ui.js("Store.values[%r]" % k) - acts[0]["change"][k]) < 1e-6, "the draft holds the suggested value")
        ui.wait_until(lambda: ui.js("!!Store.preview"), 60, "the draft preview")
        ui.settle(300)
        ui.shot("fit-action-draft")
        ui.click_text("Discard")
        ui.wait_until(lambda: ui.store.get("hasDraft") is False, 3, "Discard")
    else:
        raise AssertionError("no suggested action carries a change")
    # back to the window the design started with
    ui.key("Ctrl+3")
    ui.settle(400)
    ui.fill("fitHi", str(hi), enter=True)
    ui.wait_until(lambda: abs(data(ui)["fit"]["window"][1] - hi) < 1e-6, 20, "the original window")
    ui.idle(120)


def journey_prove(ui):
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the Prove stage")
    ui.settle(500)
    checks = data(ui)["checks"]["checks"]
    passed = [c for c in checks if c["status"] == "PASS"]
    ui.check(len(passed) > 0, "some checks pass")
    if not ui.find_all(name="passedCheck"):
        fold(ui, "Passed")
    rows = ui.wait_until(lambda: ui.find_all(name="passedCheck"), 4, "the passed checks to expand")
    ui.eq(len(rows), len(passed), "one row per passed check")
    # a passed check with a place on the part: click it → a marker
    link = [i for i, c in enumerate(passed) if c.get("at")]
    ui.check(link, "a passed check points at a place on the part")
    ui.click(rows[link[0]], 0.5, 0.3)
    ui.wait_until(lambda: ui.js("!!Store.viewer.marker"), 4, "a marker on the part")
    ui.expect(passed[link[0]].get("detail", "")[:24] or passed[link[0]]["label"])
    ui.settle(500)
    ui.shot("prove-check-marker")
    # orientation
    fold_open = ui.exists(text="Find the best orientation")
    if not fold_open:
        fold(ui, "Print orientation")
    o0 = data(ui)["project"]["orientation"]
    ui.click_text("Find the best orientation")
    ui.wait_until(lambda: ui.store.get("orient") is not None and ui.store.get("orientBusy") is False, 180, "the orientation candidates")
    cands = ui.store.get("orient")["candidates"]
    ui.check(len(cands) >= 2, "several orientations were compared")
    ui.settle(300)
    ui.shot("prove-orientations")
    use = ui.find_all(name="orientUse")
    if use:
        ui.click(use[0])
        ui.wait_until(lambda: data(ui)["project"]["orientation"] != o0, 30, "the orientation to change in the engine")
        wait_job(ui, S["pid"])
        ui.idle(300)
        # put it back: the rest of the journey releases the original design
        ui.api("/projects/" + S["pid"] + "/settings", {"orientation": o0})
        wait_job(ui, S["pid"])
        ui.run_js("Store.refresh(true)")
        ui.idle(300)
    else:
        print("  (the current orientation already ranks first: nothing to apply)")
    ui.run_js("Store.orient = null")


def journey_release(ui):
    ui.key("Ctrl+5")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "the Release stage with Ctrl+5")
    ui.settle(500)
    g = data(ui)["gate"]
    ui.check(g["ready"], f"the gate is ready: {g}")
    n0 = len(data(ui)["releases"])
    btn = ui.item(text="Approve and release r%02d" % head(ui))
    for c in ui.find_all(name="ackCheck"):
        ui.check(btn.property("enabled") is False, "Approve is disabled until every warning is acknowledged")
        ui.click(c)
    ui.wait_until(lambda: len(ui.store.get("ack")) == len(g.get("warnings") or []), 3, "every warning acknowledged")
    ui.wait_until(lambda: btn.property("enabled") is True, 3, "Approve to be enabled")
    ui.shot("release-ready")
    ui.click(btn)
    ui.wait_until(lambda: len(data(ui)["releases"]) == n0 + 1, 60, "a release in the engine")
    rel = data(ui)["releases"][-1]
    ui.wait_until(lambda: data(ui)["approval"]["state"] == "approved", 60, "the approval to be recorded")
    ui.expect(rel)
    ui.click_text("Verify")
    try:
        ui.expect("files intact", timeout=30)
    except Exception:                  # seen once on a Windows runner: the row had only just appeared and the click missed it
        print("  (Verify did not answer; pressing it again)")
        ui.settle(500)
        ui.click_text("Verify")
        ui.expect("files intact", timeout=90)
    ui.check(ui.api("/projects/%s/release/%s" % (S["pid"], rel))["intact"], "the engine agrees the release is intact")
    ui.settle(300)
    ui.shot("release-approved")
    # save a release report (the native dialog is answered with a path in the test's folder)
    ui.click_text("Save report…")
    rep = ui.saved(rel + "-REPORT.md")
    ui.check(rel.split("-")[0] in rep.read_text(encoding="utf-8") or len(rep.read_text(encoding="utf-8")) > 200, "the report was written")
    # a working file
    if not ui.exists(text="Save FreeCAD macro…"):
        fold(ui, "Working files for r%02d" % data(ui)["exports"]["rev"])
    files = list(data(ui)["exports"]["files"].values())
    step = [f for f in files if f["name"].lower().endswith((".step", ".stp"))][0]
    row = [t for t in ui.find_all(text=step["name"])][0]
    save = [b for b in ui.find_all(text="Save…", within=row.parentItem().parentItem())][0]
    ui.click(save)
    out = ui.saved(step["name"])
    ui.eq(out.stat().st_size, step["bytes"], "the saved STEP is the exported file")
    ui.check(any(w == "reveal" for w, _ in ui.outside), "the saved file would be revealed in the file manager")
    # maker documents
    docs = data(ui)["documents"]
    ui.check(docs, "the project offers maker documents")
    fold(ui, "Maker documents for r%02d" % head(ui))
    ui.click_text("Save all with images (.zip)…")
    z = ui.saved("%s_r%02d_docs.zip" % (S["pid"], head(ui)), 120)
    names = zipfile.ZipFile(z).namelist()
    ui.check(all(any(n.endswith(d) for n in names) for d in docs), f"the zip holds every document: {names}")
    # the project archive
    toasts_gone(ui)
    fold(ui, "Project file")
    ui.click_text("Save .formproj…")
    arch = ui.saved(S["pid"] + ".formproj", 60)
    ui.check(zipfile.is_zipfile(arch), "the .formproj is an archive")
    ui.settle(300)
    ui.shot("release-files")
