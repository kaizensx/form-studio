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

# key → what the Settings sheet and the CLI need to know. type: str | path | bool | float | int | choice | vec3
SCHEMA: dict[str, dict] = {
    "data.dir": {"type": "path", "tab": "general", "label": "Project folder", "restart": True,
                 "help": "Where designs, their history and releases are kept. Takes effect when FORM restarts; "
                         "existing projects are not moved."},
    "updates.check": {"type": "bool", "tab": "general", "label": "Check for a newer FORM once a day",
                      "help": "Reads public release information from GitHub. Nothing is downloaded or installed."},
    "bench.auto_open": {"type": "bool", "tab": "general", "label": "Open FORM's page when an agent starts working",
                        "help": "Applies to agents that use FORM over MCP outside this app."},
    "slicer.kind": {"type": "choice", "tab": "printer", "label": "Slicer",
                    "choices": ["auto", "bambu", "orca", "prusa", "superslicer", "qidi"],
                    "help": "“auto” uses the first one installed: Bambu Studio, OrcaSlicer, PrusaSlicer."},
    "slicer.machine": {"type": "str", "tab": "printer", "label": "Printer preset",
                       "help": "“auto” follows what is selected in the slicer. A preset name pins it."},
    "slicer.process": {"type": "str", "tab": "printer", "label": "Process preset", "help": "“auto”, or a preset name."},
    "slicer.filament": {"type": "str", "tab": "printer", "label": "Filament preset", "help": "“auto”, or a preset name."},
    "slicer.timeout_s": {"type": "int", "tab": "printer", "label": "Slice time limit", "unit": "s", "min": 30, "max": 7200},
    "printer.name": {"type": "str", "tab": "printer", "label": "Printer name",
                     "help": "Used when no slicer is available. With a slicer, its selected printer wins."},
    "printer.envelope_mm": {"type": "vec3", "tab": "printer", "label": "Bed size (X, Y, Z)", "unit": "mm", "min": 20, "max": 2000},
    "printer.plate_margin_mm": {"type": "float", "tab": "printer", "label": "Keep-out margin at the bed edge", "unit": "mm",
                                "min": 0, "max": 50},
    "chat.enabled": {"type": "bool", "tab": "chat", "label": "Chat with Claude in FORM"},
    "chat.cli": {"type": "str", "tab": "chat", "label": "Agent program", "help": "The Claude Code command, or its full path."},
    "chat.model": {"type": "str", "tab": "chat", "label": "Model", "help": "A Claude Code model name: opus, sonnet, haiku, or a full id."},
    "chat.web": {"type": "bool", "tab": "chat", "label": "Let Claude look things up on the web",
                 "help": "Datasheets and mechanical drawings. Off: Claude works only from what you tell it."},
    "chat.budget_usd_per_message": {"type": "float", "tab": "chat", "label": "Spending limit per message", "unit": "USD",
                                    "min": 0.05, "max": 100,
                                    "help": "Claude Code stops a reply when it has cost this much on your account."},
    "blender.app": {"type": "path", "tab": "apps", "label": "Blender", "help": "Empty: look in the usual places."},
    "cad.openscad": {"type": "path", "tab": "apps", "label": "OpenSCAD", "help": "Empty: look in the usual places."},
    "cad.freecad": {"type": "path", "tab": "apps", "label": "FreeCAD (FreeCADCmd)", "help": "Empty: look in the usual places."},
    "apps.slicer": {"type": "str", "tab": "apps", "label": "“Open in slicer” uses",
                    "help": "An application name (macOS) or a command. Empty: the system default for the file type."},
    "apps.cad": {"type": "str", "tab": "apps", "label": "“Open in CAD” uses", "help": "Empty: the system default."},
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
        if t == "choice":
            s = str(value).strip()
            if s not in spec["choices"]:
                raise ValueError("expected one of " + ", ".join(spec["choices"]))
            return s
        s = str(value).strip() if value is not None else ""
        if "\n" in s or "\r" in s or len(s) > 1000:
            raise ValueError("expected one line of text")
        if key in ("data.dir", "chat.cli", "chat.model", "printer.name") and not s:
            raise ValueError("cannot be empty")
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
    clean = {k: coerce(k, v) for k, v in values.items()}
    path = Path(path) if path else target(cfg)
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        before = tomllib.loads(old) if old else {}
    except ValueError as e:
        raise ConfigError(f"{path} is not valid TOML, so FORM will not edit it: {e}", "Fix or remove the file, then try again.")
    except OSError as e:
        raise ConfigError(f"Could not read {path}: {e}")
    changed = {k: v for k, v in clean.items()
               if not (isinstance(before.get(k.split(".", 1)[0]), dict) and k.split(".", 1)[1] in before[k.split(".", 1)[0]]
                       and before[k.split(".", 1)[0]][k.split(".", 1)[1]] == v and type(before[k.split(".", 1)[0]][k.split(".", 1)[1]]) is type(v))}
    if not changed:
        _apply(cfg, clean)
        return {"path": str(path), "backup": None, "changed": {}, "restart": False}
    text = old or "# FORM configuration (written by FORM; every value is optional)\n"
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
        os.replace(tmp, path)
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
    return {"path": str(p), "path_short": str(p).replace(home, "~") if len(home) > 1 else str(p), "exists": p.exists(),
            "settings": rows, "data_dir": cfg["data"]["dir"],
            "env_overrides": [n for n in ("FORM_DATA", "FORM_CONFIG") if os.environ.get(n)]}


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
