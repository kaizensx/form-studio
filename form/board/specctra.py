"""Specctra: write a board as a .dsn design, read a .ses session back, and run Freerouting between the two.

Freerouting (https://github.com/freerouting/freerouting, GPL-3.0) is a separate program. Form Studio contains none
of its code and never downloads it: when the person has installed it and switched it on (Settings > Engines &
software > Freerouting, off by default), `run` starts it as its own process on a .dsn Form Studio wrote and reads the
.ses it writes. The copper it routed is then checked like any other: by Form Studio's own geometric check, and by
KiCad's DRC when kicad-cli is installed.

    write_dsn(doc, "board.dsn")            # the outline, keep-outs, every pad with its shape, the nets, the classes
    read_ses("board.ses")                  # {"wires": [...], "vias": [...]} in the board file's millimetres
    apply_ses(doc, ses)                    # as segments and vias in the .kicad_pcb
    run(doc, work_dir, cfg, passes=20)     # Freerouting, when it is there

The .dsn follows the Specctra design language as KiCad's own export uses it (resolution um 10, y up). Each part
is written as its own image with its pads where they are on the board, so no rotation or mirroring is left to the
reader. Written here and read back by Form Studio's own reader in the tests; the exchange with Freerouting itself
runs only on a computer that has it.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import geom
from .pcb import Pcb
from .sexpr import atoms, children, first, head, num, parse, walk

RES = 10                      # units per micrometre
HOME = "https://github.com/freerouting/freerouting"
INSTALL = {"id": "freerouting", "page": HOME + "/releases",
           "how": "Settings > Engines & software > Freerouting: install it from its own releases page (it needs Java), "
                  "give its path in [cad] freerouting, and switch it on. Form Studio does not download it."}
TIMEOUT_S = 1800


def _um(v: float) -> str:
    s = f"{v * 1000:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _name(s: str) -> str:
    return s if re.fullmatch(r"[A-Za-z0-9_.+\-/~$&#@:\[\]]+", s or "") else '"' + (s or "").replace('"', "'") + '"'


def via_name(size: float, drill: float) -> str:
    return f"Via[0-1]_{round(size * 1000)}:{round(drill * 1000)}_um"


def write_dsn(doc: Pcb, path, nets=None) -> dict:
    """The board as a Specctra design. Tracks and vias already on the board are written as protected wiring."""
    cu = [x for x in doc.cu_layers() if x in ("F.Cu", "B.Cu")] or ["F.Cu", "B.Cu"]
    names = doc.nets()
    rules = doc.rules
    outline, cutouts, notes = doc.edges()
    if not outline:
        raise ValueError("The board has no closed outline (Edge.Cuts).")
    dflt = rules.for_net("")
    L: list[str] = []
    w = L.append
    name = (doc.path.stem if doc.path else "board")
    w(f"(pcb {_name(name + '.dsn')}")
    w('  (parser\n    (string_quote ")\n    (space_in_quoted_tokens on)\n    (host_cad "Form Studio")\n    (host_version "K2")\n  )')
    w(f"  (resolution um {RES})\n  (unit um)")
    w("  (structure")
    for i, lay in enumerate(cu):
        w(f"    (layer {lay}\n      (type signal)\n      (property\n        (index {i})\n      )\n    )")
    pts = " ".join(f"{_um(x)} {_um(-y)}" for x, y in outline + [outline[0]])
    w(f"    (boundary\n      (path pcb 0 {pts})\n    )")
    for c in cutouts:
        pts = " ".join(f"{_um(x)} {_um(-y)}" for x, y in c)
        for lay in cu:
            w(f'    (keepout "" (polygon {lay} 0 {pts}))')
    for z in doc.keepouts():
        pts = " ".join(f"{_um(x)} {_um(-y)}" for x, y in z["polygon"])
        t, v = z["keepout"].get("tracks") == "not_allowed", z["keepout"].get("vias") == "not_allowed"
        kind = "keepout" if t and v else "via_keepout" if v else "wire_keepout" if t else None
        if kind:
            for lay in z["layers"]:
                if lay in cu:
                    w(f'    ({kind} "" (polygon {lay} 0 {pts}))')
    classes: dict = {}
    for nid, nm in names.items():
        if nid > 0:
            c = rules.for_net(nm)
            classes.setdefault(c["class"], {"rule": c, "nets": []})["nets"].append(nm)
    vias = sorted({via_name(c["rule"]["via_diameter"], c["rule"]["via_drill"]): c["rule"] for c in classes.values()}.items()) or \
        [(via_name(dflt["via_diameter"], dflt["via_drill"]), dflt)]
    w("    (via " + " ".join(_name(v) for v, _ in vias) + ")")
    w(f"    (rule\n      (width {_um(dflt['track_width'])})\n      (clearance {_um(dflt['clearance'])})\n"
      f"      (clearance {_um(rules.board['min_copper_edge_clearance'])} (type default_boundary))\n    )")
    w("  )")
    stacks: dict = {}

    def padstack(p) -> str:
        shape, _exact = geom.pad_shape(p["shape"], (0.0, 0.0), p["w"], p["h"], p["angle"], p["rratio"] or 0.25)
        pts_, r = shape
        lays = [x for x in p["layers"] if x in cu]
        if len(pts_) == 1:
            body = lambda lay: f"(shape (circle {lay} {_um(2 * r)}))"
            key = f"Round[{'A' if len(lays) > 1 else lays[0][0]}]Pad_{round(2 * r * 1000)}_um"
        elif len(pts_) == 2:
            (ax, ay), (bx, by) = pts_
            body = lambda lay: f"(shape (path {lay} {_um(2 * r)} {_um(ax)} {_um(-ay)} {_um(bx)} {_um(-by)}))"
            key = (f"Oval[{'A' if len(lays) > 1 else lays[0][0]}]Pad_{round(2 * r * 1000)}_"
                   f"{round(ax * 1000)}_{round(ay * 1000)}_{round(bx * 1000)}_{round(by * 1000)}_um")
        else:
            # a rounded rectangle is written as its outer rectangle: more copper than there is, never less
            q = geom.pad_shape("rect", (0.0, 0.0), p["w"], p["h"], p["angle"])[0][0]
            pp = " ".join(f"{_um(x)} {_um(-y)}" for x, y in q)
            body = lambda lay: f"(shape (polygon {lay} 0 {pp}))"
            key = (f"Rect[{'A' if len(lays) > 1 else lays[0][0]}]Pad_{round(p['w'] * 1000)}x{round(p['h'] * 1000)}_"
                   f"{round((p['angle'] or 0) * 10) % 3600}_um")
        if key not in stacks:
            stacks[key] = "    (padstack " + _name(key) + "\n" + "\n".join("      " + body(lay) for lay in lays) + "\n      (attach off)\n    )"
        return key
    images, places, pins_of = [], [], {}
    for f in doc.footprints():
        pads = [p for p in f["pads"] if p["kind"] != "np_thru_hole" and [x for x in p["layers"] if x in cu]]
        if not pads or not f["ref"]:
            continue
        img = [f"    (image {_name(f['ref'])}"]
        seen: dict = {}
        for p in pads:
            pin = p["num"] or "0"
            seen[pin] = seen.get(pin, 0) + 1
            pid = pin if seen[pin] == 1 else f"{pin}@{seen[pin] - 1}"
            img.append(f"      (pin {_name(padstack(p))} {_name(pid)} {_um(p['x'] - f['x'])} {_um(-(p['y'] - f['y']))})")
            if p["net"] > 0:
                pins_of.setdefault(p["net"], []).append(f"{_name(f['ref'])}-{_name(pid)}")
        img.append("    )")
        images.append("\n".join(img))
        places.append(f"    (component {_name(f['ref'])}\n      (place {_name(f['ref'])} {_um(f['x'])} {_um(-f['y'])} front 0)\n    )")
    w("  (placement\n" + "\n".join(places) + "\n  )")
    for vn, c in vias:
        stacks[vn] = ("    (padstack " + _name(vn) + "\n" + "\n".join(f"      (shape (circle {lay} {_um(c['via_diameter'])}))" for lay in cu) +
                      "\n      (attach off)\n    )")
    w("  (library\n" + "\n".join(images) + "\n" + "\n".join(stacks[k] for k in sorted(stacks)) + "\n  )")
    w("  (network")
    want = set(nets) if nets else None
    routed = []
    for nid in sorted(pins_of):
        nm = names.get(nid, str(nid))
        if want is not None and nm not in want:
            continue
        routed.append(nm)
        w(f"    (net {_name(nm)}\n      (pins {' '.join(pins_of[nid])})\n    )")
    for cl in sorted(classes):
        c = classes[cl]
        mine = [n for n in c["nets"] if n in routed]
        if not mine:
            continue
        w(f"    (class {_name(cl)} {' '.join(_name(n) for n in mine)}\n      (circuit\n        (use_via "
          f"{_name(via_name(c['rule']['via_diameter'], c['rule']['via_drill']))})\n      )\n      (rule\n        (width "
          f"{_um(c['rule']['track_width'])})\n        (clearance {_um(c['rule']['clearance'])})\n      )\n    )")
    w("  )")
    w("  (wiring")
    for t in doc.tracks():
        if t["layer"] in cu and t["net"] > 0:
            w(f"    (wire (path {t['layer']} {_um(t['w'])} {_um(t['a'][0])} {_um(-t['a'][1])} {_um(t['b'][0])} {_um(-t['b'][1])})"
              f" (net {_name(names.get(t['net'], ''))}) (type protect))")
    for v in doc.vias():
        if v["net"] > 0:
            w(f"    (via {_name(via_name(v['size'], v['drill']))} {_um(v['at'][0])} {_um(-v['at'][1])} (net {_name(names.get(v['net'], ''))}) (type protect))")
    w("  )\n)")
    path = Path(path)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"file": str(path), "nets": len(routed), "components": len(places), "padstacks": len(stacks), "layers": cu,
            "notes": notes + (["A rounded-rectangle pad is written as its outer rectangle."] if any(
                p["shape"] == "roundrect" for p in doc.pads()) else [])}


def read_ses(path) -> dict:
    """The wires and vias of a Specctra session, in millimetres with y down (the board file's frame)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\(\s*string_quote\s+[\"']\s*\)", "", text)
    tree = parse(text)
    if head(tree) != "session":
        raise ValueError(f"Not a Specctra session (it starts with “{head(tree) or '?'}”, not session).")
    routes = first(tree, "routes")
    if routes is None:
        return {"wires": [], "vias": [], "nets": 0, "file": str(path)}
    res = first(routes, "resolution")
    ra = atoms(res) if res is not None else []
    unit, per = (str(ra[0]), num(ra[1], 1.0)) if len(ra) >= 2 else ("um", float(RES))
    mm = {"um": 0.001, "mm": 1.0, "mil": 0.0254, "inch": 25.4}.get(unit, 0.001) / (per or 1.0)
    stacks = {}
    for ps in [n for n in walk(routes) if head(n) == "padstack"]:
        nm = str(atoms(ps)[0]) if atoms(ps) else ""
        for sh in children(ps, "shape"):
            c = first(sh, "circle")
            if c is not None and len(atoms(c)) >= 2:
                stacks[nm] = (num(atoms(c)[1], 0.0) or 0.0) * mm
    wires, vias, nets = [], [], 0
    out = first(routes, "network_out")
    for net in children(out, "net") if out is not None else []:
        nm = str(atoms(net)[0]) if atoms(net) else ""
        nets += 1
        for wnode in children(net, "wire"):
            p = first(wnode, "path")
            a = atoms(p) if p is not None else []
            if len(a) < 6:
                continue
            xy_ = [num(v, 0.0) for v in a[2:]]
            pts = [(xy_[i] * mm, -xy_[i + 1] * mm) for i in range(0, len(xy_) - 1, 2)]
            wires.append({"net": nm, "layer": str(a[0]), "width": (num(a[1], 0.0) or 0.0) * mm, "points": pts})
        for v in children(net, "via"):
            a = atoms(v)
            if len(a) >= 3:
                m = re.search(r"_(\d+):(\d+)_um", str(a[0]))
                size = (int(m.group(1)) / 1000.0) if m else stacks.get(str(a[0]), 0.0)
                vias.append({"net": nm, "at": ((num(a[1], 0.0) or 0.0) * mm, -(num(a[2], 0.0) or 0.0) * mm),
                             "size": size, "drill": (int(m.group(2)) / 1000.0) if m else None, "padstack": str(a[0])})
    return {"wires": wires, "vias": vias, "nets": nets, "file": str(path)}


