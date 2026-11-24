"""The refinement search: after the functional build, try named operators, keep the ones that lower the deficit
vector while every function gate holds, and write each kept one into the source as a @feature(role="refine").

    from form.refine import engine
    job = engine.start(st, pid)                 # background thread; engine.status(st, pid, job) follows it
    r = engine.refine(st, pid)                  # the same, synchronously: {"applied": [...], "head": n, ...}
    engine.undo(st, pid, "refine_parting_line") # one refine feature out again (featureprog.delete_feature)

The search (search()) is independent of Studio: it takes a Design, an Evaluator (builds sources and measures them)
and operators, so tests drive it with stubs and Studio drives it with StudioEvaluator.

  * Greedy beam: width 3, depth up to 4. Each round ranks (state, operator) pairs by the mean deficit of the
    operator's targets x the style's weight x the ledger's prior, keeps the top 6 distinct sources and builds them
    in one batch (StudioEvaluator: form/candidates.run, in parallel kernel workers).
  * Score of a state = its deficit total + COMPLEXITY x the summed cost of its operators (lower is better). A step
    is kept when it lowers the score by at least MIN_GAIN (2 %) of the base deficit total.
  * Hard gates (gate()): the candidate builds; its function checks are not worse (every PASS stays PASS and the
    FAIL count does not rise, the lighten._compare rule); the faces of frozen features (roles fit, access,
    mechanism, interface) are identical (per-feature area, face count and bounding box); the walls stay above the
    minimum; for a game asset, the validator and the triangle budgets pass. A candidate that fails a gate is never
    kept, whatever its score. An operator that fails gates twice is dropped for the rest of the run.
  * Stops when no step gains 2 %, the time budget is spent (CAD 20 s, game 90 s; never past featureprog.time_left()
    when called inside a feature), or no operator is left.
  * Game candidates are judged on geometry only; final_check (one bake and form.game.validate) runs on the result,
    and the path is shortened one step at a time until it passes.

Opt-out at three levels: `refine = False` on the design class, refine="off" from the caller, `[refine] enabled =
false` in studio.toml. Learning: form/refine/ledger.py records every try (local file, never uploaded).
"""
from __future__ import annotations

import ast
import hashlib
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from . import REFINE_ROLE, Analysis, Design, Operator, Patch, operators as all_operators, parse_features, rename_method
from . import styles as styles_mod
from .ledger import Ledger

WIDTH, DEPTH, PER_ROUND = 3, 4, 6
MIN_GAIN = 0.02                   # of the base deficit total
COMPLEXITY = 0.01                 # score penalty per unit of operator cost
GATE_STRIKES = 2
FEATURE_SHARE = 0.5               # a candidate's refine feature may take this share of the time left (its alarm)
FEATURE_MIN_S = 2.0
BUDGET_S = {"cad": 20.0, "game": 90.0}
WALL_FLOOR = {"print": 0.8, "model": 0.5, "game": 0.0}     # mm; print: two perimeters of a 0.4 mm nozzle
WALL_KEEP = 0.8                   # a candidate's thinnest wall stays at least this share of the base's
FROZEN_AREA_REL, FROZEN_MM = 1e-3, 1e-3
BUDGET_TOL = 0.02


# ---- what an evaluator returns -------------------------------------------------------------------------------------

@dataclass
class Evaluation:
    ok: bool
    analysis: Analysis | None = None
    error: str = ""
    checks: list | None = None            # check rows {"id", "label", "status"} (form/checks.py)
    frozen: dict | None = None            # {feature id: {"area", "faces", "lo", "hi"}} (kernel._signature)
    wall_mm: float | None = None          # thinnest wall (2nd percentile of critique.walls)
    game: dict | None = None              # form.game.validate.validate() report
    triangles: int | None = None          # LOD0 triangles (game)
    bbox: tuple | None = None
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


class Evaluator:
    """Builds sources and measures them. evaluate() gets a batch and may build it in parallel."""
    purpose: str = "model"
    budgets: list | None = None           # game: triangles per LOD

    def evaluate(self, sources: list[str], timeout: float | None = None) -> list[Evaluation]:
        raise NotImplementedError

    def final_check(self, source: str) -> Evaluation | None:
        """Optional: the expensive check of the result (a game asset's bake and validator). None: nothing to run."""
        return None


# ---- gates ---------------------------------------------------------------------------------------------------------

