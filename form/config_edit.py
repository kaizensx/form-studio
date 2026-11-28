"""Read and change studio.toml safely: `form config get/set`, the Settings sheet, GET/POST /api/config.

A change rewrites only the lines of the keys that changed. Comments, blank lines, key order and every other
key stay exactly as they were. Before the file is replaced a backup copy is saved next to it
(studio.toml.bak-form-<time>), and the new text is parsed and compared with the old one: if anything other than
the requested keys would differ, nothing is written.

    form config get                  every setting FORM knows, its value, and where the file is
    form config get chat.model       one value
    form config set chat.web false   change one value (backup first)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path

from . import config
from . import fsutil

# key → what the Settings sheet and the CLI need to know. type: str | path | bool | float | int | choice | vec3 |
# agent | model | effort (strings the sheet picks from what is installed)
SCHEMA: dict[str, dict] = {
    # tab: general | printer (Printing, shown only to someone who prints) | chat (Agents) | apps | updates | advanced.
    # type "printer" rows are not text: the Settings sheet shows the default printer and opens the printer picker.
    # what Form Studio is set up for (form/capabilities.py): Settings shows it as the "Set up for" cards, not a field
    "general.capabilities": {"type": "capabilities", "tab": "general", "hidden": True, "label": "Set up for",
                             "help": "Ids from form/capabilities.py: core, parts, mesh, render, exchange, print. Turning one "
                                     "off hides it and never uninstalls anything."},
    # the older answer; writing it sets the capability "print" instead (kept so older scripts and CLIs still work)
    "general.printing": {"type": "bool", "tab": "general", "hidden": True, "label": "3D printing",
                         "help": "true turns the 3D printing capability on, false turns it off (general.capabilities)."},
    # CADFit as one more mesh-to-CAD candidate (form/recon/cadfit; CC BY-NC 4.0, included with its author's permission).
    # Settings > Engines & software turns it on when it installs it.
    "recon.cadfit": {"type": "bool", "tab": "software", "hidden": True, "label": "CADFit mesh to CAD search",
                     "help": "true also tries CADFit's IoU search when a mesh is made editable (non-commercial licence)."},
    # "Use in Form Studio" (form/use.py): the switch on each card of Settings › Engines & software. Applied at once.
    "recon.learned": {"type": "bool", "tab": "software", "hidden": True, "label": "Use CAD-Recode",
                      "help": "false: CAD-Recode is never asked, also when it is installed (non-commercial licence)."},
    **{"use." + k: {"type": "bool", "tab": "software", "hidden": True, "label": "Use " + n,
                    "help": "false: " + n + " is never called, also when it is installed."}
       for k, n in (("coacd", "CoACD"), ("corpus", "the CADEvolve corpus"), ("blender", "Blender"), ("freecad", "FreeCAD"),
                    ("openscad", "OpenSCAD"), ("bambu", "Bambu Studio"), ("orca", "OrcaSlicer"), ("prusa", "PrusaSlicer"),
                    ("superslicer", "SuperSlicer"), ("qidi", "QIDISlicer"), ("elegoo", "ElegooSlicer"),
                    ("snapmaker", "Snapmaker Orca"))},
    "refine.enabled": {"type": "bool", "tab": "general", "label": "Refine every design after it builds",
                       "help": "Adds named, reversible refinements (fillet tiers, parting lines, grip zones, materials) "
                               "as one more revision, kept only when the design's checks still pass. Each one can be "
                               "undone in the workspace."},
    "refine.game": {"type": "bool", "tab": "general", "label": "Refine game assets",
                    "help": "Off by default while game assets are in Beta: a game asset is refined only when you ask "
                            "for it (Refine again in the workspace). On: every game asset is refined after it builds, "
                            "like a CAD design."},
    "data.dir": {"type": "path", "tab": "general", "label": "Project folder", "restart": True,
                 "help": "Where designs, their history and releases are kept. Takes effect when Form Studio restarts; "
                         "existing projects are not moved."},
    "parts.catalogue": {"type": "bool", "tab": "general", "label": "Supplier catalogue service (parts list)",
                        "help": "Off by default. On: the parts list can search a supplier catalogue for part numbers; before "
                                "each search it shows what is sent (the designation only) and to whom, and waits for you. "
                                "No provider is configured yet, so nothing is sent; supplier numbers come from you or a "
                                "link you give."},
    "parts.catalogue_provider": {"type": "str", "tab": "general", "hidden": True, "label": "Catalogue provider",
                                 "help": "The provider id (form/bom.py PROVIDERS). Empty: none."},
    "updates.check": {"type": "bool", "tab": "updates", "label": "Check for a newer Form Studio once a day",
                      "help": "Reads public release information from GitHub. Nothing is downloaded or installed."},
    "updates.channel": {"type": "choice", "tab": "updates", "label": "Update channel", "choices": ["stable", "preview"],
                        "help": "Stable: releases only. Preview: also pre-releases from the dev branch, where new features are tested first."},
    "bench.auto_open": {"type": "bool", "tab": "chat", "label": "Open Form Studio's page when an outside agent starts working",
                        "help": "For agents that use Form Studio over MCP from their own window or a terminal."},
    # what a new design is for when nobody says (form/purpose.py default): a 3D model unless this is "print"
    "general.new_designs": {"type": "choice", "tab": "printer", "label": "New designs are made for",
                            "choices": ["model", "print"],
                            "help": "model: a new design is a 3D model unless you or the request say it is for printing. "
                                    "print: every new design is made for your printer. Applies only while 3D printing is on."},
    "slicer.kind": {"type": "choice", "tab": "printer", "label": "Slicer",
                    "choices": ["auto", "bambu", "orca", "prusa", "superslicer", "qidi", "elegoo", "snapmaker"],
                    "help": "Automatic uses the first one installed: Bambu Studio, OrcaSlicer, PrusaSlicer. Slicers found on this computer are marked."},
    "slicer.enabled": {"type": "bool", "tab": "printer", "label": "Slice designs made for printing",
                       "help": "Off: Design only. Designs, checks, exports, renders and releases work without a slicer; "
                               "the release says that it was not sliced."},
    "slicer.machine": {"type": "str", "tab": "advanced", "hidden": True, "label": "Pinned printer preset",
                       "help": "“auto” follows what is selected in the slicer. Choose the printer in Settings › Printing instead."},
    "slicer.process": {"type": "str", "tab": "advanced", "hidden": True, "label": "Pinned process preset", "help": "“auto”, or a preset name."},
    "slicer.filament": {"type": "str", "tab": "advanced", "hidden": True, "label": "Pinned filament preset", "help": "“auto”, or a preset name."},
    "slicer.timeout_s": {"type": "int", "tab": "advanced", "label": "Slice time limit", "unit": "s", "min": 30, "max": 7200,
                         "help": "A slice that takes longer is stopped and reported. Large or detailed parts may need more."},
    "printer.name": {"type": "str", "tab": "advanced", "label": "Printer name when none is chosen",
                     "help": "Named in the checks while no default printer is chosen in Printing. A chosen printer brings its own name and bed."},
    "printer.envelope_mm": {"type": "vec3", "tab": "advanced", "label": "Bed size when no printer is chosen (X, Y, Z)", "unit": "mm", "min": 20, "max": 2000,
                            "help": "The build volume the checks use until a default printer is chosen in Printing."},
    # The default printer (form/printers.py): written by the printer picker and `form printers use --default`.
    # Empty = follow [slicer].kind and the selection in that slicer. Not shown as text fields in Settings.
    "printer.slicer": {"type": "str", "tab": "printer", "hidden": True, "label": "Default printer: slicer",
                       "help": "A slicer kind (bambu, orca, prusa, …), or empty."},
    "printer.machine": {"type": "str", "tab": "printer", "hidden": True, "label": "Default printer: printer preset"},
    "printer.process": {"type": "str", "tab": "printer", "hidden": True, "label": "Default printer: process preset"},
    "printer.filament": {"type": "str", "tab": "printer", "hidden": True, "label": "Default printer: filament preset"},
    "printer.plate_margin_mm": {"type": "float", "tab": "printer", "label": "Keep-out margin at the bed edge", "unit": "mm",
                                "min": 0, "max": 50, "help": "Parts must stay this far from the edge of the bed."},
    "printer.plate_spacing_mm": {"type": "float", "tab": "printer", "label": "Gap between parts on a plate", "unit": "mm",
                                 "min": 0, "max": 50,
                                 "help": "Used when a design's parts are laid out on several plates."},
    "apps.slicer": {"type": "str", "tab": "printer", "label": "“Open in slicer” uses",
                    "help": "An application name (macOS) or a command. Empty: the system default for the file type."},
    "chat.enabled": {"type": "bool", "tab": "chat", "label": "Chat with an agent in Form Studio"},
    "chat.agent": {"type": "agent", "tab": "chat", "label": "Agent for new conversations",
                   "help": "Empty: the first one available. Each conversation can also pick its own."},
    "chat.model": {"type": "model", "tab": "chat", "label": "Model",
                   "help": "“Default” lets the agent choose. You can also pick it per conversation."},
    "chat.effort": {"type": "effort", "tab": "chat", "label": "Effort", "help": "Empty: the agent's default."},
    "chat.auto_effort": {"type": "bool", "tab": "chat", "label": "Raise effort for hard tasks",
                         "help": "A mesh to make editable, a mechanism, gears, a styled form or several parts run at high "
                                 "effort, and the conversation says so. Off: every message runs at the effort you picked."},
    "chat.web": {"type": "bool", "tab": "chat", "label": "Let the agent look things up on the web",
                 "help": "Datasheets and mechanical drawings, for agents that can search the web. Off: the agent works only from what you tell it."},
    "chat.cli": {"type": "path", "tab": "advanced", "label": "Claude Code command",
                 "help": "Only for Claude Code: its command name, or its full path when it is not on the PATH."},
    "chat.ask_timeout_s": {"type": "int", "tab": "advanced", "label": "Wait for your answers", "unit": "s", "min": 30, "max": 7200,
                           "help": "How long the agent waits when it asks you a question in chat before it continues without the answer."},
    "chat.budget_usd_per_message": {"type": "float", "tab": "chat", "label": "Spending cap per message", "unit": "USD",
                                    "min": 0.05, "max": 100,
                                    "help": "A reply stops when it has cost this much, for agents that report cost (Claude "
                                            "Code, OpenRouter). What it saved is kept; send “continue” to carry on. A "
                                            "remodel or a “make it beautiful” loop with photos can cost several dollars."},
    "blender.app": {"type": "path", "tab": "apps", "label": "Blender", "unlocks": "Photo-real renders of a design",
                    "help": "Optional. Empty: found in the usual places."},
    "cad.openscad": {"type": "path", "tab": "apps", "label": "OpenSCAD", "unlocks": "Designs written in OpenSCAD",
                     "help": "Optional. Empty: found in the usual places."},
    "cad.freecad": {"type": "path", "tab": "apps", "label": "FreeCAD (FreeCADCmd)", "unlocks": "“Open in FreeCAD” and a re-import check of each STEP",
                    "help": "Optional. Empty: found in the usual places."},
    "apps.cad": {"type": "str", "tab": "apps", "label": "“Open in CAD” uses", "help": "An application name or a command. Empty: the system default."},
    "apps.viewer": {"type": "str", "tab": "apps", "label": "“Open in viewer” uses", "help": "Empty: the system default."},
}


class ConfigError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message, self.hint = message, hint


def target(cfg: dict) -> Path:
    """The studio.toml FORM reads, or the one it would create."""
    p = Path(str(cfg.get("_path", "")))
    if os.environ.get("FORM_CONFIG"):
        return Path(os.environ["FORM_CONFIG"]).expanduser()
    return p if p.exists() else config.USER_CONFIG


def get(cfg: dict, key: str):
    if key not in SCHEMA:
        raise ConfigError(f"Unknown setting “{key}”.", "Known: " + ", ".join(SCHEMA))
    sec, name = key.split(".", 1)
    return (cfg.get(sec) or {}).get(name, (config.DEFAULTS.get(sec) or {}).get(name))


def file_value(cfg: dict, key: str):
    """The value as written in the file (None when the file does not set it)."""
    p = target(cfg)
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return None
    sec, name = key.split(".", 1)
    return (data.get(sec) or {}).get(name) if isinstance(data.get(sec), dict) else None


def coerce(key: str, value):
    """Validate one value against the schema; accepts the strings a CLI passes."""
    spec = SCHEMA.get(key)
    if spec is None:
        raise ConfigError(f"Unknown setting “{key}”.", "Known: " + ", ".join(SCHEMA))
    t = spec["type"]
    try:
        if t == "bool":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("true", "yes", "on", "1"):
                return True
            if s in ("false", "no", "off", "0"):
                return False
            raise ValueError("expected true or false")
        if t in ("float", "int"):
            if isinstance(value, bool):
                raise ValueError("expected a number")
            v = float(value)
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError("expected a number")
            if "min" in spec and v < spec["min"] or "max" in spec and v > spec["max"]:
                raise ValueError(f"must be between {spec.get('min')} and {spec.get('max')}")
            return int(round(v)) if t == "int" else v
        if t == "vec3":
            if isinstance(value, str):
                value = [x for x in re.split(r"[,\sx×]+", value.strip().strip("[]")) if x]
            v = [float(x) for x in value]
            if len(v) != 3 or any(x != x for x in v):
                raise ValueError("expected three numbers, e.g. 256,256,256")
            if any(x < spec["min"] or x > spec["max"] for x in v):
                raise ValueError(f"each must be between {spec['min']} and {spec['max']}")
            return [int(x) if x == int(x) else x for x in v]
        if t == "capabilities":
            from . import capabilities
            raw = [x for x in re.split(r"[,\s]+", value.strip().strip("[]")) if x] if isinstance(value, str) else value
            if not isinstance(raw, (list, tuple)):
                raise ValueError("expected a list of capability ids")
            raw = [str(x).strip().strip("\"'").lower() for x in raw]
            bad = [x for x in raw if x not in capabilities.IDS]
            if bad:
                raise ValueError(f"unknown capability {bad[0]}; known: " + ", ".join(capabilities.IDS))
            return capabilities.normalise(raw)
        if t in ("agent", "model", "effort"):
            t = "str"
        if t == "choice":
            s = str(value).strip()
            if s not in spec["choices"]:
                raise ValueError("expected one of " + ", ".join(spec["choices"]))
            return s
        s = str(value).strip() if value is not None else ""
        if "\n" in s or "\r" in s or len(s) > 1000:
            raise ValueError("expected one line of text")
        if key in ("data.dir", "chat.cli", "printer.name") and not s:
            raise ValueError("cannot be empty")
        if key == "chat.model" and not s:
            s = "default"
        return s
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{key}: {e}.", spec.get("help", ""))


def _toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:g}" if isinstance(v, float) else str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)          # a TOML basic string has JSON's escapes


_VALUE = r"(\"\"\".*?\"\"\"|'''.*?'''|\"(?:[^\"\\]|\\.)*\"|'[^']*'|\[[^\]]*\]|[^#\r\n]*?)"


def set_text(text: str, section: str, name: str, value) -> str:
    """Set [section].name in TOML text. Only that key's line changes (or one line is added)."""
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"
    head = re.compile(r"^\s*\[\s*" + re.escape(section) + r"\s*\]\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if head.match(ln.rstrip("\r\n"))), None)
    new = f"{name} = {_toml(value)}"
    if start is None:
        body = text if not text or text.endswith(("\n", "\r\n")) else text + nl
        return body + (nl if body.strip() else "") + f"[{section}]{nl}{new}{nl}"
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    key = re.compile(r"^(\s*)" + re.escape(name) + r"(\s*=\s*)" + _VALUE + r"(\s*(?:#.*)?)$")
    for i in range(start + 1, end):
        raw = lines[i].rstrip("\r\n")
        m = key.match(raw)
        if not m:
            if re.match(r"^\s*" + re.escape(name) + r"\s*=", raw):      # a value that spans lines: leave it alone
                raise ConfigError(f"[{section}].{name} spans several lines in the file.", "Edit that value by hand.")
            continue
        val = m.group(3).strip()
        if val.count("[") != val.count("]") or (val[:3] in ('"""', "'''") and (len(val) < 6 or val[-3:] != val[:3])):
            raise ConfigError(f"[{section}].{name} spans several lines in the file.", "Edit that value by hand.")
        eol = lines[i][len(raw):]
        lines[i] = f"{m.group(1)}{name}{m.group(2)}{_toml(value)}{m.group(4)}{eol}"
        return "".join(lines)
    if not lines[start].endswith(("\n", "\r\n")):
        lines[start] += nl
    last = start                                            # after the last key line of the section, before trailing blanks
    for i in range(start + 1, end):
        if lines[i].strip():
            last = i
    if not lines[last].endswith(("\n", "\r\n")):
        lines[last] += nl
    lines.insert(last + 1, new + nl)
    return "".join(lines)


def _drop(d: dict, keys: list[str]) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in d.items()}
    for key in keys:
        sec, name = key.split(".", 1)
        if isinstance(out.get(sec), dict):
            out[sec].pop(name, None)
            if not out[sec]:
                out.pop(sec)
    return out


