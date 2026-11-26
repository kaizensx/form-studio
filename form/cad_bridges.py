"""Bridges to other CAD tools: OpenSCAD (a design language), FreeCAD (inspection and an integration re-check).

Nothing here imports OCCT. The OpenSCAD runner is used by the kernel worker (form/recipes/scad.py); the FreeCAD
helpers are used by the studio after export. Every external program is optional: when it is missing, the feature
says so and FORM carries on without it.

FreeCAD was written against its documented command-line and Python API (FreeCADCmd runs a .py file it is given;
Part.Shape.read / isValid / Volume / BoundBox). It was first written against the documented API; since FORM 11 it is also run against FreeCAD 1.1.4. The script
it generates and the output parser are tested with fixtures.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---- finding the programs ------------------------------------------------------------------------------------------

def _candidates_openscad() -> list[str]:
    if sys.platform == "darwin":
        return ["/opt/homebrew/bin/openscad", "/usr/local/bin/openscad",
                "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"]
    if sys.platform.startswith("win"):
        pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        return [str(Path(d) / "OpenSCAD" / n) for d in pf for n in ("openscad.com", "openscad.exe")]
    return ["/usr/bin/openscad", "/usr/local/bin/openscad", "/snap/bin/openscad"]


def _candidates_freecad() -> list[str]:
    if sys.platform == "darwin":
        out = []
        for app in ["/Applications/FreeCAD.app"] + sorted(glob.glob("/Applications/FreeCAD*.app")):
            for sub in ("Contents/Resources/bin/freecadcmd", "Contents/Resources/bin/FreeCADCmd", "Contents/MacOS/FreeCADCmd"):
                out.append(str(Path(app) / sub))
        return out
    if sys.platform.startswith("win"):
        pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")]
        out = []
        for d in pf:
            if d:
                for root in sorted(glob.glob(str(Path(d) / "FreeCAD*")), reverse=True):
                    out += [str(Path(root) / "bin" / "freecadcmd.exe"), str(Path(root) / "bin" / "FreeCADCmd.exe")]
        return out
    return ["/usr/bin/freecadcmd", "/usr/bin/FreeCADCmd", "/usr/local/bin/freecadcmd", "/snap/bin/freecad.cmd"]


def _find(configured: str, names: tuple, candidates: list[str]) -> str | None:
    if configured:
        p = shutil.which(configured) or (configured if Path(configured).exists() else None)
        return p
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return next((c for c in candidates if Path(c).is_file()), None)


def openscad(cfg: dict | None = None) -> str | None:
    """OpenSCAD to build with: None when it is not installed or its "Use in Form Studio" switch is off (form/use.py)."""
    from . import use
    return find_openscad(cfg) if use.on("openscad", cfg) else None


def freecad(cfg: dict | None = None) -> str | None:
    """FreeCADCmd to run: None when it is not installed or its "Use in Form Studio" switch is off."""
    from . import use
    return find_freecad(cfg) if use.on("freecad", cfg) else None


def find_openscad(cfg: dict | None = None) -> str | None:
    conf = ((cfg or {}).get("cad") or {}).get("openscad", "") or os.environ.get("FORM_OPENSCAD", "")
    return _find(conf, ("openscad",), _candidates_openscad())


def find_freecad(cfg: dict | None = None) -> str | None:
    conf = ((cfg or {}).get("cad") or {}).get("freecad", "") or os.environ.get("FORM_FREECADCMD", "")
    return _find(conf, ("freecadcmd", "FreeCADCmd"), _candidates_freecad())


def freecad_gui_app(cfg: dict | None = None) -> str | None:
    """What `open` should hand a STEP to for "Open in FreeCAD": an app name on macOS, an executable elsewhere."""
    if sys.platform == "darwin":
        apps = ["/Applications/FreeCAD.app"] + sorted(glob.glob("/Applications/FreeCAD*.app"))
        return next((a for a in apps if Path(a).exists()), None)
    for n in ("freecad", "FreeCAD"):
        if shutil.which(n):
            return shutil.which(n)
    cmd = find_freecad(cfg)
    if cmd:
        gui = Path(cmd).with_name("freecad.exe" if sys.platform.startswith("win") else "freecad")
        for g in (gui, gui.with_name(gui.name.replace("freecad", "FreeCAD"))):
            if g.exists():
                return str(g)
    return None


def version(exe: str, timeout=15) -> str:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        line = (r.stdout + r.stderr).strip().splitlines()
        return line[0].strip() if line else "unknown version"
    except (OSError, subprocess.SubprocessError):
        return "unknown version"


def status(cfg: dict | None = None) -> dict:
    """What the app shows: which bridges exist on this machine."""
    from . import use
    o, f = openscad(cfg), freecad(cfg)
    o_on, f_on = use.on("openscad", cfg), use.on("freecad", cfg)
    return {"openscad": {"available": bool(o), "path": o, "use": o_on,
                         "reason": "" if o else use.off_reason("openscad") if not o_on
                         else "OpenSCAD not found. Install it from https://openscad.org/downloads.html."},
            "freecad": {"available": bool(f), "path": f, "gui": freecad_gui_app(cfg) if f_on else None, "use": f_on,
                        "reason": "" if f else use.off_reason("freecad") if not f_on
                        else "FreeCAD not found. Install it from https://www.freecad.org/downloads.php."}}


# ---- OpenSCAD: Customizer parameters --------------------------------------------------------------------------------

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_ASSIGN = re.compile(rf"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*({_NUM})\s*;\s*(?://\s*(.*))?$")
_RANGE = re.compile(rf"^\[\s*({_NUM})\s*:\s*({_NUM})\s*(?::\s*({_NUM})\s*)?\]")
_LIST = re.compile(r"^\[\s*([^\]]+)\]")
_GROUP = re.compile(r"^\s*/\*\s*\[\s*([^\]]+?)\s*\]\s*\*/\s*$")
_UNIT = re.compile(r"\((mm|deg|°|degrees|%)\)\s*$", re.I)


def parse_scad_params(source: str) -> dict:
    """Customizer-style parameters from OpenSCAD source.

    `name = 12; // [5:0.5:40]` (min:step:max) or `[5:40]` (min:max) becomes a FORM parameter; the comment line
    directly above is its label. `/* [Hidden] */` ends the parameters, as in OpenSCAD's Customizer. Numeric
    assignments without a range, strings, booleans and lists stay fixed in the source and are reported in `fixed`.
    Only assignments before the first module/function/geometry statement count, as in the Customizer.
    """
    params, fixed, group, hidden, last_comment = [], [], "", False, ""
    for raw in source.splitlines():
        line = raw.rstrip()
        g = _GROUP.match(line)
        if g:
            group = g.group(1)
            hidden = group.lower() == "hidden"
            last_comment = ""
            continue
        s = line.strip()
        if not s:
            last_comment = ""
            continue
        if s.startswith("//"):
            last_comment = s[2:].strip()
            continue
        if re.match(r"^(module|function)\b", s) or (not _ASSIGN.match(line) and not re.match(r"^[A-Za-z_$][\w$]*\s*=", s)
                                                    and not s.startswith(("/*", "*", "include", "use"))):
            break                                    # first geometry/module: the Customizer stops here too
        m = _ASSIGN.match(line)
        if not m:
            nm = re.match(r"^([A-Za-z_$][\w$]*)\s*=", s)
            if nm and not nm.group(1).startswith("$"):
                fixed.append({"key": nm.group(1), "why": "not a plain number"})
            last_comment = ""
            continue
        key, val, comment = m.group(1), float(m.group(2)), (m.group(3) or "").strip()
        if hidden:
            last_comment = ""
            continue
        rng = _RANGE.match(comment)
        lst = None if rng else _LIST.match(comment)
        lo = hi = step = None
        if rng:
            a, b, c = rng.groups()
            if c is None:
                lo, hi, step = float(a), float(b), 1.0 if float(a).is_integer() and float(b).is_integer() and val.is_integer() else 0.1
            else:
                lo, step, hi = float(a), float(b), float(c)
        elif lst:
            try:
                opts = [float(x.split(":")[0]) for x in lst.group(1).split(",")]
                lo, hi = min(opts), max(opts)
                diffs = sorted({round(abs(b - a), 9) for a, b in zip(sorted(opts), sorted(opts)[1:]) if b != a})
                step = diffs[0] if diffs else 1.0
            except ValueError:
                lo = None
        if lo is None or hi is None or hi <= lo or not (lo - 1e-9 <= val <= hi + 1e-9):
            fixed.append({"key": key, "why": "no [min:step:max] range comment" if lo is None else "range does not contain the default"})
            last_comment = ""
            continue
        label = last_comment or key.replace("_", " ").capitalize()
        unit = "mm"
        um = _UNIT.search(label)
        if um:
            unit = {"deg": "°", "degrees": "°"}.get(um.group(1).lower(), um.group(1))
            label = label[:um.start()].strip()
        elif re.search(r"angle|deg", key, re.I):
            unit = "°"
        elif re.search(r"count|number|num_|_n$|^n_", key, re.I) and step >= 1:
            unit = ""
        params.append({"key": key, "label": label[:60], "default": val, "min": lo, "max": hi, "step": step or 0.1,
                       "unit": unit, "group_name": group})
        last_comment = ""
    return {"params": params, "fixed": fixed}


def scad_title(source: str) -> tuple[str, str]:
    """First comment line is the title; the rest of a leading comment block is the summary."""
    lines = []
    for raw in source.splitlines():
        s = raw.strip()
        if s.startswith("//"):
            lines.append(s[2:].strip())
        elif s.startswith("/*") and not _GROUP.match(raw):
            lines.append(s.strip("/* "))
        elif s:
            break
    if not lines:
        return "OpenSCAD design", ""
    first, _, rest = lines[0].partition(". ")          # "Cable box. Notes..." -> title "Cable box"
    title = first.rstrip(".")[:40]
    return title, " ".join(([rest] if rest else []) + lines[1:]).strip()[:300]


def _scad_value(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def run_openscad(exe: str, scad: Path, values: dict, out_stl: Path, timeout: float = 120) -> dict:
    """Render a .scad file to a binary STL with -D overrides. Raises RuntimeError with OpenSCAD's own message."""
    cmd = [exe, "-o", str(out_stl), "--export-format", "binstl"]
    for k, v in sorted(values.items()):
        cmd += ["-D", f"{k}={_scad_value(v)}"]
    cmd.append(str(scad))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           cwd=str(scad.parent))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"OpenSCAD did not finish within {timeout:g} s.")
    log = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0 or not out_stl.exists() or out_stl.stat().st_size < 84:
        err = [ln for ln in log.splitlines() if re.search(r"ERROR|WARNING|error", ln)] or log.strip().splitlines()[-3:]
        from . import compat                        # an OpenSCAD outside the supported range that dropped an option
        why = compat.wrap_message("openscad", version(exe), "OpenSCAD failed: " + " ".join(err)[:600], log)
        raise RuntimeError(f"{why[0]} {why[1]}" if why else "OpenSCAD failed: " + " ".join(err)[:600])
    if "Current top level object is empty" in log or "top level object is not a 3D object" in log.lower():
        raise RuntimeError("OpenSCAD produced no 3D object.")
    return {"command": cmd, "log": log[-2000:]}


