"""Replay real source edits as edit_design ops and measure what they cost, before and after.

    .venv/bin/python scripts/bench_edits.py --projects DIR --sources DIR [--manifest edits.json] [--build] [--json out]

--projects   a folder of project.json copies (any name ending .json); --sources their source store (<sha>.py).
             Both are only read.
--manifest   which edits to replay: [{"project": id, "from": rev, "to": rev, "tool": "update_design" |
             "add_feature"}]. Without it: every revision an agent made by changing the source.
--build      also run every edit through the kernel in a temporary data folder, twice: as it was sent
             (update_design with the whole file) and as ops (edit_design), and record wall time, which features
             were built and which loaded from checkpoints, and whether both give the same solid.

Characters. "before" is the JSON of the tool call as it was sent: update_design with the whole new source, or
add_feature with the new method. "after" is the JSON of the edit_design call that makes the same change: the ops
form.edits.delta derives between the canonical form of the old source and the canonical form of the new one. Two
ways of writing ops are measured: "features" (whole feature methods and functions replaced by name), "text" (only
the lines that differ, with the context that makes them unique) and "mixed" (by name where a function was
rewritten, as text where a few lines of it changed: the shorter of the two per function). Every delta is checked:
applying it to the old source gives the new one exactly. An edit whose ops are longer than the file (a rewrite)
counts at the file's length, since update_design(source=) is still there for it.

No model runs. Nothing here says how long a model takes to write the characters.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_projects(folder: Path) -> dict:
    out = {}
    for f in sorted(folder.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(p, dict) and p.get("revisions"):
            out[p.get("id") or f.stem] = p
            out[f.stem] = p
    return out


def rid_of(p: dict, n: int) -> str:
    r = next(x for x in p["revisions"] if x["n"] == n)
    return r.get("recipe") or p["recipe"]


def source(store: Path, rid: str) -> str:
    return (store / f"{rid.split(':', 1)[1]}.py").read_text(encoding="utf-8")


def all_agent_edits(projects: dict) -> list:
    out, seen = [], set()
    for pid, p in projects.items():
        if id(p) in seen:
            continue
        seen.add(id(p))
        revs = {r["n"]: r for r in p["revisions"]}
        for r in p["revisions"]:
            par = r.get("parent")
            if par in revs and str(r.get("origin", "")).startswith("agent") and rid_of(p, r["n"]) != rid_of(p, par) \
                    and rid_of(p, r["n"]).startswith("src:") and rid_of(p, par).startswith("src:"):
                out.append({"project": pid, "from": par, "to": r["n"], "tool": "update_design"})
    return out


def chars(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False))


def measure(e: dict, p: dict, store: Path) -> dict:
    from form import canon, edits, featureprog
    old, new = source(store, rid_of(p, e["from"])), source(store, rid_of(p, e["to"]))
    r_to = next(x for x in p["revisions"] if x["n"] == e["to"])
    r_from = next(x for x in p["revisions"] if x["n"] == e["from"])
    note = r_to.get("note", "")
    vals = {k: v for k, v in r_to["values"].items() if k in r_from["values"] and r_from["values"][k] != v}
    base = {"project": p.get("id", ""), "expect_head": e["from"], "note": note, **({"values": vals} if vals else {})}
    row = {**e, "lines": len(new.splitlines()), "note": note[:70]}
    if e.get("tool") == "add_feature":
        added = [k for k in featureprog.method_spans(new) if k not in featureprog.method_spans(old)]
        code = edits._method_text(new, featureprog.method_spans(new)[added[0]]) if added else new
        row["before"] = chars({**{k: v for k, v in base.items() if k != "note"}, "kind": "code",
                               "feature": added[0] if added else "", "code": code})
    else:
        row["before"] = chars({**base, "source": new})
    whole = chars({**base, "source": new})
    ca, cb = canon.lift(old), canon.lift(new)
    row["forms"] = [ca["mode"], cb["mode"]]
    set_ops = [{"op": "set_param", "param": k, "value": v} for k, v in vals.items()]
    for name, structural in (("features", True), ("text", False), ("mixed", True)):
        ops = edits.delta(ca["source"], cb["source"], structural)
        if name == "mixed":
            ops = edits.tighten(ca["source"], ops)
        ok = True
        if ops:
            try:
                ok = edits.apply(ca["source"], ops)[0] == cb["source"]
            except Exception:                              # noqa: BLE001 - a delta that does not apply is not counted
                ok = False
        n = chars({k: v for k, v in base.items() if k != "values"} | {"ops": ops + set_ops})
        row[name] = {"ops": len(ops) + len(set_ops), "chars": n, "exact": ok, "counted": min(n, whole) if ok else whole,
                     "as": "ops" if ok and n <= whole else "whole file"}
        if name == "features":
            row["_ops"] = ops + set_ops
            row["touched"] = sorted({o.get("feature") or o.get("def") or "text" for o in ops})
    return row


def totals(rows: list) -> dict:
    b = sum(r["before"] for r in rows)
    out = {"edits": len(rows), "before_chars": b}
    for k in ("features", "text", "mixed"):
        a = sum(r[k]["counted"] for r in rows)
        out[k] = {"after_chars": a, "fewer_pct": round(100 * (1 - a / b), 1) if b else 0.0,
                  "sent_as_ops": sum(1 for r in rows if r[k]["as"] == "ops"),
                  "exact": sum(1 for r in rows if r[k]["exact"])}
    return out


def _replay_one(tag: str, rows: list, projects: dict, store: Path) -> dict:
    """Every project's chain in a Studio of its own (its own data folder, kernel workers and checkpoints), the
    counted edits as whole files (tag "A") or as ops (tag "B"). {(project, to): result}"""
    os.environ["FORM_DATA"] = tempfile.mkdtemp(prefix=f"form-edits-{tag}-")
    os.environ.pop("FORM_SOURCES", None)
    os.environ.pop("FORM_CHECKPOINTS", None)
    from form import canon, config, edits
    from form.studio import Studio, StudioError
    st = Studio(config.load())
    out = {}
    try:
        by_project: dict = {}
        for r in rows:
            by_project.setdefault(r["project"], []).append(r)
        for pid, es in by_project.items():
            p = projects[pid]
            revs = {r["n"]: r for r in p["revisions"]}
            first = min(revs)
            wanted = {e["to"] for e in es}
            q = st.create_design(f"{pid[:30]} {tag}", source(store, rid_of(p, first)), values=revs[first]["values"],
                                 partial=True)
            qid = q["id"]
            for n in sorted(revs):
                r = revs[n]
                par = revs.get(r.get("parent"))
                if n == first or par is None:
                    continue
                new_rid, old_rid = rid_of(p, n), rid_of(p, par["n"])
                vals = {k: v for k, v in r["values"].items() if par["values"].get(k) != v and k in par["values"]}
                q = st.load(qid)
                t = time.time()
                try:
                    if new_rid == old_rid:
                        if vals:
                            q = st.commit(q, {k: v for k, v in vals.items() if k in st.rev(q)["values"]}, origin="replay")
                        res = {"kind": "values"}
                    elif tag == "A" or n not in wanted:
                        q = st.update_design(q, source(store, new_rid), values=vals or None, origin="replay", partial=True)
                        log = st.rev(q).get("build_log") or []
                        res = {"kind": "whole file", "built": [x["feature"] for x in log if x["status"] == "built"],
                               "reused": [x["feature"] for x in log if x["status"] == "checkpoint"]}
                    else:
                        c = edits.canonical(st, q)
                        target = canon.lift(source(store, new_rid))["source"]
                        ops = edits.delta(c["source"], target) + [{"op": "set_param", "param": k, "value": v}
                                                                  for k, v in vals.items()]
                        e = edits.edit(st, q, ops, origin="replay", partial=True, preflight="off")
                        q = e["project"]
                        res = {"kind": "ops", "form": c["mode"],
                               "built": [x["feature"] for x in e["changed"] if x["status"] == "built"],
                               "reused": e["reused"],
                               "skipped": [x["feature"] for x in e["changed"] if x["status"] == "skipped"]}
                    res["s"] = round(time.time() - t, 2)
                    s = st.head_summary(st.load(qid))
                    res["volume_mm3"] = round(s["volume_mm3"], 3)
                    res["faces"] = s["faces"]
                    res["partial"] = bool(st.rev(st.load(qid)).get("partial"))
                except StudioError as err:
                    res = {"error": str(err)[:200], "s": round(time.time() - t, 2)}
                out[(pid, n)] = res
                print(tag, pid[:24], n, json.dumps(res, default=str)[:260], flush=True)
    finally:
        st.kernel.stop()
    return out


def build_replay(rows: list, projects: dict, store: Path) -> list:
    """Each project's chain twice, each time in a Studio of its own so neither run finds the other's checkpoints:
    whole files (A) and ops (B). The seconds are the wall time of the call that made the revision (for the first
    edit of a plain Recipe as ops that includes the build that checks the lift)."""
    a = _replay_one("A", rows, projects, store)
    b = _replay_one("B", rows, projects, store)
    wanted = {(r["project"], r["to"]) for r in rows}
    out = []
    for key in a:
        step = {"project": key[0], "to": key[1], "counted": key in wanted, "A": a[key], "B": b.get(key, {"error": "not run"})}
        x, y = step["A"], step["B"]
        if "volume_mm3" in x and "volume_mm3" in y:
            step["same_solid"] = abs(x["volume_mm3"] - y["volume_mm3"]) <= 1e-6 * max(1.0, abs(x["volume_mm3"])) \
                and x["faces"] == y["faces"]
        out.append(step)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    projects = load_projects(Path(a.projects))
    store = Path(a.sources)
    edits_ = json.loads(Path(a.manifest).read_text(encoding="utf-8")) if a.manifest else all_agent_edits(projects)
    rows = []
    for e in edits_:
        p = projects.get(e["project"])
        if p is None:
            print("unknown project", e["project"])
            continue
        try:
            rows.append(measure(e, p, store))
        except (OSError, StopIteration, KeyError) as err:
            print("skipped", e, type(err).__name__, err)
    tot = totals(rows)
    for r in rows:
        print(f"{r['project'][:28]:<28} r{r['from']:>2}->r{r['to']:<2} {r.get('tool', ''):<13} {r['lines']:>4} lines  "
              f"before {r['before']:>6}  features {r['features']['counted']:>6} ({r['features']['as']})  "
              f"text {r['text']['counted']:>6} ({r['text']['as']})  mixed {r['mixed']['counted']:>6}  {'/'.join(r['forms'])}")
    print(json.dumps(tot, indent=1))
    out = {"totals": tot, "rows": [{k: v for k, v in r.items() if k != "_ops"} for r in rows]}
    if a.build:
        steps = build_replay(rows, projects, store)
        cnt = [s for s in steps if s["counted"] and "s" in s.get("A", {}) and "s" in s.get("B", {})]
        both = [s for s in cnt if "error" not in s["A"] and "error" not in s["B"]]
        out["build"] = {"steps": steps, "counted": len(cnt), "both_built": len(both),
                        "same_solid": sum(1 for s in both if s.get("same_solid")),
                        "wall_s_whole_file": round(sum(s["A"]["s"] for s in both), 1),
                        "wall_s_ops": round(sum(s["B"]["s"] for s in both), 1),
                        "features_built_ops": sum(len(s["B"].get("built", [])) for s in both if s["B"].get("kind") == "ops"),
                        "features_reused_ops": sum(len(s["B"].get("reused", [])) for s in both if s["B"].get("kind") == "ops")}
        print(json.dumps({k: v for k, v in out["build"].items() if k != "steps"}, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