def set_values(cfg: dict, values: dict, path: Path | None = None) -> dict:
    """Write these settings to studio.toml and apply them to the running `cfg`.
    Returns {"path", "backup", "changed": {key: value}, "restart": bool}."""
    if not isinstance(values, dict) or not values:
        raise ConfigError("Nothing to change.")
    if "general.printing" in values:                # the older yes/no: it turns the capability "print" on or off
        from . import capabilities
        values = dict(values)
        on = coerce("general.printing", values.pop("general.printing"))
        values.setdefault("general.capabilities", capabilities.with_cap(cfg, "print", on))
    clean = {k: coerce(k, v) for k, v in values.items()}
    path = Path(path) if path else target(cfg)
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        before = tomllib.loads(old) if old else {}
    except ValueError as e:
        raise ConfigError(f"{path} is not valid TOML, so Form Studio will not edit it: {e}", "Fix or remove the file, then try again.")
    except OSError as e:
        raise ConfigError(f"Could not read {path}: {e}")
    changed = {k: v for k, v in clean.items()
               if not (isinstance(before.get(k.split(".", 1)[0]), dict) and k.split(".", 1)[1] in before[k.split(".", 1)[0]]
                       and before[k.split(".", 1)[0]][k.split(".", 1)[1]] == v and type(before[k.split(".", 1)[0]][k.split(".", 1)[1]]) is type(v))}
    if not changed:
        _apply(cfg, clean)
        return {"path": str(path), "backup": None, "changed": {}, "restart": False}
    text = old or "# Form Studio configuration (written by Form Studio; every value is optional)\n"
    for k, v in changed.items():
        sec, name = k.split(".", 1)
        text = set_text(text, sec, name, v)
    try:
        after = tomllib.loads(text)
    except ValueError as e:
        raise ConfigError(f"The edit would break {path.name}; it was left as it was. ({e})")
    ok = _drop(after, list(changed)) == _drop(before, list(changed)) and all(
        after.get(k.split(".", 1)[0], {}).get(k.split(".", 1)[1]) == v for k, v in changed.items())
    if not ok:
        raise ConfigError(f"Could not change only {', '.join(changed)} in {path}; it was left as it was.",
                          "Edit the file by hand.")
    backup = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(path.name + f".bak-form-{int(time.time())}")
            n = 1
            while backup.exists():                         # two saves in one second keep both backups
                backup = path.with_name(path.name + f".bak-form-{int(time.time())}-{n}")
                n += 1
            backup.write_bytes(path.read_bytes())
        tmp = path.with_name(path.name + ".tmp-form")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        fsutil.replace(tmp, path)
    except OSError as e:
        raise ConfigError(f"Could not write {path}: {e}", "Check that the file and its folder are writable.")
    _apply(cfg, clean)
    cfg["_path"] = str(path)
    return {"path": str(path), "backup": str(backup) if backup else None, "changed": changed,
            "restart": any(SCHEMA[k].get("restart") for k in changed)}


