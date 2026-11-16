"""Illustrative renders in Blender, as cached project artifacts.

A render is keyed by the exports key (which follows the geometry key and the print orientation), the preset,
the material, the colour, the layer height, the engine and the Blender version. Change the design and the
expected key changes, so an old render simply stops being current — the same rule as every other artifact.

A render is an illustration. It says nothing about strength, fit or print quality, and it is never evidence.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .adapters import blender as bl
from .studio import H, StudioError

_info: dict = {"at": 0.0, "v": None, "key": None}
_busy: set = set()
_busy_lock = threading.Lock()


def blender(cfg: dict, refresh: bool = False) -> dict:
    """Is Blender usable here? Cached for a minute."""
    key = json.dumps(cfg.get("blender", {}), sort_keys=True, default=str)
    if refresh or _info["v"] is None or _info["key"] != key or time.time() - _info["at"] > 60:
        _info.update(v=bl.resolve(cfg), at=time.time(), key=key)
    return _info["v"]


def layer_height(st) -> dict:
    """The layer height the slicer would use now, from its selected process preset."""
    try:
        s = st.slicer_info()
        data = s.get("presets", {}).get("process", {}).get("data", {}) if s.get("available") else {}
        v = data.get("layer_height")
        if isinstance(v, list):
            v = v[0] if v else None
        mm = float(v) if v not in (None, "") else None
        if mm and 0.04 <= mm <= 1.0:
            return {"mm": mm, "source": "specified", "note": f"slicer process preset “{s['presets']['process']['name']}”"}
    except (StudioError, ValueError, TypeError, KeyError):
        pass
    return {"mm": None, "source": None, "note": "no slicer process preset is selected, so no layer lines are drawn"}


def _dir(st, p) -> Path:
    return st.dir(p["id"]) / "artifacts" / "photo"


def _options(st, preset, finish, color, fast, layer_lines) -> dict:
    if preset not in bl.PRESETS:
        raise StudioError(f"Unknown preset “{preset}”.", "Presets: " + ", ".join(bl.PRESETS) + ".")
    if finish not in bl.FINISHES:
        raise StudioError(f"Unknown material “{finish}”.", "Materials: " + ", ".join(bl.FINISHES) + ".")
    color = (color or bl.DEFAULT_COLOR).strip().lower()
    if not color.startswith("#"):
        color = "#" + color
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise StudioError(f"“{color}” is not a colour.", "Use a hex colour such as #3d6fb6.")
    layer = layer_height(st) if layer_lines else {"mm": None, "source": None, "note": "layer lines off"}
    return {"preset": preset, "finish": finish, "color": color, "fast": bool(fast), "layer": layer}


def key_for(st, p, o: dict) -> str:
    b = blender(st.cfg)
    keys = st.keys(p)
    return H("photo", keys["exports"], o["preset"], o["finish"], o["color"], o["fast"], o["layer"]["mm"],
             bl.SCENE_VERSION, b.get("version"))


def renders(st, p) -> list:
    """Every render of this project, newest first, each marked current or stale."""
    d = _dir(st, p)
    if not d.exists():
        return []
    try:
        gk = st.keys(p)["exports"]
    except Exception:                # kernel not up: nothing can be shown as current
        gk = None
    out = []
    for f in d.glob("*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if (d / f"{m.get('key')}.png").is_file():
            m["current"] = m.get("exports_key") == gk
            out.append(m)
    return sorted(out, key=lambda m: m.get("ts", 0), reverse=True)


def latest(st, p) -> dict | None:
    return next((m for m in renders(st, p) if m["current"]), None)


def state(st, p) -> dict:
    """Everything the Render sheet needs."""
    rs = renders(st, p)
    return {"blender": blender(st.cfg), "label": bl.LABEL,
            "presets": [{"id": k, **v} for k, v in bl.PRESETS.items()],
            "finishes": [{"id": k, "label": v["label"]} for k, v in bl.FINISHES.items()],
            "swatches": bl.SWATCHES, "default_color": bl.DEFAULT_COLOR, "layer": layer_height(st),
            "latest": next((m for m in rs if m["current"]), None), "current": [m for m in rs if m["current"]][:12],
            "stale": len([m for m in rs if not m["current"]]), "busy": p["id"] in _busy}


def render(st, p, preset="studio", finish="matte", color=None, fast=False, layer_lines=True, job=None) -> dict:
    """Render the current revision. Returns the render's record (cached if this exact render exists)."""
    b = blender(st.cfg, refresh=True)
    if not b["available"]:
        raise StudioError("Blender is not available, so FORM cannot render.", b["reason"], status=409)
    o = _options(st, preset, finish, color, fast, layer_lines)

    def say(frac, text):
        if job is not None:
            if frac is not None:
                job["progress"] = round(frac, 3)
            job["text"] = text

    key = key_for(st, p, o)
    d = _dir(st, p)
    meta_f, png = d / f"{key}.json", d / f"{key}.png"
    if meta_f.exists() and png.exists():
        m = json.loads(meta_f.read_text(encoding="utf-8"))
        m["cached"], m["current"] = True, True
        return m
    with _busy_lock:
        if p["id"] in _busy:
            raise StudioError("A render of this project is already running.", "Wait for it to finish.", status=409)
        _busy.add(p["id"])
    try:
        keys = st.keys(p)
        if st.read(p, "exports", keys["exports"]) is None:
            say(None, "Exporting the STL first")
            j = st.run_sync(p["id"], ["geometry", "exports"])
            if j["state"] != "done":
                bad = next((s for s in j["steps"] if s.get("error")), {})
                err = bad.get("error") or j.get("error") or {}
                raise StudioError("The STL could not be exported, so there is nothing to render.",
                                  err.get("message", ""), status=422)
            p = st.load(p["id"])
            keys = st.keys(p)
        ex = st.read(p, "exports", keys["exports"])
        stl = st.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{key}.tmp.png"
        try:
            jobspec = bl.build_job(stl, tmp, o["preset"], o["finish"], o["color"], o["layer"]["mm"], o["fast"],
                                   samples=int(st.cfg.get("blender", {}).get("samples", 128)))
        except ValueError as e:
            raise StudioError(str(e))
        timeout = float(st.cfg.get("blender", {}).get("timeout_s", 180))
        say(0.0, "Starting Blender")
        try:
            rep = bl.run_job(b["app"], jobspec, d / f"{key}.job.json", timeout=timeout, progress=say)
        except bl.BlenderFailed as e:
            tmp.unlink(missing_ok=True)
            raise StudioError(str(e), e.hint, status=422, log=e.log)
        finally:
            (d / f"{key}.job.json").unlink(missing_ok=True)
        tmp.replace(png)
        rev = st.rev(p)
        m = {"key": key, "file": png.name, "project": p["id"], "rev": rev["n"], "ts": time.time(),
             "exports_key": keys["exports"], "geometry_key": keys["geometry"], "stl_sha256": ex["files"]["stl"]["sha256"],
             "preset": o["preset"], "preset_label": bl.PRESETS[o["preset"]]["label"], "finish": o["finish"],
             "finish_label": bl.FINISHES[o["finish"]]["label"], "color": o["color"], "layer": o["layer"],
             "engine": rep.get("engine"), "device": rep.get("device"), "samples": rep.get("samples"),
             "blender": rep.get("blender") or b["version"], "seconds": rep.get("seconds"),
             "resolution": list(bl.SIZE), "camera": jobspec["view"], "label": bl.LABEL, "evidence": "illustration",
             "note": "Invented light and material on the exported STL. Not a photo of a print, and not evidence."}
        meta_f.write_text(json.dumps(m, indent=1), encoding="utf-8")
        m["cached"], m["current"] = False, True
        return m
    finally:
        with _busy_lock:
            _busy.discard(p["id"])


