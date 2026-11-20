"""Candidates: build several versions of a risky design (or of one risky step) at the same time, verify and score each,
and keep the best. One shot becomes a search with the kernel as the judge.

    from form import candidates
    r = candidates.run(st, [{"label": "loft", "source": A}, {"label": "sweep", "source": B},
                            {"label": "thin wall", "values": {"wall": 1.6}}],          # same source as the first, other values
                       name="Bike grip", brief="...", targets={"size_mm": [130, 34, 34]}, keep="best")
    r["ranking"]    # [{"label", "ok", "score", "parts": {...}, "build_s", "notes", "error", "diagnosis"}], best first
    r["project"]    # the design made from the best candidate (keep="best" with a name), or the project updated

Each candidate is built in its own kernel worker (form/worker.py KernelPool), so N candidates take about as long as
the slowest one, not N times one. Scores (0-100, heuristic; the parts are reported):
  builds      gate: a valid B-rep with the declared number of solids; a candidate that fails scores 0 and carries
              the build diagnosis (form/build_diag.py)
  brief       targets: overall size (size_mm, within tolerance_mm), solids, and named derived values
  quality     form.critique metrics: rounded where it matters (sharp-edge fraction, a fillet exists), no folded skins,
              no invalid intermediate stage; the product class silhouette score when there is a class
  robust      fewer form.craft fallbacks taken (each one is an operation that did not work as written)
  editable    the share of parameters that still build at both ends of their range (a sweep within a time budget)
A candidate that fails is dropped without sinking the others.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

MAX = 6
WEIGHTS = {"brief": 25, "quality": 30, "robust": 15, "editable": 30}


# ---- kernel side (runs in a worker) -------------------------------------------------------------------------------

def op_candidate(key, recipe_id, values, tol=0.1, sweep=True, sweep_budget_s=25.0, product_class=None,
                 sweep_params=None):
    """Build one candidate, measure it, and sweep its parameters to the ends of their ranges (within budget)."""
    from . import kernel
    from .recipes import RecipeError
    t0 = time.perf_counter()
    model = kernel._get(key, recipe_id, values, tol)
    t_build = time.perf_counter() - t0
    s = kernel._summary(model)
    out = {"build_s": round(t_build, 3), "bbox": s["bbox"], "volume_mm3": s["volume_mm3"],
           "solids": len(model["shape"].solids()), "declared": getattr(model["recipe"], "solids", 1),
           "valid": bool(model["shape"].is_valid), "faces": len(model["shape"].faces()),
           "craft_notes": list(model.get("craft_notes") or []), "derived": s.get("derived") or []}
    try:
        from . import critique
        m = critique.op_critique_metrics(key, recipe_id, values, tol, product_class=product_class)
        out["metrics"] = {k: m.get(k) for k in ("smallest_fillet_mm", "sharp_edge_fraction", "folds", "walls",
                                                "surface_mix", "symmetry")}
        cl = (m.get("form") or {}).get("class")
        if cl:
            out["class_score"] = round(float(cl["score"]), 3)
    except Exception as e:                              # metrics are a bonus, never a failure
        out["metrics_error"] = f"{type(e).__name__}: {e}"[:200]
    if sweep:
        recipe = model["recipe"]
        rows, t1 = [], time.perf_counter()
        params = [p for p in recipe.params if p.max > p.min and (not sweep_params or p.key in sweep_params)]
        for p in params:
            for end in ("lo", "hi"):
                if time.perf_counter() - t1 > sweep_budget_s:
                    break
                vals = {**model["values"], p.key: (p.min if end == "lo" else p.max)}
                try:
                    recipe.validate(vals)
                    kernel._build(recipe_id, vals, max(tol, 0.25))
                    rows.append({"param": p.key, "at": end, "ok": True})
                except RecipeError as e:
                    rows.append({"param": p.key, "at": end, "ok": False, "error": str(e)[:160]})
                except Exception as e:
                    rows.append({"param": p.key, "at": end, "ok": False, "error": f"{type(e).__name__}: {e}"[:160]})
        out["sweep"] = {"rows": rows, "params": len(params), "tested": len({r["param"] for r in rows}),
                        "seconds": round(time.perf_counter() - t1, 2)}
    out["seconds"] = round(time.perf_counter() - t0, 3)
    return out


KERNEL_OPS = {"candidate": op_candidate}


# ---- scoring (plain data) -----------------------------------------------------------------------------------------

def score(m: dict, targets: dict | None = None) -> tuple[float, dict, list]:
    """(score 0-100, parts, notes) for one built candidate's measurements m (op_candidate's result)."""
    notes = []
    if not m.get("valid") or m.get("solids") != m.get("declared"):
        return 0.0, {"builds": 0}, ["not a valid solid with the declared count"]
    parts = {"builds": 1}
    # brief conformance
    t = targets or {}
    b = 1.0
    if t.get("size_mm"):
        lo, hi = m["bbox"]
        size = sorted(round(y - x, 2) for x, y in zip(lo, hi))
        want = sorted(float(v) for v in t["size_mm"])
        tol = float(t.get("tolerance_mm", max(1.0, 0.02 * max(want))))
        dev = max(abs(a - w) for a, w in zip(size, want))
        b *= 1.0 if dev <= tol else max(0.0, 1.0 - (dev - tol) / max(want))
        if dev > tol:
            notes.append(f"size {size} mm is {dev:.1f} mm off the target {want}")
    if t.get("solids") is not None and m["solids"] != int(t["solids"]):
        b *= 0.5
        notes.append(f"{m['solids']} solids, the brief wants {t['solids']}")
    for k, v in (t.get("derived") or {}).items():
        got = next((d["value"] for d in m.get("derived", []) if d.get("key") == k), None)
        if got is None:
            b *= 0.8
            notes.append(f"derived value {k} is not reported")
        elif abs(float(got) - float(v)) > max(0.02 * abs(float(v)), 0.05):
            b *= 0.8
            notes.append(f"{k} = {got}, the brief wants {v}")
    parts["brief"] = round(b, 3)
    # quality
    mt = m.get("metrics") or {}
    q = 1.0
    sharp = mt.get("sharp_edge_fraction")
    if isinstance(sharp, (int, float)) and sharp > 0.6:
        q -= min(0.3, (sharp - 0.6))
        notes.append(f"sharp-edge fraction {sharp:.2f}")
    if mt and mt.get("smallest_fillet_mm") is None:
        q -= 0.1
        notes.append("no fillet anywhere")
    if (mt.get("folds") or {}).get("folds"):
        q -= 0.35
        notes.append("a lofted skin folds")
    if any("not a valid solid" in n for n in m.get("craft_notes", [])):
        q -= 0.2
        notes.append("an intermediate stage was not a valid solid")
    if "class_score" in m:
        q = 0.5 * q + 0.5 * m["class_score"]
    parts["quality"] = round(max(0.0, q), 3)
    fb = [n for n in m.get("craft_notes", []) if "failed; used" in n or "did not fit" in n or "left sharp" in n]
    parts["robust"] = round(max(0.0, 1.0 - 0.15 * len(fb)), 3)
    if fb:
        notes.append(f"{len(fb)} craft fallback(s): " + "; ".join(fb)[:200])
    sw = m.get("sweep")
    if sw and sw.get("rows"):
        by = {}
        for r in sw["rows"]:
            by.setdefault(r["param"], []).append(r["ok"])
        ok_params = sum(1 for v in by.values() if all(v))
        parts["editable"] = round(ok_params / max(1, len(by)), 3)
        bad = [k for k, v in by.items() if not all(v)]
        if bad:
            notes.append("does not build at the end of its range: " + ", ".join(bad[:6]))
        if sw["tested"] < sw["params"]:
            notes.append(f"swept {sw['tested']} of {sw['params']} parameters within the time budget")
    else:
        parts["editable"] = None
    w = {k: v for k, v in WEIGHTS.items() if parts.get(k) is not None}
    total = 100.0 * sum(WEIGHTS[k] * parts[k] for k in w) / sum(w.values())
    return round(total, 1), parts, notes


# ---- engine side ----------------------------------------------------------------------------------------------------

def _entries(cands: list) -> list[dict]:
    from .studio import StudioError
    if not isinstance(cands, list) or not 1 <= len(cands) <= MAX:
        raise StudioError(f"Give 1 to {MAX} candidates.", "Each is {label, source} or {label, values} (values on the "
                          "first candidate's source).")
    out, base = [], None
    for i, c in enumerate(cands):
        c = c if isinstance(c, dict) else {}
        src = str(c.get("source") or "")
        if not src.strip():
            if base is None:
                raise StudioError("The first candidate needs its source.", "Pass {label, source} first; later "
                                  "candidates may give only values to try on it.")
            src = base
        base = base or src
        try:
            vals = {k: float(v) for k, v in (c.get("values") or {}).items()}
        except (TypeError, ValueError):
            raise StudioError(f"Candidate {i + 1}: values must be numbers.")
        out.append({"label": " ".join(str(c.get("label") or f"Candidate {chr(65 + i)}").split())[:60], "source": src,
                    "values": vals, "language": str(c.get("language") or "python")})
    return out


def run(st, cands: list, name: str = "", project: str = "", brief: str = "", targets: dict | None = None,
        product_class: str | None = None, keep: str = "best", purpose: str | None = None, sweep: bool = True,
        sweep_budget_s: float = 25.0, note: str = "", expect_head: int | None = None, by: str = "agent") -> dict:
    """Build every candidate in parallel, score, rank, and keep the best (see the module docstring).
    keep: "best" (make the design from the best one: create with name, or a new revision of project) or "none"
    (report only)."""
    from .studio import H, StudioError
    if keep not in ("best", "none"):
        raise StudioError("keep is \"best\" or \"none\".")
    if keep == "best" and not (name or project):
        raise StudioError("Name the design to create (name=...) or the project to update (project=...).",
                          "Or pass keep=\"none\" to compare the candidates only.")
    entries = _entries(cands)
    p = st.load(project) if project else None
    t0 = time.time()
    pool = st.kernel
    if hasattr(pool, "warm"):
        pool.warm(min(len(entries), getattr(pool, "size", 1)))
    t_warm = time.time() - t0
    rows = []
    for e in entries:
        row = {"label": e["label"], "ok": False, "score": 0.0}
        try:
            e["rid"] = st._load_design(e["source"], e["language"])
            rec = st.recipes[e["rid"]]
            e["full"] = {**rec.defaults(), **e["values"]}
            if p is not None:                                  # values that still exist carry over from the head
                head = st.rev(p)["values"]
                e["full"] = {**rec.defaults(), **{k: v for k, v in head.items() if k in e["full"]}, **e["values"]}
            st._check_assembly(e["rid"], e["full"])
        except StudioError as err:
            row["error"] = err.public()
            e["rid"] = None
        rows.append(row)
    t1 = time.time()

    def build(i):
        e, row = entries[i], rows[i]
        if not e.get("rid"):
            return
        key = "pv-" + H(e["rid"], e["values"] if p is None else e["full"])
        try:
            m = st._k("candidate", key=key, recipe_id=e["rid"], values=e["full"], tol=0.1, sweep=sweep,
                      sweep_budget_s=sweep_budget_s, product_class=product_class, p=p, timeout=240)
            row["score"], row["parts"], row["notes"] = score(m, targets)
            row["ok"] = row["parts"].get("builds") == 1
            row.update(build_s=m["build_s"], seconds=m["seconds"], size_mm=[round(b - a, 1) for a, b in zip(*m["bbox"])],
                       solids=m["solids"], faces=m["faces"], craft_notes=m["craft_notes"],
                       **({"class_score": m["class_score"]} if "class_score" in m else {}),
                       **({"sweep": {k: m["sweep"][k] for k in ("params", "tested", "seconds")}} if m.get("sweep") else {}))
        except StudioError as err:
            pub = err.public()
            row["error"] = {k: v for k, v in pub.items() if k != "diagnosis"}
            if pub.get("diagnosis"):
                row["diagnosis"] = pub["diagnosis"]
    workers = max(1, min(len(entries), getattr(pool, "size", 1)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(build, range(len(entries))))
    t_build = time.time() - t1
    order = sorted(range(len(rows)), key=lambda i: (-rows[i]["score"], rows[i].get("build_s", 1e9)))
    ranking = [rows[i] for i in order]
    for r in ranking:
        if r.get("craft_notes") is not None and len(r["craft_notes"]) > 6:
            r["craft_notes"] = r["craft_notes"][:6]
    out = {"ranking": ranking, "best": ranking[0]["label"] if ranking and ranking[0]["ok"] else None,
           "built": sum(1 for r in rows if r["ok"]), "failed": sum(1 for r in rows if not r["ok"]),
           "parallel": workers, "seconds": {"warm": round(t_warm, 2), "build_and_score": round(t_build, 2),
                                            "total": round(time.time() - t0, 2)},
           "evidence": "heuristic scores from computed measurements"}
    if not out["best"]:
        st.activity(project or None, "candidates", f"None of {len(rows)} candidates built", by=by)
        raise StudioError("None of the candidates built.", "; ".join(
            f"{r['label']}: {(r.get('error') or {}).get('message', '')}" for r in rows)[:1500], ranking=ranking)
    best = entries[order[0]]
    if keep == "best":
        if p is not None:
            q = st.update_design(p, best["source"], note or f"Best of {len(rows)} candidates: {best['label']}",
                                 best["values"] or None, by, expect_head, best["language"])
            out["project"], out["head"] = q["id"], q["head"]
        else:
            q = st.create_design(name, best["source"], brief, best["values"] or None, best["language"], purpose=purpose)
            out["project"], out["head"] = q["id"], q["head"]
        with st.lock(out["project"]):
            q = st.load(out["project"])
            st.decide(q, "candidates", f"r{q['head']}: best of {len(rows)} candidates, {best['label']} "
                      f"(score {ranking[0]['score']:g}); " + ", ".join(f"{r['label']} {r['score']:g}" for r in ranking[1:]))
            st.save(q)
    st.activity(out.get("project") or project or None, "candidates",
                f"{out['built']} of {len(rows)} candidates built in {out['seconds']['build_and_score']:g} s; best: "
                f"{out['best']}", by=by)
    return out