def _apply(cfg: dict, clean: dict) -> None:
    for k, v in clean.items():
        if SCHEMA[k].get("restart"):
            continue                                        # e.g. the project folder: the running engine keeps its own
        sec, name = k.split(".", 1)
        cfg.setdefault(sec, {})[name] = v


def describe(cfg: dict) -> dict:
    """Everything the Settings sheet shows."""
    home = str(Path.home())
    p = target(cfg)
    rows = []
    for key, spec in SCHEMA.items():
        sec, name = key.split(".", 1)
        fv = file_value(cfg, key)
        rows.append({"key": key, **{k: v for k, v in spec.items()}, "value": fv if (spec.get("restart") and fv is not None) else get(cfg, key),
                     "default": (config.DEFAULTS.get(sec) or {}).get(name), "in_file": fv is not None})
    det = detected(cfg)
    for r in rows:
        if r["key"] in det:
            r["detected"] = det[r["key"]]
    return {"path": str(p), "path_short": str(p).replace(home, "~") if len(home) > 1 else str(p), "exists": p.exists(),
            "settings": rows, "data_dir": cfg["data"]["dir"],
            "env_overrides": [n for n in ("FORM_DATA", "FORM_CONFIG") if os.environ.get(n)]}


_DETECTED: dict = {}


