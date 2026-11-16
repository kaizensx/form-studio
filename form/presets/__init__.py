"""Brief templates: the questions that matter for a kind of part, sensible environment defaults, a material to start
from and the checks to plan for. A filled-in template becomes a chat prompt for Claude and, once Claude creates the
project, the structured answers in the project's brief (``brief.answers``).

The answers travel with a short token in the brief text, "(FORM brief b-1a2b3c4d)": the app saves the answers under
the data folder, Claude passes the brief text to create_design/create_project, and Studio.create attaches them.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

HERE = Path(__file__).parent
ORDER = ["remote-holder", "desk-accessory", "organizer", "bathroom-mount", "enclosure", "automotive-accessory"]
KINDS = ("number", "text", "choice")
TOKEN = re.compile(r"\(FORM brief (b-[0-9a-f]{8})\)")
PENDING = ".briefs"


def _load(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8"))


def all_presets() -> list[dict]:
    found = {f.stem: _load(f) for f in sorted(HERE.glob("*.json"))}
    return [found[k] for k in ORDER if k in found] + [v for k, v in found.items() if k not in ORDER]


def get(preset_id: str) -> dict:
    for p in all_presets():
        if p["id"] == preset_id:
            return p
    raise KeyError(preset_id)


def problems(p: dict) -> list[str]:
    """Everything that makes a preset incomplete or inconsistent (empty list = valid)."""
    out = []
    for k in ("id", "title", "summary", "questions", "environment", "material", "checks"):
        if not p.get(k):
            out.append(f"missing {k}")
    if out:
        return out
    if len(p["summary"]) > 120 or "\n" in p["summary"]:
        out.append("summary must be one short line")
    keys = [q.get("key") for q in p["questions"]]
    if len(set(keys)) != len(keys):
        out.append("question keys are not unique")
    for q in p["questions"]:
        for k in ("key", "label", "kind", "why"):
            if not q.get(k):
                out.append(f"question {q.get('key')}: missing {k}")
        if q.get("kind") not in KINDS:
            out.append(f"question {q.get('key')}: kind must be one of {KINDS}")
        if q.get("kind") == "number" and not q.get("unit"):
            out.append(f"question {q.get('key')}: a number needs a unit")
        if q.get("kind") == "choice" and len(q.get("choices") or []) < 2:
            out.append(f"question {q.get('key')}: a choice needs at least two choices")
    if not any(q.get("required") for q in p["questions"]):
        out.append("at least one question must be required")
    env = p["environment"]
    for k in ("setting", "temperature_c", "humidity", "uv", "load"):
        if k not in env:
            out.append(f"environment: missing {k}")
    t = env.get("temperature_c")
    if not (isinstance(t, list) and len(t) == 2 and t[0] < t[1]):
        out.append("environment.temperature_c must be [min, max]")
    if env.get("uv") not in ("none", "indirect", "direct"):
        out.append("environment.uv must be none, indirect or direct")
    if not isinstance(env.get("load"), dict) or not {"kind", "mass_g", "note"} <= set(env.get("load") or {}):
        out.append("environment.load needs kind, mass_g and note")
    if not {"suggested", "why"} <= set(p["material"]):
        out.append("material needs suggested and why")
    for c in p["checks"]:
        if not c.get("name") or not c.get("why"):
            out.append("every check needs name and why")
    return out


def _fmt(v: float) -> str:
    return f"{v:g}"


def normalize(p: dict, answers: dict, measured: bool) -> list[dict]:
    """Answers keyed by question; numbers become floats. Raises ValueError naming the question on bad input."""
    out = []
    for q in p["questions"]:
        raw = answers.get(q["key"])
        raw = "" if raw is None else str(raw).strip()
        if not raw:
            if q.get("required"):
                raise ValueError(f"“{q['label']}” is needed.")
            continue
        row = {"key": q["key"], "label": q["label"], "kind": q["kind"]}
        if q["kind"] == "number":
            try:
                val = float(raw.replace(",", "."))
            except ValueError:
                raise ValueError(f"“{q['label']}” must be a number in {q['unit']}.") from None
            if not (val > 0 or q["unit"] == "°C") or abs(val) > 100000:
                raise ValueError(f"“{q['label']}” is out of range.")
            row.update(value=val, unit=q["unit"], source="measured" if measured else "assumed")
        else:
            if q["kind"] == "choice" and raw not in q["choices"]:
                raise ValueError(f"“{q['label']}”: pick one of the choices.")
            row.update(value=raw[:600])
        out.append(row)
    return out


def brief_text(p: dict, rows: list[dict], token: str) -> str:
    parts = [f"{r['label']}: {_fmt(r['value'])} {r['unit']}" if r["kind"] == "number" else f"{r['label']}: {r['value']}"
             for r in rows]
    return f"{p['title']}. " + "; ".join(parts) + f". (FORM brief {token})"


def prompt(p: dict, rows: list[dict], measured: bool, token: str) -> str:
    env, mat = p["environment"], p["material"]
    answered = {r["key"] for r in rows}
    lines = [f"Design a {p['title'].lower()} for me with FORM. I filled in FORM's “{p['title']}” brief.", "", "My answers:"]
    for r in rows:
        if r["kind"] == "number":
            lines.append(f"- {r['label']}: {_fmt(r['value'])} {r['unit']} ({r['source']})")
        else:
            lines.append(f"- {r['label']}: {r['value']}")
    missing = [q["label"] for q in p["questions"] if q["key"] not in answered]
    if missing:
        lines += ["", "Not answered yet: " + "; ".join(missing) + "."]
    lines += ["", ("I measured the numbers above." if measured else
                   "I did not say I measured these numbers: treat them as assumed until I confirm how I measured them."),
              "", "Template defaults (assumed, correct me where they are wrong):",
              f"- Setting: {env['setting']}, {env['temperature_c'][0]} to {env['temperature_c'][1]} °C, "
              f"humidity {env['humidity']}, UV {env['uv']}.",
              f"- Load: {env['load']['kind']}, about {env['load']['mass_g']} g. {env['load']['note']}",
              f"- Material to start from: {mat['suggested']}. {mat['why']}" + (f" {mat['consider']}" if mat.get("consider") else ""),
              "", "Checks to plan for:"]
    lines += [f"- {c['name']}: {c['why']}" for c in p["checks"]]
    hint = (f"The closest built-in recipe may be “{p['closest_recipe']}”; use it only if it really fits, "
            "otherwise read design_guide and write a design.") if p.get("closest_recipe") else \
        "No built-in recipe covers this; read design_guide and write a design."
    lines += ["", "How to work:",
              f"- {hint}",
              f"- When you create the project, pass exactly this as brief: {brief_text(p, rows, token)}",
              "- Ask me at most three questions, only for missing values that change fit or function, and say why each matters.",
              "- Record provenance honestly: measured only for numbers I measured, specified for datasheet values, otherwise assumed.",
              "- After creating it, render(view=\"sheet\"), look at it, run the checks and tell me what is still assumed.",
              "- A slice is a simulation and fit yield is a model. Do not start a print."]
    return "\n".join(lines)


def start_brief(root: Path, preset_id: str, answers: dict, measured: bool = False) -> dict:
    """Save a filled-in brief as pending and return the chat prompt that carries its token."""
    try:
        p = get(preset_id)
    except KeyError:
        raise ValueError("Unknown brief template.") from None
    rows = normalize(p, answers or {}, bool(measured))
    token = "b-" + secrets.token_hex(4)
    rec = {"id": token, "preset": p["id"], "title": p["title"], "answers": rows, "measured": bool(measured),
           "environment": p["environment"], "material": p["material"]["suggested"],
           "checks": [c["name"] for c in p["checks"]], "ts": time.time()}
    d = Path(root) / PENDING
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{token}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return {"id": token, "prompt": prompt(p, rows, bool(measured), token), "brief": brief_text(p, rows, token)}


def attach(root: Path, text: str) -> dict | None:
    """The structured brief a project's brief text refers to, or None. The pending file is consumed."""
    m = TOKEN.search(text or "")
    if not m:
        return None
    f = Path(root) / PENDING / f"{m.group(1)}.json"
    if not f.is_file():
        return None
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        f.unlink()
    except OSError:
        pass
    return {"preset": rec["preset"], "preset_title": rec["title"], "answers": rec["answers"], "measured": rec["measured"],
            "environment": rec["environment"], "material": rec["material"], "checks": rec["checks"]}
