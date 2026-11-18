"""`form setup` for the desktop app: the same checks and fixes, over the engine API.

    GET  /api/setup                 every item from setup.check(), grouped, plus first-run state
    POST /api/setup/apply           {ids, shown: {id: [commands]}} → {job}; runs only those fixes
    GET  /api/setup/job/<id>        progress: each fix, its commands, output, and the item re-checked afterwards
    POST /api/setup/seen            remember that the welcome was shown (the user pressed Skip or Done)
    POST /api/setup/step            {step} remember which onboarding step the user reached

The installer registry (form/installer.py), sign-in, settings and examples, all through route_get/route_post:
    GET  /api/install               every installable thing, detected, with the commands an install would run
    POST /api/install               {ids, shown: {id: [commands]}, methods?} → job (runs only what was shown)
    GET  /api/install/job/<id>?from=N   state, steps, new log lines
    POST /api/install/job/<id>/cancel
    POST /api/install/auto {ids?}   hands-free: install what is needed, pause only where the person must act (sign in,
                                    a download page), detect that and continue; same job API, steps may be "needs_user"
    POST /api/install/job/<id>/skip {id}    leave one item of a hands-free setup
    GET  /api/claude/auth           is Claude Code installed and signed in (no account details)
    POST /api/claude/login          start `claude auth login` in the background → job with the sign-in link
    GET  /api/claude/login/<id>     POST …/code {code}     POST …/cancel
    GET  /api/config                studio.toml settings and their schema;  POST /api/config {values} writes them
    GET  /api/examples              shipped examples;  POST /api/examples {ids?} adds them (never automatic)

Same safety as the CLI: a fix runs only when the user ticked it and pressed Apply; the commands it runs must be
exactly the ones the app showed (otherwise it refuses and asks to check again); config files are backed up by the
fix itself (see setup._json_register / _write_printer); every applied item is checked again afterwards.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config_edit, installer
from . import secrets as agent_keys          # FORM's store of agent keys (the stdlib secrets is used below too)
from . import setup as setup_mod
from .studio import StudioError

MARKER = ".form-setup.json"
STEP_FILE = ".form-onboarding.json"          # which first-run step the user reached
REQUIRED = ("kernel", "data")
# id prefix → group. Items another workstream adds land in the group of their prefix, or in "other".
GROUPS = [
    ("engine", "Form Studio itself", ("kernel", "data", "python")),
    ("slicer", "Slicer and printer", ("slicer", "printer")),
    ("cad", "CAD and 3D apps", ("cad", "freecad", "blender", "openscad", "fusion", "onshape")),
    ("chat", "Agents for chat", ("chat.", "agent.claude")),
    ("agents", "Other agents", ("agent.",)),
    ("other", "Other", ()),
]
RELEASES = "https://github.com/kaizensx/form-studio/releases"


def group_of(item_id: str) -> str:
    for gid, _, prefixes in GROUPS:
        for p in prefixes:
            if p.endswith("."):
                if item_id.startswith(p):
                    return gid
            elif item_id == p or item_id.startswith((p + ".", p + "_")):
                return gid
    return "other"


def _packaged_fix(fix: setup_mod.Fix | None) -> setup_mod.Fix | None:
    """In the packaged app there is no uv tool install to repair; point at the download instead."""
    if not fix or not getattr(sys, "frozen", False) or not any(c.startswith("uv tool") for c in fix.commands):
        return fix
    return setup_mod.Fix("Download the Form Studio app again", [], recommended=fix.recommended,
                         note=f"This copy of Form Studio is a packaged app. Get the current build from {RELEASES}")


def items(cfg: dict, studio=None) -> list[setup_mod.Item]:
    out = setup_mod.check(cfg, studio)
    for i in out:
        i.fix = _packaged_fix(i.fix)
    return out


def _runnable(fix: setup_mod.Fix | None) -> bool:
    return bool(fix and (fix.action or fix.commands))


def marker_path(cfg: dict) -> Path:
    return Path(cfg["data"]["dir"]) / MARKER


def first_run(cfg: dict) -> bool:
    return not marker_path(cfg).exists()


def onboarding(cfg: dict) -> dict:
    """Where the first-run flow stopped: {"step": 0-2, "done": bool}. Kept in a small file in the data folder."""
    for name in (MARKER, STEP_FILE):
        try:
            rec = json.loads((Path(cfg["data"]["dir"]) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if name == MARKER:
            return {"step": 0, "done": True}
        return {"step": max(0, min(2, int(rec.get("step", 0)))), "done": False}
    return {"step": 0, "done": False}


def set_step(cfg: dict, step) -> dict:
    try:
        n = max(0, min(2, int(step)))
    except (TypeError, ValueError):
        raise StudioError("step must be 0, 1 or 2.")
    p = Path(cfg["data"]["dir"]) / STEP_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"step": n, "ts": time.time()}), encoding="utf-8")
    except OSError as e:
        raise StudioError(f"Could not write {p}: {e}", hint="Check that the project folder is writable.")
    return {"step": n, "done": False}


def mark_seen(cfg: dict, how: str = "seen") -> dict:
    from . import __version__
    p = marker_path(cfg)
    rec = {"ts": time.time(), "version": __version__, "how": how}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec), encoding="utf-8")
    except OSError as e:
        raise StudioError(f"Could not write {p}: {e}", hint="Check that the project folder is writable.")
    return rec


def public(item: setup_mod.Item) -> dict:
    d = item.public()
    home = str(Path.home())
    if home and len(home) > 1:                              # display only; commands are never rewritten
        d["detail"] = d["detail"].replace(home, "~")
    d["group"] = group_of(item.id)
    d["required"] = item.id in REQUIRED
    d["runnable"] = _runnable(item.fix) and item.status != "ok"
    d["edits_file"] = bool(item.fix and item.fix.action)
    d["default"] = d["runnable"] and d["required"]         # required fixes start ticked, optional ones never
    return d


def report(cfg: dict, studio=None) -> dict:
    its = [public(i) for i in items(cfg, studio)]
    need = [i for i in its if i["required"]]
    groups = []
    for gid, title, _ in GROUPS:
        members = [i["id"] for i in its if i["group"] == gid]
        if members:
            groups.append({"id": gid, "title": title, "items": members})
    detected = [{"id": i["id"], "label": i["label"], "detail": i["detail"]} for i in its
                if i["group"] in ("slicer", "cad") and i["status"] == "ok"]
    attention = [i["id"] for i in its if i["status"] in ("missing", "warn") and
                 (i["required"] or (i.get("fix") or {}).get("recommended"))]
    return {"items": its, "groups": groups, "detected": detected,
            "required_ok": all(i["status"] in ("ok", "info") for i in need),
            "first_run": first_run(cfg), "attention": attention, "mcp_command": setup_mod.mcp_command(),
            "checked": time.time(), "onboarding": onboarding(cfg)}


# ---- applying fixes ---------------------------------------------------------

class ApplyJob:
    def __init__(self, cfg, studio, chosen: list[setup_mod.Item]):
        self.id = secrets.token_hex(5)
        self.cfg, self.studio = cfg, studio
        self.chosen = chosen
        self.state = "running"
        self.started = time.time()
        self.steps = [{"id": i.id, "label": i.label, "summary": i.fix.summary, "commands": list(i.fix.commands),
                       "edits_file": bool(i.fix.action), "state": "waiting", "message": "", "output": ""} for i in chosen]
        self.after: dict = {}

    def public(self) -> dict:
        return {"id": self.id, "state": self.state, "steps": self.steps, "after": self.after}

    def run(self):
        try:
            for step, item in zip(self.steps, self.chosen):
                step["state"] = "running"
                ok, msg, out = _execute(item.fix)
                step.update(state="done" if ok else "failed", message=msg, output=out)
            after = {i.id: public(i) for i in items(self.cfg, self.studio)}
            self.after = {s["id"]: after.get(s["id"]) for s in self.steps}
            if self.studio is not None:
                try:
                    self.studio.slicer_info(refresh=True)
                except Exception:
                    pass
            self.state = "failed" if any(s["state"] == "failed" for s in self.steps) else "done"
        except Exception as e:                 # never leave a job "running" forever
            self.state = "failed"
            self.steps.append({"id": "_", "label": "Setup", "summary": "", "commands": [], "state": "failed",
                               "message": f"{type(e).__name__}: {e}", "output": ""})


def _execute(fix: setup_mod.Fix, timeout: int = 1800) -> tuple[bool, str, str]:
    if fix.action:
        try:
            return True, fix.action(), ""
        except Exception as e:
            return False, str(e), ""
    log = []
    for cmd in fix.commands:
        log.append(f"$ {cmd}")
        try:
            # no terminal stdin: Bun-based CLIs (claude) crash on /dev/tty on macOS; shell=True runs cmd.exe on Windows
            r = subprocess.run(cmd, shell=True, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"stopped after {timeout // 60} minutes", "\n".join(log)[-6000:]
        except OSError as e:
            return False, str(e), "\n".join(log)[-6000:]
        if (r.stdout or r.stderr).strip():
            log.append((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            return False, f"exited with {r.returncode}", "\n".join(log)[-6000:]
    return True, "done", "\n".join(log)[-6000:]


def _fresh(root: Path) -> bool:
    try:
        return not any(f.is_file() for d in root.iterdir() if d.is_dir() for f in (d / "artifacts").rglob("*"))
    except OSError:
        return False


class Setup:
    """One per engine. Holds apply jobs; only one runs at a time."""

    def __init__(self, cfg, studio=None):
        self.cfg, self.studio = cfg, studio
        self.jobs: dict[str, ApplyJob] = {}
        # a new data folder: nothing built yet (no artifacts). Measured at engine start.
        self.fresh = studio is not None and _fresh(Path(cfg["data"]["dir"]))
        self._lock = threading.Lock()
        self.installer = installer.Installer(cfg, on_done=self._installed)

    def _installed(self, job) -> None:
        if self.studio is not None:                         # a new slicer or CLI: the engine should see it at once
            try:
                self.studio.slicer_info(refresh=True)
            except Exception:
                pass

    def report(self) -> dict:
        return report(self.cfg, self.studio)

    def apply(self, ids, shown, start: bool = True) -> ApplyJob:
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise StudioError("Pick at least one item to set up.")
        if not isinstance(shown, dict):
            raise StudioError("The app must send the commands it showed.", hint="Check setup again, then apply.")
        with self._lock:
            if any(j.state == "running" for j in self.jobs.values()):
                raise StudioError("Setup is already running.", status=409)
            current = {i.id: i for i in items(self.cfg, self.studio)}
            chosen = []
            for iid in dict.fromkeys(ids):
                i = current.get(iid)
                if i is None:
                    raise StudioError(f"Unknown setup item “{iid}”.", status=400)
                if i.status == "ok" or not _runnable(i.fix):
                    raise StudioError(f"{i.label}: there is nothing Form Studio can run for this.",
                                      hint=(i.fix.note if i.fix else "") or "It is already set up.", status=400)
                if list(shown.get(iid) or []) != list(i.fix.commands):
                    raise StudioError(f"{i.label}: the fix changed since it was shown.",
                                      hint="Check setup again and review the commands before applying.", status=409)
                chosen.append(i)
            job = ApplyJob(self.cfg, self.studio, chosen)
            self.jobs[job.id] = job
        if start:
            threading.Thread(target=job.run, daemon=True, name="form-setup").start()
        mark_seen(self.cfg, "applied")
        return job

    def job(self, jid: str) -> ApplyJob:
        j = self.jobs.get(jid)
        if not j:
            raise StudioError("Unknown setup job.", status=404)
        return j


# ---- installer, sign-in, settings, examples: the engine routes (form/server.py calls these two) ---------------------

def _wrap(fn):
    try:
        return fn()
    except installer.InstallError as e:
        raise StudioError(e.message, hint=e.hint, status=e.status)
    except config_edit.ConfigError as e:
        raise StudioError(e.message, hint=e.hint)
    except agent_keys.SecretError as e:
        raise StudioError(str(e), hint=e.hint)
    except RuntimeError as e:
        raise StudioError(str(e))


def software(cfg: dict) -> dict:
    rows = installer.survey(cfg)
    return {"software": rows, **installer.summary(rows), "platform": installer.platform_key(),
            "packaged": installer.frozen(), "onboarding": onboarding(cfg), "checked": time.time()}


def route_get(st, path: str, q: dict):
    """Returns the JSON for a GET this module owns, or None."""
    sa: Setup = st.setup_app
    if path == "/api/install":
        return software(st.cfg)
    m = re.fullmatch(r"/api/install/job/([0-9a-f]{10})", path)
    if m:
        return _wrap(lambda: sa.installer.job(m.group(1)).public(int(q.get("from") or 0)))
    if path == "/api/install/auto":               # hands-free setup: would it start, and for what (engine workstream)
        import os
        return {"enabled": os.environ.get("FORM_NO_AUTO_SETUP", "") != "1",
                "ids": installer.auto_ids(installer.survey(st.cfg), st.cfg)}
    if path == "/api/claude/auth":
        return installer.claude_auth(st.cfg)
    m = re.fullmatch(r"/api/claude/login/([0-9a-f]{10})", path)
    if m:
        return _wrap(lambda: sa.installer.login_job(m.group(1)).public())
    if path == "/api/config":
        return config_edit.describe(st.cfg)
    if path == "/api/secrets":                    # which agent keys are stored: never their values
        return {"keys": list(agent_keys.status().values())}
    if path == "/api/examples":
        from .studio import list_examples
        return {"examples": list_examples(st.root)}
    return None


def route_post(st, path: str, body):
    """Returns the JSON for a POST this module owns, or None."""
    sa: Setup = st.setup_app
    body = body if isinstance(body, dict) else {}
    if path == "/api/setup/step":
        return set_step(st.cfg, body.get("step"))
    if path == "/api/install":
        job = _wrap(lambda: sa.installer.install(body.get("ids"), body.get("shown") if isinstance(body.get("shown"), dict) else {},
                                                 body.get("methods") if isinstance(body.get("methods"), dict) else None))
        st.activity(None, "setup", "Installing: " + ", ".join(s["label"] for s in job.steps), by="you")
        return job.public()
    if path == "/api/updates/install":            # upgrade FORM itself: the command that was shown, as an install job
        job = _wrap(lambda: sa.installer.update(body.get("shown") if isinstance(body.get("shown"), str) else None))
        st.activity(None, "setup", "Upgrading Form Studio", by="you")
        return job.public()
    # -- hands-free setup (engine workstream): install everything needed, pause only for the person --
    if path == "/api/install/auto":
        ids = body.get("ids") if isinstance(body.get("ids"), list) else None
        job = _wrap(lambda: sa.installer.auto(ids))
        if job.steps:
            st.activity(None, "setup", "Setting up: " + ", ".join(s["label"] for s in job.steps), by="you")
        return job.public()
    m = re.fullmatch(r"/api/install/job/([0-9a-f]{10})/skip", path)
    if m:
        j = _wrap(lambda: sa.installer.job(m.group(1)))
        if not hasattr(j, "skip"):
            raise StudioError("Only a hands-free setup can skip an item.")
        j.skip(str(body.get("id") or ""))
        return j.public()
    m = re.fullmatch(r"/api/install/job/([0-9a-f]{10})/cancel", path)
    if m:
        j = _wrap(lambda: sa.installer.job(m.group(1)))
        j.cancel()
        return {"ok": True}
    if path == "/api/claude/login":
        return _wrap(lambda: sa.installer.login().public())
    m = re.fullmatch(r"/api/claude/login/([0-9a-f]{10})/(code|cancel)", path)
    if m:
        j = _wrap(lambda: sa.installer.login_job(m.group(1)))
        if m.group(2) == "cancel":
            j.cancel()
        else:
            _wrap(lambda: j.send_code(str(body.get("code", ""))[:400]))
        return j.public()
    if path == "/api/config":
        done = _wrap(lambda: config_edit.set_values(st.cfg, body.get("values")))
        if done["changed"]:
            try:
                st.slicer_info(refresh=True)
            except Exception:
                pass
            st.activity(None, "settings", "Settings changed: " + ", ".join(done["changed"]) + ".", by="you")
        return {**done, "config": config_edit.describe(st.cfg)}
    if path == "/api/secrets":                    # {name, value} stores a key; {name, clear: true} removes it
        name = str(body.get("name") or "")
        if body.get("clear"):
            row = _wrap(lambda: agent_keys.clear(name))
            st.activity(None, "settings", f"{row['label']} removed.", by="you")
        else:
            row = _wrap(lambda: agent_keys.set_value(name, str(body.get("value") or "")))
            st.activity(None, "settings", f"{row['label']} saved.", by="you")
        from .agents import providers as _prov            # the model lists that key gave (or did not) are stale
        _prov.forget()
        return {"key": row, "keys": list(agent_keys.status().values())}
    if path == "/api/examples":
        ids = body.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(x, str) for x in ids)):
            raise StudioError("ids must be a list of example ids.")
        made = st.seed_examples(ids or None)
        return {"added": made, "projects": st.list()}
    return None
