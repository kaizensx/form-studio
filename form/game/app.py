"""The game asset in the desktop app: what the engine's HTTP API (form/server.py) serves the Game asset sheet
(form/app/qml/Form/GameSheet.qml).

    GET  /api/projects/<pid>/game                     state(): presets, budgets, Blender and CoACD, the last build
    POST /api/projects/<pid>/game {action, preset...}  build(): game_asset() (build | validate | export)
    GET  /api/projects/<pid>/game/<key>/lod/<i>       lod(): one LOD's triangles, UVs and wireframe for the viewport
    GET  /api/projects/<pid>/game/<key>/tex/<map>.png  texture(): a baked map (base_color, normal, orm, ao)
    GET  /api/projects/<pid>/game/<key>.zip            archive(): every file of the asset, for the engine

Every asset lives under <data>/.cache/game/<key>/ (form/game/__init__.py); the last one built for a project is
remembered in <data>/.cache/game/last/<pid>.json so the sheet opens on it. Reads projects, never writes them.
"""
from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np

from . import presets as pz

KEY_RE = re.compile(r"[0-9a-f]{16}")
MAPS = ("base_color", "normal", "orm", "ao")
# what the sheet offers: the engine presets the person picks between (glTF and Godot share the GLB)
ENGINE_CHOICES = [{"id": "gltf", "label": "glTF / Godot", "detail": "GLB, metres, +Y up"},
                  {"id": "unity", "label": "Unity", "detail": "FBX and GLB, metres"},
                  {"id": "unreal", "label": "Unreal", "detail": "FBX and GLB, centimetres, Z up, UCX_ collision"}]


def _base(st) -> Path:
    return Path(st.root) / ".cache" / "game"


def _dir(st, key: str) -> Path:
    if not KEY_RE.fullmatch(str(key or "")):
        from ..studio import StudioError
        raise StudioError("Unknown game asset.", status=404)
    d = _base(st) / key
    if not (d / "report.json").is_file():
        from ..studio import StudioError
        raise StudioError("There is no game asset with that key.", "Build it first.", status=404)
    return d


def _last_file(st, pid: str) -> Path:
    return _base(st) / "last" / f"{re.sub(r'[^a-z0-9-]', '', pid)[:80]}.json"


def software(cfg) -> dict:
    """Is Blender there (the pipeline bakes in it), and CoACD (optional collision)?"""
    out = {"blender": False, "blender_reason": "", "coacd": False}
    try:
        from ..adapters.blender import resolve
        r = resolve(cfg)
        out["blender"] = bool(r.get("available"))
        out["blender_reason"] = "" if out["blender"] else str(r.get("reason") or "Blender is not installed.")
        out["blender_version"] = r.get("version") if out["blender"] else None
    except Exception as e:                                       # noqa: BLE001 - a broken install reads as missing
        out["blender_reason"] = str(e)
    try:
        from .. import engines
        from .lod import COACD_ENGINE
        out["coacd"] = engines.python(COACD_ENGINE, cfg) is not None
    except Exception:                                            # noqa: BLE001
        out["coacd"] = False
    return out


def summary(res: dict) -> dict:
    """What the sheet shows of a game_asset() result."""
    return {k: res.get(k) for k in ("key", "preset", "lods", "uv", "bake", "collision", "validation", "size_mm",
                                    "notes", "retopology_note", "cached", "rev")}


def textures(st, key: str) -> dict:
    """map -> the baked PNG's path on this computer (the app's viewport reads them as local files)."""
    d = _base(st) / key
    try:
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {m: str(d / "textures" / f"{rep['asset']}_{m}.png") for m in MAPS
            if (d / "textures" / f"{rep['asset']}_{m}.png").is_file()}