def detected(cfg: dict) -> dict:
    """Cached for 30 s per configuration: the Settings sheet asks on every open and save."""
    k = json.dumps({s: cfg.get(s) for s in ("cad", "blender", "chat", "slicer")}, sort_keys=True, default=str)
    hit = _DETECTED.get(k)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    out = _detect(cfg)
    _DETECTED.clear()
    _DETECTED[k] = (time.time(), out)
    return out


def _detect(cfg: dict) -> dict:
    """What Form Studio found on this computer for the settings that name a program: {key: found}. For a program a
    path ("" = not found); for the slicer, the kinds that are installed. Never raises: a check that fails says nothing."""
    out: dict = {}
    home = str(Path.home())
    short = lambda x: (str(x).replace(home, "~") if x and len(home) > 1 else str(x or ""))
    try:
        from . import cad_bridges
        out["cad.openscad"] = short(cad_bridges.find_openscad(cfg) or "")
        out["cad.freecad"] = short(cad_bridges.find_freecad(cfg) or "")
    except Exception:
        pass
    try:
        from .adapters import blender
        b = blender.probe(cfg)
        out["blender.app"] = short(b.get("app") or "") if b.get("available") else ""
    except Exception:
        pass
    try:
        import shutil
        out["chat.cli"] = short(shutil.which(str(cfg.get("chat", {}).get("cli") or "claude")) or "")
    except Exception:
        pass
    try:
        from . import slicer
        kinds = []
        for kind in slicer.AUTO_ORDER:
            try:
                if slicer.adapter(kind).find_app(cfg):
                    kinds.append(kind)
            except Exception:
                continue
        out["slicer.kind"] = kinds
    except Exception:
        pass
    return out


def main(argv=None) -> int:
    """`form config get [key]` / `form config set key value`"""
    argv = list(argv or [])
    cfg = config.load()

    def out(o):
        print(json.dumps(o, indent=1, ensure_ascii=False, default=str))
    try:
        if argv[:1] == ["get"] and len(argv) <= 2:
            if len(argv) == 2:
                out({"key": argv[1], "value": get(cfg, argv[1]), "file": str(target(cfg))})
            else:
                out({"file": str(target(cfg)), "values": {k: get(cfg, k) for k in SCHEMA}})
            return 0
        if argv[:1] == ["set"] and len(argv) >= 3:
            out(set_values(cfg, {argv[1]: " ".join(argv[2:])}))
            return 0
    except ConfigError as e:
        out({"error": {"message": e.message, **({"hint": e.hint} if e.hint else {})}})
        return 2
    print("usage: form config get [key]\n       form config set <key> <value>\n\nkeys: " + ", ".join(SCHEMA), file=sys.stderr)
    return 2
