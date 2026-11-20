"""Make it lighter and Replace a broken part, in the window.

Make it lighter: a storage box is searched for real (kernel builds, the real checks, the slicer when one is installed);
the sheet shows the engine's own numbers, and applying the lightest geometry candidate makes a new revision with
exactly its values. Replace a broken part: from Home, a photo and a name; the message goes through the normal chat to
the stand-in agent (tests/fixtures/fake_agent.py), which creates a design and asks for a measurement; the steps above
the conversation follow, and the measured value is committed as measured. No model is called."""
from _lib import make, open_sheet_wait, sheet, toasts_gone, wait_job, printing_on

DATA = "fresh"
S = {}


def png(path):
    import struct
    import zlib

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x60\x80\xa0" * 32 for _ in range(32))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def journey_lighter(ui):
    printing_on(ui)                      # this journey is about printing: turn it on as someone who prints would
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    pid = S["pid"] = make(ui, "storage_box", "Drawer box")
    head0 = ui.api("/projects/" + pid)["project"]["head"]
    ui.run_js("Store.openSheet('lighter')")
    open_sheet_wait(ui, "lighter")
    ui.shot("lighter-before")
    ui.click(ui.item("lighterSearch"))
    ui.wait_until(lambda: ui.store.get("lighterBusy") is True or ui.js("!!Store.lighter"), 10, "the search to start")
    r = ui.wait_until(lambda: ui.js("Store.lighter"), 900, "the lighter candidates")
    ref = ui.api("/projects/%s/lighten" % pid)
    ui.eq([(c["id"], c["mass_g"], c["slice_g"]) for c in r["candidates"]], [(c["id"], c["mass_g"], c["slice_g"]) for c in ref["candidates"]],
          "the window shows the engine's candidates")
    ui.check(len(r["candidates"]) >= 1, f"at least one lighter candidate: {r.get('none_why')} {r.get('rejected')}")
    base = r["baseline"]
    for c in r["candidates"]:
        ui.check(c["mass_g"] <= base["mass_g"] + 1e-9, f"{c['id']} is not heavier ({c['mass_g']} g vs {base['mass_g']} g)")
        passed = {x["id"] for x in base["checks"] if x["status"] == "PASS"}
        ui.check(all(x["after"] == "PASS" for x in c["checks"] if x["id"] in passed), f"{c['id']} keeps every passing check")
        if c["slice_g"] is not None and base["slice_g"] is not None:
            ui.check(c["slice_g"] < base["slice_g"], f"{c['id']} is lighter in the slicer too")
    ui.wait_until(lambda: len(ui.find_all(name="lighterCandidate")) == len(r["candidates"]), 10, "a row per candidate")
    ui.settle(1200)
    ui.shot("lighter-candidates")
    geo = [c for c in r["candidates"] if c["kind"] == "geometry"]
    ui.check(geo, "a geometry candidate to apply")
    c = geo[0]
    i = [x["id"] for x in r["candidates"]].index(c["id"])
    ui.click(ui.find_all(name="lighterCandidate")[i], 0.5, 0.2)
    ui.wait_until(lambda: ui.js("Store.sheet && Store.sheet.kind") == "lighter", 2, "still open")
    ui.click(ui.item("lighterApply"))
    ui.wait_until(lambda: sheet(ui) is None, 120, "the candidate to be applied")
    p = ui.api("/projects/" + pid)["project"]
    ui.eq(p["head"], head0 + 1, "a new revision")
    hv = next(x for x in p["revisions"] if x["n"] == p["head"])["values"]
    ui.check(all(abs(hv[k] - v) < 1e-9 for k, v in c["changes"].items()), f"the revision has the candidate's values {c['changes']}")
    wait_job(ui, pid)
    d = ui.api("/projects/" + pid)
    ui.eq(d["status"]["checks"]["state"], "current", "the checks are current (made during the search, so the run finds them)")
    toasts_gone(ui)
    ui.settle(800)
    ui.shot("lighter-applied")


def journey_replace(ui):
    ui.run_js("Store.startNew()")
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(500)
    ui.click("startReplace")
    open_sheet_wait(ui, "replace")
    ui.shot("replace-empty")
    ui.pick_file(png(ui.files / "broken-clip.png"))
    ui.click("replacePhotoWell")
    ui.wait_until(lambda: [a for a in ui.store.get("chatAttach") if a["kind"] == "image"], 15, "the photo attached")
    ui.click("replaceName")
    ui.type("Shelf clip")
    ui.settle(600)
    ui.shot("replace-ready")
    ui.click("replaceStart")
    card = ui.wait_until(lambda: ui.find("measureCard"), 60, "the measurement card")
    ui.wait_until(lambda: ui.exists("replaceSteps") and ui.js("Store.replaceActive"), 10, "the steps above the conversation")
    ui.eq(ui.js("JSON.stringify(Store.replaceProgress)"), '{"done":2,"active":2}', "the Measure step is the one in progress")
    items = ui.api("/conversations/" + ui.store.get("convId"))["items"]
    first = next(e for e in items if e["t"] == "user")
    ui.check(first["text"].startswith("Replace a broken part: Shelf clip."), "the guided message went through the chat")
    ui.check("ask_measurement" in first["text"] and "scale" in first["text"], "it asks for the photo scale and the measurements")
    ui.check(first.get("attachments") and first["attachments"][0]["kind"] == "image", "with the photo")
    ui.settle(800)
    ui.shot("replace-measure")
    ui.click(ui.item("measureValue", within=card))
    ui.type("42.5")
    ui.click("measureSend")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False and any("You measured: 42.5 mm" in (e.get("text") or "")
                  for e in ui.api("/conversations/" + ui.store.get("convId"))["items"]), 60, "the agent's reply")
    ui.wait_until(lambda: ui.js("Store.replaceProgress.done") == 4, 20, "every step done")
    projects = [p for p in ui.api("/studio")["projects"] if p.get("name") == "Shelf clip"]
    ui.check(projects, "the replacement design exists")
    p = ui.api("/projects/" + projects[0]["id"])["project"]
    h = next(x for x in p["revisions"] if x["n"] == p["head"])
    ui.eq(h["values"]["size"], 42.5, "the measured size is in the design")
    ui.eq(h["provenance"]["size"]["source"], "measured", "and marked measured")
    ui.settle(1500)
    ui.shot("replace-done")
