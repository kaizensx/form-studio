"""The person's own KiCad, through `kicad-cli` (KiCad 8 and later): design-rule and electrical-rule checks, Gerbers,
drill files, pick-and-place, BOM and the board STEP.

Form Studio never ships KiCad and never claims its results: each result is KiCad's report file, kept as it came, and
read into rows that say "KiCad DRC" or "KiCad ERC". When kicad-cli is not installed the result says so and names the
install route (Settings > Engines & software, `form install kicad`), which the person starts.

    find(cfg)                      the kicad-cli path, or None ([cad].kicad_cli, $FORM_KICAD_CLI, PATH, the usual places)
    drc(exe, pcb, out_dir)         KiCad's DRC as JSON: violations, unconnected items, schematic parity
    erc(exe, sch, out_dir)         KiCad's ERC as JSON
    export(exe, pcb, kind, out)    gerbers | drill | pos | step | bom (from the schematic)
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT_S = 600
INSTALL = {"id": "kicad", "how": "Settings > Engines & software > KiCad, or `form install kicad` (Homebrew cask, winget, "
                                 "Flathub, or the official download page)", "page": "https://www.kicad.org/download/"}


def _candidates() -> list[str]:
    if sys.platform == "darwin":
        apps = ["/Applications/KiCad/KiCad.app"] + sorted(glob.glob("/Applications/KiCad*/KiCad.app")) + \
            sorted(glob.glob("/Applications/KiCad*.app"))
        return [str(Path(a) / "Contents/MacOS/kicad-cli") for a in apps]
    if sys.platform.startswith("win"):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        return [str(Path(r) / "bin" / "kicad-cli.exe") for r in sorted(glob.glob(str(Path(pf) / "KiCad" / "*")), reverse=True)]
    return ["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli", "/snap/bin/kicad.kicad-cli"]


def find(cfg: dict | None = None) -> str | None:
    conf = ((cfg or {}).get("cad") or {}).get("kicad_cli", "") or os.environ.get("FORM_KICAD_CLI", "")
    if conf:
        return shutil.which(conf) or (conf if Path(conf).is_file() else None)
    if os.environ.get("FORM_SETUP_PRETEND_MISSING", "") and "kicad" in os.environ["FORM_SETUP_PRETEND_MISSING"].split(","):
        return None
    p = shutil.which("kicad-cli")
    return p or next((c for c in _candidates() if Path(c).is_file()), None)


def version(exe: str) -> str:
    try:
        r = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "unknown version"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "unknown version"


def status(cfg: dict | None = None) -> dict:
    from .. import use
    if find(cfg) and not use.on("kicad", cfg):
        return {"available": False, "reason": "KiCad is installed but switched off (Settings > Engines & software, "
                                              "Use in Form Studio).", "install": INSTALL}
    exe = find(cfg)
    if not exe:
        return {"available": False, "reason": "KiCad's kicad-cli is not installed on this computer.", "install": INSTALL}
    return {"available": True, "path": exe, "version": version(exe)}


def _run(cmd: list[str], timeout: int = TIMEOUT_S) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": None, "log": f"kicad-cli did not finish in {timeout} s.", "cmd": cmd}
    except OSError as e:
        return {"ok": False, "code": None, "log": f"kicad-cli could not start: {e}", "cmd": cmd}
    return {"ok": r.returncode == 0, "code": r.returncode, "log": ((r.stdout or "") + (r.stderr or ""))[-4000:], "cmd": cmd}


# ---- rule checks ---------------------------------------------------------------------------------------------------
def _items(v: dict) -> list:
    out = []
    for it in v.get("items") or []:
        pos = it.get("pos") or {}
        out.append({"description": it.get("description", ""), "x": pos.get("x"), "y": pos.get("y"), "uuid": it.get("uuid", "")})
    return out


def parse_drc(report: dict) -> dict:
    """KiCad's DRC JSON report as rows. Only what the report says: type, severity, description, items."""
    rows = []
    for group, label in (("violations", "violation"), ("unconnected_items", "unconnected"), ("schematic_parity", "parity")):
        for v in report.get(group) or []:
            rows.append({"group": label, "type": v.get("type", ""), "severity": v.get("severity", ""),
                         "description": v.get("description", ""), "items": _items(v)})
    sev = {}
    for r in rows:
        sev[r["severity"] or "unknown"] = sev.get(r["severity"] or "unknown", 0) + 1
    return {"by": "KiCad DRC", "kicad_version": report.get("kicad_version", ""), "date": report.get("date", ""),
            "units": report.get("coordinate_units", ""), "rows": rows, "counts": sev, "total": len(rows)}


