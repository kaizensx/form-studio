"""Schematic, placement and routing for a design's board (wave K2), and for a board file on its own.

    schematic(st, action, project=... | file=...)     read, netlist, erc, edit (operations), symbols, to_board
    place(st, project=... | file=...)                 parts against the enclosure's keep-outs, openings and lid
    route(st, project=... | file=..., engine="form")  Form Studio's router, or the person's Freerouting
    copper_check(st, p)                               Form Studio's geometric check of the copper as it is

In a design, the files worked on are the copies in <project>/board/ (board_import made them); the person's own
files are never opened for writing. Every change keeps the version it replaced in <project>/board/history/, the
board model (board.json) is read again from the changed file, and the Bench entries that depend on the board go
stale. On a file outside a design, the result is written to a new file beside it (or to out=) and the file given
is left as it was.

Who checked what is always said: "Form Studio geometric check" and "Form Studio ERC" are Form Studio's own; "KiCad
DRC" and "KiCad ERC" are KiCad's reports, run only when kicad-cli is installed. Nothing here calls a result clean
on KiCad's behalf.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from . import api, drc as drc_mod, kicad_cli, model, place as place_mod, route as route_mod, specctra
from .pcb import Pcb, from_netlist, library_dirs
from .schematic import Libraries, Schematic

VERSION = 1


def _err(msg, hint="", status=400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _keep(path: Path) -> str | None:
    """Copy the file as it is into history/ beside it before it is changed. Returns the copy's name."""
    if not path.is_file():
        return None
    h = path.parent / "history"
    h.mkdir(exist_ok=True)
    n = len(list(h.glob(f"*-{path.name}"))) + 1
    name = f"{n:03d}-{_sha(path)[:8]}-{path.name}"
    shutil.copyfile(path, h / name)
    return name


def _project_files(st, pid: str) -> tuple[dict, dict, Path, Path]:
    p = st.load(pid)
    board = api.load(st, p)
    if board is None:
        raise _err("This design has no board.", "board_import(file=..., project=...) brings one in.", 409)
    if board["format"] != "kicad_pcb":
        raise _err("The design's board is an IDF file: schematic, placement and routing work on KiCad files.",
                   "Import the board's .kicad_pcb.", 409)
    d = api.board_dir(st, p["id"])
    pcb = d / board["file"]
    if not pcb.is_file():
        raise _err(f"The board file {board['file']} is missing from the design's folder.", "Import the board again.", 409)
    return p, board, pcb, pcb.with_suffix(".kicad_sch")


def _refresh(st, p: dict, pcb: Path, prev: dict, text: str) -> dict:
    """Read the board model again from the changed file (in the same frame), and record it on the design."""
    board = api.read(pcb, origin=prev.get("origin"))
    known = {c["ref"]: c["height"] for c in prev["components"] if (c.get("height") or {}).get("provenance") in ("given", "measured")}
    for c in board["components"]:
        if c["ref"] in known and (c.get("height") or {}).get("value") is None:
            c["height"] = known[c["ref"]]
    if prev.get("connector_overrides"):
        board["connector_overrides"] = prev["connector_overrides"]
    board["connectors"] = model.connectors(board, board.get("connector_overrides"))
    board["imported"] = {**(prev.get("imported") or {}), "changed": time.time(), "changed_by": text}
    d = pcb.parent
    tmp = d / "board.json.tmp"
    tmp.write_text(json.dumps(board, indent=1, default=str), encoding="utf-8")
    from .. import fsutil
    fsutil.replace(tmp, d / "board.json")
    with st.lock(p["id"]):
        p = st.load(p["id"])
        p["board"] = {**(p.get("board") or {}), "file": pcb.name, "format": "kicad_pcb", "sha256": board["sha256"],
                      "ts": time.time(), "key": api.board_key(board)}
        st.decide(p, "board", text)
        st.save(p)
    return board


