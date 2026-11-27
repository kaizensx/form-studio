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
  * Stops when no step gains 2 %, the time budget is spent (CAD 20 s, game 300 s; never past featureprog.time_left()
    when called inside a feature), or no operator is left.
  * Game candidates are judged on a quick bake each (form/refine/game_eval.py: the game evidence of 256 px maps);
    final_check (one full bake and form.game.validate) runs on the result,
    and the path is shortened one step at a time until it passes.

Opt-out at three levels: `refine = False` on the design class, refine="off" from the caller, `[refine] enabled =
false` in studio.toml. Game assets are opt-in: refine="on", the design turned on (refine_design action="on"), or
`[refine] game = true` (Settings › Refine game assets). Learning: form/refine/ledger.py records every try (local file, never uploaded).
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
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
# a candidate's refine feature carries this alarm (seconds). A constant, not a share of the time left: the candidate's
# source (and so its checkpoints and its result) is then the same on a fast and a slow machine
FEATURE_BUDGET_S = 10.0
FEATURE_MIN_S = 2.0
BUDGET_S = {"cad": 20.0, "game": 300.0}      # game: every candidate gets a quick bake (game_eval)
FINAL_RESERVE_S = 5.0             # CAD: of the budget, kept for the final check (STL export and mesh audit, twice)
WALL_FLOOR = {"print": 1.2, "model": 0.5, "game": 0.0}     # mm; form/wallguard.py floor_for (print: 0.4 mm nozzle)
WALL_KEEP = 0.8                   # a candidate's thinnest wall stays at least this share of the base's
FROZEN_AREA_REL, FROZEN_BREP_MM = 1e-3, 1e-3      # B-rep faces: exact area (relative) and centre (mm)
FROZEN_TESS_MM = 0.1              # without a B-rep face list (a texture): the view's tessellation tolerance
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