# ---- FreeCAD: independent re-import ---------------------------------------------------------------------------------

RESULT_TAG = "FORM_FREECAD_RESULT "


def freecad_check_script(step_path: str) -> str:
    """Python for FreeCADCmd: import the STEP, report validity, volume and bounding box on one tagged line."""
    return f'''# Written by Form Studio. Runs headless in FreeCADCmd; reads one STEP file and prints one line.
import json, sys
try:
    import FreeCAD, Part
    s = Part.Shape()
    s.read({str(step_path)!r})
    # The exact box: the default BoundBox is padded on curved faces (0.5 mm on a filleted part with FreeCAD 1.1).
    try:
        bb = s.optimalBoundingBox(False, False)
    except Exception:
        bb = s.BoundBox
    out = {{"ok": True, "valid": bool(s.isValid()), "volume_mm3": float(s.Volume), "solids": len(s.Solids),
           "bbox": [[bb.XMin, bb.YMin, bb.ZMin], [bb.XMax, bb.YMax, bb.ZMax]],
           "version": ".".join(str(x) for x in FreeCAD.Version()[:3])}}
except Exception as e:
    out = {{"ok": False, "error": type(e).__name__ + ": " + str(e)}}
sys.stdout.write({RESULT_TAG!r} + json.dumps(out) + "\\n")
sys.stdout.flush()
'''


