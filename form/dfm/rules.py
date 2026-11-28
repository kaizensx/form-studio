"""Rules as data: form/dfm/rules/<process>.toml, each limit with the page it was read from.

A rule names a measure (form/dfm/measure.py takes it on the part), a comparison (``>=``, ``<=``, ``fits`` or
``info``), a ``fail`` limit (cannot be made as drawn, or the source's minimum) and a ``warn`` limit (the source's
recommendation), its unit, and ``source``: the id of a [[source]] in the same file (title, publisher, URL, the date
it was published or "undated", and the date it was read), or ``computed`` when the limit is geometry rather than a
recommendation (a tool of radius r cannot leave a corner smaller than r). A limit nobody published is not a rule:
it is left out, or the rule says ``unsourced``.

A limit can depend on an option (``by = "resin"``: one value per resin); a rule whose option is missing is
*not checked*, with the reason, never passed. A person's shop can override a limit
(``overrides={"cnc.wall": {"warn": 1.0}}``); the row then says ``specified`` and keeps the source it replaced.

Outcomes per rule: pass, warn, fail, not_checked (with why), n/a (nothing on the part it applies to, say what),
info (a number with no limit). The verdict of a check is fail if any rule fails, else *not proven* if any rule was
not checked, else warn, else pass. Not checked is never a pass.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).with_name("rules")
ORDER = ("fail", "not_checked", "warn", "info", "pass", "n/a")
PRINTING = ("fdm", "sla", "sls", "mjf", "lpbf")


@lru_cache(maxsize=None)
def _raw(process: str) -> dict:
    path = DIR / f"{process}.toml"
    if not path.is_file():
        raise KeyError(process)
    return tomllib.loads(path.read_text(encoding="utf-8"))


def processes() -> list[str]:
    order = ["cnc", "injection", *PRINTING, "sheet_metal"]
    have = {p.stem for p in DIR.glob("*.toml")}
    return [p for p in order if p in have] + sorted(have - set(order))


def table(process: str) -> dict:
    """The rule table of a process: {"process": {...}, "sources": {id: {...}}, "rules": [...]}."""
    raw = _raw(process)
    return {"process": raw.get("process", {}), "sources": {s["id"]: s for s in raw.get("source", [])},
            "rules": list(raw.get("rule", [])), "extra": {k: v for k, v in raw.items() if k not in ("process", "source", "rule")}}


def digest(process: str) -> str:
    """A hash of the table's text: part of every result's key, so editing a rule makes results stale."""
    return hashlib.sha256((DIR / f"{process}.toml").read_bytes()).hexdigest()[:16]


def source_text(src: dict) -> str:
    return f"{src['title']}, {src['publisher']} ({src.get('published', 'undated')}; read {src.get('read', '?')})"


def evidence_of(rule: dict, sources: dict, overridden: bool = False) -> str:
    s = rule.get("source", "unsourced")
    if overridden:
        return "specified (your override)"
    if s == "computed":
        return "computed (B-rep)"
    if s == "unsourced":
        return "unsourced"
    src = sources.get(s)
    return f"rule ({src['title']}, {src['publisher']}, read {src.get('read', '?')})" if src else "unsourced"


def _norm(v) -> str:
    return str(v or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def limits(rule: dict, options: dict) -> tuple[float | None, float | None, str | None]:
    """(fail, warn, why not) for this design's options. A limit by an option the design did not state gives why."""
    def pick(v):
        if isinstance(v, dict):
            key = rule.get("by", "")
            want = _norm(options.get(key))
            for k, x in v.items():
                if _norm(k) == want:
                    return x, None
            if "default" in v and not want:
                return v["default"], None
            if "default" in v and want:
                return v["default"], None
            if not want:
                return None, f"{key} not stated (one of: {', '.join(k for k in v if k != 'default')})"
            return None, f"no limit for {key}={options.get(key)} (the source lists: {', '.join(k for k in v if k != 'default')})"
        if v == "tool_r":
            d = options.get("tool_d")
            return (float(d) / 2, None) if d else (None, "tool_d not stated")
        return v, None
    f, why_f = pick(rule.get("fail")) if "fail" in rule else (None, None)
    w, why_w = pick(rule.get("warn")) if "warn" in rule else (None, None)
    why = why_f or why_w
    if why and f is None and w is None:
        return None, None, why
    return (None if f is None else float(f)), (None if w is None else float(w)), None


def applies(rule: dict, options: dict) -> bool:
    return not rule.get("when") or bool(options.get(rule["when"]))


def spec(process: str, options: dict) -> dict:
    """What the measurement needs to know: per measure, the band to search in ((fail, warn) for walls and drafts),
    and the process's machine."""
    t = table(process)
    out: dict = {}
    for r in t["rules"]:
        if not applies(r, options):
            continue
        f, w, _why = limits(r, options)
        lim = [x for x in (f, w) if x is not None]
        key = r["measure"]
        if key in ("wall_min_mm", "draft_deg", "wall_max_mm"):
            cur = out.get(key)
            lo = min(lim) if lim else None
            hi = max(lim) if lim else None
            if cur and cur[0] is not None and lo is not None:
                lo, hi = min(cur[0], lo), max(cur[1], hi)
            out[key] = (lo, hi)
        else:
            out.setdefault(key, True)
    if t["process"].get("machine"):
        out["machine"] = t["process"]["machine"]
    return out


