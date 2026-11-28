"""The board and enclosure loop for a project: import a board, make or keep its enclosure, check both, make fab files.

    imp = import_board(st, "board.kicad_pcb")                       # a new design: the enclosure around the board
    imp = import_board(st, "board.kicad_pcb", project=pid)          # the board changed: the checks say what moved
    fit(st, p)                                                      # the board against the enclosure (computed)
    checks(st, p, fabs=["jlcpcb"])                                  # KiCad's DRC/ERC (when installed) and fab limits
    fab_files(st, p, kinds=["gerbers", "drill", "pos", "bom", "step"])

The board's files are copied into the project (<project>/board/), never changed where they are. The board model is
<project>/board/board.json; p["board"] records the file, its SHA-256 and when it came in. The Bench lists "Board
and enclosure", "Board checks" and "Board fab files" for a design with a board.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import enclosure, fabs as fabs_mod, kicad_cli, model

VERSION = 1
FORMATS = {".kicad_pcb": "kicad_pcb", ".emn": "idf"}
STEP = (".step", ".stp")


def _err(msg, hint="", status=400):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status)


def read(path: str | Path, origin=None) -> dict:
    """The board model of a board file. origin: the frame's origin in the file's coordinates (a re-import keeps the
    first import's, so a part that moved reads as moved)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise _err(f"File not found: {p}", "Give the absolute path of a .kicad_pcb or an IDF .emn board file.", 404)
    kind = FORMATS.get(p.suffix.lower())
    try:
        if kind == "kicad_pcb":
            from . import kicad
            return kicad.read(p, origin=origin)
        if kind == "idf":
            from . import idf
            return idf.read(p, origin=origin)
    except ValueError as e:
        raise _err(f"Could not read {p.name}: {e}", "Check that the file is a complete board export.")
    if p.suffix.lower() in STEP:
        raise _err("A board STEP gives heights, not the board itself.",
                   "Give the .kicad_pcb (or IDF .emn) as file and the STEP as step=.")
    raise _err(f"{p.name} is not a board file Form Studio reads.", "KiCad .kicad_pcb, or IDF 3.0 .emn (with its .emp).")


def board_dir(st, pid: str) -> Path:
    return st.dir(pid) / "board"


def load(st, p: dict) -> dict | None:
    f = board_dir(st, p["id"]) / "board.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def board_key(board: dict) -> str:
    from ..studio import H
    return H("board", VERSION, json.dumps(board, sort_keys=True, default=str))


def _apply(board: dict, heights: dict | None, connectors: dict | None, height_source: str) -> list:
    notes = []
    if connectors:
        board["connector_overrides"] = {k: dict(v) for k, v in connectors.items()}
    if heights:
        bad = model.set_heights(board, heights, height_source)
        if bad:
            notes.append(f"Not on the board, so not used: {', '.join(bad)}.")
    board["connectors"] = model.connectors(board, board.get("connector_overrides"))
    return notes


def _step_heights(st, board: dict, step: Path, out: Path | None) -> dict:
    r = st._k("board_step", timeout=300, path=str(step), board=board, z0=0.0, out=str(out) if out else None)
    return r


def import_board(st, file: str, project: str | None = None, name: str = "", step: str | None = None,
                 heights: dict | None = None, connectors: dict | None = None, regenerate: bool = False,
                 expect_head: int | None = None, lid_screw: float = 3.0, purpose: str | None = None,
                 use_kicad_step: bool = False) -> dict:
    """Read a board and bring it into a project. Without project: a new design, the enclosure around the board.
    With project: the board replaces the project's board; the enclosure stays as it is unless regenerate=True, so
    its checks show what the new board no longer fits."""
    src = Path(file).expanduser().resolve()
    board = read(src)
    notes = list(board["notes"])
    prev = None
    if project:
        p0 = st.load(project)
        prev = load(st, p0)
        if prev and prev.get("origin") and board["format"] == prev.get("format"):
            # the same frame as before (where the old board's centre was), so a moved part reads as moved
            board = read(src, origin=prev["origin"])
    step_path = Path(step).expanduser().resolve() if step else None
    tmp_step = None
    if step_path is None and use_kicad_step:
        exe = kicad_cli.find(st.cfg)
        if not exe:
            raise _err("KiCad is not installed, so it cannot export the board STEP.", kicad_cli.INSTALL["how"])
        tmp_dir = st.root / ".cache" / "board-step" / board["sha256"][:16]
        r = kicad_cli.export(exe, src, "step", tmp_dir)
        if not r["ok"]:
            raise _err("KiCad could not export the board STEP.", r.get("log", "")[-400:])
        step_path = tmp_step = Path(r["files"][0])
    hs = {}
    if step_path:
        if not step_path.is_file():
            raise _err(f"File not found: {step_path}", "Give the board STEP KiCad exported (File > Export > STEP).")
        r = _step_heights(st, board, step_path, None)
        hs = r["heights"]
        notes += _apply(board, hs, None, f"measured on the board STEP {step_path.name} (computed)")
    notes += _apply(board, heights, connectors, "given by the person")
    board["imported"] = {"from": src.name, "ts": time.time(), "step": step_path.name if step_path else None,
                         "step_heights": len(hs)}

    created = False
    if not project:
        text, _defaults = enclosure.source(board, name or f"Enclosure for {src.stem}", lid_screw)
        p = st.create_design(name or f"Enclosure for {src.stem}", text, brief=f"An enclosure for the board {src.name}.",
                             purpose=purpose)
        created = True
    else:
        p = st.load(project)
        if regenerate:
            text, _defaults = enclosure.source(board, p["name"], lid_screw)
            p = st.update_design(p, text, note=f"Enclosure made again for the board {src.name}", origin="agent",
                                 expect_head=expect_head)
    d = board_dir(st, p["id"])
    d.mkdir(parents=True, exist_ok=True)
    for f in [src] + [src.with_suffix(s) for s in (".kicad_pro", ".kicad_sch", ".emp")]:
        if f.is_file():
            shutil.copyfile(f, d / f.name)
    if step_path:
        shutil.copyfile(step_path, d / step_path.name)
    if tmp_step:
        shutil.rmtree(tmp_step.parent, ignore_errors=True)
    tmp = d / "board.json.tmp"
    tmp.write_text(json.dumps(board, indent=1, default=str), encoding="utf-8")
    from .. import fsutil
    fsutil.replace(tmp, d / "board.json")
    with st.lock(p["id"]):
        p = st.load(p["id"])
        p["board"] = {"file": src.name, "format": board["format"], "sha256": board["sha256"], "ts": time.time(),
                      "step": step_path.name if step_path else None, "key": board_key(board)}
        st.decide(p, "board", f"Board {src.name} " + ("brought in" if created or not prev else "brought in again") +
                  f": {board['size'][0]:g} × {board['size'][1]:g} mm, {len(board['components'])} parts, "
                  f"{len(board['mounting_holes'])} mounting holes (read from the file).")
        st.save(p)
    companion = _companion(st, p, board, step_path)
    out = {"project": p["id"], "head": p["head"], "created": created, "board": model.summary(board),
           "connectors": [{k: c[k] for k in ("ref", "side_name", "side_from", "plug")} for c in board["connectors"]],
           "missing_heights": model.missing_heights(board), "notes": notes, "companion": companion}
    if prev and not regenerate:
        out["changes"] = changes(prev, board)
    if out["missing_heights"]:
        out["next"] = ("Some parts have no height, so they are not checked against the lid: give heights={ref: mm}, "
                       "a board STEP (step=), or use_kicad_step=True when KiCad is installed.")
    return out


def changes(old: dict, new: dict, tol: float = 0.01) -> list:
    """What moved between two readings of a board (computed on the two board models, both in the same frame)."""
    out = []
    if abs(old["size"][0] - new["size"][0]) > tol or abs(old["size"][1] - new["size"][1]) > tol:
        out.append({"what": "outline", "was": old["size"], "now": new["size"], "text":
                    f"Board size {old['size'][0]:g} × {old['size'][1]:g} → {new['size'][0]:g} × {new['size'][1]:g} mm."})
    oc = {c["ref"]: c for c in old["components"]}
    for c in new["components"]:
        o = oc.pop(c["ref"], None)
        if o is None:
            out.append({"what": "part", "ref": c["ref"], "text": f"{c['ref']} is new."})
            continue
        dx, dy = c["x"] - o["x"], c["y"] - o["y"]
        if (dx * dx + dy * dy) ** 0.5 > tol or abs((c["rot"] or 0) - (o["rot"] or 0)) > 0.01:
            out.append({"what": "part", "ref": c["ref"], "moved_mm": [round(dx, 4), round(dy, 4)],
                        "text": f"{c['ref']} moved {dx:+.2f}, {dy:+.2f} mm" +
                                (f" and turned {c['rot'] - o['rot']:+g}°" if abs((c['rot'] or 0) - (o['rot'] or 0)) > 0.01 else "") + "."})
        oh, nh = (o.get("height") or {}).get("value"), (c.get("height") or {}).get("value")
        if oh != nh:
            out.append({"what": "height", "ref": c["ref"], "text": f"{c['ref']} height {oh} → {nh} mm."})
    for ref in oc:
        out.append({"what": "part", "ref": ref, "text": f"{ref} is gone."})
    om = sorted((round(h["x"], 2), round(h["y"], 2), h["screw"]) for h in old["mounting_holes"])
    nm = sorted((round(h["x"], 2), round(h["y"], 2), h["screw"]) for h in new["mounting_holes"])
    if om != nm:
        out.append({"what": "mounting_holes", "text": f"Mounting holes changed: {om} → {nm}."})
    return out


def _companion(st, p: dict, board: dict, step: Path | None) -> dict | None:
    """The board drawn beside the design (a reference part in the enclosure's frame): the board STEP moved into
    place, or Form Studio's plain board model (slab and part boxes) when no STEP was given."""
    try:
        r = st.rev(p)
        rec = st.recipe(p)
        if not hasattr(rec, "board_layout"):
            return None
        z0 = rec.board_layout(rec.validate(r["values"]))["board_z"]
    except Exception:                                    # noqa: BLE001 - the drawing is a convenience, never a failure
        return None
    out = board_dir(st, p["id"]) / "board-in-enclosure.step"
    try:
        if step:
            st._k("board_step", timeout=300, path=str(step), board=board, z0=z0, out=str(out))
            what = f"the board STEP {step.name}, moved into the enclosure"
        else:
            st._k("board_model", timeout=300, board=board, z0=z0, out=str(out))
            what = "Form Studio's plain board model: the slab and a box per part of known height"
        st.import_reference(p, out, name="board.step")
        return {"file": "board.step", "what": what, "board_z": z0}
    except Exception as e:                               # noqa: BLE001
        return {"error": f"The board could not be drawn beside the design: {e}"}


# ---- checks --------------------------------------------------------------------------------------------------------
def _need(st, p: dict) -> dict:
    b = load(st, p)
    if b is None:
        raise _err("This design has no board.", "board_import(file=..., project=...) brings one in.", 409)
    return b


def fit(st, p: dict) -> dict:
    """The board as it is now in the project against the head revision's enclosure, measured on the solids."""
    from ..studio import H
    board = _need(st, p)
    r = st.rev(p)
    gk = st.keys(p)["geometry"]
    key = H("board-fit", VERSION, gk, board_key(board))
    cache = board_dir(st, p["id"]) / f"fit-{key}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    raw = st._k("board_fit", timeout=600, key=gk, recipe_id=st.rid(p), values=r["values"], p=p, board=board)
    rows = raw["rows"]
    bad = sum(x["status"] == "FAIL" for x in rows)
    warn = sum(x["status"] == "WARN" for x in rows)
    nc = sum(x["status"] == "NOT CHECKED" for x in rows)
    made_for = None
    try:
        made_for = st.recipe(p).board_layout(st.recipe(p).validate(r["values"])).get("board_sha256")
    except Exception:                                    # noqa: BLE001
        pass
    out = {"rev": r["n"], "board": board["file"], "board_sha256": board["sha256"], "rows": rows,
           "ok": bad == 0, "evidence": "computed (B-rep)", "layout": raw.get("layout"),
           "headline": (f"{bad} do not fit" if bad else "the board fits") +
                       (f", {warn} to look at" if warn else "") + (f", {nc} not checked" if nc else "")}
    if made_for and not board["sha256"].startswith(made_for):
        out["made_for_other_board"] = True
        out["note"] = ("The enclosure was made for an earlier version of this board; these checks measure it against "
                       "the board as it is now. board_import(..., regenerate=True) makes it again.")
    cache.write_text(json.dumps(out, default=str), encoding="utf-8")
    return out


def _kicad_files(st, p: dict, board: dict) -> tuple[Path | None, Path | None]:
    d = board_dir(st, p["id"])
    pcb = d / board["file"] if board["format"] == "kicad_pcb" else None
    sch = (d / board["file"]).with_suffix(".kicad_sch") if pcb else None
    return (pcb if pcb and pcb.is_file() else None), (sch if sch and sch.is_file() else None)


def checks(st, p: dict, fabs: list[str] | None = None, kicad: bool = True) -> dict:
    """KiCad's own DRC and ERC when kicad-cli is installed (its report, as KiCad wrote it), and the fabs' published
    limits against the board's sizes."""
    board = _need(st, p)
    out = {"board": board["file"], "fab": fabs_mod.check(board, fabs)}
    ks = kicad_cli.status(st.cfg)
    out["kicad"] = ks
    if not kicad:
        out["drc"] = out["erc"] = {"ran": False, "why": "Not asked for (kicad=False)."}
        return _headline(out)
    if not ks["available"]:
        why = f"{ks['reason']} Install it from {ks['install']['how']} to run KiCad's own DRC and ERC; nothing is run in its place."
        out["drc"] = out["erc"] = {"ran": False, "why": why}
        return _headline(out)
    pcb, sch = _kicad_files(st, p, board)
    d = board_dir(st, p["id"]) / "kicad" / board["sha256"][:16]
    out["drc"] = kicad_cli.drc(ks["path"], pcb, d) if pcb else {"ran": False, "why": "The board is not a KiCad file."}
    out["erc"] = kicad_cli.erc(ks["path"], sch, d) if sch else {
        "ran": False, "why": "No schematic (.kicad_sch) beside the board, so there is no ERC to run."}
    return _headline(out)


def _headline(out: dict) -> dict:
    parts = []
    for k in ("drc", "erc"):
        r = out[k]
        if r.get("ran"):
            parts.append(f"{r['by']}: {r['total']} " + ("finding" if r["total"] == 1 else "findings"))
        else:
            parts.append(f"KiCad {k.upper()} not run")
    fb = [f"{f['fab']} {f['headline']}" for f in out["fab"]["fabs"]]
    out["headline"] = " · ".join(parts + fb)
    out["note"] = ("No findings from KiCad is KiCad's result, not a manufacturability approval; fab limits are the fabs' "
                   "published claims, quoted with their page and date.")
    return out


def fab_files(st, p: dict, kinds: list[str] | None = None) -> dict:
    """Gerbers, drill files, pick-and-place, BOM and the board STEP through the person's KiCad, into
    <project>/board/fab/<board hash>/. Without KiCad only the board STEP can be made, from Form Studio's plain model."""
    board = _need(st, p)
    kinds = list(kinds or ["gerbers", "drill", "pos", "bom", "step"])
    for k in kinds:
        if k not in kicad_cli.KINDS:
            raise _err(f"Unknown fab file “{k}”.", ", ".join(kicad_cli.KINDS))
    out_dir = board_dir(st, p["id"]) / "fab" / board["sha256"][:16]
    ks = kicad_cli.status(st.cfg)
    res = {"board": board["file"], "folder": str(out_dir), "kicad": ks, "files": {}}
    pcb, sch = _kicad_files(st, p, board)
    for k in kinds:
        if ks["available"] and pcb:
            res["files"][k] = kicad_cli.export(ks["path"], pcb, k, out_dir, sch)
            res["files"][k]["by"] = f"KiCad ({ks['version']})"
        elif k == "step":
            out_dir.mkdir(parents=True, exist_ok=True)
            f = out_dir / (Path(board["file"]).stem + "-form-model.step")
            st._k("board_model", timeout=300, board=board, z0=0.0, out=str(f))
            res["files"][k] = {"kind": k, "ok": True, "files": [str(f)], "by": "Form Studio",
                               "note": "Form Studio's plain board model (the slab and a box per part of known height), "
                                       "not KiCad's STEP: measure the real parts before designing to them."}
        else:
            res["files"][k] = {"kind": k, "ok": False, "files": [],
                               "why": (f"{ks['reason']} {k} files come from KiCad: install it from {ks['install']['how']}."
                                       if not ks["available"] else "The board is not a KiCad file.")}
    made = sum(1 for v in res["files"].values() if v.get("ok"))
    res["headline"] = f"{made} of {len(kinds)} made" + ("" if ks["available"] else " (KiCad is not installed)")
    return res


# ---- the Bench (form/studies.py) -----------------------------------------------------------------------------------
def _has_board(ctx) -> bool:
    return bool(ctx.p.get("board")) and (board_dir(ctx.st, ctx.p["id"]) / "board.json").is_file()


def _fit_key(ctx):
    from ..studio import H
    return H("board-fit", VERSION, ctx.keys["geometry"], (ctx.p.get("board") or {}).get("key"))


def _fit_run(ctx):
    r = fit(ctx.st, ctx.p)
    return {"headline": r["headline"], "evidence": "computed", "data": r}


def _checks_key(ctx):
    from ..studio import H
    ks = kicad_cli.status(ctx.st.cfg)
    return H("board-checks", VERSION, (ctx.p.get("board") or {}).get("key"), ks.get("version"), fabs_mod.READ)


def _checks_run(ctx):
    r = checks(ctx.st, ctx.p)
    files = [x["report"] for x in (r["drc"], r["erc"]) if x.get("report")]
    return {"headline": r["headline"], "evidence": "KiCad's own report; rule (fab pages, read " + fabs_mod.READ + ")",
            "files": files, "data": r}


def _fab_run(ctx):
    r = fab_files(ctx.st, ctx.p)
    files = [f for v in r["files"].values() for f in v.get("files", [])]
    return {"headline": r["headline"], "evidence": "made by KiCad" if r["kicad"]["available"] else "Form Studio's board model",
            "files": files, "data": r}


def register_studies(register) -> None:
    from ..studies import APPLIES, Study
    APPLIES["board"] = (_has_board, "Only for a design with a board (board_import).")
    register(Study("board.fit", "study", "Board and enclosure",
                   "The board against its enclosure on the solids: walls, standoffs, connector plugs, part heights "
                   "under the lid, screwdriver access.", "computed", run=_fit_run, key=_fit_key, needs=("board",),
                   inputs=("geometry", "the board file"), app="board", tool="board_check", order=76))
    register(Study("board.checks", "study", "Board checks",
                   "KiCad's own DRC and ERC through the person's kicad-cli, and the board against JLCPCB, PCBWay and "
                   "OSH Park's published limits.", "KiCad's report; rule (fab pages)", run=_checks_run, key=_checks_key,
                   needs=("board",), inputs=("the board file", "KiCad's version", "the fab pages' date"), app="board",
                   tool="board_check", order=77))
    register(Study("doc.board_fab", "document", "Board fab files",
                   "Gerbers, drill files, pick-and-place, BOM and the board STEP from the person's KiCad.",
                   "made by KiCad", run=_fab_run, key=_checks_key, needs=("board",),
                   inputs=("the board file", "KiCad's version"), app="board", tool="board_fab", order=30))
