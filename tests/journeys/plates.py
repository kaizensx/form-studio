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
    S["pid"] = make(ui, "hinged_box", "Wide box", {"inner_w": 110, "inner_d": 80}, purpose="print")
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


def drawn_box(ui, pid):
    """Where a part is drawn now, on the plate: its print box's corners through the part's transform and the shift."""
    return ui.js("(function(){ var v = Store.viewer, x = v.partById(%r), xf = v.partXf(x), b = x.print_bbox, lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];"
                 " for (var m = 0; m < 8; m++) { var p = xf.rot.times(Qt.vector3d(b[m & 1][0], b[(m >> 1) & 1][1], b[(m >> 2) & 1][2])).plus(xf.pos).plus(v.shift);"
                 " lo = [Math.min(lo[0], p.x), Math.min(lo[1], p.y), Math.min(lo[2], p.z)]; hi = [Math.max(hi[0], p.x), Math.max(hi[1], p.y), Math.max(hi[2], p.z)] }"
                 " return [lo, hi] })()" % pid)


def journey_every_plate_in_the_view(ui):
    """The 3D view shows both plates, each part lying on its own as it prints, never off a plate or under it."""
    ui.wait_until(lambda: ui.js("Store.viewer.platesOn") is True, 10, "the parts laid out on their plates")
    ui.eq(ui.js("Store.viewer.plateCount"), 2, "two plates drawn")
    ui.check(ui.js("Store.viewer.plateBed[0]") == data(ui)["checks"]["context"]["plates"]["bed_mm"][0], "each the bed's own size")
    ui.wait_until(lambda: ui.sees("Plate 1 of 2") and ui.sees("Plate 2 of 2"), 5, "each plate says which it is")
    plan = data(ui)["checks"]["context"]["plates"]
    bed, gap = plan["bed_mm"], ui.js("Store.viewer.plateGapMm")
    sx, sy = ui.js("[Store.viewer.shift.x, Store.viewer.shift.y]")
    for plate in plan["plates"]:
        x0 = sx + (plate["n"] - 1) * (bed[0] + gap)
        for q in plate["parts"]:
            lo, hi = drawn_box(ui, q["id"])
            ui.check(lo[2] > -1e-3, f"{q['id']} rests on the plate (lowest z {lo[2]:.3f})")
            ui.check(x0 - 1e-3 <= lo[0] and hi[0] <= x0 + bed[0] + 1e-3 and sy - 1e-3 <= lo[1] and hi[1] <= sy + bed[1] + 1e-3,
                     f"{q['id']} lies on plate {plate['n']}: {lo} {hi}")
    ui.settle(600)
    ui.shot("plates-in-the-view")


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


# Built lying down: a post modelled along X beside its base, stood upright by its placement about a point under the
# base and pulled down for the exploded view (tests/test_assembly_views.py LYING). Shown naively it hangs under the
# ground; every view rests the whole set on it instead.
def journey_lying_down_assembly_rests_on_the_ground(ui):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fixtures.lying_design import LYING
    from _lib import click_stage, open_project
    d = ui.studio.create_design("Lying post", LYING)
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, d["id"])
    open_project(ui, d["id"])
    ui.wait_until(lambda: ui.store.get("assembly") is not None, 20, "the post and its base as an assembly")
    click_stage(ui)
    ui.key("E")
    ui.wait_until(lambda: ui.js("Ws.tool") == "assembly", 5, "E to open Assembly")
    bar = ui.item("asmBar")
    for mode, label in (("assembled", "Assembled"), ("exploded", "Exploded")):
        ui.click_text(label, within=bar)
        ui.wait_until(lambda: ui.store.get("asmMode") == mode, 3, mode)
        ui.settle(900)                       # the parts glide to their places
        lows = [drawn_box(ui, pid)[0][2] for pid in ("base", "post")]
        ui.check(min(lows) > -1e-3, f"{mode}: nothing under the ground (lowest {min(lows):.3f} mm)")
        ui.check(abs(min(lows)) < 1e-2, f"{mode}: the set rests on the ground ({min(lows):.3f} mm)")
        lo, hi = drawn_box(ui, "post")
        ui.check(hi[2] - lo[2] > 50, f"{mode}: the post stands upright ({hi[2] - lo[2]:.1f} mm tall)")
        ui.shot(f"lying-{mode}")
