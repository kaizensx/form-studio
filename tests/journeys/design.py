"""A new design (a recipe is still a building block agents use; here it is made through the engine): pipeline, stages, select on the model, draft by slider and by typing,
commit, and go back with the timeline."""
from _lib import head, open_sheet_wait, wait_job

DATA = "fresh"


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.settle(300)
    # ── created the way an agent does, opened the way a person does: its card on Home ──
    pid = ui.api("/projects", {"name": "Sensor case", "recipe": "enclosure", "brief": ""})["id"]
    ui.run_js("Store.reloadStudio()")
    card = ui.wait_until(lambda: next((c for c in ui.find_all(name="projectCard") if ui.sees("Sensor case", c)), None), 30, "the new design on Home")
    ui.scroll_to(card)
    ui.click(card, 0.5, 0.4)
    ui.wait_until(lambda: ui.store.get("screen") == "work", 120, "the new project to open")
    ui.eq(len(ui.api("/studio")["projects"]), 1, "one project")
    ui.eq(ui.store.get("pid"), pid)
    ui.eq(ui.api("/projects/" + pid)["project"]["name"], "Sensor case", "the typed name reached the engine")
    ui.eq(ui.api("/projects/" + pid)["project"]["recipe"], "enclosure")
    wait_job(ui, pid)
    ui.idle(300)
    st = ui.api("/projects/" + pid)["status"]
    ui.check(all(v["state"] == "current" for v in st.values()), f"the pipeline ran to completion: {st}")
    ui.settle(800)
    ui.shot("design-created")

    # ── every stage tab ──
    for stage in ("brief", "fit", "prove", "release", "shape"):
        ui.click("stage-" + stage)
        ui.wait_until(lambda: ui.store.get("stage") == stage, 3, f"the {stage} stage")
        ui.settle(450)
        ui.shot("design-stage-" + stage)

    # ── select a feature by clicking the model ──
    ui.eq(ui.store.get("feature"), "")
    ui.click("viewport", 0.5, 0.5)
    got = ui.wait_until(lambda: ui.store.get("feature"), 5, "a feature to be selected by clicking the model")
    ui.check(got in [f["id"] for f in ui.js("Store.recipe.features")], f"{got} is a feature of the recipe")
    ui.expect("Drives this feature")
    ui.settle(500)
    ui.shot("design-feature-selected")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("feature") == "", 3, "Esc to clear the selection")
    ui.settle(400)

    # ── drag a parameter slider: a draft appears and the impact card fills ──
    fid = ui.js("Store.recipe.features.filter(function (f) { return Store.recipe.params.some(function (p) { return p.feature === f.id && p.group !== 'brief' }) })[0].id")
    ui.click("feature-" + fid)
    ui.wait_until(lambda: ui.store.get("feature") == fid, 3, "the feature picked from the list")
    ui.settle(500)
    rows = ui.wait_until(lambda: [r for r in ui.find_all() if r.objectName().startswith("param-") and ui._on_screen(r)], 5, "a parameter row")
    row = rows[0]
    key = row.objectName()[6:]
    spec = ui.js("Store.spec(%r)" % key)
    v0 = ui.js("Store.values[%r]" % key)
    beam = ui.find(name="paramBeam", within=row)
    frac = (v0 - spec["min"]) / (spec["max"] - spec["min"])
    to = 0.25 if frac > 0.5 else 0.75
    ui.drag(beam, ((to - frac) * beam.width(), 0), fx=frac * (beam.width() - 10) / beam.width() + 5 / beam.width())
    ui.wait_until(lambda: ui.store.get("hasDraft") is True, 3, "a draft after dragging the slider")
    v1 = ui.js("Store.values[%r]" % key)
    ui.check(abs(v1 - v0) > 1e-6, f"the slider changed {key}: {v0} → {v1}")
    ui.wait_until(lambda: ui.js("!!Store.preview && !!Store.preview.impact"), 60, "the draft preview and its impact")
    ui.check(any(p["key"] == key for p in ui.js("Store.preview.impact.params")), "the impact card lists the parameter")
    card = ui.item("draftCard")
    ui.check(ui.sees("Draft change", card) and ui.sees(spec["label"], card), "the draft card shows the change")
    ui.settle(500)
    ui.shot("design-draft-slider")

    # ── type a value ──
    field = ui.find(name="paramField", within=row)
    target = round(spec["min"] + (spec["max"] - spec["min"]) * 0.6, 1)
    ui.fill(field, str(target), enter=True)
    ui.wait_until(lambda: abs(ui.js("Store.values[%r]" % key) - target) < 1e-6, 3, f"{key} to be {target} after typing")
    ui.wait_until(lambda: ui.js("!!Store.preview && Math.abs(Store.preview.impact.params[0].to - %r) < 1e-6" % target), 60, "the preview of the typed value")
    ui.check(not ui.store.get("draftError"), f"the typed value builds: {ui.store.get('draftError')}")

    # ── commit ──
    h0 = head(ui)
    n_revs = len(ui.api("/projects/" + pid)["project"]["revisions"])
    ui.click_text("Commit as r%02d" % (n_revs + 1))
    ui.wait_until(lambda: head(ui) == n_revs + 1, 30, "the new revision to exist in the engine")
    ui.wait_until(lambda: ui.store.get("hasDraft") is False, 5, "the draft to clear")
    rev = [r for r in ui.api("/projects/" + pid)["project"]["revisions"] if r["n"] == n_revs + 1][0]
    ui.check(abs(rev["values"][key] - target) < 1e-6, "the revision holds the typed value")
    wait_job(ui, pid)
    ui.idle(300)
    ui.settle(600)
    ui.shot("design-committed")

    # ── undo: timeline → scrub to r01 → Branch from here ──
    ui.key("T")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is True, 3, "the timeline to open with T")
    ui.settle(400)
    track = ui.item("timelineTrack")
    ui.click(track, 0.02, 0.5)
    ui.wait_until(lambda: (ui.store.get("scrub") or {}).get("rev") == h0, 20, f"r{h0:02d} to be shown from the timeline")
    ui.eq(head(ui), n_revs + 1, "looking changes nothing")
    ui.settle(500)
    ui.shot("design-timeline-scrub")
    ui.click_text("Branch from here")
    ui.wait_until(lambda: head(ui) == h0, 30, "head to go back")
    ui.eq(len(ui.api("/projects/" + pid)["project"]["revisions"]), n_revs + 1, "nothing was deleted")
    wait_job(ui, pid)
    ui.idle(300)
    ui.wait_until(lambda: abs(ui.js("Store.values[%r]" % key) - v0) < 1e-6, 10, "the old value to be back")
    ui.settle(600)
    ui.shot("design-branched")