def _out_path(src: Path, out: str | None, suffix: str, overwrite: bool) -> Path:
    o = Path(out).expanduser().resolve() if out else src.with_name(f"{src.stem}-{suffix}{src.suffix}")
    if o == src.resolve():
        raise _err("The result would overwrite the file you gave.", "Give out= a different path; the file given is never changed.")
    if o.exists() and not overwrite:
        raise _err(f"{o.name} already exists.", "Give another out=, or overwrite=True.", 409)
    for ext in (".kicad_pro",):                       # the rules travel with the board
        s, t = src.with_suffix(ext), o.with_suffix(ext)
        if s.is_file() and not t.exists():
            shutil.copyfile(s, t)
    return o


def _file(path: str, suffix: str) -> Path:
    f = Path(path).expanduser().resolve()
    if not f.is_file():
        raise _err(f"File not found: {f}", f"Give the absolute path of a {suffix} file.", 404)
    if f.suffix.lower() != suffix:
        raise _err(f"{f.name} is not a {suffix} file.")
    return f


# ---- schematic -----------------------------------------------------------------------------------------------------------
ACTIONS = ("read", "netlist", "erc", "edit", "symbols", "to_board")


def schematic(st, action: str = "read", project: str | None = None, file: str | None = None, ops: list | None = None,
              libraries: list | None = None, query: str = "", out: str | None = None, size: list | None = None,
              overwrite: bool = False, kicad: bool = True) -> dict:
    a = (action or "read").lower()
    if a not in ACTIONS:
        raise _err(f"Unknown action “{action}”.", ", ".join(ACTIONS) + ".")
    cfg = st.cfg
    if a == "symbols":
        libs = Libraries(libraries, cfg)
        res = {"libraries": libs.status()}
        if query:
            res["symbols"] = libs.search(query)
            if ":" in query and len(res["symbols"]) == 1 or any(s["lib_id"] == query for s in res["symbols"]):
                from .schematic import lib_pins
                try:
                    res["pins"] = [{k: p[k] for k in ("number", "name", "type", "x", "y")} for p in lib_pins(libs.symbol(query))]
                except KeyError:
                    pass
        return res
    p = None
    if project:
        p, board, pcb, sch_path = _project_files(st, project)
    elif file:
        sch_path = _file(file, ".kicad_sch") if (a != "edit" or Path(file).expanduser().is_file()) else Path(file).expanduser().resolve()
        pcb = sch_path.with_suffix(".kicad_pcb")
    else:
        raise _err("Give project= (a design with a board) or file= (a .kicad_sch).")
    try:
        if sch_path.is_file():
            sch = Schematic.load(sch_path)
        elif a == "edit":
            sch = Schematic.new(sch_path.stem)
            sch.path = sch_path
        else:
            raise _err(f"There is no schematic ({sch_path.name}).", 'action="edit" starts one; or import the board with its .kicad_sch beside it.', 404)
    except ValueError as e:
        raise _err(f"Could not read {sch_path.name}: {e}")
    if a == "read":
        nl = sch.netlist()
        return {"file": str(sch_path), "symbols": [{k: s[k] for k in ("ref", "value", "footprint", "lib_id", "at", "rot", "unit")}
                                                    for s in sch.symbols() if not s["power"]],
                "power_symbols": sorted({s["value"] for s in sch.symbols() if s["power"]}),
                "nets": [{"name": n["name"], "pins": [f"{x['ref']}.{x['pin']}" for x in n["nodes"]]} for n in nl["nets"]],
                "sheets": nl["sheets"], "notes": nl["notes"]}
    if a == "netlist":
        return {"file": str(sch_path), **Schematic.public(sch.netlist())}
    if a == "erc":
        res = {"file": str(sch_path), "form": sch.erc()}
        ks = kicad_cli.status(cfg)
        if not kicad:
            res["kicad"] = {"ran": False, "why": "Not asked for (kicad=False)."}
        elif ks["available"]:
            res["kicad"] = kicad_cli.erc(ks["path"], sch_path, sch_path.parent / "kicad" / "erc")
        else:
            res["kicad"] = {"ran": False, "why": f"{ks['reason']} Form Studio's own subset is above; KiCad's ERC needs "
                                                 f"KiCad: {ks['install']['how']}."}
        res["headline"] = res["form"]["headline"] + (
            f"; KiCad ERC: {res['kicad']['total']} findings" if res["kicad"].get("ran") else "; KiCad ERC not run")
        return res
    if a == "edit":
        if not ops:
            raise _err("edit needs ops.", "For example [{\"op\": \"place\", \"lib_id\": \"Device:R\", \"at\": [100, 50]}].")
        libs = Libraries((libraries or []) + ([sch_path.parent] if sch_path.parent.is_dir() else []), cfg)
        try:
            done = sch.apply(ops, libs)
        except ValueError as e:
            raise _err(str(e), "Symbols come from the KiCad libraries on this computer; action=\"symbols\" lists them.")
        if p is not None:
            kept = _keep(sch_path)
            sch.save(sch_path)
            with st.lock(p["id"]):
                p2 = st.load(p["id"])
                st.decide(p2, "board", f"Schematic {sch_path.name} changed: {len(done)} operation(s).")
                st.save(p2)
            target = sch_path
        else:
            # a schematic that exists is never written over: the result goes to out= (or <name>-edited.kicad_sch)
            target = _out_path(sch_path, out, "edited", overwrite) if sch_path.exists() else sch_path
            kept = None
            target.parent.mkdir(parents=True, exist_ok=True)
            sch.save(target)
        check = Schematic.load(target).erc()
        return {"file": str(target), "done": done, "kept_previous": kept, "erc": {k: check[k] for k in ("by", "headline", "total", "counts", "rows")}}
    # to_board: the netlist as a new board with footprints from the person's KiCad libraries
    if not size or len(size) != 2:
        raise _err("to_board needs size=[width, depth] in mm for the new board's outline.")
    if p is not None:
        raise _err("This design already has a board.", "to_board makes a new board from a schematic file: give file= and "
                   "out=, then board_import the result.", 409)
    nl = sch.netlist()
    dirs = [Path(x).expanduser() for x in (libraries or []) if Path(x).expanduser().is_dir()] + library_dirs(cfg, "footprints")
    doc, info = from_netlist(nl, (float(size[0]), float(size[1])), dirs)
    target = Path(out).expanduser().resolve() if out else pcb
    if target.exists() and not overwrite:
        raise _err(f"{target.name} already exists.", "Give out= another path, or overwrite=True.", 409)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(target)
    return {"file": str(target), **info, "footprint_folders": [str(d) for d in dirs],
            "next": "board_place places the parts; board_route routes them; board_import makes the enclosure around the board."}