def _rollup(rows):
    c = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in rows or []:
        c[r.get("status")] = c.get(r.get("status"), 0) + 1
    return c


def gate(base: Evaluation, cand: Evaluation, purpose: str = "model", budgets: list | None = None) -> list[str]:
    """Why a candidate may not be kept ([] when every gate holds)."""
    if not cand.ok:
        return [f"build: {cand.error or 'did not build'}"]
    out = []
    if base.checks is not None:
        if cand.checks is None:
            out.append("checks: the candidate has no checks to compare")
        else:
            by = {c["id"]: c for c in cand.checks}
            broken = [c["label"] for c in base.checks if c.get("status") == "PASS"
                      and (by.get(c["id"]) or {}).get("status") != "PASS"]
            if broken:
                out.append("checks: no longer pass: " + ", ".join(broken))
            if _rollup(cand.checks)["FAIL"] > _rollup(base.checks)["FAIL"]:
                out.append(f"checks: {_rollup(cand.checks)['FAIL']} FAIL, the base had {_rollup(base.checks)['FAIL']}")
    for fid, a in (base.frozen or {}).items():
        b = (cand.frozen or {}).get(fid)
        if b is None:
            out.append(f"frozen: {fid} has no faces")
            continue
        moved = (abs(b["area"] - a["area"]) > max(FROZEN_AREA_REL * abs(a["area"]), 0.01) or b["faces"] != a["faces"]
                 or any(abs(x - y) > FROZEN_MM for x, y in zip(list(a["lo"]) + list(a["hi"]), list(b["lo"]) + list(b["hi"]))))
        if moved:
            out.append(f"frozen: the faces of {fid} changed (area {a['area']:g} to {b['area']:g} mm2, faces "
                       f"{a['faces']} to {b['faces']})")
    floor = WALL_FLOOR.get(purpose, 0.5)
    if cand.wall_mm is not None and (cand.wall_mm < floor or (base.wall_mm is not None and
                                                              cand.wall_mm < WALL_KEEP * base.wall_mm)):
        out.append(f"wall: thinnest wall {cand.wall_mm:g} mm (floor {floor:g} mm"
                   + (f", base {base.wall_mm:g} mm" if base.wall_mm is not None else "") + ")")
    if purpose == "game":
        if cand.game is not None and not cand.game.get("ok"):
            bad = [c["label"] for c in cand.game.get("checks", []) if c.get("status") != "PASS"]
            out.append("game: validator fails: " + ", ".join(bad[:4]))
        if budgets and cand.triangles is not None and cand.triangles > budgets[0] * (1 + BUDGET_TOL):
            out.append(f"game: LOD0 {cand.triangles} triangles over the budget {budgets[0]}")
    return out


# ---- the search -----------------------------------------------------------------------------------------------------

@dataclass
class Step:
    op: str
    fid: str | None
    label: str
    reason: str
    params: dict
    before: float
    after: float
    deltas: dict
    cost: float


@dataclass
class State:
    source: str
    design: Design
    eval: Evaluation
    steps: list
    cost: float

    @property
    def score(self) -> float:
        return round(self.eval.analysis.total + COMPLEXITY * self.cost, 6)


class Budget:
    """Seconds left: the engine's own budget, capped by featureprog.time_left() when run inside a feature."""
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.clock, self.t0, self.seconds = clock, clock(), float(seconds)

    def left(self) -> float:
        own = self.seconds - (self.clock() - self.t0)
        try:
            from ..featureprog import time_left
            tl = time_left()
        except Exception:                                    # noqa: BLE001
            tl = None
        return own if tl is None else min(own, tl)

    def spent(self) -> float:
        return self.clock() - self.t0


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def _fid(design: Design, op: Operator) -> str:
    base = f"refine_{op.name}"[:44]
    taken = set(design.features)
    fid, i = base, 2
    while fid in taken:
        fid, i = f"{base}_{i}", i + 1
    return fid


def _decorated(code: str, fid: str, label: str, doc: str, budget: float | None = None) -> str:
    code = textwrap.dedent(code).strip("\n")
    lines = [ln for ln in code.splitlines()]
    while lines and lines[0].lstrip().startswith("@"):        # an operator's own decorator gives way to ours
        lines.pop(0)
    b = f", budget={round(max(FEATURE_MIN_S, budget), 1)!r}" if budget is not None else ""
    return f"@feature({label!r}, role={REFINE_ROLE!r}, doc={doc!r}{b})\n" + rename_method("\n".join(lines), fid)


