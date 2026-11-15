"""Design intelligence that stays accountable.

Three things live here:
  * intent     — turn "make the lip a bit taller" on a selected feature into a
                 concrete, range-checked parameter proposal. Rules first; the
                 configured Claude model only when asked.
  * alternatives — build a grid of real candidates and compare them against
                 explicit objectives.
  * consult    — one bounded call to the installed `claude` CLI. The model
                 proposes; the kernel and the user decide.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time

from . import fit as fit_mod

UP = r"(increase|raise|more|bigger|larger|thicker|wider|deeper|taller|higher|longer|steeper|looser|grow|add|up)"
DOWN = r"(decrease|reduce|lower|less|smaller|thinner|narrower|shallower|shorter|slimmer|tighter|shrink|remove|down)"
HINTS = {  # adjective -> words that should appear in a parameter label
    "thicker": ["wall", "lip", "floor", "thick"], "thinner": ["wall", "lip", "floor", "thick"],
    "wider": ["width"], "narrower": ["width"], "deeper": ["depth"], "shallower": ["depth"],
    "taller": ["height"], "higher": ["height"], "shorter": ["height"], "steeper": ["lean", "angle"],
    "looser": ["clearance"], "tighter": ["clearance"], "rounder": ["radius"], "softer": ["radius"], "sharper": ["radius"],
}


def parse_intent(recipe, values: dict, text: str, feature: str | None) -> dict | None:
    """Deterministic reading of simple intents. Returns None when unsure."""
    t = text.lower().strip()
    if not t:
        return None
    params = [p for p in recipe.params if not feature or p.feature == feature] or list(recipe.params)
    scored = []
    for p in params:
        words = [w for w in re.split(r"[^a-z]+", p.label.lower()) if len(w) > 2]
        score = sum(2 for w in words if re.search(rf"\b{w}", t))
        for adj, keys in HINTS.items():
            if adj in t and any(k in p.label.lower() for k in keys):
                score += 1
        if p.key.replace("_", " ") in t:
            score += 3
        scored.append((score, p))
    scored.sort(key=lambda s: -s[0])
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    p = scored[0][1]
    cur = values[p.key]
    m_to = re.search(r"\bto\s+(-?\d+(?:\.\d+)?)", t)
    m_by = re.search(r"(?:\bby\s+|\+|-)?(\d+(?:\.\d+)?)\s*(mm|deg|°|%|g)?", t)
    up, down = re.search(rf"\b{UP}\b", t), re.search(rf"\b{DOWN}\b", t)
    sign = -1 if (down and not up) else 1
    if re.search(r"\b(softer|rounder)\b", t):
        sign = 1
    if re.search(r"\bsharper\b", t):
        sign = -1
    if m_to:
        new, how = float(m_to.group(1)), f"set to {m_to.group(1)}"
    elif m_by and (up or down or re.search(r"[+-]\s*\d", t)):
        amt = float(m_by.group(1))
        if m_by.group(2) == "%":
            amt = abs(cur) * amt / 100
        new, how = cur + sign * amt, f"{'+' if sign > 0 else '−'}{amt:g}"
    elif up or down or re.search(r"\b(softer|rounder|sharper)\b", t):
        small = bool(re.search(r"\b(bit|slightly|little|touch|tad)\b", t))
        amt = max(p.step, abs(cur) * (0.1 if small else 0.2), (p.max - p.min) * 0.02)
        amt = round(amt / p.step) * p.step
        new, how = cur + sign * amt, f"{'+' if sign > 0 else '−'}{amt:g} (no amount given, so a {'small' if small else 'moderate'} step)"
    else:
        return None
    clamped = min(p.max, max(p.min, round(new / p.step) * p.step))
    note = "" if abs(clamped - new) < p.step else f" Limited to the supported range {p.min:g}–{p.max:g}."
    return {"source": "rule", "changes": [{"key": p.key, "label": p.label, "from": cur, "to": round(clamped, 4), "unit": p.unit,
                                           "reason": f"Read as: {p.label.lower()} {how}.{note}"}],
            "summary": f"{p.label}: {cur:g} → {clamped:g} {p.unit}", "cautions": []}


SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "changes", "cautions"],
    "properties": {
        "summary": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["key", "value", "reason"],
                                                 "properties": {"key": {"type": "string"}, "value": {"type": "number"}, "reason": {"type": "string"}}}},
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = (
    "You are the design engineer inside FORM, a parametric studio for FDM-printed objects. "
    "You receive one design's parameters, limits, derived dimensions, current check results and a request. "
    "Reply with parameter changes only: keys must exist, values must be inside min/max and in the stated units. "
    "Change as few parameters as achieve the intent. Protect interface dimensions unless the request is about fit. "
    "Never claim a part will print, fit or survive load; say what should be checked instead. "
    "If the request cannot be met by these parameters, return no changes and explain in summary. Be brief and concrete."
)


def cli_status(cfg: dict) -> dict:
    if not cfg["models"].get("cli"):
        return {"available": False, "path": None, "default": None, "specialist": None,
                "note": "Built-in model consultation is off. Connect an agent over MCP (form-mcp); rule-based intents still work."}
    exe = shutil.which(cfg["models"]["cli"])
    return {"available": bool(exe), "path": exe, "default": cfg["models"]["default"], "specialist": cfg["models"]["specialist"] or None,
            "note": "Model names are passed to the installed client unchanged; it resolves aliases." if exe else
                    f"The `{cfg['models']['cli']}` command is not on PATH. Rule-based intents still work."}


def consult(cfg: dict, recipe, values: dict, context: dict, text: str, feature: str | None, tier: str = "default") -> dict:
    """One bounded, tool-less call. Returns a validated proposal or raises RuntimeError."""
    m = cfg["models"]
    exe = shutil.which(m["cli"])
    if not exe:
        raise RuntimeError(f"The `{m['cli']}` command is not installed, so no model can be consulted.")
    model = m["default"] if tier == "default" else m["specialist"]
    if not model:
        raise RuntimeError("No specialist model is configured. Set [models].specialist in studio.toml.")
    payload = {
        "object": recipe.title, "selected_feature": feature,
        "features": [{"id": f.id, "label": f.label, "role": f.role, "doc": f.doc} for f in recipe.features],
        "parameters": [{"key": p.key, "label": p.label, "value": values[p.key], "unit": p.unit, "min": p.min, "max": p.max,
                        "feature": p.feature, "doc": p.doc} for p in recipe.params],
        **context, "request": text,
    }
    cmd = [exe, "-p", json.dumps(payload), "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(SCHEMA), "--system-prompt", SYSTEM, "--tools", "",
           "--strict-mcp-config", "--no-session-persistence"]
    if tier != "default":
        cmd += ["--max-budget-usd", str(m["specialist_budget_usd"])]
    t0 = time.time()
    with tempfile.TemporaryDirectory() as cwd:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=m["timeout_s"], cwd=cwd)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"The model did not answer within {m['timeout_s']} s.")
    try:
        env = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("The client returned no usable answer: " + (r.stderr or r.stdout).strip()[:300])
    if env.get("is_error"):
        raise RuntimeError("The client reported an error: " + str(env.get("result"))[:300])
    out = env.get("structured_output")
    if out is None:
        try:
            out = json.loads(env.get("result", ""))
        except (ValueError, TypeError):
            raise RuntimeError("The model did not return a structured proposal.")
    changes, dropped = [], []
    keys = {p.key: p for p in recipe.params}
    for c in out.get("changes", []):
        p = keys.get(c.get("key"))
        v = c.get("value")
        if p is None or not isinstance(v, (int, float)):
            dropped.append(f"Ignored unknown parameter “{c.get('key')}”.")
            continue
        v2 = min(p.max, max(p.min, float(v)))
        if abs(v2 - v) > 1e-9:
            dropped.append(f"{p.label} was limited to {v2:g} {p.unit} (asked for {v:g}).")
        if abs(v2 - values[p.key]) > 1e-9:
            changes.append({"key": p.key, "label": p.label, "from": values[p.key], "to": v2, "unit": p.unit, "reason": str(c.get("reason", ""))[:400]})
    used = sorted((env.get("modelUsage") or {}).keys())
    return {"source": "model", "tier": tier, "requested_model": model, "resolved_models": used,
            "cost_usd": env.get("total_cost_usd"), "seconds": round(time.time() - t0, 1),
            "summary": str(out.get("summary", ""))[:600], "changes": changes,
            "cautions": [str(c)[:300] for c in out.get("cautions", [])][:6] + dropped}


OBJECTIVES = {
    "material": {"label": "Less material", "unit": "cm³", "better": "low"},
    "stability": {"label": "Harder to tip", "unit": "N", "better": "high"},
    "fit": {"label": "Fit yield", "unit": "%", "better": "high"},
    "footprint": {"label": "Smaller footprint", "unit": "cm²", "better": "low"},
}


def alternatives(studio, p: dict, axes: list, weights: dict) -> dict:
    """axes: [{key, values:[...]}, ...] (1–2 axes). Every candidate is really built."""
    recipe = studio.recipe(p)
    base = studio.rev(p)["values"]
    if not 1 <= len(axes) <= 2:
        raise ValueError("Choose one or two parameters to vary.")
    grid = [{}]
    for ax in axes:
        sp = recipe.spec(ax["key"])
        vals = [min(sp.max, max(sp.min, float(v))) for v in ax["values"]][:5]
        grid = [{**g, ax["key"]: v} for g in grid for v in vals]
    rows = studio._k("variants", timeout=120, recipe_id=studio.rid(p), base=base, grid=grid)
    for r in rows:
        if not r["ok"]:
            continue
        vals = {**base, **r["changes"]}
        f = studio.fit(p, vals)
        bb = r["bbox"]
        r["metrics"] = {
            "material": r["volume_mm3"] / 1000,
            "stability": (r.get("statics") or {}).get("tip_force_n", (r.get("statics") or {}).get("safety_factor")),
            "fit": f["yield"] * 100 if f else None,
            "footprint": (bb[1][0] - bb[0][0]) * (bb[1][1] - bb[0][1]) / 100,
        }
    ok = [r for r in rows if r["ok"]]
    used = [k for k in OBJECTIVES if weights.get(k, 0) > 0 and all(r["metrics"].get(k) is not None for r in ok)]
    for k in used:
        xs = [r["metrics"][k] for r in ok]
        lo, hi = min(xs), max(xs)
        for r in ok:
            n = 0.5 if hi - lo < 1e-9 else (r["metrics"][k] - lo) / (hi - lo)
            r.setdefault("norm", {})[k] = n if OBJECTIVES[k]["better"] == "high" else 1 - n
    tw = sum(weights[k] for k in used) or 1
    for r in ok:
        r["score"] = sum(weights[k] * r["norm"][k] for k in used) / tw if used else 0

    def dominates(a, b):
        ge = all(a["norm"][k] >= b["norm"][k] - 1e-9 for k in used)
        return ge and any(a["norm"][k] > b["norm"][k] + 1e-9 for k in used)
    for r in ok:
        r["pareto"] = bool(used) and not any(dominates(o, r) for o in ok if o is not r)
        r["is_current"] = all(abs(base[k] - v) < 1e-9 for k, v in r["changes"].items())
    best = max(ok, key=lambda r: r["score"], default=None)
    if best:
        best["best"] = True
    return {"axes": [{"key": a["key"], "label": recipe.spec(a["key"]).label, "unit": recipe.spec(a["key"]).unit} for a in axes],
            "objectives": {k: {**OBJECTIVES[k], "weight": weights.get(k, 0), "used": k in used} for k in OBJECTIVES},
            "rows": rows,
            "note": "Each candidate was built by the kernel. Scores rank only the objectives you weighted; "
                    "print time is not compared until a candidate is sliced."}