# ---- placement -----------------------------------------------------------------------------------------------------------
def _enclosure(st, p: dict) -> tuple[dict | None, dict | None]:
    try:
        r = st.rev(p)
        rec = st.recipe(p)
        if not hasattr(rec, "board_layout"):
            return None, None
        v = rec.validate(r["values"])
        return rec.board_layout(v), dict(v)
    except Exception:                                    # noqa: BLE001 - a design without the enclosure's layout
        return None, None


def place(st, project: str | None = None, file: str | None = None, out: str | None = None, fixed: dict | None = None,
          keepouts: list | None = None, max_height: float | None = None, rotate: bool = True, only: list | None = None,
          check_only: bool = False, overwrite: bool = False) -> dict:
    if project:
        p, board, pcb, _sch = _project_files(st, project)
        layout, values = _enclosure(st, p)
    elif file:
        p, pcb = None, _file(file, ".kicad_pcb")
        board = api.read(pcb)
        layout = values = None
    else:
        raise _err("Give project= (a design with a board) or file= (a .kicad_pcb).")
    doc = Pcb.load(pcb)
    cons = place_mod.constraints(doc, board, layout, values, fixed, keepouts, max_height)
    if check_only:
        return {"file": str(pcb), "constraints": cons.describe(), "check": place_mod.check(doc, cons)}
    res = place_mod.place(doc, cons, rotate=rotate, only=only)
    cleared = 0
    if res["moved"]:
        refs = {m["ref"] for m in res["moved"]}
        nets = {pd["net"] for f in doc.footprints() if f["ref"] in refs for pd in f["pads"] if pd["net"] > 0}
        cleared = doc.clear_routes(nets) if nets else 0
    if p is not None:
        kept = _keep(pcb)
        doc.save(pcb)
        new = _refresh(st, p, pcb, board, f"Board parts placed: {len(res['moved'])} moved (Form Studio placement).")
        res["changes"] = api.changes(board, new)
        target = pcb
    else:
        target = _out_path(pcb, out, "placed", overwrite)
        doc.save(target)
        kept = None
    res.update({"file": str(target), "kept_previous": kept, "tracks_removed": cleared})
    if cleared:
        res["note"] = (f"{cleared} tracks and vias of the nets of the moved parts were removed: they no longer reach their "
                       "pads. board_route routes them again.")
    if p is not None and res["moved"]:
        res["next"] = 'board_check(what="fit") measures the moved parts against the enclosure on the solids; board_route routes.'
    return res


