"""Shared steps for the UI journeys (tests/journeys/*.py). Setup goes through the engine API; the thing under
test goes through the window."""


def wait_job(ui, pid, timeout=300):
    """Until the project's pipeline is current (solid, exports, checks; slice when a slicer is installed and slicing is on)."""
    def done():
        d = ui.api("/projects/" + pid)
        return isinstance(d, dict) and d.get("status") and not d.get("job") and all(
            v["state"] in ("current", "blocked", "failed", "off") or v.get("unavailable") for v in d["status"].values())
    try:
        ui.wait_until(done, timeout, f"the pipeline of {pid}")
    except Exception as e:                 # say where it stopped: a timeout alone explains nothing on a remote runner
        d = ui.api("/projects/" + pid)
        st = {k: {x: v.get(x) for x in ("state", "blocked", "unavailable", "error") if v.get(x)} for k, v in (d.get("status") or {}).items()} if isinstance(d, dict) else d
        jobs = getattr(ui.studio, "jobs", {})
        last = [{"state": j.get("state"), "steps": [(s.get("node"), s.get("state"), str(s.get("error"))[:300]) for s in j.get("steps", [])]} for j in list(jobs.values())[-2:]]
        err = {k: d.get(k) for k in ("error", "hint", "detail") if k in d} if isinstance(d, dict) else {}
        raise type(e)(f"{e}; job={d.get('job') if isinstance(d, dict) else None} status={st} answer={err or str(d)[:300]} "
                      f"last jobs={last}") from None


def make(ui, recipe, name, values=None, open=True):
    """Create a project from a recipe through the engine, wait for its pipeline, open it in the window."""
    r = ui.api("/projects", {"name": name, "recipe": recipe, "brief": "", "values": values})
    pid = r["id"]
    wait_job(ui, pid)
    if open:
        open_project(ui, pid)
    return pid


def example(ui, pid, open=True):
    ui.api("/examples", {"ids": [pid]})
    ui.api("/projects/" + pid + "/run", {"nodes": [], "force": False})
    wait_job(ui, pid)
    if open:
        open_project(ui, pid)
    return pid


def open_project(ui, pid):
    ui.run_js("Store.reloadStudio().then(function () { Store.open(%r) })" % pid)
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pid, 60, f"{pid} to open")
    ui.wait_until(lambda: ui.js("!!Store.view && !!Store.viewer"), 60, "the model to load")
    ui.idle(300)
    ui.settle(700)


def sheet(ui):
    s = ui.store.get("sheet")
    return s["kind"] if s else None


def open_sheet_wait(ui, kind):
    ui.wait_until(lambda: sheet(ui) == kind, 6, f"the {kind} sheet")
    ui.settle(300)


def close_sheet_esc(ui):
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close on Esc")
    ui.settle(200)


def head(ui, pid=None):
    return ui.api("/projects/" + (pid or ui.store.get("pid")))["project"]["head"]


def fold(ui, title):
    """Open or close a folding section of the inspector by clicking its header."""
    f = ui.item(text=title)
    ui.scroll_to(f, 0.0)
    ui.click(f, 0.5, 20.0 / max(40.0, f.height()))
    ui.settle(250)


def toasts_gone(ui):
    """Toasts sit over the bottom right corner and wait while the pointer rests on them: move away, let them leave."""
    ui.hover("viewport", 0.5, 0.3)
    ui.wait_until(lambda: ui.store.get("toasts") == [], 15, "the toasts to leave")
    ui.settle(200)


def has_slicer(ui):
    return bool(ui.js("Store.slicer.available"))
