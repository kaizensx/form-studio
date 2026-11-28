"""Manufacturability: every rule of the process a design names, measured on its exact solid, drawn on the part,
with a fix written into the design's source and proved by checking again.

Processes (one rule table each, form/dfm/rules/<id>.toml, every limit with its source):

    cnc          3-, 4- and 5-axis (3+2) milling: tool access per setup with a flat end mill of a stated diameter
                 (and holder), internal corners against the tool and the cavity depth, tool reach, thin walls,
                 holes (depth, size, drill series), the fewest setups
    injection    two-plate moulding: a proposed pull direction and parting line, undercuts with the side action or
                 lifter each needs, draft per face, wall range per resin, projected area, depth, clamp tonnage
    fdm sla sls mjf lpbf
                 printing: thinnest wall, overhangs from level (not for powder beds), smallest hole, enclosed
                 voids with escape holes, the machine's build volume
    sheet_metal  measured by form/sheet (the unfold, folded back), judged here with the same rule format

    from form import dfm
    r = dfm.check(st, p, "cnc", {"tool_d": 6, "material": "metal"})   # rows, findings, verdict, overlay file
    f = dfm.apply_fix(st, p, "cnc", "cnc.corner_tool", {"tool_d": 6, "material": "metal"})
    #   proposes the edit, builds it without saving and checks it (preview), then saves it as a revision through
    #   edit_design and checks the new head again; claimed fixed only when that second check passes the rule

Measuring runs in the kernel worker (op "dfm", form/dfm/measure.py); rules, verdicts and fixes are plain Python
here. A result is stored under artifacts/dfm/ keyed by the geometry key, the process, the rule table's hash and the
options, so a newer revision or an edited rule makes it stale by construction.

Overlay for the viewport: artifacts/dfm/overlay-<key>.json, format "form-dfm-overlay/1" (see `overlay`), the
same fields an analysis map has (positions, indices, values, colors as base64) plus per-face status, markers and the
parting line, so the window can draw it with the map renderer.
"""
from __future__ import annotations

import base64
import json
import time

import numpy as np

from . import rules

VERSION = 1
OVERLAY_FORMAT = "form-dfm-overlay/1"
ALIASES = {"moulding": "injection", "molding": "injection", "injection_moulding": "injection", "injection_molding": "injection",
           "im": "injection", "resin": "sla", "msla": "sla", "dlp": "sla", "dmls": "lpbf", "slm": "lpbf", "metal": "lpbf",
           "pbf": "lpbf", "fff": "fdm", "print": "fdm", "mill": "cnc", "milling": "cnc", "machining": "cnc",
           "sheet": "sheet_metal", "sheetmetal": "sheet_metal", "multi_jet_fusion": "mjf"}
COLOURS = {"fail": (255, 111, 81), "warn": (233, 184, 96), "not_checked": (134, 168, 255), "pass": (216, 211, 200),
           "n/a": (216, 211, 200), "info": (216, 211, 200)}
CODE = {"pass": 0, "n/a": 0, "info": 0, "warn": 1, "fail": 2, "not_checked": 3}