def start(st, pid: str, body: dict) -> dict:
    """Start a render in the background. Returns {"job"} or, when it already exists, {"render"}."""
    p = st.load(pid)
    args = {k: body.get(k) for k in ("preset", "finish", "color", "fast", "layer_lines") if body.get(k) is not None}
    args.setdefault("preset", "studio")
    args.setdefault("finish", "matte")
    b = blender(st.cfg)
    if not b["available"]:
        raise StudioError("Blender is not available, so FORM cannot render.", b["reason"], status=409)
    o = _options(st, args["preset"], args["finish"], args.get("color"), args.get("fast", False), args.get("layer_lines", True))
    try:
        key = key_for(st, p, o)
        f = _dir(st, p) / f"{key}.json"
        if f.exists() and (_dir(st, p) / f"{key}.png").exists():
            m = json.loads(f.read_text(encoding="utf-8"))
            m["cached"], m["current"] = True, True
            return {"render": m}
    except StudioError:
        pass
    job = {"id": uuid.uuid4().hex[:10], "project": pid, "kind": "photo", "state": "running", "started": time.time(),
           "progress": 0.0, "text": "Queued", "steps": [{"node": "photo", "label": "Render", "state": "running"}]}
    st.jobs[job["id"]] = job

    def go():
        try:
            job["result"] = render(st, st.load(pid), job=job, **args)
            job["state"], job["steps"][0]["state"], job["progress"] = "done", "done", 1.0
        except StudioError as e:
            job["state"], job["steps"][0]["state"], job["error"] = "failed", "failed", e.public()
        except Exception as e:      # never lose the project over a render
            job["state"], job["steps"][0]["state"] = "failed", "failed"
            job["error"] = {"message": f"Unexpected {type(e).__name__}: {e}", "hint": "The project is unchanged."}
        job["finished"] = time.time()
    threading.Thread(target=go, daemon=True, name="form-photo").start()
    return {"job": job["id"]}


def file(st, p, name: str) -> Path:
    """A render's PNG by key, or 'latest' (newest render of the current geometry)."""
    if name == "latest":
        m = latest(st, p)
        if not m:
            raise StudioError("No current render.", status=404)
        name = m["key"]
    if not re.fullmatch(r"[0-9a-f]{16}", name):
        raise StudioError("Unknown render.", status=404)
    f = _dir(st, p) / f"{name}.png"
    if not f.is_file():
        raise StudioError("That render does not exist.", status=404)
    return f


def latest_all(st) -> dict:
    """Newest current render per project (for the Home cards)."""
    out = {}
    for q in st.list():
        if q.get("error"):
            continue
        try:
            d = st.dir(q["id"]) / "artifacts" / "photo"
            if not d.exists():
                continue
            m = latest(st, st.load(q["id"]))
            if m:
                out[q["id"]] = {"key": m["key"], "preset": m["preset_label"], "ts": m["ts"]}
        except StudioError:
            continue
    return out