def frozen_moved(a: dict, b: dict) -> str:
    """Why the faces of one frozen feature differ between two builds ("" when they are the same). With the B-rep
    face list on both sides (kernel._signature "brep": surface type, exact area and centre per face) faces are
    compared one for one (FROZEN_AREA_REL, FROZEN_BREP_MM); else the tessellated area and box, at the view's
    tessellation tolerance: a neighbour's fillet changes how a face's edges are split, not the face."""
    ba, bb = a.get("brep"), b.get("brep")
    if ba is not None and bb is not None:
        if len(ba) != len(bb):
            return f"{len(ba)} to {len(bb)} faces"
        for x, y in zip(ba, bb):
            if x[0] != y[0]:
                return f"a {str(x[0]).lower()} face became {str(y[0]).lower()}"
            if abs(x[1] - y[1]) > max(FROZEN_AREA_REL * abs(x[1]), 1e-3):
                return f"face area {x[1]:g} to {y[1]:g} mm2"
            if any(abs(p - q) > FROZEN_BREP_MM for p, q in zip(x[2:], y[2:])):
                return "a face moved"
        return ""
    if b["faces"] != a["faces"]:
        return f"faces {a['faces']} to {b['faces']}"
    if abs(b["area"] - a["area"]) > max(FROZEN_AREA_REL * abs(a["area"]), 0.01):
        return f"area {a['area']:g} to {b['area']:g} mm2"
    if any(abs(x - y) > FROZEN_TESS_MM for x, y in zip(list(a["lo"]) + list(a["hi"]), list(b["lo"]) + list(b["hi"]))):
        return "its bounding box moved"
    return ""


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
        why = frozen_moved(a, b)
        if why:
            out.append(f"frozen: the faces of {fid} changed ({why})")
    # integrity: a refinement must not fold a skin, thin a shell out, leave an invalid stage or spoil the class outline
    bi, ci = base.extra.get("integrity") or {}, cand.extra.get("integrity") or {}
    if ci and bi:
        if ci.get("folds", 0) > bi.get("folds", 0):
            out.append(f"integrity: the skin folds ({ci['folds']} sample pairs, the base {bi.get('folds', 0)})")
        if ci.get("thin_fraction", 0) > max(0.01, bi.get("thin_fraction", 0) + 0.005):
            out.append(f"integrity: {ci['thin_fraction'] * 100:.1f} % of the walls are thin (the base "
                       f"{bi.get('thin_fraction', 0) * 100:.1f} %)")
        if ci.get("invalid_stages", 0) > bi.get("invalid_stages", 0):
            out.append("integrity: a stage is not a valid solid")
        if bi.get("class_score") is not None and ci.get("class_score") is not None \
                and ci["class_score"] < bi["class_score"] - 0.02:
            out.append(f"silhouette: the class outline score fell from {bi['class_score']:.2f} to {ci['class_score']:.2f}")
    floor = WALL_FLOOR.get(purpose, 0.5)
    # under the floor fails when the refinement thinned it (a base already under it is the design's own wall: the
    # structure check reports that; a refinement may still round it), and no candidate loses more than WALL_KEEP
    thinned = base.wall_mm is None or cand.wall_mm is None or cand.wall_mm < base.wall_mm - 0.05
    if cand.wall_mm is not None and ((cand.wall_mm < floor and thinned) or (base.wall_mm is not None and
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
    domain: str = "cad"
    edit: dict | None = None          # a source edit (no feature method): {"before", "after"} text, or {"ops": [...]}


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
    """Seconds for one refinement run (the base measurement included): CAD 20 s, game 300 s."""
    return BUDGET_S["game" if purpose == "game" else "cad"]


def _priority(op: Operator, a: Analysis, style: str, ledger: Ledger, product_class) -> float:
    t = [a.deficits.get(k, 0.0) for k in op.targets] or [0.0]
    return (sum(t) / len(t)) * styles_mod.weight(style, op.name) * ledger.prior(product_class, style, op.name)


def search(design: Design, evaluator: Evaluator, ops: list[Operator] | None = None, ledger: Ledger | None = None,
           budget_s: float | None = None, clock: Callable[[], float] = time.monotonic, width: int = WIDTH,
           depth: int = DEPTH, per_round: int = PER_ROUND, base: Evaluation | None = None,
           progress: Callable[[dict], None] | None = None, cancel: Callable[[], bool] | None = None) -> dict:
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
        if cancel is not None and cancel():
            stopped = "cancelled: the design changed"
            break
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
            made = _apply(s, op, style, FEATURE_BUDGET_S)
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
        emit({"kind": "refine_try", "round": d + 1, "operators": [b[1].name for b in batch],
              "labels": [b[3].label or b[1].label or b[1].name for b in batch]})
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
                        float(op.cost), op.domain, None if fid else edit_record(s.source, src, op.domain))
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
    if best.steps:
        # the expensive check of the result (a game asset's bake; a CAD design's exported STL and STEP checks),
        # against the same check of the base when the evaluator compares like with like; shortened until it passes
        ref = base
        if getattr(evaluator, "final_base", False):
            emit({"kind": "refine_final", "text": "Checking the exported mesh"})
            ref = evaluator.final_check(root.source) or base
        steps, src = list(best.steps), best.source
        dropped = []
        while steps:
            fc = evaluator.final_check(src)
            why = [] if fc is None else gate(ref, fc, purpose, evaluator.budgets)
            if not why:
                break
            # take out the last step that changed the geometry (a material edit cannot fail a mesh or a bake check),
            # else the last step; the others stay
            k = max((i for i, st in enumerate(steps) if st.fid or st.domain == "cage"), default=len(steps) - 1)
            st = steps.pop(k)
            src = delete_feature_or_edit(src, st)
            dropped.append(st.op)
            final_note = f"the final check failed ({why[0]}); took out {', '.join(dropped)}"
        if dropped:
            ev2 = evaluator.evaluate([src])[0] if steps else root.eval
            if steps and (not ev2.ok or ev2.analysis is None):
                steps, src, ev2 = [], root.source, root.eval
            nd = Design.from_source(src, purpose=purpose, style=style)
            best = State(src, nd, ev2, steps, sum(x.cost for x in steps))
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
        applied.append({"operator": st.op, "feature": st.fid, "id": st.fid or f"refine_{st.op}",
                        "kind": "feature" if st.fid else ("ops" if (st.edit or {}).get("ops") is not None else "edit"),
                        "domain": st.domain, "label": st.label, "reason": st.reason,
                        "params": st.params, "before": st.before, "after": st.after, "doc": doc,
                        "deltas": {k: v for k, v in st.deltas.items() if abs(v) >= 0.005},
                        **({"edit": st.edit} if st.edit else {})})
    out.update(source=src, changed=bool(best.steps), applied=applied, stopped=stopped,
               final={"total": best.eval.analysis.total, "deficits": best.eval.analysis.deficits, "score": best.score},
               seconds=round(budget.spent(), 2), budget_s=budget.seconds, strikes=strikes,
               **({"final_check": final_note} if final_note else {}))
    return out


def edit_record(old: str, new: str, domain: str) -> dict:
    """What a source edit changed, so it can be undone alone: the cage ops it appended (REFINE_OPS), or the one
    block of lines that differs ({"before", "after"})."""
    if domain == "cage":
        try:
            from .ops_cage import refine_ops_of
            a, b = refine_ops_of(old), refine_ops_of(new)
            if b[:len(a)] == a:
                return {"ops": b[len(a):]}
        except Exception:                                     # noqa: BLE001 - fall back to the text block
            pass
    x, y = old.splitlines(), new.splitlines()
    i = 0
    while i < min(len(x), len(y)) and x[i] == y[i]:
        i += 1
    j = 0
    while j < min(len(x), len(y)) - i and x[-1 - j] == y[-1 - j]:
        j += 1
    return {"before": "\n".join(x[i:len(x) - j]), "after": "\n".join(y[i:len(y) - j]), "line": i + 1}


def delete_feature_or_edit(src: str, st: Step) -> str:
    """The source with one kept step taken out (its refine feature, or its recorded edit)."""
    from ..featureprog import delete_feature
    if st.fid:
        return delete_feature(src, st.fid)
    if st.edit:
        try:
            return undo_edit(src, st.edit)
        except ValueError:
            return src
    return src


def _prefix(root: State, s: State, n: int) -> State:
    """The state after the first n steps of s's path (rebuilt from the root's source by re-applying patches is not
    needed: the sources nest, so the prefix is found by deleting the later refine features)."""
    from ..featureprog import delete_feature
    src = s.source
    for st in reversed(s.steps[n:]):
        if st.fid:
            src = delete_feature(src, st.fid)
        elif st.edit:
            src = undo_edit(src, st.edit)
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


def kind_of(source: str) -> tuple[str | None, str]:
    """How a source takes refinement: "feature" (a FeatureDesign: refine features go after its features), "recipe"
    (a plain Recipe: form/refine/adapter.py wraps its build() as the skeleton feature first), "cage" (a game cage
    source: cage and material operators edit REFINE_OPS and materials()), or (None, why not)."""
    from . import adapter
    if not (source or "").strip():
        return None, "the design has no source (a built-in recipe takes its finish from its parameters)"
    if re.search(r"^CAGES\s*=", source, re.M):
        return "cage", ""
    if parse_features(source):                  # a FeatureDesign, or a Recipe wrapped before
        return "feature", ""
    why = adapter.why_not(source)
    if why:
        return None, f"this design cannot take refine features: {why}"
    return "recipe", ""


ASKED_ON = (True, "on", "yes", 1, "force")


def is_game(p: dict | None, source: str = "") -> bool:
    """True for a game asset: a design made for a game engine (purpose "game") or a game cage source."""
    if (p or {}).get("purpose") == "game":
        return True
    return bool(re.search(r"^CAGES\s*=", source or "", re.M))


def enabled(cfg: dict | None, source: str, refine=None, game: bool | None = None) -> tuple[bool, str]:
    """(on, why not) from the opt-outs, in order: the caller, FORM_REFINE=off, the config, the design class; then
    whether the source can take refinement at all (kind_of). A game asset (game=True, or a cage source when game is
    None) is refined only when it is asked for: refine="on" (refine_design action="on" or "rerun") or
    [refine] game = true (Settings › Refine game assets). CAD designs are refined unless turned off."""
    import os
    if refine in (False, "off", "no", 0):
        return False, "refine=\"off\" was asked for"
    if str(os.environ.get("FORM_REFINE", "")).lower() in ("off", "0", "false", "no"):
        return False, "FORM_REFINE=off in the environment"
    rc = (cfg or {}).get("refine") or {}
    if rc.get("enabled", True) in (False, "off", 0, "false"):
        return False, "refinement is turned off in Settings ([refine] enabled = false)"
    if game is None:
        game = is_game(None, source)
    if game and refine not in ASKED_ON and rc.get("game", False) in (False, "off", 0, "false", None):
        return False, ("refinement of game assets is off unless you turn it on (Settings › Refine game assets, or "
                       "refine_design action=\"on\" for this design)")
    if class_opt_out(source):
        return False, "the design class says refine = False"
    kind, why = kind_of(source)
    if kind is None:
        return False, why
    return True, ""


def asked(p: dict | None, refine=None):
    """The refine request for a project: the caller's, or "on" when the design was turned on (refine_design
    action="on"), or "off" when it was turned off."""
    if refine in (None, "auto", ""):
        v = (p or {}).get("refine")
        if v in ("on", "off"):
            return v
    return refine


# ---- Studio: the evaluator and the entry points ----------------------------------------------------------------------

def _decode(b64: str, dtype):
    import base64
    import numpy as np
    return np.frombuffer(base64.b64decode(b64), dtype=dtype)


def integrity(metrics: dict) -> dict:
    """What gate() compares for integrity, from critique metrics: folded skin sample pairs, the thin-wall share,
    stages that are not valid solids (craft notes) and the product class's outline score."""
    m = metrics or {}
    fo, wl = m.get("folds") or {}, m.get("walls") or {}
    cl = ((m.get("form") or {}).get("class")) or {}
    return {"folds": int(fo.get("folds") or 0),
            "thin_fraction": float(wl.get("thin_fraction") or 0.0) if wl.get("samples") else 0.0,
            "invalid_stages": sum(1 for n in m.get("craft_notes") or [] if "not a valid solid" in str(n)),
            "class_score": cl.get("score")}


class StudioEvaluator(Evaluator):
    """Builds candidates with form/candidates.run (parallel kernel workers) and measures each with the kernel's
    view (tessellation, per-feature signature, interface audit, statics) and critique metrics (fillets, creases,
    walls). Checks are form/checks.build on that summary in its model form (solid, interfaces, size, statics);
    print-only checks (overhang, adhesion, envelope) need an export and a slice, so they are left to the real
    pipeline that runs on the committed revision.

    Measurements are kept: a source measured once is not measured again (memo), and a candidate whose built solid is
    the same as one already measured (volume, area, faces, triangles, box) reuses that geometry's measures; only its
    material zones and the analysis are computed again (a material operator, or an operator that found nothing to
    do). The base is measured from the head's build, not built again."""

    def __init__(self, st, p: dict, product_class: str | None = None, zones_of=None, frozen: set | None = None,
                 texture: set | None = None):
        from .. import purpose as purpose_mod
        self.st, self.p = st, p
        self.purpose = purpose_mod.of(p)
        self.product_class = product_class
        self.frozen = set(frozen or ())
        self.texture = set(texture or ())
        self.head = st.rev(p)["values"]
        # features the head already leaves out (a partial revision): a candidate that leaves out the same ones built
        self.skipped = {x.get("feature") for x in (st.rev(p).get("partial") or {}).get("skipped") or []}
        self.zones_of = zones_of
        self.weights = None
        self.timeout = 180.0
        self._memo: dict = {}
        self._geo: dict = {}
        self._gen = 0                          # batches started under an older generation are stale (close())
        self.stats = {"measured": 0, "geometry_reused": 0, "memo": 0}

    @staticmethod
    def _fingerprint(view: dict) -> tuple:
        bb = view.get("bbox") or [[0, 0, 0], [0, 0, 0]]
        return (round(float(view.get("volume_mm3") or 0), 3), round(float(view.get("area_mm2") or 0), 3),
                int(view.get("faces") or 0), int(view.get("triangles") or 0),
                tuple(round(float(x), 3) for c in bb for x in c))

    def _measure(self, src: str, row: dict) -> Evaluation:
        import numpy as np
        from .. import checks as checks_mod
        from .. import purpose as purpose_mod
        from ..studio import H
        from .analyze import Measurement, analyze
        st, p = self.st, self.p
        t0 = time.time()
        h = _h(src)
        if h in self._memo:
            self.stats["memo"] += 1
            return self._memo[h]
        rid = st._load_design(src, "python")
        rec = st.recipes[rid]
        full = {**rec.defaults(), **{k: v for k, v in self.head.items() if k in rec.defaults()}}
        key = "pv-" + H(rid, full)
        view = st._k("view", key=key, recipe_id=rid, values=full, tol=0.1, edges=False, p=p, timeout=self.timeout)
        fp = self._fingerprint(view)
        geo = self._geo.get(fp)
        if geo is None:
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
            geo = {"P": np.concatenate(Ps), "T": np.concatenate(Ts), "tf": tf, "metrics": metrics}
            self._geo[fp] = geo
            self.stats["measured"] += 1
        else:
            self.stats["geometry_reused"] += 1
        zones = []
        try:
            from .. import appearance
            zones = appearance.declared(rec, full)
        except Exception:                                      # noqa: BLE001 - no zones is a deficit, not an error
            zones = []
        a = analyze(Measurement(geo["P"], geo["T"], tri_feature=geo["tf"], metrics=geo["metrics"], zones=zones,
                                purpose=self.purpose, product_class=self.product_class,
                                extra={"texture_features": self.texture}), weights=self.weights)
        a.measures["surface_mix"] = geo["metrics"].get("surface_mix") or {}     # what the operators' preconditions read
        brep = {"valid": bool(row.get("ok", True)), "solids": row.get("solids", getattr(rec, "solids", 1)),
                "expected_solids": getattr(rec, "solids", 1), "volume_mm3": view.get("volume_mm3", 0.0)}
        rows = checks_mod.build(rec, view, {"brep": brep, "interface_audit": view.get("interface_audit") or []},
                                {"purpose": "model", "process": purpose_mod.process(p)}, None)
        sig = view.get("signature") or {}
        walls = geo["metrics"].get("walls") or {}
        statics = view.get("statics") or {}
        sids = [f"statics.{c['id']}" for c in statics.get("checks") or [] if isinstance(c, dict) and c.get("id")]
        if "tip_force_n" in statics:
            sids.append("statics.stability")
        out = Evaluation(ok=True, analysis=a, checks=rows, frozen={k: sig[k] for k in self.frozen if k in sig},
                         wall_mm=walls.get("p2_mm"), bbox=tuple(map(tuple, view["bbox"])) if view.get("bbox") else None,
                         seconds=round(time.time() - t0 + float(row.get("seconds") or 0), 2),
                         extra={"signature": sig, "statics_ids": sids, "fingerprint": fp,
                                "integrity": integrity(geo["metrics"])})
        self._memo[h] = out
        return out

    final_base = True                     # final_check(base) is the reference for final_check(result)

    def final_check(self, source: str) -> Evaluation | None:
        """The checks the pipeline runs on an exported design, on this source: STL export at the pipeline's
        tolerance, its mesh audit (closed, manifold) and STL-to-CAD volume, and FreeCAD's re-import of the STEP when
        FreeCAD is installed. None when it cannot run (the engine then keeps its result as measured)."""
        import shutil
        import tempfile as _tf
        from pathlib import Path as _P
        from .. import cad_bridges, checks as checks_mod
        from .. import purpose as purpose_mod
        from ..studio import H, STL_TOL
        h = "final-" + _h(source)
        if h in self._memo:
            return self._memo[h]
        st, p = self.st, self.p
        tmp = _P(_tf.mkdtemp(prefix="form-refine-final-"))
        try:
            rid = st._load_design(source, "python")
            rec = st.recipes[rid]
            full = {**rec.defaults(), **{k: v for k, v in self.head.items() if k in rec.defaults()}}
            key = "pv-" + H(rid, full)
            r = st._k("export", key=key, recipe_id=rid, values=full, out_dir=str(tmp), name="refine",
                      orientation=p.get("orientation") or "as_modelled", tol=STL_TOL, p=p, timeout=300)
            a = st._k("analyse", key=key, recipe_id=rid, values=full, stl_path=str(r["stl"]), nozzle=0.4,
                      envelope=[1e6, 1e6, 1e6], orientation=p.get("orientation") or "as_modelled", p=p, margin=0.0,
                      timeout=300)
            summary = st._k("summary", key=key, recipe_id=rid, values=full, tol=0.1, p=p, timeout=300)
            rows = checks_mod.build(rec, summary, a, {"orientation": p.get("orientation"), "purpose": "model",
                                                      "process": purpose_mod.process(p)}, None)
            fc = st._freecad()
            if fc and r.get("step"):
                res = cad_bridges.freecad_recheck(fc, _P(r["step"]), timeout=120)
                rows.append(cad_bridges.recheck_item(res, a["brep"]["volume_mm3"], summary["bbox"]))
            out = Evaluation(ok=True, checks=rows, analysis=None)
        except Exception as e:                                    # noqa: BLE001 - not checked: say so, keep going
            out = None
            self.stats["final_error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._memo[h] = out
        return out

    def prime(self, src: str) -> None:
        """Build a source once so its features' checkpoints exist for the candidates (a wrapped Recipe's stages)."""
        from ..studio import H
        try:
            rid = self.st._load_design(src, "python")
            rec = self.st.recipes[rid]
            full = {**rec.defaults(), **{k: v for k, v in self.head.items() if k in rec.defaults()}}
            self.st._k("summary", key="pv-" + H(rid, full), recipe_id=rid, values=full, tol=0.1, p=self.p,
                       timeout=600)
        except Exception:                                         # noqa: BLE001 - the candidates build it then
            pass

    def measure_base(self, src: str) -> Evaluation:
        """The base design measured from its own build (the head's, already in the kernel's cache): no candidate
        build. A source that is not the head's (a wrapped Recipe) is built once here."""
        try:
            return self._measure(src, {"ok": True})
        except Exception as e:                                    # noqa: BLE001 - reported as a base that did not build
            return Evaluation(ok=False, error=f"{type(e).__name__}: {e}"[:300])

    def evaluate(self, sources, timeout=None):
        """Build and measure the batch. With timeout, the engine waits that long (wall clock) and counts what has
        not finished as over budget; that work runs on in its kernel workers and its results are dropped."""
        self.timeout = max(15.0, float(timeout)) if timeout else 180.0
        self._gen += 1
        gen = self._gen
        results: list = [None] * len(sources)
        todo = []
        for i, s in enumerate(sources):
            if _h(s) in self._memo:
                self.stats["memo"] += 1
                results[i] = self._memo[_h(s)]
            else:
                todo.append(i)
        if todo:
            sub: list = [None] * len(todo)
            th = threading.Thread(target=self._batch, args=([sources[i] for i in todo], sub, gen), daemon=True,
                                  name="refine-batch")
            th.start()
            th.join(None if timeout is None else max(1.0, float(timeout)))
            if th.is_alive():
                self.close()                 # what is left of the batch is stale: nothing more starts or is measured
            for k, i in enumerate(todo):
                results[i] = sub[k]
        return [r if r is not None else Evaluation(ok=False, error="over the time budget") for r in results]

    def close(self) -> None:
        """Make every batch still running stale (the engine stopped waiting for it, or the run is over): a stale
        batch starts no more candidate builds and measures nothing it gets back, so an abandoned batch does not hold
        a kernel worker or the server's interpreter while the next design builds. A build already in a kernel worker
        finishes there (stopping it would kill the worker and its cache)."""
        self._gen += 1

    def _batch(self, sources, results, gen=None):
        from concurrent.futures import ThreadPoolExecutor
        from .. import candidates
        from ..studio import StudioError
        labels = [f"refine {i}" for i in range(len(sources))]
        gen = self._gen if gen is None else gen

        def one(i):
            # one candidate per call, so a quick one (a material edit) lands while a slow fillet still builds
            if gen != self._gen:
                return
            try:
                r = candidates.run(self.st, [{"label": labels[i], "source": sources[i]}], project=self.p["id"],
                                   keep="none", sweep=False, product_class=self.product_class, by="refine")
                rows = r["ranking"]
            except StudioError as e:
                rows = e.extra.get("ranking") or []
            row = next((x for x in rows if x.get("label") == labels[i]), {})
            notes = row.get("notes") or []
            gone = {f.strip() for n in notes if str(n).startswith("feature(s) skipped: ")
                    for f in str(n)[len("feature(s) skipped: "):].split(",")}
            if not row.get("ok") and gone and gone <= self.skipped and not row.get("error"):
                row = {**row, "ok": True}            # only what the head leaves out already
            if not row.get("ok"):
                err = row.get("error") or {}
                results[i] = Evaluation(ok=False, error=(err.get("message") if isinstance(err, dict) else str(err))
                                        or "; ".join(row.get("notes") or []) or "did not build")
                return
            if gen != self._gen:                                 # stale: its result is dropped unmeasured
                return
            try:
                results[i] = self._measure(sources[i], row)
            except Exception as e:                               # noqa: BLE001 - a candidate that cannot be measured
                results[i] = Evaluation(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        pool = getattr(self.st.kernel, "size", 1)
        with ThreadPoolExecutor(max_workers=max(1, min(len(sources), pool))) as ex:
            list(ex.map(one, range(len(sources))))


def prepare(st, pid: str, refine=None, style: str | None = None,
            game: dict | None = None) -> tuple[Design | None, Evaluator | None, str]:
    """(design, evaluator, why not) for a project's head revision. A plain Recipe is wrapped first
    (form/refine/adapter.py), so design.source is the source the refine features go into."""
    from .. import critique
    from . import adapter
    from .analyze import texture_features
    p = st.load(pid)
    src = st.source_text(p) or ""
    on, why = enabled(getattr(st, "cfg", {}), src, asked(p, refine), is_game(p, src))
    if not on:
        return None, None, why
    kind, _why = kind_of(src)
    if kind == "recipe":
        src = adapter.wrap(src)
    feats = parse_features(src)
    frozen = {k for k, f in feats.items() if f.get("role") in ("fit", "access", "mechanism", "interface")}
    brief = (p.get("brief") or {}).get("text", "") or ""
    pc = critique.product_class(p)
    sty = style or styles_mod.detect(brief + " " + (p.get("name") or ""), pc)
    from .. import purpose as purpose_mod
    if kind == "cage":                          # a cage: Blender replays it, a quick bake per candidate, one full bake
        from .game_eval import GameEvaluator
        ev = GameEvaluator(st, p, pc, frozen=frozen, **(game or {}))
    else:
        ev = StudioEvaluator(st, p, pc, frozen=frozen, texture=texture_features(feats))
    ev.weights = styles_mod.deficit_weights(sty)
    d = Design(source=src, purpose=ev.purpose, values=st.rev(p)["values"], brief=brief, product_class=pc, style=sty,
               features=feats, head=p["head"])
    return d, ev, ""


def _base_for(d: Design, ev: Evaluator, base: Evaluation) -> None:
    """What the operators read from the base build: frozen boxes, the box, the base's check ids."""
    if not base.ok:
        return
    sig = base.extra.get("signature") or {}
    d.frozen_boxes = {k: (tuple(sig[k]["lo"]), tuple(sig[k]["hi"])) for k in d.frozen if k in sig}
    d.bbox = base.bbox
    d.checks = {c["id"]: c.get("status") for c in base.checks or [] if isinstance(c, dict) and c.get("id")}
    for k in base.extra.get("statics_ids") or []:
        d.checks[k] = next((c.get("status") for c in base.checks or [] if f"statics.{c.get('id')}" == k), "PASS")


def refine(st, pid: str, refine=None, style: str | None = None, budget_s: float | None = None, commit: bool = True,
           ops: list | None = None, ledger: Ledger | None = None, progress=None, cancel=None,
           game: dict | None = None) -> dict:
    """Refine a project's head revision. With commit, the kept steps land as one new revision "Refined: N changes"
    (origin "refine"), with what each change was in the revision's "refine" record; nothing is committed when no
    step was kept or the head moved meanwhile."""
    d, ev, why = prepare(st, pid, refine, style, game)
    if d is None:
        return {"project": pid, "skipped": why}
    # the head the source was read from: an edit that lands while refine runs makes the commit below refuse (409)
    # rather than put a refinement of the old source on top of it
    head = d.head
    p = st.load(pid)
    t0 = time.monotonic()
    emit = progress or (lambda e: None)
    emit({"kind": "refine_base", "text": "Measuring the design"})
    from . import adapter
    head_src = st.source_text(p, head) or ""
    wrapped = adapter.is_wrapped(d.source) and d.source != head_src
    # a wrapped Recipe has the head's geometry: measure the head's own build (in the kernel's cache), not a new one
    measured = head_src if wrapped else d.source
    base = ev.measure_base(measured) if hasattr(ev, "measure_base") else ev.evaluate([measured])[0]
    _base_for(d, ev, base)
    prime_s = 0.0
    if wrapped and base.ok and hasattr(ev, "prime"):
        # once per design: the wrapped skeleton is built so its stages are checkpoints every candidate loads (a
        # Recipe's own build time, which the time budget below does not count)
        emit({"kind": "refine_base", "text": "Preparing the design for refine features"})
        t1 = time.monotonic()
        ev.prime(d.source)
        prime_s = time.monotonic() - t1
    led = ledger if ledger is not None else Ledger.open()
    total = engine_budget(d.purpose) if budget_s is None else float(budget_s)
    reserve = FINAL_RESERVE_S if getattr(ev, "final_base", False) else 0.0   # the exported-mesh check of the result
    try:
        r = search(d, ev, ops=ops, ledger=led, budget_s=max(0.0, total - reserve - (time.monotonic() - t0 - prime_s)),
                   base=base, progress=progress, cancel=cancel)
    finally:
        if hasattr(ev, "close"):
            ev.close()                       # nothing of the search runs on behind the result (or the next build)
    r["prime_s"] = round(prime_s, 2)
    r["wrapped"] = wrapped
    r["budget_s"] = total
    r["wall_s"] = round(time.monotonic() - t0, 2)
    r["base_s"] = round(base.seconds, 2)
    r.update(project=pid, from_rev=head, measure=getattr(ev, "stats", None))
    if commit and r["changed"] and not (cancel is not None and cancel()):
        n = len(r["applied"])
        note = f"Refined: {n} change{'s' if n != 1 else ''} (" + ", ".join(a["label"] for a in r["applied"]) + ")"
        try:
            q = st.update_design(st.load(pid), r["source"], note, None, "refine", head, "python")
            r["head"] = q["head"]
            record_revision(st, pid, q["head"], {"from_rev": head, "style": r.get("style"),
                                                 "steps": r["applied"], "base": r.get("base"), "final": r.get("final")})
        except Exception as e:                                   # noqa: BLE001 - the head moved, or it did not build
            public = getattr(e, "public", None)
            r["commit_error"] = {**(public() if callable(public) else {"message": str(e)}),
                                 "status": getattr(e, "status", None)}
    return r


def record_revision(st, pid: str, n: int, meta: dict) -> None:
    """Keep what a refine (or undo) revision changed on that revision (rev["refine"])."""
    with st.lock(pid):
        p = st.load(pid)
        for rev in p["revisions"]:
            if rev["n"] == n:
                rev["refine"] = json.loads(json.dumps(meta, default=str))
        st.save(p)


# ---- the changes a design carries, and undo --------------------------------------------------------------------------

def changes(st, p: dict) -> list[dict]:
    """The refine changes in a project's head: every refine feature in the source, and the source edits (materials,
    cage ops) of the last refine revision that are still in it. [{"id", "label", "reason", "kind", "operator", ...}]"""
    src = st.source_text(p) or ""
    feats = parse_features(src)
    meta = None
    for rev in sorted(p.get("revisions") or [], key=lambda r: -r["n"]):
        if rev.get("refine") and rev["n"] <= p["head"]:
            meta = rev["refine"]
            break
    steps = {s.get("id") or s.get("feature"): s for s in (meta or {}).get("steps") or []}
    out = []
    for k, f in feats.items():
        if f.get("role") != REFINE_ROLE:
            continue
        s = steps.get(k) or {}
        out.append({"id": k, "label": f.get("label") or k, "reason": s.get("reason") or f.get("doc", ""),
                    "doc": f.get("doc", ""), "kind": "feature", "operator": s.get("operator") or k[len("refine_"):],
                    "deltas": s.get("deltas") or {}})
    for k, s in steps.items():
        if s.get("kind") in ("edit", "ops") and _edit_present(src, s.get("edit") or {}):
            out.append({"id": k, "label": s.get("label") or k, "reason": s.get("reason", ""), "doc": s.get("doc", ""),
                        "kind": s["kind"], "operator": s.get("operator"), "deltas": s.get("deltas") or {}})
    return out


def _edit_present(src: str, e: dict) -> bool:
    if e.get("ops") is not None:
        from .ops_cage import refine_ops_of
        return _find_run(refine_ops_of(src), e["ops"]) is not None
    return bool(e.get("after")) and e["after"] in src


def _find_run(seq: list, run: list):
    if not run:
        return None
    for i in range(len(seq) - len(run) + 1):
        if seq[i:i + len(run)] == run:
            return i
    return None


def undo_edit(src: str, e: dict) -> str:
    """The source with one recorded edit taken back (edit_record): cage ops removed from REFINE_OPS, or the block of
    lines put back as it was. Raises ValueError when the edit is not in the source any more."""
    if e.get("ops") is not None:
        from .ops_cage import refine_ops_of, with_refine_ops
        ops = refine_ops_of(src)
        i = _find_run(ops, e["ops"])
        if i is None:
            raise ValueError("those cage ops are not in REFINE_OPS any more")
        return with_refine_ops(src, ops[:i] + ops[i + len(e["ops"]):])
    if not e.get("after") or e["after"] not in src:
        raise ValueError("the edited text is not in the source any more (a later change edited it too)")
    return src.replace(e["after"], e.get("before", ""), 1)


def undo(st, pid: str, fid: str | None = None, expect_head: int | None = None) -> dict:
    """Take refine changes out again: one (fid) or all of them, as one new revision (origin "refine", so it does
    not start a refinement of its own). A wrapped Recipe with no refine feature left is unwrapped."""
    from ..featureprog import delete_feature
    from ..studio import StudioError
    from . import adapter
    p = st.load(pid)
    src = st.source_text(p) or ""
    have = changes(st, p)
    ids = [c["id"] for c in have]
    if fid is not None:
        if fid not in ids:
            raise StudioError(f"No refine change “{fid}” in this design.", "Refine changes: " + (", ".join(ids) or "none"))
        todo = [c for c in have if c["id"] == fid]
    else:
        todo = list(reversed(have))
    if not todo:
        raise StudioError("This design has no refine changes.", "")
    meta = None
    for rev in sorted(p.get("revisions") or [], key=lambda r: -r["n"]):
        if rev.get("refine"):
            meta = rev["refine"]
            break
    steps = {s.get("id") or s.get("feature"): s for s in (meta or {}).get("steps") or []}
    for c in todo:
        if c["kind"] == "feature":
            src = delete_feature(src, c["id"])
        else:
            try:
                src = undo_edit(src, (steps.get(c["id"]) or {}).get("edit") or {})
            except ValueError as e:
                raise StudioError(f"“{c['label']}” cannot be undone alone: {e}.",
                                  "Undo the later refine change first, or undo all of them.")
    src = adapter.unwrap(src)
    labels = ", ".join(c["label"] for c in todo)
    q = st.update_design(p, src, "Undid refinement: " + labels, None, "refine",
                         p["head"] if expect_head is None else expect_head, "python")
    left = [s for s in (meta or {}).get("steps") or [] if (s.get("id") or s.get("feature")) not in {c["id"] for c in todo}]
    record_revision(st, pid, q["head"], {**(meta or {}), "steps": left, "undid": [c["id"] for c in todo]})
    return q


# ---- background jobs (form/refine/jobs.py keeps them per project, persisted and cancellable) --------------------------

def start(st, pid: str, refine_flag=None, **kw) -> str | None:
    """Refinement as a background job after the functional build. Returns the job id (None when it is off)."""
    from . import jobs
    return jobs.start(st, pid, refine_flag, **kw)


def status(jid: str) -> dict | None:
    from . import jobs
    return jobs.by_id(jid)