def _status(op: str, v, fail, warn) -> str:
    if op == "info":
        return "info"
    if op == "fits":
        return "pass" if v else "fail"
    if v is None:
        return "pass"
    if op == ">=":
        if fail is not None and v < fail - 1e-9:
            return "fail"
        if warn is not None and v < warn - 1e-9:
            return "warn"
        return "pass"
    if fail is not None and v > fail + 1e-9:
        return "fail"
    if warn is not None and v > warn + 1e-9:
        return "warn"
    return "pass"


def worst(statuses) -> str:
    st = list(statuses)
    for s in ORDER:
        if s in st:
            return s
    return "pass"


def verdict(rows: list) -> str:
    s = [r["status"] for r in rows]
    if "fail" in s:
        return "fail"
    if "not_checked" in s:
        return "not proven"
    if "warn" in s:
        return "warn"
    return "pass"


def evaluate(process: str, measured: dict, options: dict) -> dict:
    """Rows (one per rule, with its verdict, worst value, limit and source) and findings (one per place that warns
    or fails), from the measures of form/dfm/measure.py."""
    t = table(process)
    overrides = options.get("overrides") or {}
    rows, findings = [], []
    meas = measured.get("measures") or {}
    for r in t["rules"]:
        row = {"id": r["id"], "title": r["title"], "unit": r.get("unit", ""), "op": r.get("op"),
               "source": r.get("source", "unsourced"), "fix": r.get("fix")}
        src = t["sources"].get(r.get("source", ""))
        if src:
            row["source_ref"] = {k: src.get(k) for k in ("title", "publisher", "url", "published", "read")}
        if r.get("quote"):
            row["quote"] = r["quote"]
        if r.get("why"):
            row["why"] = r["why"]
        if not applies(r, options):
            rows.append({**row, "status": "n/a", "note": f"applies when {r['when']} is set"})
            continue
        f, w, why = limits(r, options)
        ov = overrides.get(r["id"]) or {}
        if ov:
            f = float(ov["fail"]) if ov.get("fail") is not None else f
            w = float(ov["warn"]) if ov.get("warn") is not None else w
            why = None
        row.update({"fail": f, "warn": w, "evidence": evidence_of(r, t["sources"], bool(ov))})
        if ov:
            row["replaced"] = evidence_of(r, t["sources"])
        if why:
            rows.append({**row, "status": "not_checked", "reason": f"Not checked: {why}."})
            continue
        m = meas.get(r["measure"])
        if m is None:
            rows.append({**row, "status": "not_checked", "reason": measured.get("reason") or "Not measured."})
            continue
        if m.get("state") != "measured":
            rows.append({**row, "status": "not_checked", "reason": m.get("reason", "Not measured.")})
            continue
        items = m.get("items") or []
        row["method"] = m.get("method")
        if not items:
            rows.append({**row, "status": "n/a" if m.get("none") else "pass", "value": None,
                         "note": m.get("none") or "nothing on the part reaches the limit"})
            continue
        sts = [_status(r["op"], it.get("value"), f, w) for it in items]
        vals = [it.get("value") for it in items if isinstance(it.get("value"), (int, float)) and not isinstance(it.get("value"), bool)]
        if m.get("total_mm2") is not None and r["op"] == "<=":
            row["value"] = m["total_mm2"]
        elif r["op"] == ">=" and vals:
            row["value"] = min(vals)
        elif r["op"] in ("<=", "info") and vals:
            row["value"] = max(vals)
        else:
            row["value"] = items[0].get("value")
        row["status"] = worst(sts)
        if r["op"] in ("info", "fits"):
            row["detail"] = {k: v for k, v in items[0].items() if k not in ("value",)}
        n = 0
        for it, s in zip(items, sts):
            if s not in ("fail", "warn"):
                continue
            n += 1
            fd = {"id": f"{r['id']}#{n}", "rule": r["id"], "title": r["title"], "status": s, "value": it.get("value"),
                  "limit": f if s == "fail" else w, "unit": r.get("unit", ""), "op": r["op"],
                  "evidence": row["evidence"], "fix": r.get("fix")}
            for k in ("at", "faces", "feature", "features", "area_mm2", "kind", "axis", "depth_mm", "d_mm", "r_mm",
                      "sharp", "nearest_drill_mm", "half", "how", "to", "voids", "size_mm", "machine_mm"):
                if k in it:
                    fd[k] = it[k]
            findings.append(fd)
        row["places"] = n
        rows.append(row)
    return {"rows": rows, "findings": findings, "verdict": verdict(rows)}


def overrides_key(options: dict) -> str:
    return json.dumps(options.get("overrides") or {}, sort_keys=True)