def parse_freecad_output(text: str) -> dict:
    """The tagged result line from FreeCADCmd's output (which also carries banners and log lines)."""
    for line in reversed((text or "").splitlines()):
        i = line.find(RESULT_TAG)
        if i >= 0:
            try:
                return json.loads(line[i + len(RESULT_TAG):])
            except ValueError:
                break
    return {"ok": False, "error": "FreeCAD did not report a result. Last output: " + " ".join((text or "").strip().splitlines()[-3:])[:300]}


def freecad_recheck(exe: str, step_path: Path, timeout: float = 120) -> dict:
    with tempfile.TemporaryDirectory(prefix="form-fc-") as d:
        script = Path(d) / "form_recheck.py"
        script.write_text(freecad_check_script(str(step_path)), encoding="utf-8")
        try:
            r = subprocess.run([exe, str(script)], capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL, cwd=d)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"FreeCAD did not finish within {timeout:g} s."}
        except OSError as e:
            return {"ok": False, "error": f"FreeCAD could not start: {e}"}
        out = parse_freecad_output((r.stdout or "") + "\n" + (r.stderr or ""))
    if not out.get("ok"):                           # a FreeCAD outside the supported range whose Python API changed
        from . import compat
        why = compat.wrap_message("freecad", version(exe), out.get("error", ""), (r.stdout or "") + (r.stderr or ""))
        if why:
            out["error"] = f"{why[0]} {why[1]}"
    return out