def _apply(state: State, op: Operator, style: str, budget: float | None = None) -> tuple[str, Patch, str | None] | None:
    from ..featureprog import insert_feature
    params = styles_mod.params(style, op)
    try:
        patch = op.apply(state.design, state.eval.analysis, params)
    except Exception:                                         # noqa: BLE001 - a broken operator proposes nothing
        return None
    if patch is None:
        return None
    if isinstance(patch, str):
        patch = Patch(code=patch)
    if not patch.params:
        patch.params = params
    if patch.edit is not None:
        try:
            return patch.edit(state.source), patch, None
        except Exception:                                     # noqa: BLE001
            return None
    if not patch.code.strip():
        return None
    fid = _fid(state.design, op)
    label = patch.label or op.label or op.name.replace("_", " ").capitalize()
    code = _decorated(patch.code, fid, label, patch.reason or label, budget)
    try:
        return insert_feature(state.source, fid, code, after=patch.after), patch, fid
    except Exception:                                         # noqa: BLE001 - code that does not parse or fit
        return None


def engine_budget(purpose: str) -> float:
    """Seconds for one refinement run (the base measurement included): CAD 20 s, game 90 s."""
    return BUDGET_S["game" if purpose == "game" else "cad"]


def _priority(op: Operator, a: Analysis, style: str, ledger: Ledger, product_class) -> float:
    t = [a.deficits.get(k, 0.0) for k in op.targets] or [0.0]
    return (sum(t) / len(t)) * styles_mod.weight(style, op.name) * ledger.prior(product_class, style, op.name)