def parse_erc(report: dict) -> dict:
    rows = []
    for sheet in report.get("sheets") or []:
        for v in sheet.get("violations") or []:
            rows.append({"sheet": sheet.get("path", ""), "type": v.get("type", ""), "severity": v.get("severity", ""),
                         "description": v.get("description", ""), "items": _items(v)})
    sev = {}
    for r in rows:
        sev[r["severity"] or "unknown"] = sev.get(r["severity"] or "unknown", 0) + 1
    return {"by": "KiCad ERC", "kicad_version": report.get("kicad_version", ""), "date": report.get("date", ""),
            "rows": rows, "counts": sev, "total": len(rows)}


def _check(exe: str, kind: str, src: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = out_dir / f"{kind}.json"
    rep.unlink(missing_ok=True)
    sub = ["pcb", "drc"] if kind == "drc" else ["sch", "erc"]
    cmd = [exe, *sub, "--format", "json", "--severity-all", "--units", "mm", "--output", str(rep), str(src)]
    if kind == "erc":
        cmd.remove("--units")
        cmd.remove("mm")
    run = _run(cmd)
    if not rep.is_file():
        return {"ran": False, "by": f"KiCad {kind.upper()}", "error": "kicad-cli wrote no report.", "log": run["log"],
                "cmd": run["cmd"]}
    try:
        data = json.loads(rep.read_text(encoding="utf-8"))
    except ValueError:
        return {"ran": False, "by": f"KiCad {kind.upper()}", "error": "KiCad's report is not JSON.", "log": run["log"]}
    res = parse_drc(data) if kind == "drc" else parse_erc(data)
    return {"ran": True, **res, "report": str(rep), "cmd": run["cmd"], "exit_code": run["code"]}


def drc(exe: str, pcb: Path, out_dir: Path) -> dict:
    return _check(exe, "drc", Path(pcb), Path(out_dir))


def erc(exe: str, sch: Path, out_dir: Path) -> dict:
    return _check(exe, "erc", Path(sch), Path(out_dir))


# ---- fab outputs ---------------------------------------------------------------------------------------------------
KINDS = ("gerbers", "drill", "pos", "step", "bom")


def export(exe: str, pcb: Path, kind: str, out_dir: Path, sch: Path | None = None) -> dict:
    """One kicad-cli export into out_dir. Returns the files it made and kicad-cli's log."""
    pcb, out_dir = Path(pcb), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pcb.stem
    if kind == "gerbers":
        d = out_dir / "gerbers"
        d.mkdir(exist_ok=True)
        cmd = [exe, "pcb", "export", "gerbers", "--output", str(d) + os.sep, str(pcb)]
    elif kind == "drill":
        d = out_dir / "drill"
        d.mkdir(exist_ok=True)
        cmd = [exe, "pcb", "export", "drill", "--format", "excellon", "--generate-map", "--map-format", "pdf",
               "--output", str(d) + os.sep, str(pcb)]
    elif kind == "pos":
        d = out_dir / f"{stem}-pos.csv"
        cmd = [exe, "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--output", str(d), str(pcb)]
    elif kind == "step":
        d = out_dir / f"{stem}.step"
        cmd = [exe, "pcb", "export", "step", "--force", "--subst-models", "--output", str(d), str(pcb)]
    elif kind == "bom":
        if sch is None or not Path(sch).is_file():
            return {"kind": kind, "ok": False, "files": [], "error": "A BOM comes from the schematic: no .kicad_sch beside the board."}
        d = out_dir / f"{stem}-bom.csv"
        cmd = [exe, "sch", "export", "bom", "--output", str(d), str(sch)]
    else:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    before = set(out_dir.rglob("*"))
    run = _run(cmd)
    made = sorted(str(f) for f in set(out_dir.rglob("*")) - before if f.is_file())
    if not made and Path(d).is_file():
        made = [str(d)]
    out = {"kind": kind, "ok": run["ok"] and bool(made), "files": made, "cmd": run["cmd"], "log": run["log"]}
    if kind == "gerbers" and made and not any("edge_cuts" in Path(f).name.lower() or f.lower().endswith(".gm1") for f in made):
        out["warning"] = "No Edge.Cuts Gerber was made: a fab needs the board outline."
    return out