# ---- routing -------------------------------------------------------------------------------------------------------------
def _kicad_drc(st, pcb: Path, use: bool) -> dict:
    if not use:
        return {"ran": False, "why": "Not asked for (kicad=False)."}
    ks = kicad_cli.status(st.cfg)
    if not ks["available"]:
        return {"ran": False, "why": f"{ks['reason']} The result above is Form Studio's own geometric check, not KiCad's "
                                     f"DRC. To run KiCad's: {ks['install']['how']}."}
    return kicad_cli.drc(ks["path"], pcb, pcb.parent / "kicad" / ("drc-" + _sha(pcb)[:16]))


def route(st, project: str | None = None, file: str | None = None, out: str | None = None, engine: str = "form",
          nets: list | None = None, skip: list | None = None, layers: list | None = None, pitch: float | None = None,
          strategy: str = "auto", algorithm: str = "auto", keep_existing: bool = True, vias: bool = True,
          smooth: bool = True, passes: int = 20, time_limit: float = 120.0, kicad: bool = True,
          overwrite: bool = False) -> dict:
    eng = (engine or "form").lower()
    if eng not in ("form", "freerouting"):
        raise _err(f"Unknown engine “{engine}”.", "form (Form Studio's router) or freerouting (yours, when installed).")
    if project:
        p, board, pcb, _sch = _project_files(st, project)
    elif file:
        p, board, pcb = None, None, _file(file, ".kicad_pcb")
    else:
        raise _err("Give project= (a design with a board) or file= (a .kicad_pcb).")
    doc = Pcb.load(pcb)
    try:
        if eng == "form":
            res = route_mod.route(doc, pitch=pitch, layers=tuple(layers or ("F.Cu", "B.Cu")), nets=nets, skip=skip,
                                  strategy=strategy, algorithm=algorithm, keep_existing=keep_existing, vias=vias,
                                  smooth=smooth, time_limit=float(time_limit), check=False)
        else:
            if not keep_existing:
                doc.clear_routes()
            work = (pcb.parent / "freerouting") if p is not None else (Path(out).expanduser().resolve().parent if out else pcb.parent)
            res = specctra.run(doc, work, st.cfg, passes=passes, nets=nets)
            if not res["ran"]:
                return {"file": str(pcb), "changed": False, **res, "next": 'engine="form" routes with Form Studio\'s own router.'}
    except ValueError as e:
        raise _err(str(e))
    if p is not None:
        kept = _keep(pcb)
        doc.save(pcb)
        _refresh(st, p, pcb, board, f"Board routed by {res['by']}: {res.get('segments', 0)} segments, {res.get('vias', 0)} vias.")
        target = pcb
    else:
        target = _out_path(pcb, out, "routed", overwrite)
        doc.save(target)
        kept = None
    # the checks read the file as it was written, not the router's memory of it
    written = Pcb.load(target)
    res["check"] = drc_mod.check(written)
    res["kicad_drc"] = _kicad_drc(st, target, kicad)
    un = res["check"]["unconnected_total"]
    res.update({"file": str(target), "kept_previous": kept, "changed": True,
                "checked_by": [drc_mod.BY] + ([res["kicad_drc"]["by"]] if res["kicad_drc"].get("ran") else []),
                "headline": (f"{res.get('segments', 0)} segments and {res.get('vias', 0)} vias by {res['by']}; " +
                             res["check"]["headline"] + ("; KiCad DRC: " + str(res["kicad_drc"]["total"]) + " findings"
                                                         if res["kicad_drc"].get("ran") else "; KiCad DRC not run")),
                "complete": un == 0 and (res.get("complete", True) if eng == "form" else True)})
    return res