def recheck_item(result: dict, brep_volume: float, brep_bbox: list) -> dict:
    """The extra check row. Volume within 0.1 % and bbox within 0.01 mm of FORM's own kernel."""
    base = "Integration validation: FreeCAD and build123d both use the OpenCascade kernel family, so this " \
           "confirms the STEP file reads back the same in another program; it is not an independent proof of the geometry."
    if not result.get("ok"):
        return {"id": "freecad", "label": "Re-imported in FreeCAD", "status": "WARN", "value": "could not re-import",
                "detail": f"{result.get('error', 'unknown error')}. {base}", "evidence": "computed"}
    dv = abs(result["volume_mm3"] - brep_volume) / max(brep_volume, 1e-9)
    db = max(abs(a - b) for lo_hi in zip(result["bbox"], brep_bbox) for a, b in zip(*lo_hi))
    ok = result["valid"] and dv <= 0.001 and db <= 0.01
    return {"id": "freecad", "label": "Re-imported in FreeCAD", "status": "PASS" if ok else "WARN",
            "value": ("valid" if result["valid"] else "not valid") + f" · Δ {dv*100:.3f}% volume",
            "detail": f"FreeCAD {result.get('version', '?')}: isValid() = {result['valid']}, {result.get('solids', '?')} solid(s), "
                      f"volume {result['volume_mm3']/1000:.3f} cm³ (Form Studio {brep_volume/1000:.3f} cm³), bounding box within "
                      f"{db:.4f} mm. {base}", "evidence": "computed"}


# ---- FreeCAD: a macro that rebuilds the part ------------------------------------------------------------------------

def freecad_macro(name: str, rev: int, step_name: str, step_sha256: str, params: list[dict]) -> str:
    """A .FCMacro: opens the STEP that sits next to it (checking its hash), and adds a spreadsheet of FORM's parameters.

    params: [{key, label, value, unit, source}]. The STEP is a frozen solid; the spreadsheet records the values it
    was built from. Changing a cell does not change the solid: edit the design in FORM, export again.
    """
    rows = json.dumps([{k: p[k] for k in ("key", "label", "value", "unit", "source")} for p in params], indent=1)
    return f'''# -*- coding: utf-8 -*-
# FreeCAD macro written by Form Studio for {name} r{rev:02d}.
# Rebuilds the part from {step_name} (put it in the same folder as this macro) and adds a
# spreadsheet "FORM_parameters" with the values it was made from and how each one is known.
# The STEP is a frozen solid: editing a cell does not change it. Change the design in Form Studio and export again.
import hashlib
import os

import FreeCAD as App
import Part

STEP_NAME = {step_name!r}
STEP_SHA256 = {step_sha256!r}
PARAMS = {rows}


def _find_step():
    here = os.path.dirname(os.path.abspath(globals().get("__file__", "") or "."))
    cand = os.path.join(here, STEP_NAME)
    if os.path.exists(cand):
        return cand
    try:
        from PySide import QtGui
        path, _ = QtGui.QFileDialog.getOpenFileName(None, "Choose " + STEP_NAME, here, "STEP (*.step *.stp)")
        return path or None
    except Exception:
        return None


step = _find_step()
if not step:
    raise RuntimeError("Put " + STEP_NAME + " next to this macro and run it again.")
with open(step, "rb") as fh:
    digest = hashlib.sha256(fh.read()).hexdigest()
doc = App.newDocument({re.sub(r"[^A-Za-z0-9_]", "_", name)[:40] or "FORM"!r})
sheet = doc.addObject("Spreadsheet::Sheet", "FORM_parameters")
for col, head in zip("ABCDE", ("Parameter", "Key", "Value", "Unit", "Source")):
    sheet.set(col + "1", head)
for i, p in enumerate(PARAMS, start=2):
    sheet.set("A%d" % i, p["label"])
    sheet.set("B%d" % i, p["key"])
    sheet.set("C%d" % i, repr(p["value"]))
    sheet.set("D%d" % i, p["unit"])
    sheet.set("E%d" % i, p["source"])
    try:
        sheet.setAlias("C%d" % i, p["key"])
    except Exception:
        pass
shape = Part.Shape()
shape.read(step)
part = doc.addObject("Part::Feature", "FORM_part")
part.Shape = shape
part.Label = {f"{name} r{rev:02d}"!r}
note = "STEP hash matches the Form Studio export." if digest == STEP_SHA256 else "WARNING: this STEP is not the file Form Studio exported for this revision."
sheet.set("A%d" % (len(PARAMS) + 3), note)
doc.recompute()
App.Console.PrintMessage("Form Studio: " + note + "\\n")
try:
    import FreeCADGui as Gui
    Gui.SendMsgToActiveView("ViewFit")
except Exception:
    pass
'''


