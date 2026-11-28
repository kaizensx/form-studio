"""What to dimension, and which parameter each dimension is.

Sizes come from the B-rep (views.measure): plane levels along each axis, cylinders (full: holes and bosses; partial:
fillets and rounds), the axes of holes. A design parameter is bound to the size whose value it equals, preferring
the size made by the parameter's own feature; when the drawing may build the design a second time with the parameter
nudged, the binding is *proved* (the size moved by the nudge and nothing else claims it) rather than *matched*.

    cands = candidates(measure)
    b = bind(params, values, cands, perturbed)       # one row per parameter: bound, proved, or why not
    plan = choose(cands, b, ...)                    # the dimensions the sheet will carry, each once

Every displayed value is the model's (measured on the solid); the parameter only names it.
"""
from __future__ import annotations

from collections import defaultdict

EPS = 1e-3


def _levels(planes, axis):
    out = []
    for p in sorted((p for p in planes if p["axis"] == axis), key=lambda p: p["at"]):
        if out and abs(out[-1]["at"] - p["at"]) < 1e-4:
            out[-1]["faces"].append(p["face"])
            out[-1]["features"].add(p["feature"])
            out[-1]["planes"].append(p)
        else:
            out.append({"at": p["at"], "faces": [p["face"]], "features": {p["feature"]}, "planes": [p]})
    return out


def candidates(m: dict) -> list[dict]:
    """Every size a dimension could show: id, kind (linear, diameter, radius, pitch, location), axis, value,
    the faces and features it is measured between, and where it sits (for placing it)."""
    out = []
    bb = m["bbox"]
    for k, ax in enumerate("xyz"):
        lv = _levels(m["planes"], ax)
        ext = bb[k + 3] - bb[k]
        out.append({"id": f"ext_{ax}", "kind": "linear", "axis": ax, "value": round(ext, 4), "from": bb[k],
                    "to": bb[k + 3], "faces": [], "features": [], "overall": True})
        for i in range(len(lv)):
            for j in range(i + 1, len(lv)):
                a, b = lv[i], lv[j]
                v = round(b["at"] - a["at"], 4)
                if v < EPS:
                    continue
                out.append({"id": f"lin_{ax}_{i}_{j}", "kind": "linear", "axis": ax, "value": v, "from": a["at"],
                            "to": b["at"], "faces": a["faces"] + b["faces"],
                            "features": sorted(f for f in a["features"] | b["features"] if f),
                            "overall": abs(a["at"] - bb[k]) < 1e-4 and abs(b["at"] - bb[k + 3]) < 1e-4,
                            "planes": [a["planes"][0], b["planes"][0]]})
    groups = defaultdict(list)
    for c in m["cylinders"]:
        if c["axis"] is None:
            continue
        key = (c["axis"], round(c["r"], 4), c["full"], c["inner"])
        groups[key].append(c)
    for (ax, r, full, inner), cs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        uniq = []
        for c in cs:                                     # one per axis position (a hole split into faces is one)
            if not any(_same_axis(c, u) for u in uniq):
                uniq.append(c)
        gid = f"{'d' if full else 'r'}_{ax}_{r:g}_{'in' if inner else 'out'}"
        kind = "diameter" if full else "radius"
        out.append({"id": gid, "kind": kind, "axis": ax, "value": round(2 * r if full else r, 4), "count": len(uniq),
                    "inner": inner, "faces": [c["face"] for c in cs],
                    "features": sorted({c["feature"] for c in cs if c["feature"]}), "cyls": uniq})
        if full and len(uniq) > 1:                        # pitch between equal holes along the other two axes
            for k2 in "xyz":
                if k2 == ax:
                    continue
                i2 = "xyz".index(k2)
                xs = sorted({round(u["at"][i2], 4) for u in uniq})
                for a, b in zip(xs, xs[1:]):
                    out.append({"id": f"pitch_{gid}_{k2}_{a:g}", "kind": "pitch", "axis": k2, "value": round(b - a, 4),
                                "from": a, "to": b, "of": gid, "view_axis": ax, "faces": [c["face"] for c in cs],
                                "features": sorted({c["feature"] for c in cs if c["feature"]})})
    return out


def _same_axis(a, b) -> bool:
    return a["axis"] == b["axis"] and all(abs(x - y) < 1e-4 for x, y in zip(a["at"], b["at"]))


def _index(cands):
    by = defaultdict(list)
    for c in cands:
        by[(c["kind"], c["axis"])].append(c["value"])
    return by


def _factor(kind: str) -> tuple:
    return (1.0,) if kind != "diameter" else (1.0, 2.0)