def copper_check(st, p: dict, kicad: bool = False) -> dict:
    _p, _board, pcb, _sch = _project_files(st, p["id"])
    res = drc_mod.check(Pcb.load(pcb))
    res["file"] = pcb.name
    if kicad:
        res["kicad_drc"] = _kicad_drc(st, pcb, True)
    return res


# ---- the Bench -----------------------------------------------------------------------------------------------------------
def _is_kicad(ctx) -> bool:
    return api._has_board(ctx) and (ctx.p.get("board") or {}).get("format") == "kicad_pcb"


def _has_sch(ctx) -> bool:
    b = ctx.p.get("board") or {}
    return _is_kicad(ctx) and (api.board_dir(ctx.st, ctx.p["id"]) / b.get("file", "")).with_suffix(".kicad_sch").is_file()


def _key(name):
    def key(ctx):
        from ..studio import H
        extra = ""
        if name == "sch":
            f = (api.board_dir(ctx.st, ctx.p["id"]) / (ctx.p.get("board") or {}).get("file", "x")).with_suffix(".kicad_sch")
            extra = _sha(f) if f.is_file() else ""
        if name == "place":
            extra = ctx.keys["geometry"]
        return H("board-k2", name, VERSION, (ctx.p.get("board") or {}).get("key"), extra)
    return key


def _copper_run(ctx):
    r = copper_check(ctx.st, ctx.p)
    return {"headline": r["headline"], "evidence": "computed (Form Studio's own check; not KiCad's DRC)", "data": r}


def _place_run(ctx):
    r = place(ctx.st, project=ctx.p["id"], check_only=True)
    return {"headline": r["check"]["headline"], "evidence": "computed (courtyards in the plane)", "data": r}


def _sch_run(ctx):
    r = schematic(ctx.st, "erc", project=ctx.p["id"], kicad=False)
    return {"headline": r["form"]["headline"], "evidence": "computed (Form Studio's ERC subset; not KiCad's ERC)", "data": r}


def register_studies(register) -> None:
    from ..studies import APPLIES, Study
    APPLIES["board_kicad"] = (_is_kicad, "Only for a design whose board is a KiCad file.")
    APPLIES["board_sch"] = (_has_sch, "Only for a design whose board has its schematic (.kicad_sch).")
    register(Study("board.copper", "study", "Board copper",
                   "Form Studio's own geometric check of the board's tracks, vias and pads: clearances, the board "
                   "edge, keep-outs and the connections not yet made. Not KiCad's DRC.", "computed", run=_copper_run,
                   key=_key("copper"), needs=("board_kicad",), inputs=("the board file", "its net classes"), app="board",
                   tool="board_route", order=78))
    register(Study("board.placement", "study", "Board placement",
                   "Every part against the enclosure's constraints: connectors on their openings, the standoffs and "
                   "screw heads, the room under the lid, the board's keep-outs.", "computed", run=_place_run,
                   key=_key("place"), needs=("board_kicad",), inputs=("the board file", "geometry"), app="board",
                   tool="board_place", order=79))
    register(Study("board.schematic", "study", "Schematic checks",
                   "Form Studio's electrical checks of the schematic: pins left open, power pins nothing drives, "
                   "outputs that fight. A subset; not KiCad's ERC.", "computed", run=_sch_run, key=_key("sch"),
                   needs=("board_sch",), inputs=("the schematic file",), app="board", tool="board_schematic", order=80))