def state(st, p: dict) -> dict:
    from .. import purpose as purpose_mod
    last = None
    f = _last_file(st, p["id"])
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
        d = _base(st) / rec["key"]
        if (d / "report.json").is_file():
            last = {**rec, "current": rec.get("geometry") == st.keys(p)["geometry"], "textures": textures(st, rec["key"])}
    except (OSError, ValueError, KeyError):
        last = None
    return {"purpose": purpose_mod.of(p), "engines": ENGINE_CHOICES,
            "presets": [{"id": k, "label": v["label"]} for k, v in pz.PRESETS.items()],
            "budgets": list(pz.DEFAULT_BUDGETS), "texture_px": list(pz.TEXTURE_PX), "bake": list(pz.BAKE),
            "software": software(getattr(st, "cfg", None)), "last": last}


def build(st, pid: str, body: dict) -> dict:
    """game_asset() with the sheet's options; remembers the result as the project's last asset."""
    from . import game_asset
    body = body if isinstance(body, dict) else {}
    res = game_asset(st, pid, action=str(body.get("action") or "build"), preset=str(body.get("preset") or "gltf"),
                     budgets=body.get("budgets") or None, texture_px=int(body.get("texture_px") or 1024),
                     bake=str(body.get("bake") or "fast"), collision=str(body.get("collision") or "hull"))
    p = st.load(pid)
    rec = {**summary(res), "geometry": st.keys(p)["geometry"], "files": sorted(Path(x).name for x in
                                                                                (res.get("files") or {}).values())}
    f = _last_file(st, pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, default=float), encoding="utf-8")
    return {**rec, "current": True, "textures": textures(st, res["key"])}


def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode()


def lod(st, key: str, i: int) -> dict:
    """One LOD for the viewport: positions (mm, Z up, as the design), triangles, UVs (v up) and its edges as line
    segments (the wireframe), with its triangle count and budget."""
    d = _dir(st, key)
    f = d / "lods" / f"lod{int(i)}.npz"
    if not f.is_file():
        from ..studio import StudioError
        raise StudioError(f"LOD{i} is not in this asset.", status=404)
    z = np.load(f, allow_pickle=False)
    P, T, UV = z["P"].astype(np.float64), z["T"].astype(np.int64), z["UV"].astype(np.float64)
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    off = np.asarray(rep.get("pivot_offset_mm") or [0, 0, 0], dtype=np.float64)
    P = P - off                                   # back where the design sits (the asset's pivot moved it)
    # the wireframe: every triangle edge once, welded across UV and normal seams
    key_pts = np.round(P, 5)
    _, weld = np.unique(key_pts, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    E = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    W = np.sort(weld[E], axis=1)
    _, first = np.unique(W, axis=0, return_index=True)
    E = E[np.sort(first)]
    seg = P[E].reshape(-1, 3)
    row = next((r for r in rep["lods"] if int(r["lod"]) == int(i)), {})
    return {"lod": int(i), "triangles": int(len(T)), "budget": row.get("budget"), "source": row.get("source", ""),
            "positions": _b64(P, np.float32), "indices": _b64(T, np.uint32), "uvs": _b64(UV, np.float32),
            "wire": _b64(seg, np.float32), "edges": int(len(E)),
            "bbox": [P.min(0).round(4).tolist(), P.max(0).round(4).tolist()]}


def texture(st, key: str, name: str) -> bytes:
    from ..studio import StudioError
    if name not in MAPS:
        raise StudioError("Unknown map.", "Maps: " + ", ".join(MAPS) + ".", status=404)
    d = _dir(st, key)
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    f = d / "textures" / f"{rep['asset']}_{name}.png"
    if not f.is_file():
        raise StudioError(f"This asset has no {name} map.", status=404)
    return f.read_bytes()


def archive(st, key: str) -> tuple[bytes, str]:
    """Every file of the asset in one zip, under a folder named after it and its preset. (bytes, file name)"""
    d = _dir(st, key)
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    name = f"{rep['asset']}-{rep['preset']['id']}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.rglob("*")):
            if f.is_file():
                z.write(f, f"{name}/{f.relative_to(d).as_posix()}")
    return buf.getvalue(), f"{name}.zip"