def search(design: Design, evaluator: Evaluator, ops: list[Operator] | None = None, ledger: Ledger | None = None,
           budget_s: float | None = None, clock: Callable[[], float] = time.monotonic, width: int = WIDTH,
           depth: int = DEPTH, per_round: int = PER_ROUND, base: Evaluation | None = None,
           progress: Callable[[dict], None] | None = None) -> dict:
    """Refine design.source (see the module docstring). Returns {"source", "changed", "applied", "base", "final",
    "rounds", "rejected", "stopped", ...}; nothing is written anywhere except the ledger (when it has a path)."""
    purpose = design.purpose
    budget = Budget(engine_budget(purpose) if budget_s is None else budget_s, clock)
    ledger = ledger or Ledger.memory()
    style = design.style or styles_mod.DEFAULT
    ops = all_operators() if ops is None else list(ops)
    want = ("cage", "material") if purpose == "game" else ("cad", "material")
    ops = sorted((o for o in ops if o.domain in want), key=lambda o: o.name)
    emit = progress or (lambda ev: None)
    if base is None:
        base = evaluator.evaluate([design.source], timeout=budget.left())[0]
    out = {"style": style, "product_class": design.product_class, "purpose": purpose, "rounds": [], "rejected": [],
           "applied": [], "changed": False, "source": design.source}
    if not base.ok or base.analysis is None:
        out.update(stopped=f"the base design did not build: {base.error}", seconds=round(budget.spent(), 2))
        return out
    root = State(design.source, design, base, [], 0.0)
    best, beam = root, [root]
    out["base"] = {"total": base.analysis.total, "deficits": base.analysis.deficits}
    strikes: dict = {}
    tried: list = []                                   # (op name, passed gates)
    seen = {_h(design.source)}
    round_s = 0.0
    stopped = f"depth {depth} reached"
    for d in range(depth):
        if budget.left() <= max(round_s, 0.5):
            stopped = "time budget spent"
            break
        pairs = []
        for bi, s in enumerate(beam):
            done = {st.op for st in s.steps}
            for op in ops:
                if op.name in done or strikes.get(op.name, 0) >= GATE_STRIKES:
                    continue
                ok, _why = op.check(s.design, s.eval.analysis)
                if not ok:
                    continue
                pr = _priority(op, s.eval.analysis, style, ledger, design.product_class)
                if pr > 0:
                    pairs.append((-pr, bi, op.name, s, op))
        pairs.sort(key=lambda x: x[:3])
        batch = []
        for _npr, _bi, _n, s, op in pairs:
            if len(batch) >= per_round:
                break
            made = _apply(s, op, style, FEATURE_SHARE * budget.left())
            if made is None:
                continue
            src, patch, fid = made
            h = _h(src)
            if h in seen:
                continue
            seen.add(h)
            batch.append((s, op, src, patch, fid))
        if not batch:
            stopped = "no operator applies"
            break
        t0 = clock()
        evals = evaluator.evaluate([b[2] for b in batch], timeout=budget.left())
        round_s = clock() - t0
        children, rows = [], []
        for (s, op, src, patch, fid), ev in zip(batch, evals):
            why = gate(s.eval, ev, purpose, evaluator.budgets) if ev.ok and ev.analysis is not None else \
                [f"build: {ev.error or 'not measured'}"]
            if not why:
                # frozen faces are compared with the root too, so drift cannot creep in over several steps
                why = [w for w in gate(base, ev, purpose, evaluator.budgets) if w.startswith(("frozen", "checks"))]
            row = {"round": d + 1, "operator": op.name, "feature": fid}
            if why:
                strikes[op.name] = strikes.get(op.name, 0) + 1
                tried.append((op.name, False, 0.0))
                out["rejected"].append({**row, "why": why})
                rows.append({**row, "kept": False, "why": why[0]})
                continue
            nd = Design(source=src, purpose=purpose, values=design.values, brief=design.brief,
                        product_class=design.product_class, style=style, features=parse_features(src),
                        frozen_boxes=design.frozen_boxes, bbox=ev.bbox or design.bbox)
            step = Step(op.name, fid, patch.label or op.label or op.name, patch.reason, patch.params,
                        s.eval.analysis.total, ev.analysis.total,
                        {k: round(s.eval.analysis.deficits.get(k, 0) - v, 4) for k, v in ev.analysis.deficits.items()},
                        float(op.cost))
            child = State(src, nd, ev, s.steps + [step], s.cost + float(op.cost))
            gain = (s.score - child.score) / max(base.analysis.total, 1e-6)
            tried.append((op.name, True, max(0.0, s.eval.analysis.total - ev.analysis.total)))
            rows.append({**row, "kept": gain >= MIN_GAIN, "total": ev.analysis.total, "gain": round(gain, 4)})
            if gain >= MIN_GAIN:
                children.append(child)
        out["rounds"].append({"round": d + 1, "built": len(batch), "seconds": round(round_s, 2), "candidates": rows})
        emit({"kind": "refine_round", "round": d + 1, "candidates": rows})
        if not children:
            stopped = "no step gains 2 %"
            break
        children.sort(key=lambda c: (c.score, [st.op for st in c.steps]))
        beam = children[:width]
        if beam[0].score < best.score:
            best = beam[0]
    else:
        stopped = f"depth {depth} reached"
    # game: one expensive check of the result; shorten the path until it passes
    final_note = None
    if best.steps and purpose == "game":
        cand = best
        while cand.steps:
            fc = evaluator.final_check(cand.source)
            if fc is None or not gate(base, fc, purpose, evaluator.budgets):
                break
            final_note = f"the final check failed with {len(cand.steps)} steps; shortened"
            cand = _prefix(root, cand, len(cand.steps) - 1)
        best = cand
    # the ledger: kept steps count as accepts with their gain, every other try as a miss
    kept = {st.op: st.before - st.after for st in best.steps}
    for name, passed, _g in tried:
        ledger.record(design.product_class, style, name, accepted=passed and name in kept, gain=kept.get(name, 0.0))
    try:
        ledger.save()
    except OSError:
        pass
    src = best.source
    applied = []
    for st in best.steps:
        doc = (st.reason + " " if st.reason else "") + f"[{_delta_text_steps(st)}]"
        if st.fid:
            src = _redoc(src, st.fid, doc)
        applied.append({"operator": st.op, "feature": st.fid, "label": st.label, "reason": st.reason,
                        "params": st.params, "before": st.before, "after": st.after, "doc": doc,
                        "deltas": {k: v for k, v in st.deltas.items() if abs(v) >= 0.005}})
    out.update(source=src, changed=bool(best.steps), applied=applied, stopped=stopped,
               final={"total": best.eval.analysis.total, "deficits": best.eval.analysis.deficits, "score": best.score},
               seconds=round(budget.spent(), 2), budget_s=budget.seconds, strikes=strikes,
               **({"final_check": final_note} if final_note else {}))
    return out