def bind(params: list, values: dict, cands: list, perturbed: dict | None = None) -> list[dict]:
    """Bind each size parameter to the candidate size it is. Returns one row per parameter."""
    perturbed = perturbed or {}
    rows = []
    taken = set()
    for p in params:
        key, v = p["key"], values.get(p["key"])
        row = {"param": key, "label": p.get("label", key), "feature": p.get("feature", ""), "value": v,
               "unit": p.get("unit", "mm"), "status": "not a size"}
        if p.get("unit") != "mm" or v is None or not isinstance(v, (int, float)):
            rows.append(row)
            continue
        hits = []
        for c in cands:
            for f in _factor(c["kind"]):
                if abs(c["value"] - f * v) < EPS:
                    hits.append((c, f))
        pert = perturbed.get(key) or {}
        proof = None
        if hits and pert.get("error"):
            row["why"] = "the nudged build failed, so the binding is by value: " + pert["error"][:160]
        if hits and pert.get("measure"):
            after = _index(candidates(pert["measure"]))
            before = _index(cands)
            good = []
            for c, f in hits:
                k = (c["kind"], c["axis"])
                moved = any(abs(x - (c["value"] + f * pert["delta"])) < EPS for x in after[k])
                fewer = sum(abs(x - c["value"]) < EPS for x in after[k]) < sum(abs(x - c["value"]) < EPS for x in before[k])
                if moved and fewer:
                    good.append((c, f))
            if good:
                hits, proof = good, True
            else:
                proof = False
        if not hits:
            row["status"] = "no size of its own"
            if pert.get("measure"):
                row["drives"] = _drives(cands, candidates(pert["measure"]))
            elif pert.get("error"):
                row["why"] = "nudging it does not build: " + pert["error"]
            rows.append(row)
            continue
        feat = p.get("feature") or ""
        rank = {"diameter": 0, "radius": 0, "pitch": 1, "linear": 2}
        hits.sort(key=lambda h: (h[0]["id"] in taken, feat not in h[0]["features"], h[0].get("overall", False) is False
                                 and h[0]["kind"] == "linear" and not h[0]["features"], rank.get(h[0]["kind"], 3),
                                 len(h[0]["features"]) != 1))
        c, f = hits[0]
        taken.add(c["id"])
        row.update(status="proved" if proof else "matched", candidate=c["id"], kind=c["kind"], factor=f,
                   measured=c["value"], alternatives=len(hits) - 1)
        if proof is False:
            row["why"] = "the nudged build did not move this size alone; bound by value"
        rows.append(row)
    return rows


def _drives(before: list, after: list) -> list:
    """Sizes that changed when the parameter was nudged (for a parameter that is no size itself)."""
    bi, ai = _index(before), _index(after)
    out = []
    for c in before:
        if c["kind"] == "linear" and not c.get("overall") and not c["features"]:
            continue
        k = (c["kind"], c["axis"])
        if sum(abs(x - c["value"]) < EPS for x in ai[k]) < sum(abs(x - c["value"]) < EPS for x in bi[k]):
            out.append({"candidate": c["id"], "kind": c["kind"], "value": c["value"]})
    return out[:4]


def completeness(rows: list) -> dict:
    sizes = [r for r in rows if r["status"] != "not a size"]
    shown = [r for r in sizes if r["status"] in ("proved", "matched")]
    twice = len(shown) - len({r["candidate"] for r in shown})
    return {"size_params": len(sizes), "dimensioned": len(shown), "proved": sum(r["status"] == "proved" for r in shown),
            "twice": twice, "not_shown": [{"param": r["param"], "why": r.get("why") or r["status"],
                                            "drives": r.get("drives", [])} for r in sizes if r not in shown],
            "text": f"{len(shown)} of {len(sizes)} size parameters dimensioned, {twice} twice"}


def choose(cands: list, rows: list, holes_mode: str = "baseline") -> list[dict]:
    """The dimensions the sheet carries: every bound parameter once, the overall sizes, every hole and boss
    diameter and radius group once, and the locations of hole patterns (baseline or chain, ISO 129-1)."""
    by = {c["id"]: c for c in cands}
    out, used = [], set()
    for r in rows:
        if r.get("candidate") and r["candidate"] not in used:
            c = by[r["candidate"]]
            out.append({**c, "param": r["param"], "binding": r["status"], "label": r["label"]})
            used.add(c["id"])
    for ax in "xyz":
        c = by[f"ext_{ax}"]
        if not any(abs(d["value"] - c["value"]) < EPS and d["axis"] == ax and d["kind"] == "linear" for d in out):
            out.append({**c, "param": None, "binding": "model"})
    for c in cands:
        if c["kind"] in ("diameter", "radius") and c["id"] not in used:
            out.append({**c, "param": None, "binding": "model"})
            used.add(c["id"])
    # hole pattern locations: a bound pitch locates a pattern on its axis, and on the other axis too when the
    # spacing there is the same; a pattern centred on the part needs only its pitch (the symmetry places it);
    # otherwise from the part's lower edge (baseline) or hole to hole (chain), ISO 129-1. Coaxial groups (a
    # counterbore over its hole) are located once.
    located = []
    for c in cands:
        if c["kind"] != "diameter" or not c.get("inner") or c["count"] < 1:
            continue
        if any(all(any(_same_axis(u, w) for w in o["cyls"]) for u in c["cyls"]) for o in located):
            continue
        located.append(c)
        for k2 in "xyz":
            if k2 == c["axis"]:
                continue
            i2 = "xyz".index(k2)
            xs = sorted({round(u["at"][i2], 4) for u in c["cyls"]})
            ext = by[f"ext_{k2}"]
            mid = (ext["from"] + ext["to"]) / 2
            pitch = [d for d in out if d["kind"] == "pitch" and d.get("of") == c["id"]]
            if any(d["axis"] == k2 for d in pitch):
                continue
            same = [d for d in pitch if len(xs) == 2 and abs(d["value"] - (xs[1] - xs[0])) < EPS]
            if same:
                pc = next((q for q in cands if q["kind"] == "pitch" and q.get("of") == c["id"] and q["axis"] == k2), None)
                if pc is not None:
                    out.append({**pc, "param": None, "binding": "model"})
                    continue
            if abs(sum(xs) / len(xs) - mid) < 1e-4 and (len(xs) == 1 or pitch):
                continue                                   # centred: the symmetry and the pitch say where
            prev = ext["from"]
            for x in xs:
                a = ext["from"] if holes_mode == "baseline" else prev
                if x - a > EPS:
                    out.append({"id": f"loc_{c['id']}_{k2}_{x:g}", "kind": "location", "axis": k2, "value": round(x - a, 4),
                                "from": a, "to": x, "of": c["id"], "view_axis": c["axis"], "faces": c["faces"],
                                "features": c["features"], "param": None, "binding": "model", "mode": holes_mode})
                prev = x
    return out
