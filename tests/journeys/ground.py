"""A creation studio, not a slicer preview. With 3D printing on: a new design is a 3D model; the top bar never names a
printer (Home, a design being made, a model, a print); every design sits on a neutral studio floor with an origin
cross and a scale cue; the build plate and the printer chip appear only in Fit, Review and Make of a design made for
printing (or on "Show build plate") and leave again on the way back."""
from _lib import DOCK, make, printing_on, toasts_gone

DATA = "fresh"
S = {}


def printer_name(ui):
    return ui.js("Store.printing && Store.printing.available ? Store.printing.presets.machine.name : ''") or ""


def top_bar_is_quiet(ui, where):
    ui.check(ui.find(name="printerChip", within=ui.item("topBar")) is None, f"{where}: no printer chip in the top bar")
    ui.check(not ui.sees("not for printing", "topBar"), f"{where}: no purpose chip")
    name = printer_name(ui) or "nozzle"
    ui.check(not ui.sees(name, "topBar"), f"{where}: the top bar names no printer ({name})")


def plate(ui):
    return ui.js("!!Store.viewer && Store.viewer.plateShown") is True


def stage(ui, sid):
    ui.click("stage-" + sid)
    ui.wait_until(lambda: ui.store.get("stage") == sid, 3, sid)
    ui.settle(500)


def journey_home_and_designing(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    printing_on(ui)
    ui.settle(600)
    top_bar_is_quiet(ui, "Home")
    ui.eq(ui.js("Store.purposeInfo['default']"), "model", "a new design is a 3D model, printing on or not")
    ui.eq(ui.js("Store.newPurposeEffective"), "model", "Home starts at Anything")
    ui.check(ui.sees("Anything", "startPurpose") and ui.sees("My printer", "startPurpose"), "Make it for: Anything / My printer")
    ui.check(not ui.exists("startPrinter"), "no printer under the composer until My printer is picked")
    ui.shot("ground-home")
    ui.run_js("Store.startBlank()")
    ui.wait_until(lambda: ui.store.get("screen") == "designing", 5, "the blank canvas")
    ui.settle(800)
    top_bar_is_quiet(ui, "Designing")
    ui.check(ui.sees("Nothing here yet"), "the blank canvas has no plate to speak of")
    ui.shot("ground-blank")
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")


def journey_a_model_is_never_on_a_plate(ui):
    S["model"] = make(ui, "storage_box", "Desk tray")          # no purpose given: the default, a 3D model
    ui.eq(ui.api("/projects/" + S["model"])["purpose"]["purpose"], "model", "a 3D model")
    ui.eq(ui.js("Store.stageMode"), "studio", "the studio floor")
    for sid in ("brief", "shape", "prove", "release"):
        stage(ui, sid)
        top_bar_is_quiet(ui, "a model in " + sid)
        ui.check(ui.find(name="printerChip") is None, f"no printer chip anywhere in {sid}")
        ui.check(not plate(ui), f"no build plate in {sid}")
        ui.check(not ui.exists("showPlate"), f"no build plate toggle for a model ({sid})")
    stage(ui, "shape")
    ui.wait_until(lambda: ui.exists("scaleCue"), 5, "the scale cue on the studio floor")
    ui.check(ui.exists("releaseForPrinting") is False, "Make's one-click switch is only in Make")
    ui.shot("ground-model")


def journey_the_plate_belongs_to_printing(ui):
    toasts_gone(ui)
    S["print"] = make(ui, "dock", "Hallway phone dock", DOCK, purpose="print")
    stage(ui, "shape")
    ui.check(not plate(ui), "a print in Design: the studio floor")
    ui.check(ui.find(name="printerChip") is None, "no printer chip in Design")
    top_bar_is_quiet(ui, "a print in Design")
    ui.shot("ground-print-design")
    ui.click("showPlate")
    ui.wait_until(lambda: plate(ui), 3, "the plate on request")
    ui.click("showPlate")
    ui.wait_until(lambda: not plate(ui), 3, "the plate gone again")
    for sid in ("fit", "prove", "release"):
        stage(ui, sid)
        ui.wait_until(lambda: plate(ui), 3, f"the build plate in {sid}")
        ui.item("printerChip")
        top_bar_is_quiet(ui, "a print in " + sid)
        if sid == "fit":
            ui.shot("ground-print-fit")
    stage(ui, "shape")
    ui.wait_until(lambda: not plate(ui), 3, "the plate leaves on the way back")
    ui.check(ui.find(name="printerChip") is None, "and the printer chip with it")


def journey_make_marks_a_model_for_printing(ui):
    toasts_gone(ui)
    ui.run_js("Store.open(%r)" % S["model"])
    ui.wait_until(lambda: ui.store.get("pid") == S["model"] and ui.js("!!Store.data && Store.data.project.id === %r" % S["model"]), 30, "the model")
    stage(ui, "release")
    btn = ui.item("releaseForPrinting")
    ui.click(btn)
    ui.wait_until(lambda: ui.api("/projects/" + S["model"])["purpose"]["purpose"] == "print", 15, "marked for printing in one click")
    ui.wait_until(lambda: plate(ui) and ui.find(name="printerChip") is not None, 10, "the plate and the printer in Make")
    top_bar_is_quiet(ui, "after marking for printing")
    ui.no_warnings()
