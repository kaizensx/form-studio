"""Slicer adapter for PrusaSlicer (prusa3d/PrusaSlicer), and the forks that kept its formats.

Presets are INI. The selection lives in <config_dir>/PrusaSlicer.ini, section [presets]
(keys printer, print, filament; src/libslic3r/AppConfig.cpp). System presets come from vendor
bundles <config_dir>/vendor/<Vendor>.ini, sections [printer:Name], [print:Name], [filament:Name];
"inherits" lists parents separated by ";" and later parents win, names in *stars* are abstract
(flatten_configbundle_hierarchy in src/libslic3r/PresetBundle.cpp). User presets are whole
configs in <config_dir>/printer|print|filament/<Name>.ini.

FORM merges the three presets into one INI and runs

    prusa-slicer --export-gcode --load merged.ini --output plate_1.gcode model.stl

(src/libslic3r/PrintConfig.cpp CLIActionsConfigDef / CLIMiscConfigDef), with binary_gcode = 0
so the output is text G-code. A second run with --export-3mf writes a project file (not sliced
data) that opens in PrusaSlicer. G-code: ";LAYER_CHANGE", ";Z:", ";TYPE:<role>" markers,
"; estimated printing time (normal mode) = 1h 2m 3s" and "; total filament used [g] = …"
after the last layer (src/libslic3r/GCode.cpp, GCode/GCodeProcessor.cpp, Print.cpp).

SuperSlicer and QIDISlicer are PrusaSlicer forks with the same INI layout, CLI and G-code
comments; they are registered as their own kinds with their own program and folder names.

PrusaSlicer is run for real on macOS, Windows and Linux (.github/workflows/ui.yml); SuperSlicer 2.5.59.13 and
QIDISlicer 1.2.5 on Windows and Linux (.github/workflows/slicers.yml), from their official builds, never opened.

Settings, all optional, in studio.toml (table [slicer.prusa], [slicer.superslicer], [slicer.qidi]):
    app = "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
    config_dir = "~/Library/Application Support/PrusaSlicer"
    machine = "auto"      # printer preset; "auto" follows the selection in PrusaSlicer
    process = "auto"      # print preset
    filament = "auto"
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .common import SlicerBlocked, SlicerFailed, first_dir, find_app as _find, gcode_stats, gcode_version, platform, private, program_version, shipped_dirs
from .common import parse_layers as _parse_layers

SECTION = {"machine": "printer", "process": "print", "filament": "filament"}
# Preset bookkeeping, not print settings: dropped from the merged INI (print and filament presets both carry the
# compatibility keys, so one would overwrite the other). printer_model stays: start G-code uses it.
META = {"inherits", "compatible_printers", "compatible_printers_condition", "compatible_prints",
        "compatible_prints_condition", "renamed_from", "alias"}

# PrusaSlicer's extrusion role names (src/libslic3r/ExtrusionRole.cpp, gcode_extrusion_role_to_string)
# to the Bambu Studio / OrcaSlicer names the layer viewer colours. The geometry is untouched.
TYPE_MAP = {
    "External perimeter": "Outer wall", "Perimeter": "Inner wall", "Overhang perimeter": "Overhang wall",
    "Internal infill": "Sparse infill", "Solid infill": "Internal solid infill", "Top solid infill": "Top surface",
    "Bridge infill": "Bridge", "Gap fill": "Gap infill", "Skirt/Brim": "Skirt", "Support material": "Support",
    "Support material interface": "Support interface", "Wipe tower": "Prime tower",
}


@dataclass
class Variant:
    kind: str
    label: str
    ini: str                       # "PrusaSlicer.ini"
    version_re: str
    url: str
    apps: dict
    dirs: dict
    brew: str = ""
    flatpak: str = ""
    binary_gcode: bool = False     # the program knows the binary_gcode option (PrusaSlicer 2.7+)
    version_cache: dict = field(default_factory=dict)


def _flatpak(fid: str) -> list[str]:
    return [f"{root}/exports/bin/{fid}" for root in ("/var/lib/flatpak", "~/.local/share/flatpak")] if fid else []


PRUSA = Variant(
    kind="prusa", label="PrusaSlicer", ini="PrusaSlicer.ini", version_re=r"PrusaSlicer[-_ ]v?(\d[\d.]*\d)",
    url="https://www.prusa3d.com/page/prusaslicer_424/", brew="prusaslicer", flatpak="com.prusa3d.PrusaSlicer",
    binary_gcode=True,
    apps={"darwin": ["/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
                     "~/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"],
          "win": [r"%ProgramFiles%\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
                  r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe", "prusa-slicer-console.exe",
                  # Chocolatey unpacks the portable build here (found on a CI runner)
                  r"%ProgramData%\chocolatey\lib\prusaslicer\tools\*\prusa-slicer-console.exe",
                  r"%ProgramData%\chocolatey\lib\prusaslicer\tools\prusa-slicer-console.exe"],
          "linux": ["prusa-slicer", "PrusaSlicer", "~/Applications/PrusaSlicer*.AppImage"] + _flatpak("com.prusa3d.PrusaSlicer")},
    dirs={"darwin": ["~/Library/Application Support/PrusaSlicer"],
          "win": [r"%APPDATA%\PrusaSlicer"],
          "linux": ["~/.config/PrusaSlicer", "~/.PrusaSlicer", "~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer"]},
)
SUPERSLICER = Variant(
    kind="superslicer", label="SuperSlicer", ini="SuperSlicer.ini", version_re=r"SuperSlicer[-_ ]v?(\d[\d.]*\d)",
    url="https://github.com/supermerill/SuperSlicer/releases",      # not on Flathub: no flatpak to offer
    apps={"darwin": ["/Applications/SuperSlicer.app/Contents/MacOS/SuperSlicer"],
          "win": [r"%ProgramFiles%\SuperSlicer\superslicer_console.exe", "superslicer_console.exe"],
          "linux": ["superslicer", "SuperSlicer", "/opt/SuperSlicer/AppRun", "~/Applications/SuperSlicer*.AppImage"]},
    dirs={"darwin": ["~/Library/Application Support/SuperSlicer"], "win": [r"%APPDATA%\SuperSlicer"],
          "linux": ["~/.config/SuperSlicer", "~/.SuperSlicer"]},
)
QIDI = Variant(
    kind="qidi", label="QIDISlicer", ini="QIDISlicer.ini", version_re=r"QIDISlicer[-_ ]v?(\d[\d.]*\d)",
    url="https://github.com/QIDITECH/QIDISlicer/releases", binary_gcode=True,
    apps={"darwin": ["/Applications/QIDISlicer.app/Contents/MacOS/QIDISlicer"],
          "win": [r"%ProgramFiles%\QIDISlicer\qidi-slicer-console.exe", "qidi-slicer-console.exe",
                  # the official zip and installer of 1.2.5 have no console program, only this one
                  r"%ProgramFiles%\QIDISlicer\QIDISlicer.exe", r"%LOCALAPPDATA%\Programs\QIDISlicer\QIDISlicer.exe",
                  "QIDISlicer.exe"],
          "linux": ["qidi-slicer", "QIDISlicer", "/opt/QIDISlicer/AppRun", "~/Applications/QIDISlicer*.AppImage"]},
    dirs={"darwin": ["~/Library/Application Support/QIDISlicer"], "win": [r"%APPDATA%\QIDISlicer"],
          "linux": ["~/.config/QIDISlicer"]},
)


# ---- INI -------------------------------------------------------------------
def read_ini(path: Path) -> dict:
    """Sections of a PrusaSlicer INI ("" holds keys before the first section). Values stay strings."""
    out: dict = {"": {}}
    cur = out[""]
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            s = line.strip()
            if not s or s[0] in "#;":
                continue
            if s[0] == "[" and s.endswith("]"):
                cur = out.setdefault(s[1:-1], {})
                continue
            k, eq, v = line.partition("=")
            if eq:
                cur[k.strip()] = v.strip()
    return out


def split_list(value: str) -> list[str]:
    """inherits / compatible_printers: values separated by ';', each possibly in double quotes
    (escape_strings_cstyle in src/libslic3r/Config.cpp)."""
    out = []
    for part in re.findall(r'"((?:[^"\\]|\\.)*)"|([^;]+)', value or ""):
        v = (part[0].replace('\\"', '"').replace("\\\\", "\\") if part[0] else part[1]).strip()
        if v:
            out.append(v)
    return out


def shipped_profiles(app: str | None, share: str = "PrusaSlicer") -> Path | None:
    """The vendor bundles inside the program itself (PrusaSlicer.app/Contents/Resources/profiles,
    <dir>/resources/profiles, share/<Program>/profiles, an unpacked AppImage: see common.shipped_dirs)."""
    if not app:
        return None
    return next(iter(shipped_dirs(app, share)), None)


class Bundle:
    """Every preset PrusaSlicer would know about in one config folder."""

    def __init__(self, config_dir: Path, shipped: Path | None = None):
        self.dir = config_dir
        self.system: dict = {s: {} for s in SECTION.values()}     # name -> [(bundle file, section dict), ...]
        files = sorted((config_dir / "vendor").glob("*.ini"))
        # A slicer that has never been opened has no vendor folder yet. The bundles it ships inside the program
        # are the same files, so a preset pinned in studio.toml works on a fresh install. Installed ones win.
        have = {f.name for f in files}
        if shipped and shipped.is_dir():
            files += [f for f in sorted(shipped.glob("*.ini")) if f.name not in have]
        for vf in files:
            try:
                data = read_ini(vf)
            except OSError:
                continue
            for sec, body in data.items():
                kind, _, name = sec.partition(":")
                if kind in self.system and name:
                    self.system[kind].setdefault(name, []).append((vf.name, body))

    def user(self, section: str, name: str) -> Path | None:
        for d in (self.dir / section, self.dir / "presets" / section):
            p = d / f"{name}.ini"
            if p.exists():
                return p
        return None

    def flatten(self, label: str, section: str, name: str, bundle: str | None = None, depth: int = 0) -> dict:
        if depth > 16:
            raise SlicerBlocked(f"Preset “{name}” has a circular inheritance chain.")
        user = None if bundle else self.user(section, name)
        if user:
            own, src = read_ini(user)[""], None
        elif name in self.system[section]:
            found = self.system[section][name]      # a parent comes from the child's own vendor bundle when it can
            src, own = next((x for x in found if x[0] == bundle), found[0])
        else:
            raise SlicerBlocked(f"{section.capitalize()} preset “{name}” was not found under {self.dir}. "
                                f"Open {label} once with this preset selected, or set the preset name in studio.toml.")
        merged: dict = {}
        for parent in split_list(own.get("inherits", "")):
            merged.update(self.flatten(label, section, parent, src, depth + 1))
        merged.update({k: v for k, v in own.items() if k not in ("inherits", "renamed_from")})
        return merged


# ---- adapter ---------------------------------------------------------------
class Adapter:
    def __init__(self, v: Variant):
        self.v = v

    def settings(self, cfg: dict) -> dict:
        s = cfg["slicer"]
        sub = s.get(self.v.kind) if isinstance(s.get(self.v.kind), dict) else {}
        explicit = s.get("kind") == self.v.kind
        out = {k: sub.get(k) or (s.get(k, "auto") if explicit else "auto") for k in SECTION}
        out["app"], out["config_dir"] = sub.get("app") or "", sub.get("config_dir") or ""
        return out

    def find_app(self, cfg: dict) -> str | None:
        st = self.settings(cfg)
        return _find([st["app"]] if st["app"] else self.v.apps[platform()])

    def config_dir(self, cfg: dict) -> Path:
        st = self.settings(cfg)
        return Path(first_dir([st["config_dir"]] if st["config_dir"] else self.v.dirs[platform()]))

    def install_hint(self) -> dict:
        cmds = []
        if platform() == "darwin" and self.v.brew and shutil.which("brew"):
            cmds = [f"brew install --cask {self.v.brew}"]
        elif platform() == "linux" and self.v.flatpak and shutil.which("flatpak"):
            cmds = [f"flatpak install -y flathub {self.v.flatpak}"]
        return {"url": self.v.url, "cmds": cmds, "note": f"Download from {self.v.url}", "size": ""}

    def resolve(self, cfg: dict) -> dict:
        v, st = self.v, self.settings(cfg)
        app = self.find_app(cfg)
        cdir = self.config_dir(cfg)
        out = {"app": app or (st["app"] or v.apps[platform()][0]), "available": False, "presets": {}, "reason": "",
               "label": v.label, "config_dir": str(cdir)}
        if not app:
            out["reason"] = (f"{v.label} was not found (looked for {v.apps[platform()][0]}). "
                             f"Install it or set [slicer.{v.kind}].app in studio.toml.")
            return out
        try:
            selected = read_ini(cdir / v.ini).get("presets", {}) if (cdir / v.ini).exists() else {}
            names = {k: st[k] if st[k] != "auto" else selected.get(SECTION[k], "") for k in SECTION}
            out["source"] = {k: ("studio.toml" if st[k] != "auto" else f"{v.label} current selection") for k in SECTION}
            bundle = Bundle(cdir, shipped_profiles(app, v.label))
            for kind, name in names.items():
                if not name:
                    raise SlicerBlocked(f"No {SECTION[kind]} preset is selected in {v.label} and none is set in studio.toml.")
                flat = bundle.flatten(v.label, SECTION[kind], name)
                blob = "\n".join(f"{k} = {flat[k]}" for k in sorted(flat)).encode()
                out["presets"][kind] = {"name": name, "sha": hashlib.sha256(blob).hexdigest()[:16], "data": flat}
            m, p, f = (out["presets"][k]["data"] for k in ("machine", "process", "filament"))
            if m.get("printer_technology", "FFF") != "FFF":
                raise SlicerBlocked(f"“{names['machine']}” is a resin (SLA) printer. Form Studio slices FFF printers only.")
            for what, data in (("Print", p), ("Filament", f)):
                compat = split_list(data.get("compatible_printers", ""))
                if compat and names["machine"] not in compat:
                    raise SlicerBlocked(f"{what} preset “{names[{'Print': 'process', 'Filament': 'filament'}[what]]}” "
                                        f"is not compatible with “{names['machine']}”.")
            if p.get("compatible_printers_condition") or f.get("compatible_printers_condition"):
                out["unchecked"] = "compatible_printers_condition is not evaluated by Form Studio; the slicer still applies it."
            out["nozzle_mm"] = float((m.get("nozzle_diameter") or "0.4").split(",")[0])
            out["layer_height_mm"] = float(p.get("layer_height") or 0.2)
            pts = [tuple(float(c) for c in pt.split("x")) for pt in (m.get("bed_shape") or "").split(",") if "x" in pt]
            if pts:
                xs, ys = [a for a, _ in pts], [b for _, b in pts]
                out["envelope_mm"] = [max(xs) - min(xs), max(ys) - min(ys), float(m.get("max_print_height") or 200)]
            out["summary"] = {
                "walls": p.get("perimeters"), "infill": p.get("fill_density"), "supports": p.get("support_material"),
                "plate": None, "filament_type": (f.get("filament_type") or "?").split(";")[0],
                "density": float((f.get("filament_density") or "1.24").split(",")[0]),
            }
            out["available"] = True
        except SlicerBlocked as e:
            out["reason"] = str(e)
        except (ValueError, OSError) as e:
            out["reason"] = f"Could not read {v.label} presets: {e}"
        return out

    def version(self, app: str) -> str:
        c = self.v.version_cache
        if app not in c:
            c[app] = program_version(app, self.v.version_re, (self.v.label + ".dll",))
        return c[app]

    def sliced_version(self, app: str, gcode: Path) -> str:
        """The program's version for a slice: as the program reports it, else as that G-code states it."""
        v = self.version(app)
        if v in ("unknown", "unavailable"):
            said = gcode_version(gcode, self.v.label)
            if said:
                v = self.v.version_cache[app] = said
        return v

    def public(self, resolved: dict) -> dict:
        out = {k: v for k, v in resolved.items() if k != "presets"}
        out["presets"] = {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved.get("presets", {}).items()}
        if resolved.get("available"):
            out["version"] = self.version(resolved["app"])
        return out

    def merged_ini(self, resolved: dict) -> str:
        cfg: dict = {}
        for kind in ("machine", "process", "filament"):
            cfg.update({k: v for k, v in resolved["presets"][kind]["data"].items() if k not in META})
        cfg["printer_settings_id"] = resolved["presets"]["machine"]["name"]
        cfg["print_settings_id"] = resolved["presets"]["process"]["name"]
        cfg["filament_settings_id"] = resolved["presets"]["filament"]["name"]
        if self.v.binary_gcode or "binary_gcode" in cfg:
            cfg["binary_gcode"] = "0"                  # FORM reads text G-code
        head = f"# merged by Form Studio from {self.v.label} presets: " + " / ".join(
            resolved["presets"][k]["name"] for k in ("machine", "process", "filament"))
        return head + "\n" + "".join(f"{k} = {cfg[k]}\n" for k in sorted(cfg))

    def slice_stl(self, resolved: dict, stl: Path, out_dir: Path, timeout: float = 600) -> dict:
        v = self.v
        if not resolved.get("available"):
            raise SlicerBlocked(resolved.get("reason") or "Slicer unavailable.")
        out_dir = Path(out_dir).resolve()
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        ini = out_dir / "config.ini"
        ini.write_text(self.merged_ini(resolved), encoding="utf-8")
        local = out_dir / "model.stl"
        shutil.copyfile(stl, local)
        gcode = out_dir / "plate_1.gcode"
        cmd = [resolved["app"], "--export-gcode", "--load", str(ini), "--output", str(gcode), str(local)]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=out_dir, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise SlicerFailed(f"{v.label} did not finish within {timeout:g} s.",
                               "Raise [slicer].timeout_s in studio.toml, or simplify the model.")
        except OSError as e:
            raise SlicerBlocked(f"{v.label} could not be started: {e}")
        log = private(r.stdout + "\n" + r.stderr)
        (out_dir / "slicer.log").write_text(log[-200_000:], encoding="utf-8")
        if r.returncode != 0 or not gcode.exists():
            lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
            errors = [ln for ln in lines if "error" in ln.lower()] or lines
            raise SlicerFailed(f"{v.label} refused to slice: {errors[-1] if errors else f'exit code {r.returncode}'}",
                               "The full log is kept beside the failed slice. Check that the presets match the printer.",
                               "\n".join(errors[-8:]))
        info = parse_gcode(gcode)
        project = None
        try:                                            # a project file to open in the slicer; not sliced data
            r3 = subprocess.run([resolved["app"], "--export-3mf", "--load", str(ini), "--output",
                                 str(out_dir / "project.3mf"), str(local)], capture_output=True, text=True,
                                timeout=min(timeout, 120), cwd=out_dir, stdin=subprocess.DEVNULL)
            project = "project.3mf" if r3.returncode == 0 and (out_dir / "project.3mf").exists() else None
        except (OSError, subprocess.SubprocessError):
            pass
        info.update({
            "seconds": round(time.time() - t0, 2), "slicer_version": self.sliced_version(resolved["app"], gcode),
            "gcode": gcode.name, "threemf": None, "project_3mf": project,
            "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
            "presets": {k: {"name": p["name"], "sha": p["sha"]} for k, p in resolved["presets"].items()},
            "warnings": sorted({ln.strip()[:200] for ln in log.splitlines() if "warning" in ln.lower()})[:12],
        })
        return info


def parse_gcode(path: Path) -> dict:
    """Statistics comments, plus what only a pass over the file gives: layer count, top Z, supports."""
    out = gcode_stats(path)
    layers, z, support = 0, None, False
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line[0] != ";":
                continue
            if line.startswith(";LAYER_CHANGE"):
                layers += 1
            elif line.startswith(";Z:"):
                try:
                    z = float(line[3:])
                except ValueError:
                    pass
            elif line.startswith(";TYPE:Support"):
                support = True
    out.setdefault("layers", layers)
    if z is not None:
        out.setdefault("max_z_mm", z)
    out["support_used"] = support
    return out


def parse_layers_prusa(path: Path) -> list[dict]:
    return _parse_layers(path, "prusa", TYPE_MAP)


_A = Adapter(PRUSA)
LABEL = PRUSA.label
find_app, config_dir, install_hint, resolve = _A.find_app, _A.config_dir, _A.install_hint, _A.resolve
version, public, slice_stl = _A.version, _A.public, _A.slice_stl
parse_layers = parse_layers_prusa