def _prefix(root: State, s: State, n: int) -> State:
    """The state after the first n steps of s's path (rebuilt from the root's source by re-applying patches is not
    needed: the sources nest, so the prefix is found by deleting the later refine features)."""
    from ..featureprog import delete_feature
    src = s.source
    for st in s.steps[n:]:
        if st.fid:
            src = delete_feature(src, st.fid)
    if n == 0:
        return root
    prev = s.steps[n - 1]
    ev = Evaluation(ok=True, analysis=Analysis(deficits={}, total=prev.after), frozen=root.eval.frozen,
                    wall_mm=root.eval.wall_mm, checks=root.eval.checks)
    return State(src, Design.from_source(src, purpose=root.design.purpose, style=root.design.style),
                 ev, s.steps[:n], sum(x.cost for x in s.steps[:n]))


def _delta_text_steps(st: Step) -> str:
    big = sorted(((k, v) for k, v in st.deltas.items() if abs(v) >= 0.005), key=lambda kv: -abs(kv[1]))[:3]
    return (f"deficit {st.before:.3f} to {st.after:.3f}" + (": " + ", ".join(f"{k} -{v:.2f}" if v > 0 else
                                                                              f"{k} +{-v:.2f}" for k, v in big) if big else "")
            + "; form.refine.analyze, heuristic")


def _redoc(source: str, fid: str, doc: str) -> str:
    """The source with the refine feature's decorator doc set (the method body is left as it is)."""
    from ..featureprog import method_spans, replace_feature
    spans = method_spans(source)
    if fid not in spans:
        return source
    a, b = spans[fid]
    lines = source.splitlines()[a - 1:b]
    body = textwrap.dedent("\n".join(lines))
    tree = ast.parse(body)
    fn = tree.body[0]
    label = parse_features(source).get(fid, {}).get("label") or fid
    start = fn.lineno - 1                                        # the def line (decorators above it)
    code = "\n".join(body.splitlines()[start:])
    return replace_feature(source, fid, f"@feature({label!r}, role={REFINE_ROLE!r}, doc={doc!r})\n" + code)


# ---- opt-outs --------------------------------------------------------------------------------------------------------

