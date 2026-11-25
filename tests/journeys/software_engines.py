"""Settings › Software: every optional engine has its own Install button, its size and licence on the card, and a
non-commercial licence is one line in a confirmation before anything is downloaded.

Environment the test suite sets (test_software_engines): FORM_INSTALL_MOCK_DOWNLOADS=1 (the CADEvolve download is a
small local stand-in: nothing is downloaded). CAD-Recode is never accepted here (that would install PyTorch); CADFit is
accepted, which in a source checkout with its libraries only writes [recon] cadfit = true to this run's own studio.toml."""


def _row(ui, name, sid):
    for it in ui.find_all(name=name, shown=False):
        if it.property("sid") == sid:
            return it
    return None


def _status(ui, sid):
    return ui.js(f"(Store.softwareItem({sid!r}) || {{}}).status")


def run(ui):
    theme = "dark" if ui.js("Theme.dark") else "light"
    ui.run_js('Store.openSettings("software")')
    ui.run_js("Store.checkSoftware()")
    ui.wait_until(lambda: ui.store.get("software") is not None, 90, "the software check")
    ui.wait_until(lambda: ui.find(name="sheetCard") is not None, 10, "the Settings sheet")
    ui.wait_until(lambda: _row(ui, "softwareInstall", "exemplars.cadevolve") is not None, 30, "the engine rows")
    ui.settle(500)
    ui.shot(f"software-top-{theme}")

    # size and licence on every engine card, always
    for sid, want in (("recon.learned", "CC BY-NC 4.0"), ("recon.cadfit", "CC BY-NC 4.0"), ("exemplars.cadevolve", "Apache-2.0")):
        meta = _row(ui, "softwareMeta", sid)
        ui.check(meta is not None, f"{sid} shows its size and licence")
        txt = meta.property("text")
        ui.check("Size: " in txt and want in txt, f"{sid}: {txt}")
        ui.check(_row(ui, "softwareInstall", sid) is not None, f"{sid} has its own Install button")

    # every optional row that is not there has an action: Install, or a page
    for r in ui.js("Store.software.software"):
        if r["id"] == "claude.signin" or r.get("absent") or r["status"] in ("ok", "info") or r["level"] == "required":
            continue
        ui.check(r["installable"] or r["manual"] or r.get("blocked_by"), f"{r['id']} has an Install button or a page")

    # CADEvolve (Apache-2.0): one click, no question; the download is a local stand-in
    btn = _row(ui, "softwareInstall", "exemplars.cadevolve")
    ui.scroll_to(btn)
    ui.settle(300)
    ui.shot(f"software-engines-{theme}")
    ui.click(btn)
    ui.wait_until(lambda: ui.js("Store.installJob") is not None, 10, "the install to start")
    ui.check(_row(ui, "licenceConfirm", "exemplars.cadevolve") is None or not _row(ui, "licenceConfirm", "exemplars.cadevolve").isVisible(),
             "an Apache-2.0 corpus asks no licence question")
    ui.wait_until(lambda: ui.js("Store.installJob.state") != "running", 60, "the CADEvolve install to finish")
    ui.eq(ui.js("Store.installJob.state"), "done", "CADEvolve installed")
    ui.wait_until(lambda: _status(ui, "exemplars.cadevolve") == "ok", 30, "the CADEvolve row to turn ok")
    log = " ".join(l["text"] for l in ui.js("Store.installLog"))
    ui.check("FORM_INSTALL_MOCK_DOWNLOADS" in log, "the log says the download was a stand-in")

    # CAD-Recode (CC BY-NC 4.0): Install shows the licence line first; Cancel starts nothing
    job = ui.js("Store.installJob.id")
    btn = _row(ui, "softwareInstall", "recon.learned")
    ui.scroll_to(btn)
    ui.click(btn)
    ui.wait_until(lambda: _row(ui, "licenceConfirm", "recon.learned").isVisible(), 5, "the CAD-Recode licence confirmation")
    conf = _row(ui, "licenceConfirm", "recon.learned")
    ui.check(ui.sees("CC BY-NC 4.0", conf) or any("CC BY-NC 4.0" in t for t in ui.texts(conf)), "the licence is named")
    ui.check(any("non-commercial" in t and "accepts" in t for t in ui.texts(conf)), f"one licence line: {ui.texts(conf)}")
    ui.settle(300)
    ui.shot(f"software-licence-cadrecode-{theme}")
    ui.eq(ui.js("Store.installJob.id"), job, "nothing started before the licence was accepted")
    ui.click_text("Cancel", within=conf)
    ui.wait_until(lambda: not _row(ui, "licenceConfirm", "recon.learned").isVisible(), 5, "the confirmation to close")
    ui.eq(ui.js("Store.installJob.id"), job, "Cancel started nothing")

    # CADFit (CC BY-NC 4.0, with its author's permission): the same confirmation; Install there accepts it
    btn = _row(ui, "softwareInstall", "recon.cadfit")
    ui.scroll_to(btn)
    ui.click(btn)
    ui.wait_until(lambda: _row(ui, "licenceConfirm", "recon.cadfit").isVisible(), 5, "the CADFit licence confirmation")
    conf = _row(ui, "licenceConfirm", "recon.cadfit")
    ui.check(any("CC BY-NC 4.0" in t for t in ui.texts(conf)), f"the CADFit licence is named: {ui.texts(conf)}")
    ui.settle(300)
    ui.shot(f"software-licence-cadfit-{theme}")
    plan = ui.js("Store.softwareItem('recon.cadfit').plan")
    if plan and plan["id"] == "enable":            # its libraries are in this Python: accepting only turns it on
        ui.click(ui.item("licenceAccept", within=conf))
        ui.wait_until(lambda: ui.js("Store.installJob.id") != job and ui.js("Store.installJob.state") != "running", 30,
                      "CADFit to be turned on")
        ui.eq(ui.js("Store.installJob.state"), "done", "CADFit accepted and on")
        ui.wait_until(lambda: _status(ui, "recon.cadfit") == "ok", 30, "the CADFit row to turn ok")
    else:
        ui.click_text("Cancel", within=conf)
    ui.settle(400)
    ui.shot(f"software-after-{theme}")

    # every engine card says what it does and when you would want it, and what it gives you
    for sid in ("recon.learned", "recon.cadfit", "game.coacd", "exemplars.cadevolve"):
        about = _row(ui, "softwareAbout", sid)
        gives = _row(ui, "softwareGives", sid)
        ui.check(about is not None and len(about.property("text")) > 60, f"{sid} says what it does")
        ui.check(gives is not None and "What this gives you" in gives.property("text"), f"{sid} says what it gives you")

    # Remove: what Form Studio downloaded for the corpus goes, after one question; Cancel removes nothing
    ui.wait_until(lambda: ui.js("(Store.softwareItem('exemplars.cadevolve') || {}).removable") is True, 20, "CADEvolve to be removable")
    rm = ui.wait_until(lambda: _row(ui, "softwareRemove", "exemplars.cadevolve"), 10, "its Remove button")
    ui.scroll_to(rm)
    ui.settle(200)
    ui.click(rm)
    conf = ui.wait_until(lambda: (lambda c: c if c is not None and c.isVisible() else None)(_row(ui, "removeConfirm", "exemplars.cadevolve")),
                         5, "the Remove question")
    ui.check(any("Your designs are not affected" in t for t in ui.texts(conf)), f"the question says what goes: {ui.texts(conf)}")
    ui.settle(200)
    ui.shot(f"software-remove-{theme}")
    ui.click_text("Cancel", within=conf)
    ui.wait_until(lambda: not _row(ui, "removeConfirm", "exemplars.cadevolve").isVisible(), 5, "the question to close")
    ui.eq(_status(ui, "exemplars.cadevolve"), "ok", "Cancel removed nothing")
    ui.click(_row(ui, "softwareRemove", "exemplars.cadevolve"))
    conf = ui.wait_until(lambda: (lambda c: c if c is not None and c.isVisible() else None)(_row(ui, "removeConfirm", "exemplars.cadevolve")),
                         5, "the Remove question again")
    ui.click(ui.item("removeAccept", within=conf))
    ui.wait_until(lambda: _status(ui, "exemplars.cadevolve") == "missing", 30, "the CADEvolve row to say not installed")
    import os
    from pathlib import Path
    ui.check(not (Path(os.environ["FORM_DATA"]) / "corpus" / "cadevolve").exists(), "the corpus folder is gone")
    ui.check(_row(ui, "softwareInstall", "exemplars.cadevolve") is not None, "it can be installed again")
