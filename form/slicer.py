"""Facade over the configured slicer adapter ([slicer].kind: "auto" (default), "bambu", "orca", "prusa", …).

"auto" uses the first installed slicer in adapters.AUTO_ORDER (Bambu Studio first, so a machine
with Bambu Studio behaves exactly as when kind = "bambu").

A slice is a simulation by the slicer. It is not a print.
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import time
import tomllib
from pathlib import Path

from .adapters import AUTO_ORDER, SLICERS
from .adapters.bambu import flatten, parse_gcode_header  # noqa: F401
from .adapters.common import SlicerBlocked, SlicerFailed  # noqa: F401

_loaded: dict = {}


def adapter(kind: str):
    if kind not in SLICERS:
        raise SlicerBlocked(f"Unknown slicer kind “{kind}”. Known: auto, {', '.join(SLICERS)}.")
    if kind not in _loaded:
        _loaded[kind] = importlib.import_module(SLICERS[kind])
    return _loaded[kind]


def label(kind: str) -> str:
    try:
        return adapter(kind).LABEL
    except SlicerBlocked:
        return kind


def used(kind: str, cfg: dict) -> bool:
    """The slicer's "Use in Form Studio" switch (form/use.py): off, Form Studio never runs it or reads its printers."""
    from . import use
    return use.on(f"slicer.{kind}", cfg)


def _installed(kind: str, cfg: dict) -> bool:
    try:
        return bool(adapter(kind).find_app(cfg))
    except Exception:                                      # a broken adapter reads as not installed
        return False


def auto_kind(cfg: dict) -> str | None:
    """The first installed slicer that is switched on, or None."""
    for kind in AUTO_ORDER:
        try:
            if used(kind, cfg) and adapter(kind).find_app(cfg):
                return kind
        except Exception:                                  # a broken adapter must not hide the others
            continue
    return None


def resolve(cfg: dict) -> dict:
    want = cfg["slicer"].get("kind", "auto")
    kind = want
    if want == "auto":
        kind = auto_kind(cfg) or "bambu"
    off = kind in SLICERS and not used(kind, cfg)
    try:
        out = ({"available": False, "off": True, "presets": {}, "app": "",
                "reason": f"{label(kind)} is switched off in Settings › Engines & software (“Use in Form Studio”)."}
               if off else adapter(kind).resolve(cfg))
    except SlicerBlocked as e:
        out = {"available": False, "reason": str(e), "presets": {}, "app": ""}
    out["kind"] = kind
    out["chosen"] = want
    out.setdefault("label", label(kind))
    if not out.get("available") and out.get("reason") and out.get("app"):
        why = explain_failure(out, out["reason"])            # a preset format this version of Form Studio cannot read
        if why:
            out["reason"] = why[0] + " " + why[1]
    if want == "auto" and auto_kind(cfg) is None:
        idle = [label(k) for k in AUTO_ORDER if not used(k, cfg) and _installed(k, cfg)]
        others = ", ".join(label(k) for k in AUTO_ORDER if k != "bambu")
        out["reason"] = (f"{' and '.join(idle)} {'is' if len(idle) == 1 else 'are'} installed but switched off in "
                         "Settings › Engines & software (“Use in Form Studio”). Turn one on to slice."
                         if idle else f"{label('bambu')} was not found at {out.get('app') or 'its usual place'}, and neither was {others}. "
                         "Install one of them, or set [slicer].kind and its app in studio.toml.")
    return out


def _for(resolved: dict):
    return adapter(resolved.get("kind", "bambu"))


def version(app: str, kind: str = "bambu") -> str:
    return adapter(kind).version(app)


def public(resolved: dict) -> dict:
    out = _for(resolved).public(resolved)
    out["kind"] = resolved.get("kind", "bambu")
    return out


def _version_of(resolved: dict) -> str:
    try:
        return adapter(resolved.get("kind", "bambu")).version(resolved.get("app") or "") if resolved.get("app") else ""
    except Exception:
        return ""


def explain_failure(resolved: dict, message: str, log: str = "") -> tuple[str, str] | None:
    """(message, hint) naming the supported versions, when the installed version is why it failed (form/compat.py)."""
    from . import compat
    return compat.wrap_message(resolved.get("kind", "bambu"), _version_of(resolved), message, log)


def slice_stl(resolved: dict, stl, out_dir, timeout: float = 600) -> dict:
    try:
        info = _for(resolved).slice_stl(resolved, stl, out_dir, timeout)
    except SlicerFailed as e:
        why = explain_failure(resolved, str(e), e.log)
        if why:
            raise SlicerFailed(why[0], why[1], e.log) from e
        raise
    kind = resolved.get("kind", "bambu")
    info.setdefault("slicer_kind", kind)
    info.setdefault("slicer_name", label(kind))
    return info