def class_opt_out(source: str) -> bool:
    """True when the design class says `refine = False`."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return False
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            for s in n.body:
                if isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "refine" for t in s.targets):
                    try:
                        if ast.literal_eval(s.value) in (False, "off", 0):
                            return True
                    except ValueError:
                        pass
    return False


def enabled(cfg: dict | None, source: str, refine=None) -> tuple[bool, str]:
    """(on, why not) from the three opt-outs, in order: the caller, the config, the design class."""
    if refine in (False, "off", "no", 0):
        return False, "refine=\"off\" was asked for"
    rc = (cfg or {}).get("refine") or {}
    if rc.get("enabled", True) in (False, "off", 0, "false"):
        return False, "[refine] enabled = false in studio.toml"
    if class_opt_out(source):
        return False, "the design class says refine = False"
    if not parse_features(source):
        return False, "only a FeatureDesign can take refine features"
    return True, ""


# ---- Studio: the evaluator and the entry points ----------------------------------------------------------------------

def _decode(b64: str, dtype):
    import base64
    import numpy as np
    return np.frombuffer(base64.b64decode(b64), dtype=dtype)


class StudioEvaluator(Evaluator):
    """Builds candidates with form/candidates.run (parallel kernel workers) and measures each with the kernel's
    view (tessellation, per-feature signature, interface audit, statics) and critique metrics (fillets, creases,
    walls). Checks are form/checks.build on that summary in its model form (solid, interfaces, size, statics);
    print-only checks (overhang, adhesion, envelope) need an export and a slice, so they are left to the real
    pipeline that runs on the committed revision."""

    def __init__(self, st, p: dict, product_class: str | None = None, zones_of=None, frozen: set | None = None):
        from .. import purpose as purpose_mod
        self.st, self.p = st, p
        self.purpose = purpose_mod.of(p)
        self.product_class = product_class
        self.frozen = set(frozen or ())
        self.head = st.rev(p)["values"]
        self.zones_of = zones_of
        self.weights = None
        self.timeout = 180.0

    def _measure(self, src: str, row: dict) -> Evaluation:
        import numpy as np
        from .. import checks as checks_mod
        from .. import purpose as purpose_mod
        from ..studio import H
        from .analyze import Measurement, analyze
        st, p = self.st, self.p
        t0 = time.time()
        rid = st._load_design(src, "python")
        rec = st.recipes[rid]
        full = {**rec.defaults(), **{k: v for k, v in self.head.items() if k in rec.defaults()}}
        key = "pv-" + H(rid, full)
        view = st._k("view", key=key, recipe_id=rid, values=full, tol=0.1, edges=False, p=p, timeout=self.timeout)
        Ps, Ts, tf, off = [], [], [], 0
        for m in view.get("mesh") or []:
            P = _decode(m["positions"], np.float32).reshape(-1, 3).astype(float)
            T = _decode(m["indices"], np.uint32).reshape(-1, 3).astype(np.int64)
            Ps.append(P)
            Ts.append(T + off)
            tf += [m.get("feature") or "part"] * len(T)
            off += len(P)
        metrics = st._k("critique_metrics", key=key, recipe_id=rid, values=full, tol=0.1,
                        product_class=self.product_class, p=p, timeout=self.timeout)
        zones = []
        try:
            from .. import appearance
            zones = appearance.declared(rec, full)
        except Exception:                                      # noqa: BLE001 - no zones is a deficit, not an error
            zones = []
        a = analyze(Measurement(np.concatenate(Ps), np.concatenate(Ts), tri_feature=tf, metrics=metrics, zones=zones,
                                purpose=self.purpose, product_class=self.product_class), weights=self.weights)
        brep = {"valid": bool(row.get("ok")), "solids": row.get("solids", getattr(rec, "solids", 1)),
                "expected_solids": getattr(rec, "solids", 1), "volume_mm3": view.get("volume_mm3", 0.0)}
        rows = checks_mod.build(rec, view, {"brep": brep, "interface_audit": view.get("interface_audit") or []},
                                {"purpose": "model", "process": purpose_mod.process(p)}, None)
        sig = view.get("signature") or {}
        walls = metrics.get("walls") or {}
        return Evaluation(ok=True, analysis=a, checks=rows, frozen={k: sig[k] for k in self.frozen if k in sig},
                          wall_mm=walls.get("p2_mm"), bbox=tuple(map(tuple, view["bbox"])) if view.get("bbox") else None,
                          seconds=round(time.time() - t0 + float(row.get("seconds") or 0), 2),
                          extra={"signature": sig})

    def evaluate(self, sources, timeout=None):
        """Build and measure the batch. With timeout, the engine waits that long (wall clock) and counts what has
        not finished as over budget; that work runs on in its kernel workers and its results are dropped."""
        self.timeout = max(15.0, float(timeout)) if timeout else 180.0
        results: list = [None] * len(sources)
        th = threading.Thread(target=self._batch, args=(sources, results), daemon=True, name="refine-batch")
        th.start()
        th.join(None if timeout is None else max(1.0, float(timeout)))
        return [r if r is not None else Evaluation(ok=False, error="over the time budget") for r in results]

    def _batch(self, sources, results):
        from concurrent.futures import ThreadPoolExecutor
        from .. import candidates
        from ..studio import StudioError
        labels = [f"refine {i}" for i in range(len(sources))]
        try:
            r = candidates.run(self.st, [{"label": lb, "source": s} for lb, s in zip(labels, sources)],
                               project=self.p["id"], keep="none", sweep=False, product_class=self.product_class,
                               by="refine")
            by = {row["label"]: row for row in r["ranking"]}
        except StudioError as e:
            by = {row["label"]: row for row in (e.extra.get("ranking") or [])}

        def one(i):
            row = by.get(labels[i]) or {}
            if not row.get("ok"):
                err = row.get("error") or {}
                results[i] = Evaluation(ok=False, error=(err.get("message") if isinstance(err, dict) else str(err))
                                        or "; ".join(row.get("notes") or []) or "did not build")
                return
            try:
                results[i] = self._measure(sources[i], row)
            except Exception as e:                               # noqa: BLE001 - a candidate that cannot be measured
                results[i] = Evaluation(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        pool = getattr(self.st.kernel, "size", 1)
        with ThreadPoolExecutor(max_workers=max(1, min(len(sources), pool))) as ex:
            list(ex.map(one, range(len(sources))))


def prepare(st, pid: str, refine=None, style: str | None = None) -> tuple[Design | None, StudioEvaluator | None, str]:
    """(design, evaluator, why not) for a project's head revision."""
    from .. import critique
    p = st.load(pid)
    src = st.source_text(p) or ""
    on, why = enabled(getattr(st, "cfg", {}), src, refine)
    if not on:
        return None, None, why
    feats = parse_features(src)
    frozen = {k for k, f in feats.items() if f.get("role") in ("fit", "access", "mechanism", "interface")}
    brief = (p.get("brief") or {}).get("text", "") or ""
    pc = critique.product_class(p)
    sty = style or styles_mod.detect(brief + " " + (p.get("name") or ""), pc)
    ev = StudioEvaluator(st, p, pc, frozen=frozen)
    ev.weights = styles_mod.deficit_weights(sty)
    d = Design(source=src, purpose=ev.purpose, values=st.rev(p)["values"], brief=brief, product_class=pc, style=sty,
               features=feats)
    return d, ev, ""