# ---- opening a file in the user's own program -----------------------------------------------------------------------

def open_file(target: str, app: str = "") -> dict:
    """Hand a file to another program with the system's open command. Raises RuntimeError on failure.

    FORM_FAKE_LAUNCH=<file> (tests): append {"opened", "with"} to that file as one JSON line instead of opening."""
    fake = os.environ.get("FORM_FAKE_LAUNCH")
    if fake:
        import json
        with open(fake, "a", encoding="utf-8") as f:
            f.write(json.dumps({"opened": target, "with": app}) + "\n")
        return {"opened": target, "with": app or "system default", "fake": True}
    if sys.platform == "darwin":
        cmd = ["open"] + (["-a", app] if app else []) + [target]
    elif sys.platform.startswith("win") and not app:
        os.startfile(target)                      # type: ignore[attr-defined]
        return {"opened": target, "with": "system default"}
    elif app:
        cmd = [app, target]
    elif shutil.which("xdg-open"):
        cmd = ["xdg-open", target]
    else:
        raise RuntimeError("No way to open files on this system. Set [apps] in studio.toml.")
    if sys.platform == "darwin" or not app:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise RuntimeError(f"Could not open {Path(target).name}: {(r.stderr or r.stdout).strip()[:300]}")
    else:                                         # a GUI program: start it, do not wait for it to quit
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"opened": target, "with": app or "system default"}


def open_output(st, pid: str, what: str = "3mf", app: str = "") -> dict:
    """Open a current output of a project in the user's own program (MCP open_in and the app's buttons).

    what: step | stl | 3mf | gcode | folder. app: a program name or path; "freecad" finds FreeCAD itself.
    """
    from .digest import digest
    from .studio import StudioError
    d = digest(st, pid)
    files = d.get("files", {})
    if what == "folder":
        target = str(st.dir(pid))
    elif what in files:
        target = files[what]
    else:
        why = " This is a mesh design (OpenSCAD): it has an STL but no STEP." if what == "step" and d.get("mesh_design") else ""
        raise StudioError(f"No current {what} file.{why}", "Run the pipeline first; available now: " + (", ".join(files) or "none"))
    apps = st.cfg.get("apps", {})
    chosen = app or {"3mf": apps.get("slicer"), "gcode": apps.get("slicer"), "step": apps.get("cad"),
                     "stl": apps.get("viewer")}.get(what, "") or ""
    if chosen.lower() == "freecad":
        from . import use
        if not use.on("freecad", st.cfg):
            raise StudioError(use.off_reason("freecad"), "Turn it on there, or open the file in another app.", status=409)
        found = freecad_gui_app(st.cfg)
        if not found:
            raise StudioError("FreeCAD was not found on this computer.",
                              "Install FreeCAD from https://www.freecad.org/downloads.php, or set [apps].cad in studio.toml.",
                              status=409)
        chosen = Path(found).stem if sys.platform == "darwin" else found
    try:
        return open_file(target, chosen)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        raise StudioError(str(e), "Check the app name in studio.toml [apps].")
