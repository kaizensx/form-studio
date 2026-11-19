"""What the person set Form Studio up for: the launcher's "What do you want to make?" cards.

    [general].capabilities = ["core", "parts", "mesh", ...]      in studio.toml

Each capability names the software it needs (form/installer.py Software.capability). Turning one on installs only
that; turning one off hides it in the app and never uninstalls anything. "core" (the CAD kernel and the project
folder) is always on and ships with Form Studio. Printing is the capability "print": form/purpose.py printing()
is derived from it, and it is off unless the person turns it on.

Before capabilities existed the answer was one boolean, [general].printing; a file that still has only that is read
as the defaults plus "print" when it was true. migrate() runs once at engine start and keeps people who already
print (a configured slicer or printer, or designs made for printing) on printing.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# the launcher's cards, in the order shown; 3D printing is optional and comes last
CATALOGUE = [
    {"id": "core", "title": "Parametric CAD", "icon": "cuboid", "level": "required", "default": True,
     "sub": "Describe a part and the agent builds it as exact, editable CAD. STEP, STL, 3MF, OBJ and GLB exports.",
     "installs": "The CAD kernel (ships with Form Studio)"},
    {"id": "parts", "title": "Mechanical parts", "icon": "cog", "level": "recommended", "default": True,
     "sub": "Real screws, threads, bearings and gears from standard-parts libraries.",
     "installs": "bd_warehouse and py_gearworks"},
    {"id": "mesh", "title": "Mesh to CAD", "icon": "box", "level": "recommended", "default": True,
     "sub": "Bring in STL and mesh references and work from them.",
     "installs": "Nothing to download: trimesh and scipy ship with Form Studio"},
    {"id": "render", "title": "Photoreal renders", "icon": "camera", "level": "optional", "default": False,
     "sub": "Studio-lit pictures of a design in Blender. Never used for measurements.",
     "installs": "Blender"},
    {"id": "exchange", "title": "CAD exchange", "icon": "file_box", "level": "optional", "default": False,
     "sub": "Open designs in FreeCAD, re-check each STEP export, and build OpenSCAD designs.",
     "installs": "FreeCAD and OpenSCAD"},
    {"id": "print", "title": "3D printing", "icon": "printer", "level": "optional", "default": False,
     "sub": "Checks against your printer, slicing, print simulation, fit calibration and filament cost.",
     "installs": "One slicer (Bambu Studio, OrcaSlicer or PrusaSlicer)"},
]
IDS = [c["id"] for c in CATALOGUE]
DEFAULTS = [c["id"] for c in CATALOGUE if c["default"]]
REQUIRED = ("core",)
MIGRATION_FILE = ".form-migrations.json"      # in the data folder: one-time changes already made


def normalise(ids) -> list[str]:
    """Known ids in catalogue order, with "core" always in."""
    if isinstance(ids, str):
        ids = [x for x in re.split(r"[,\s]+", ids) if x]
    want = {str(x).strip().lower() for x in (ids or [])} | set(REQUIRED)
    return [i for i in IDS if i in want]


def of(cfg: dict) -> list[str]:
    """The capabilities in use. [general].capabilities, else the legacy [general].printing answer, else the defaults."""
    g = (cfg or {}).get("general") or {}
    caps = g.get("capabilities")
    if isinstance(caps, (list, tuple)):
        return normalise(caps)
    p = g.get("printing")                     # the older answer: "I have a 3D printer"
    if p is True or str(p).strip().lower() in ("true", "yes", "on", "1"):
        return normalise(DEFAULTS + ["print"])
    return list(DEFAULTS)


def has(cfg: dict, cap: str) -> bool:
    return cap in of(cfg)


def decided(cfg: dict) -> bool:
    """Has the person chosen (the launcher or Settings), or answered the older printer question? Only the file counts."""
    from . import config_edit
    return config_edit.file_value(cfg, "general.capabilities") is not None or \
        config_edit.file_value(cfg, "general.printing") is not None


def with_cap(cfg: dict, cap: str, on: bool) -> list[str]:
    caps = of(cfg)
    if on and cap not in caps:
        caps.append(cap)
    if not on and cap not in REQUIRED:
        caps = [c for c in caps if c != cap]
    return normalise(caps)


def _mb(size: str) -> float:
    m = re.search(r"([\d.]+)\s*(MB|GB)", size or "", re.I)
    if not m:
        return 0.0
    return float(m.group(1)) * (1000 if m.group(2).upper() == "GB" else 1)


def plan(rows: list[dict], caps: list[str]) -> dict:
    """For each capability: its software, what is missing, and what turning it on would download (a family such as the
    slicers needs one member: the first recommended one, unless one is already installed)."""
    by_cap: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("capability"):
            by_cap.setdefault(r["capability"], []).append(r)
    out = []
    for c in CATALOGUE:
        sw = by_cap.get(c["id"], [])
        missing = [r for r in sw if r["status"] in ("missing", "warn")]
        fams = {r["one_of"] for r in sw if r.get("one_of") and r["status"] == "ok"}
        missing = [r for r in missing if not (r.get("one_of") and r["one_of"] in fams)]
        picked, seen = [], set()
        for r in sorted(missing, key=lambda r: 0 if r["level"] in ("required", "recommended") else 1):
            if r.get("one_of"):
                if r["one_of"] in seen:
                    continue
                seen.add(r["one_of"])
            picked.append(r)
        out.append({**c, "on": c["id"] in caps, "software": [r["id"] for r in sw],
                    "ready": not picked, "install": [r["id"] for r in picked if r.get("installable")],
                    "manual": [r["id"] for r in picked if not r.get("installable")],
                    "size_mb": round(sum(_mb(r.get("size", "")) for r in picked))})
    return {"capabilities": out, "chosen": caps,
            "download_mb": round(sum(x["size_mb"] for x in out if x["on"]))}


def describe(cfg: dict, rows: list[dict] | None = None) -> dict:
    from . import installer
    rows = installer.survey(cfg) if rows is None else rows
    return {**plan(rows, of(cfg)), "decided": decided(cfg), "printing": "print" in of(cfg)}


# ---- one-time migration ------------------------------------------------------------------------------------------

def _shipped_file(cfg: dict) -> bool:
    from . import config, config_edit
    try:
        return config_edit.target(cfg).resolve() == (config.ROOT / "studio.toml").resolve()
    except OSError:
        return False


def _print_evidence(cfg: dict, root: Path) -> str:
    """Why this person already prints, or "" when nothing says so."""
    from . import config_edit, purpose
    if not _shipped_file(cfg):          # the source checkout's studio.toml is Form Studio's, not the person's choice
        kind = config_edit.file_value(cfg, "slicer.kind")
        if kind and str(kind).strip().lower() != "auto":
            return f"[slicer].kind = {kind}"
        for k in ("printer.slicer", "printer.machine", "slicer.machine", "slicer.process", "slicer.filament"):
            v = config_edit.file_value(cfg, k)
            if v and str(v).strip().lower() != "auto":
                return f"[{k.replace('.', '].', 1)} is set"
    try:
        for d in sorted(Path(root).iterdir()):
            f = d / "project.json"
            if f.is_file():
                try:
                    p = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(p, dict) and purpose.of(p) == "print":
                    return f"the design {d.name} is made for printing"
    except OSError:
        pass
    return ""


def migrate(cfg: dict, root: Path | None = None) -> dict:
    """Once per data folder: before Form Studio was creation-first, printing was on unless the person said otherwise.
    Someone who already prints keeps printing: their capabilities are written with "print" in them. Nothing else
    changes, and an answer already in studio.toml is never overridden."""
    root = Path(root or cfg["data"]["dir"])
    mark = root / MIGRATION_FILE
    try:
        done = json.loads(mark.read_text(encoding="utf-8")) if mark.exists() else {}
    except (OSError, ValueError):
        done = {}
    if done.get("capabilities"):
        return {"migrated": False, "why": "already done"}
    out = {"migrated": False, "why": "an answer is already in studio.toml"}
    if not decided(cfg):
        why = _print_evidence(cfg, root)
        if why:
            from . import config_edit
            caps = normalise(DEFAULTS + ["print"])
            if _shipped_file(cfg):          # never edit the tracked studio.toml of a source checkout: this run only
                cfg.setdefault("general", {})["capabilities"] = caps
                return {"migrated": True, "why": why, "written": False}
            try:
                config_edit.set_values(cfg, {"general.capabilities": caps})
            except config_edit.ConfigError as e:   # an unwritable file: print for this run, and try again next start
                cfg.setdefault("general", {})["capabilities"] = caps
                return {"migrated": True, "why": why, "written": False, "error": e.message}
            out = {"migrated": True, "why": why}
        else:
            out = {"migrated": False, "why": "nothing printing-related was found"}
    try:
        root.mkdir(parents=True, exist_ok=True)
        done["capabilities"] = {"ts": time.time(), **out}
        mark.write_text(json.dumps(done), encoding="utf-8")
    except OSError:
        pass
    return out


def migrate_safely(cfg: dict) -> dict:
    """migrate() for the app, the bench and the MCP server: a failure never stops them from starting."""
    try:
        return migrate(cfg)
    except Exception as e:
        return {"migrated": False, "why": f"{type(e).__name__}: {e}"}


def install_ids(cfg: dict, rows: list[dict]) -> list[str]:
    """What a setup run installs for the chosen capabilities, in registry order: what Form Studio needs
    (installer.auto_ids, already limited to the chosen capabilities) plus what each chosen capability needs (one slicer
    for printing, Blender for renders, ...). Agents are not in here: the launcher's second step picks them."""
    from . import installer
    want = set(installer.auto_ids(rows, cfg))
    for c in plan(rows, of(cfg))["capabilities"]:
        if c["on"]:
            want.update(c["install"])
    return [r["id"] for r in rows if r["id"] in want]