def refine(st, pid: str, refine=None, style: str | None = None, budget_s: float | None = None, commit: bool = True,
           ops: list | None = None, ledger: Ledger | None = None, progress=None) -> dict:
    """Refine a project's head revision. With commit, the kept steps land as one new revision "Refined: N changes"
    (origin "refine"); nothing is committed when no step was kept or the head moved meanwhile."""
    d, ev, why = prepare(st, pid, refine, style)
    if d is None:
        return {"project": pid, "skipped": why}
    p = st.load(pid)
    head = p["head"]
    t0 = time.monotonic()
    base = ev.evaluate([d.source])[0]
    if base.ok:
        sig = base.extra.get("signature") or {}
        d.frozen_boxes = {k: (tuple(sig[k]["lo"]), tuple(sig[k]["hi"])) for k in d.frozen if k in sig}
        d.bbox = base.bbox
    led = ledger if ledger is not None else Ledger.open()
    total = engine_budget(d.purpose) if budget_s is None else float(budget_s)
    r = search(d, ev, ops=ops, ledger=led, budget_s=max(0.0, total - (time.monotonic() - t0)), base=base,
               progress=progress)
    r["budget_s"] = total
    r.update(project=pid, from_rev=head)
    if commit and r["changed"]:
        n = len(r["applied"])
        note = f"Refined: {n} change{'s' if n != 1 else ''} (" + ", ".join(a["label"] for a in r["applied"]) + ")"
        try:
            q = st.update_design(st.load(pid), r["source"], note, None, "refine", head, "python")
            r["head"] = q["head"]
        except Exception as e:                                   # noqa: BLE001 - the head moved, or it did not build
            r["commit_error"] = getattr(e, "public", lambda: {"message": str(e)})()
    return r


_JOBS: dict = {}


def start(st, pid: str, refine_flag=None, **kw) -> str | None:
    """Refinement as a background job after the functional build. Returns the job id (None when it is off)."""
    p = st.load(pid)
    on, why = enabled(getattr(st, "cfg", {}), st.source_text(p) or "", refine_flag)
    if not on:
        return None
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "project": pid, "state": "running", "started": time.time(), "rounds": []}
    _JOBS[jid] = job

    def run():
        try:
            job["result"] = refine(st, pid, refine_flag, progress=lambda ev: job["rounds"].append(ev), **kw)
            job["state"] = "done"
        except Exception as e:                                   # noqa: BLE001 - reported on the job
            job.update(state="failed", error=f"{type(e).__name__}: {e}"[:400])
        job["finished"] = time.time()
    threading.Thread(target=run, daemon=True, name=f"refine-{pid}").start()
    return jid


def status(jid: str) -> dict | None:
    return _JOBS.get(jid)


def undo(st, pid: str, fid: str | None = None, expect_head: int | None = None) -> dict:
    """Take refine features out again: one (fid) or all of them, as one new revision."""
    from ..featureprog import delete_feature
    from ..studio import StudioError
    p = st.load(pid)
    src = st.source_text(p) or ""
    feats = parse_features(src)
    ids = [k for k, f in feats.items() if f.get("role") == REFINE_ROLE]
    if fid is not None:
        if fid not in ids:
            raise StudioError(f"No refine feature “{fid}” in this design.", "Refine features: " + (", ".join(ids) or "none"))
        ids = [fid]
    if not ids:
        raise StudioError("This design has no refine features.", "")
    for k in ids:
        src = delete_feature(src, k)
    return st.update_design(p, src, "Undid refinement: " + ", ".join(ids), None, "refine",
                            p["head"] if expect_head is None else expect_head, "python")