def _err(msg, hint="", status=400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


def H(*a) -> str:
    from ..studio import H as _h
    return _h(*a)


def process_id(name) -> str:
    s = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    s = ALIASES.get(s, s)
    if s not in rules.processes():
        raise _err(f"Unknown process “{name}”.", "Processes: " + ", ".join(rules.processes()) + ".")
    return s


def default_process(p: dict) -> str | None:
    """The process the design names (project["process"]), or FDM for a design made to be printed."""
    proc = (p.get("process") or "").strip()
    if proc in ("cnc", "injection", "sheet_metal"):
        return proc
    if proc in rules.processes():
        return proc
    if p.get("purpose") == "print":
        return "fdm"
    return None


def _clean(options: dict | None) -> dict:
    o = {k: v for k, v in (options or {}).items() if v not in (None, "", [])}
    for k in ("tool_d", "flute_l", "holder_d", "cavities"):
        if k in o:
            o[k] = float(o[k])
    if "axes" in o:
        o["axes"] = int(o["axes"])
        if o["axes"] not in (3, 4, 5):
            raise _err("axes is 3, 4 or 5.")
    for k in ("up", "pull", "machine"):
        if k in o and isinstance(o[k], str) and o[k] != "auto":
            try:
                o[k] = [float(x) for x in o[k].replace("[", "").replace("]", "").split(",")]
            except ValueError:
                raise _err(f"{k} is three numbers, x,y,z.")
    if "textured" in o:
        o["textured"] = o["textured"] in (True, 1, "1", "true", "yes", "on")
    return o


def options_for(st, p: dict, process: str, options: dict | None) -> dict:
    """The options a check runs with: the process table's defaults, then what was given. For FDM with no machine
    stated, the design's printer bed when printing is set up (named as such)."""
    t = rules.table(process)
    o = {**(t["process"].get("defaults") or {}), **_clean(options)}
    if process == "fdm" and not o.get("machine") and st is not None and p.get("purpose") == "print":
        try:
            env = st.printer_env(p)
            o["machine"] = [float(x) for x in env["envelope"]]
            o["machine_from"] = f"your printer ({env.get('name') or 'studio.toml'})"
        except Exception:                          # noqa: BLE001 - no printer: the size rule says not checked
            pass
    return o


def _measure_key(gk: str, process: str, options: dict) -> str:
    from . import measure
    o = {k: v for k, v in options.items() if k not in ("overrides", "machine_from")}
    return H("dfm-measure", VERSION, measure.VERSION, gk, process, rules.digest(process), rules.spec(process, o), o)


def result_key(gk: str, process: str, options: dict) -> str:
    return H("dfm", VERSION, _measure_key(gk, process, options), rules.overrides_key(options))


def _dir(st, p):
    return st.dir(p["id"]) / "artifacts" / "dfm"


def _write(path, data):
    from .. import fsutil
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    fsutil.replace(tmp, path)


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def measured(st, p: dict, process: str, options: dict, rid: str | None = None, values: dict | None = None,
             rev: int | None = None, force: bool = False) -> tuple[dict, str]:
    """The kernel's measurements of a revision (or of a candidate source rid with values, for a preview)."""
    if rid is None:
        r = st.rev(p, rev)
        rid, values = st.rid(p, r["n"]), r["values"]
        gk = st.keys(p, r["n"])["geometry"]
    else:
        gk = st.geometry_key(p, rid, values)
    mk = _measure_key(gk, process, options)
    path = _dir(st, p) / f"measure-{mk}.json"
    if not force:
        got = _read(path)
        if got is not None:
            return got, gk
    o = {k: v for k, v in options.items() if k not in ("overrides", "machine_from")}
    out = st._k("dfm", timeout=600, key=gk, recipe_id=rid, values=values, process=process,
                spec=rules.spec(process, o), options=o, p=p)
    out["measured_at"] = time.time()
    _write(path, out)
    return out, gk


def _tonnage(meas: dict, process: str, options: dict) -> None:
    if process != "injection":
        return
    pa = (meas.get("measures") or {}).get("projected_in2")
    rule = next((r for r in rules.table(process)["rules"] if r["id"] == "injection.tonnage"), None)
    if not pa or pa.get("state") != "measured" or rule is None:
        return
    it = pa["items"][0]
    cav = float(options.get("cavities") or 1)
    f = rule["factor"]
    a_in2 = it["value"] * cav
    err_in2 = it.get("error_mm2", 0) / 645.16 * cav
    t = {k: round(a_in2 * f[k], 3) for k in ("low", "start", "high")}
    meas["measures"]["tonnage_t"] = {
        "state": "measured", "method": f"projected area {a_in2:.3f} in² (± {err_in2:.3f}) × {int(cav)} cavit"
        f"{'y' if cav == 1 else 'ies'} × {f['low']:g} to {f['high']:g} tons/in² (start {f['start']:g}); the runner is not included.",
        "items": [{"value": t["start"], "range_t": [t["low"], t["high"]],
                   "range_kN": [round(t["low"] * 8.896443, 1), round(t["high"] * 8.896443, 1)],
                   "start_kN": round(t["start"] * 8.896443, 1), "projected_in2": round(a_in2, 4),
                   "projected_error_in2": round(err_in2, 4)}]}


def _headline(res: dict) -> str:
    rows = res["rows"]
    n = {s: sum(r["status"] == s for r in rows) for s in ("fail", "warn", "not_checked", "pass")}
    bits = [f"{n['fail']} fail" if n["fail"] else "", f"{n['warn']} warn" if n["warn"] else "",
            f"{n['not_checked']} not checked" if n["not_checked"] else ""]
    bits = [b for b in bits if b]
    return f"{res['label']}: {res['verdict']}" + (f" ({', '.join(bits)})" if bits else f" ({n['pass']} rules pass)")


def evaluate(st, p: dict, process: str, options: dict, meas: dict, gk: str, rev: int | None) -> dict:
    t = rules.table(process)
    _tonnage(meas, process, options)
    ev = rules.evaluate(process, meas, options)
    data = dict(meas.get("data") or {})
    res = {"project": p["id"], "rev": rev, "process": process, "label": t["process"].get("label", process),
           "verdict": ev["verdict"], "rows": ev["rows"], "findings": ev["findings"], "data": data,
           "geometry_key": gk, "key": result_key(gk, process, options),
           "options": {k: v for k, v in options.items() if k != "overrides"},
           "overrides": options.get("overrides") or {},
           "evidence": t["process"].get("evidence", "computed (B-rep)"),
           "not_judged": t["process"].get("not_judged", ""), "machine_note": t["process"].get("machine_note"),
           "samples": meas.get("samples"), "spacing_mm": meas.get("spacing_mm"), "seconds": meas.get("seconds"),
           "sources": [{**s, "text": rules.source_text(s)} for s in t["sources"].values()]}
    if options.get("machine_from"):
        res["machine_from"] = options["machine_from"]
    res["headline"] = _headline(res)
    return res


def check(st, p: dict, process: str | None = None, options: dict | None = None, rev: int | None = None,
          force: bool = False, overlay_file: bool = True) -> dict:
    """Check a revision (head by default) for a process. Returns rows (one per rule), findings (one per place),
    the verdict, the process data (pull, parting line, side actions, setups), the fixes that can be proposed and
    the overlay file."""
    process = process_id(process or default_process(p) or "")
    t = rules.table(process)
    r = st.rev(p, rev)
    if t["process"].get("routed"):
        return {"project": p["id"], "rev": r["n"], "process": process, "label": t["process"]["label"],
                "verdict": "not proven", "rows": [], "findings": [], "fixes": [],
                "headline": f"{t['process']['label']}: not checked", "routed": t["process"]["routed"],
                "evidence": "not checked"}
    if getattr(st.recipe(p, r["n"]), "mesh", False):
        return {"project": p["id"], "rev": r["n"], "process": process, "label": t["process"]["label"],
                "verdict": "not proven", "rows": [], "findings": [], "fixes": [], "evidence": "not checked",
                "headline": f"{t['process']['label']}: not checked (a mesh design has no exact solid)"}
    if t["process"].get("measured_by") == "form.sheet":
        from .. import sheet
        return sheet.dfm_check(st, p, options, r["n"])
    o = options_for(st, p, process, options)
    gk = st.keys(p, r["n"])["geometry"]
    path = _dir(st, p) / f"{process}-{result_key(gk, process, o)}.json"
    if not force:
        got = _read(path)
        if got is not None:
            got["cached"] = True
            return got
    meas, gk = measured(st, p, process, o, rev=r["n"], force=force)
    res = evaluate(st, p, process, o, meas, gk, r["n"])
    from . import fixes
    res["fixes"] = fixes.propose(st, p, res, o)
    if overlay_file:
        ov = overlay(res, meas)
        opath = _dir(st, p) / f"overlay-{res['key']}.json"
        _write(opath, ov)
        res["overlay_file"] = str(opath)
    _write(path, res)
    return res


# ---- the overlay ---------------------------------------------------------------------------------------------

def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _unb64(s, dtype):
    return np.frombuffer(base64.b64decode(s), dtype=dtype) if s else np.zeros(0, dtype)


def overlay(res: dict, meas: dict) -> dict:
    """What the viewport draws: the sample triangles (three vertices each, design frame), a colour per vertex from
    the worst status of its face's findings and of the area flags (undercut, unreached), the process map's value
    per vertex (draft °, reach × D, overhang ° from level), a status per B-rep face, a marker per finding and the
    parting line.

    {"format": "form-dfm-overlay/1", "process", "rev", "geometry_key", "map": "draft" | "reach" | "overhang" | None,
     "positions", "indices", "values", "colors" (base64 float32 xyz, uint32, float32, uint8 RGBA; as analysis maps),
     "status" (base64 uint8 per vertex: 0 pass, 1 warn, 2 fail, 3 not checked),
     "faces": [{"face", "feature", "status", "rules"}], "markers": [{"at", "status", "rule", "label"}],
     "lines": base64 float32 (n, 6) parting line segments or "", "legend": {...}}"""
    ov = meas.get("overlay") or {}
    P = _unb64(ov.get("positions"), np.float32).reshape(-1, 3)
    F = _unb64(ov.get("tri_face"), np.int32)
    n = len(F)
    face_status: dict = {}
    face_rules: dict = {}
    for f in res["findings"]:
        for fi in f.get("faces") or []:
            if CODE[f["status"]] > CODE.get(face_status.get(fi, "pass"), 0):
                face_status[fi] = f["status"]
            face_rules.setdefault(fi, set()).add(f["rule"])
    st = np.zeros(n, np.uint8)
    for fi, s in face_status.items():
        st[F == fi] = CODE[s]
    rowstat = {r["id"]: r["status"] for r in res["rows"]}
    for flag, rule in (("undercut", "injection.undercut"), ("unreached", "cnc.access")):
        fl = _unb64(ov.get("flag_" + flag), np.uint8)
        if len(fl) == n and rowstat.get(rule) in ("fail", "warn"):
            st = np.maximum(st, np.where(fl > 0, CODE[rowstat[rule]], 0).astype(np.uint8))
    # where an area flag exists for a face, the rest of that face is drawn by its own samples
    for flag in ("undercut", "unreached"):
        fl = _unb64(ov.get("flag_" + flag), np.uint8)
        if len(fl) == n:
            only = {fi for fi, s in face_status.items() if face_rules.get(fi) <= {"injection.undercut", "cnc.access"}}
            for fi in only:
                m = F == fi
                st[m] = np.where(fl[m] > 0, st[m], 0)
    names = {v: k for k, v in CODE.items() if k in ("pass", "warn", "fail", "not_checked")}
    rgb = np.array([COLOURS[names[int(c)]] for c in range(4)], dtype=np.uint8)
    col = np.concatenate([rgb[st], np.full((n, 1), 255, np.uint8)], axis=1)
    vals = _unb64(ov.get("values"), np.float32)
    out = {"format": OVERLAY_FORMAT, "process": res["process"], "rev": res["rev"], "geometry_key": res["geometry_key"],
           "map": ov.get("map"), "positions": _b64(P.astype(np.float32)),
           "indices": _b64(np.arange(3 * n, dtype=np.uint32)),
           "values": _b64(np.repeat(vals, 3).astype(np.float32)) if len(vals) == n else "",
           "colors": _b64(np.repeat(col, 3, axis=0)), "status": _b64(np.repeat(st, 3)),
           "faces": [{"face": int(fi), "feature": (meas.get("features") or [None] * (fi + 1))[fi] if fi < len(meas.get("features") or []) else None,
                      "status": s, "rules": sorted(face_rules.get(fi, ()))} for fi, s in sorted(face_status.items())],
           "markers": [{"at": f["at"], "status": f["status"], "rule": f["rule"], "finding": f["id"],
                        "label": _finding_text(f)} for f in res["findings"] if f.get("at")][:200],
           "lines": (res.get("data") or {}).get("parting_line", {}).get("lines", ""),
           "legend": {"title": f"Manufacturability · {res['label']}", "evidence": res.get("evidence"),
                      "stops": [{"color": "#%02x%02x%02x" % COLOURS[k], "label": k.replace("_", " ")}
                                for k in ("fail", "warn", "not_checked", "pass")],
                      "what": "Each face takes the worst status of the rules found on it; undercut and unreached "
                              "surface is drawn sample by sample.", "not": res.get("not_judged", "")}}
    return out


def _finding_text(f: dict) -> str:
    v = f.get("value")
    lim = f.get("limit")
    vs = f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    ls = f" (limit {f['op']} {lim:g} {f['unit']})" if isinstance(lim, (int, float)) else ""
    return f"{f['title']}: {vs} {f['unit']}{ls}".strip()


def render(st, p: dict, res: dict, view: str = "iso", title: str = "") -> str:
    """A picture of the overlay on the part (fail red, warn amber, not checked blue), with the parting line."""
    from .. import render as rnd
    path = res.get("overlay_file")
    ov = _read(__import__("pathlib").Path(path)) if path else None
    if ov is None:
        raise _err("This check has no overlay.", "Run manufacturability again.")
    vd = {"mesh": [{"feature": "dfm", "positions": ov["positions"], "indices": ov["indices"], "colors": ov["colors"]}]}
    lines = None
    if ov.get("lines"):
        L = _unb64(ov["lines"], np.float32).reshape(-1, 6).astype(np.float64)
        lines = [(L, (62, 230, 255))]
    png = rnd.render_png(vd, [], view, size=(900, 680), title=title or res.get("headline", ""), overlay=False,
                         lines=lines, caption=f"r{res['rev']:02d} · {res['label']} · {res.get('evidence', '')}")
    out = _dir(st, p) / f"overlay-{res['key']}-{view}.png"
    out.write_bytes(png)
    return str(out)


def summary(res: dict, findings: int = 30) -> dict:
    """The result without the bulky parts, for MCP and the CLI."""
    out = {k: v for k, v in res.items() if k not in ("findings", "data", "sources")}
    out["findings"] = res.get("findings", [])[:findings]
    if len(res.get("findings", [])) > findings:
        out["findings_more"] = len(res["findings"]) - findings
    d = dict(res.get("data") or {})
    if "parting_line" in d:
        d["parting_line"] = {k: v for k, v in d["parting_line"].items() if k != "lines"}
    out["data"] = d
    out["sources"] = [s["text"] for s in res.get("sources", [])]
    return out


def apply_fix(st, p, process, fix=None, options=None, apply=True, accept_trades=False, expect_head=None):
    from . import fixes
    return fixes.apply_fix(st, p, process, fix, options, apply=apply, accept_trades=accept_trades,
                           expect_head=expect_head)


# ---- the Bench (form/studies.py registers a provider's register_studies) ----------------------------------------

def _bench(process: str):
    def run(ctx):
        opts = getattr(ctx, "opts", None) or {}
        res = check(ctx.st, ctx.p, process, opts.get("options") or opts)
        return {"headline": res["headline"], "evidence": res.get("evidence"),
                "detail": "; ".join(f"{r['id']} {r['status']}" for r in res["rows"]),
                "data": summary(res), "files": [res["overlay_file"]] if res.get("overlay_file") else []}

    def key(ctx):
        o = options_for(ctx.st, ctx.p, process, {})
        return result_key(ctx.keys["geometry"], process, o)
    return run, key


def register_studies(register) -> None:
    """One Bench entry per process: Manufacturability for CNC, moulding and each printing technology."""
    from ..studies import Study
    labels = {pid: rules.table(pid)["process"].get("label", pid) for pid in rules.processes()}
    for i, pid in enumerate(rules.processes()):
        if pid == "sheet_metal":
            continue
        run, key = _bench(pid)
        short = labels[pid].split(" (")[0]               # "Metal printing (LPBF)": the line keeps the words
        register(Study(f"dfm_{pid}", "study", f"{short} check",
                       f"Manufacturability: every {labels[pid].lower()} rule measured on the exact solid, each limit with "
                       "its source, "
                       "drawn on the part, with fixes proved by checking again.",
                       "computed (B-rep), rules with sources", run=run, key=key,
                       inputs=("geometry", "rule table", "options"), app="dfm", tool="manufacturability",
                       heavy=pid in ("cnc", "injection"), order=60 + i))   # after the print studies, as one block