def parse_layers(path, kind: str | None = None) -> list:
    """Layers of a G-code file written by `kind` (default Bambu Studio)."""
    return adapter(kind or "bambu").parse_layers(Path(path))


def detect_all(cfg: dict) -> list[dict]:
    """Every slicer FORM knows, whether it is installed, its version and the presets it would use."""
    active = resolve(cfg)["kind"]
    out = []
    for kind in AUTO_ORDER:
        a = adapter(kind)
        try:
            app = a.find_app(cfg)
            r = a.resolve(cfg) if used(kind, cfg) else {
                "available": False, "presets": {}, "app": app or "",
                "reason": f"{a.LABEL} is switched off in Settings › Engines & software (“Use in Form Studio”)."}
        except Exception as e:                             # report, never hide
            app, r = None, {"available": False, "reason": f"Could not check {a.LABEL}: {e}", "presets": {}}
        entry = {
            "kind": kind, "label": a.LABEL, "installed": bool(app), "used": used(kind, cfg), "app": app or r.get("app", ""),
            "available": bool(r.get("available")), "reason": r.get("reason", ""), "active": kind == active,
            "presets": {k: v["name"] for k, v in r.get("presets", {}).items()},
            "source": r.get("source", {}), "config_dir": r.get("config_dir", ""),
            "envelope_mm": r.get("envelope_mm"), "nozzle_mm": r.get("nozzle_mm"),
            "version": a.version(app) if app else None,
            "install": None if app else a.install_hint(),
        }
        from . import compat                               # informational: which versions Form Studio is built for
        entry["compat"] = compat.status(kind, entry["version"]) if app else {"range": compat.range_text(kind) if kind in compat.RANGES else ""}
        out.append(entry)
    return out


# ---- studio.toml: [slicer].kind ----------------------------------------------
def config_target(cfg: dict) -> Path:
    """The studio.toml that `form` reads (or would read once it exists)."""
    from .config import USER_CONFIG
    p = Path(cfg.get("_path", ""))
    if os.environ.get("FORM_CONFIG") or p.exists():
        return Path(os.environ.get("FORM_CONFIG") or p).expanduser()
    return USER_CONFIG


def set_kind_text(text: str, kind: str) -> str:
    """Set [slicer].kind in TOML text; every other line stays as it was."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^\s*\[slicer\]\s*(#.*)?$", ln)), None)
    new = f'kind = "{kind}"'
    if start is None:
        return text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[slicer]\n{new}\n"
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    for i in range(start + 1, end):
        m = re.match(r"^(\s*)kind\s*=\s*(\"[^\"]*\"|'[^']*'|[^#\s]+)(\s*#.*)?(\r?\n)?$", lines[i])
        if m:
            lines[i] = f"{m.group(1)}{new}{m.group(3) or ''}{m.group(4) or ''}"
            return "".join(lines)
    nl = "\r\n" if lines[start].endswith("\r\n") else "\n"
    if not lines[start].endswith(("\n", "\r\n")):
        lines[start] += nl
    lines.insert(start + 1, new + nl)
    return "".join(lines)


def set_kind(cfg: dict, kind: str) -> dict:
    """Write [slicer].kind to studio.toml (backing the file up first). Nothing else in the file changes."""
    if kind != "auto" and kind not in SLICERS:
        raise SlicerBlocked(f"Unknown slicer kind “{kind}”. Known: auto, {', '.join(SLICERS)}.")
    path = config_target(cfg)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    new = set_kind_text(old or "# Form Studio configuration (written by Form Studio)\n", kind)
    before = tomllib.loads(old) if old else {}
    after = tomllib.loads(new)
    a, b = dict(after), dict(before)
    a_s, b_s = dict(a.pop("slicer", {})), dict(b.pop("slicer", {}))
    a_s.pop("kind", None), b_s.pop("kind", None)
    if a != b or a_s != b_s or after["slicer"]["kind"] != kind:
        raise SlicerBlocked(f"Could not change only [slicer].kind in {path}; it was left as it was.")
    backup = None
    if path.exists():
        backup = path.with_name(path.name + f".bak-form-{int(time.time())}")
        shutil.copyfile(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    cfg["slicer"]["kind"] = kind
    return {"path": str(path), "backup": str(backup) if backup else None, "kind": kind}