def apply_ses(doc: Pcb, ses: dict) -> dict:
    """The session's wires and vias as segments and vias of the board. A net the board does not have, or a via
    whose size the session does not state, is listed and left out."""
    segs = nv = 0
    length = 0.0
    skipped = []
    ids = {nm: i for i, nm in doc.nets().items()}
    for wnode in ses["wires"]:
        nid = ids.get(wnode["net"])
        if nid is None or wnode["width"] <= 0:
            skipped.append(f"wire of {wnode['net'] or 'no net'}")
            continue
        pts = wnode["points"]
        for i in range(len(pts) - 1):
            d = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            if d < 1e-7:
                continue
            doc.add_segment(pts[i], pts[i + 1], wnode["width"], wnode["layer"], nid)
            segs += 1
            length += d
    for v in ses["vias"]:
        nid = ids.get(v["net"])
        c = doc.rules.for_net(v["net"])
        size = v["size"] or 0.0
        if nid is None or size <= 0:
            skipped.append(f"via of {v['net'] or 'no net'}")
            continue
        doc.add_via(v["at"], size, v["drill"] or c["via_drill"], nid)
        nv += 1
    return {"segments": segs, "vias": nv, "length_mm": round(length, 3), "skipped": skipped}


# ---- Freerouting, the person's own ---------------------------------------------------------------------------------------
def _java() -> str | None:
    j = shutil.which("java")
    if not j:
        return None
    try:
        r = subprocess.run([j, "-version"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        return j if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def find(cfg: dict | None = None) -> str | None:
    """The Freerouting the person installed: [cad] freerouting or $FORM_FREEROUTING (a .jar or a launcher), or a
    `freerouting` launcher on PATH. Nothing is searched for beyond that, and nothing is downloaded."""
    conf = ((cfg or {}).get("cad") or {}).get("freerouting", "") or os.environ.get("FORM_FREEROUTING", "")
    if conf:
        p = shutil.which(conf) or (conf if Path(conf).expanduser().is_file() else None)
        return str(Path(p).expanduser()) if p else None
    if "freerouting" in os.environ.get("FORM_SETUP_PRETEND_MISSING", "").split(","):
        return None
    return shutil.which("freerouting")


def status(cfg: dict | None = None) -> dict:
    from .. import use
    exe = find(cfg)
    if not exe:
        return {"available": False, "reason": "Freerouting is not installed on this computer (or its path is not set).",
                "install": INSTALL, "licence": "GPL-3.0, a separate program"}
    if not use.on("freerouting", cfg):
        return {"available": False, "path": exe, "install": INSTALL, "licence": "GPL-3.0, a separate program",
                "reason": "Freerouting is installed but switched off (Settings > Engines & software, Use in Form Studio). "
                          "It is off until you turn it on."}
    if exe.lower().endswith(".jar") and not _java():
        return {"available": False, "path": exe, "install": INSTALL, "licence": "GPL-3.0, a separate program",
                "reason": "Freerouting is a Java program and no Java runtime was found."}
    return {"available": True, "path": exe, "licence": "GPL-3.0, a separate program"}


def command(exe: str, dsn: Path, ses: Path, passes: int) -> list[str]:
    base = [_java() or "java", "-jar", exe] if exe.lower().endswith(".jar") else [exe]
    return base + ["-de", str(dsn), "-do", str(ses), "-mp", str(int(passes))]


def run(doc: Pcb, work: Path, cfg: dict | None = None, passes: int = 20, nets=None, timeout: int = TIMEOUT_S) -> dict:
    """Write the .dsn, run the person's Freerouting on it, read the .ses and add its copper to doc."""
    st = status(cfg)
    if not st["available"]:
        return {"ran": False, "engine": "freerouting", "why": st["reason"], "install": INSTALL}
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stem = doc.path.stem if doc.path else "board"
    dsn, ses = work / f"{stem}.dsn", work / f"{stem}.ses"
    ses.unlink(missing_ok=True)
    wrote = write_dsn(doc, dsn, nets)
    cmd = command(st["path"], dsn, ses, passes)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=str(work))
        log, code = ((r.stdout or "") + (r.stderr or ""))[-4000:], r.returncode
    except subprocess.TimeoutExpired:
        return {"ran": False, "engine": "freerouting", "why": f"Freerouting did not finish in {timeout} s.", "cmd": cmd}
    except OSError as e:
        return {"ran": False, "engine": "freerouting", "why": f"Freerouting could not start: {e}", "cmd": cmd}
    if not ses.is_file():
        return {"ran": False, "engine": "freerouting", "why": "Freerouting wrote no session file.", "log": log, "cmd": cmd,
                "exit_code": code}
    session = read_ses(ses)
    applied = apply_ses(doc, session)
    return {"ran": True, "engine": "freerouting", "by": "Freerouting (a separate GPL-3.0 program, run on this computer)",
            "dsn": wrote, "ses": str(ses), "cmd": cmd, "exit_code": code, "log": log, **applied}
