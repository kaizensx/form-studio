"""The staged design workflow: brief -> plan -> design -> critique -> release.

An agent asked for something complex ("a helmet with texture", "a planetary gearbox") must not jump to code. The MCP
tools enforce three stages, and this module keeps their record:

  design_brief(...)  stores structured requirements: goal, requirements, key dimensions (with where they come from),
                     constraints, style, and the unknowns it could not settle (listed, never guessed).
  plan_design(...)   stores the feature plan: parts, features (each with how it will be built, e.g. which form.craft
                     helper), key dimensions, mechanisms, textures and risks.
  create_design      refuses a complex brief without a plan (assess() says why it is complex).
  critique           (form/critique.py) records a pass; a project with a brief or plan cannot be released before
                     its head revision has one.

Briefs and plans written before the project exists live in <data>/.briefs/<id>.json; create_design(plan=<id>)
attaches them to the project as p["design"] = {"brief", "plan", "critiques"}.
Plain data and file I/O only: no kernel.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from .studio import StudioError

#: words that make a brief complex: mechanisms, organic or styled forms, textures, multi-part assemblies
COMPLEX = {
    "mechanism": ("hinge", "hinged", "snap", "latch", "bayonet", "dovetail", "detent", "ratchet", "cam", "linkage",
                  "four-bar", "gear", "gearbox", "planetary", "pulley", "belt", "clamp", "quick-release", "mechanism",
                  "spring", "slide", "slider", "rotate", "rotating", "pivot", "joint", "articulated", "chain", "lock",
                  "thread", "threaded", "bearing", "axle", "lever", "knob", "trigger"),
    "organic": ("helmet", "ergonomic", "organic", "grip", "handle", "sculpted", "curved", "flowing", "lofted", "shell",
                "dome", "vase", "lamp", "shade", "body", "aerodynamic", "streamlined", "mask", "figure", "character",
                "drone", "car", "boat", "bottle", "mouse", "controller", "wearable"),
    "texture": ("texture", "textured", "knurl", "knurled", "pattern", "patterned", "ribbed", "ribs", "grain", "leather",
                "carbon", "hex", "voronoi", "embossed", "spiral", "fluted"),
    "aesthetic": ("beautiful", "elegant", "premium", "designed", "stylish", "sleek", "modern", "luxury", "aesthetic",
                  "iconic", "motorcycle", "sports"),
    "assembly": ("assembly", "assembled", "parts", "case and lid", "multi-part", "kit", "enclosure with", "two-part"),
}


def _words(text: str) -> set:
    """Words of a brief, with hyphenated words also split ("drag-chain" -> drag-chain, drag, chain) and a plural
    "s" dropped ("snaps" -> snap)."""
    out = set()
    for w in re.findall(r"[a-z][a-z\-]+", (text or "").lower()):
        for t in [w, *w.split("-")]:
            if t:
                out.add(t)
                if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
                    out.add(t[:-1])
    return out


#: phrases whose keyword is hardware, not form: "a 31 mm bolt pattern" is not a texture, "an M6 hex head" is not a
#: hex texture
_NOT = re.compile(r"\b(?:bolt|hole|mounting|screw|drill|fixing)\s+patterns?\b|\bpatterns?\s+of\s+(?:holes|screws|bolts)\b"
                  r"|\bhex(?:agon)?\s+(?:head|heads|nut|nuts|key|keys|socket|sockets|bolt|bolts|bit|bits|drive|shaft|wrench)\b", re.I)


def assess(brief: str = "", source: str = "") -> dict:
    """Is this brief complex enough to need a plan? Heuristic, and said to be: keywords by family, a long brief, or
    source that declares several solids or an assembly."""
    brief = _NOT.sub(" ", brief or "")
    w = _words(brief)
    low = (brief or "").lower()
    hits = {fam: sorted({k for k in kws if (k in w if " " not in k and "-" not in k else k in low)}) for fam, kws in COMPLEX.items()}
    hits = {k: v for k, v in hits.items() if v}
    reasons = [f"{fam}: {', '.join(v)}" for fam, v in hits.items()]
    if len(w) > 60:
        reasons.append(f"long brief ({len(w)} words)")
    if source:
        m = re.search(r"^\s*solids\s*=\s*(\d+)", source, re.M)
        if m and int(m.group(1)) >= 2:
            reasons.append(f"{m.group(1)} separate solids")
        if re.search(r"def\s+assembly\s*\(", source):
            reasons.append("declares an assembly")
        if re.search(r"def\s+mesh_texture\s*\(", source):
            reasons.append("declares a mesh texture")
    return {"complex": bool(reasons), "reasons": reasons, "families": sorted(hits), "evidence": "heuristic"}


def topics_for(families) -> list[str]:
    """Which design_guide topics to read for these families of the brief."""
    m = {"mechanism": "mechanisms", "organic": "organic", "texture": "texture", "aesthetic": "aesthetics",
         "assembly": "mechanisms"}
    out = ["core"]
    for f in families:
        t = m.get(f)
        if t and t not in out:
            out.append(t)
    if "organic" in families and "surfacing" not in out:
        out.insert(1, "surfacing")
    return out


# ---- storage -----------------------------------------------------------------------------------------------------

def _dir(st) -> Path:
    d = Path(st.root) / ".briefs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_list(x, name, item=str) -> list:
    if x is None:
        return []
    if not isinstance(x, list):
        raise StudioError(f"{name} must be a list.")
    return x


def save_brief(st, name: str, goal: str, requirements=None, dimensions=None, constraints=None, unknowns=None,
               style: str = "", purpose: str | None = None, references=None, project: str | None = None) -> dict:
    if not (goal or "").strip():
        raise StudioError("A brief needs a goal: one or two sentences of what the object is and does.")
    reqs = _clean_list(requirements, "requirements")
    dims = dimensions or {}
    if not isinstance(dims, dict):
        raise StudioError("dimensions must be an object: {name: {value, unit, source}} or {name: number}.")
    norm = {}
    for k, v in dims.items():
        if isinstance(v, (int, float)):
            v = {"value": float(v), "unit": "mm", "source": "assumed"}
        if not isinstance(v, dict) or "value" not in v:
            raise StudioError(f"dimension {k!r} needs a value.", "Give {value, unit, source}; source is measured, "
                              "specified (datasheet), or assumed.")
        v.setdefault("unit", "mm")
        v.setdefault("source", "assumed")
        norm[str(k)] = v
    a = assess(" ".join([goal, " ".join(map(str, reqs)), style or ""]))
    b = {"id": "b-" + secrets.token_hex(4), "name": name, "goal": goal.strip(), "requirements": reqs,
         "dimensions": norm, "constraints": _clean_list(constraints, "constraints"),
         "unknowns": _clean_list(unknowns, "unknowns"), "style": style, "purpose": purpose,
         "references": _clean_list(references, "references"), "ts": time.time(), "assessment": a, "plan": None}
    if project:
        attach(st, project, brief=b)
    else:
        (_dir(st) / f"{b['id']}.json").write_text(json.dumps(b, indent=1), encoding="utf-8")
    return b


def load_brief(st, ref: str) -> dict:
    """A pending brief by id, or a project's brief by project id."""
    f = _dir(st) / f"{ref}.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        p = st.load(ref)
    except StudioError:
        raise StudioError(f"Unknown brief or project {ref!r}.", "Call design_brief first; it returns the brief id.")
    d = p.get("design") or {}
    if not d.get("brief"):
        raise StudioError(f"Project {ref!r} has no design brief.", "Call design_brief(project=...) first.")
    return {**d["brief"], "plan": d.get("plan")}


REQUIRED_FEATURE_KEYS = ("id", "label", "how")


def save_plan(st, ref: str, features: list, parts=None, key_dimensions=None, mechanisms=None, textures=None,
              risks=None, approach: str = "", references_used=None) -> dict:
    b = load_brief(st, ref)
    feats = _clean_list(features, "features")
    if not feats:
        raise StudioError("A plan needs features.", "List every feature the design will have: {id, label, how}, where "
                          "how names the construction (e.g. 'craft.loft_sections of 9 superellipse sections').")
    bad = [f for f in feats if not isinstance(f, dict) or any(not str(f.get(k, "")).strip() for k in REQUIRED_FEATURE_KEYS)]
    if bad:
        raise StudioError("Every planned feature needs id, label and how.", f"Incomplete: {json.dumps(bad[:3])[:300]}")
    ids = [f["id"] for f in feats]
    if len(set(ids)) != len(ids):
        raise StudioError("Planned feature ids must be unique.")
    complex_ = b.get("assessment", {}).get("complex")
    rk = _clean_list(risks, "risks")
    if complex_ and len(feats) < 3:
        raise StudioError("This brief is complex; a plan of fewer than 3 features is not a plan.",
                          "Break it into its features: main body, each mechanism, each opening, each texture, each "
                          "interface.")
    if complex_ and not rk:
        raise StudioError("A complex design needs its risks named.", "What could make it fail? (a fillet that will not "
                          "fit, a shell that self-intersects, parts that collide, a texture too fine to print...)")
    plan = {"features": feats, "parts": _clean_list(parts, "parts"), "key_dimensions": key_dimensions or {},
            "mechanisms": _clean_list(mechanisms, "mechanisms"), "textures": _clean_list(textures, "textures"),
            "risks": rk, "approach": approach, "references_used": _clean_list(references_used, "references_used"),
            "ts": time.time()}
    f = _dir(st) / f"{ref}.json"
    if f.is_file():
        b["plan"] = plan
        f.write_text(json.dumps(b, indent=1), encoding="utf-8")
    else:
        attach(st, ref, plan=plan)
    return {"brief": b["id"], "plan": plan}


def attach(st, pid: str, brief: dict | None = None, plan: dict | None = None) -> dict:
    with st.lock(pid):
        p = st.load(pid)
        d = p.setdefault("design", {})
        if brief is not None:
            d["brief"] = {k: v for k, v in brief.items() if k != "plan"}
            if brief.get("plan"):
                d["plan"] = brief["plan"]
        if plan is not None:
            d["plan"] = plan
        d.setdefault("critiques", [])
        st.save(p)
        return d


def attach_pending(st, pid: str, ref: str) -> dict:
    """Move a pending brief (and its plan) onto a project created from it."""
    f = _dir(st) / f"{ref}.json"
    if not f.is_file():
        raise StudioError(f"Unknown brief {ref!r}.", "Pass the id design_brief returned.")
    b = json.loads(f.read_text(encoding="utf-8"))
    d = attach(st, pid, brief=b)
    f.unlink(missing_ok=True)
    return d


def require_plan(st, brief: str, source: str, plan_ref: str = "") -> dict:
    """Raise unless a complex brief comes with a plan. Returns the assessment (and the plan's brief when given)."""
    a = assess(brief, source)
    if plan_ref:
        b = load_brief(st, plan_ref)
        if not b.get("plan"):
            raise StudioError(f"Brief {plan_ref} has no plan yet.", "Call plan_design(brief=...) with the features, then "
                              "create_design(plan=...).", status=409)
        a["brief"] = b
        return a
    if a["complex"]:
        raise StudioError("This is a complex design; brief and plan it before writing code.",
                          "Reasons (heuristic): " + "; ".join(a["reasons"]) + ". Call design_brief (requirements, key "
                          "dimensions, unknowns), read design_guide for topics " + ", ".join(topics_for(a["families"]))
                          + " and design_examples for a close exemplar, then plan_design (features, how each is built, "
                          "risks), then create_design(..., plan=<brief id>).", status=409, reasons=a["reasons"])
    return a


def record_critique(st, pid: str, rev: int, summary: dict, notes: str = "") -> dict:
    with st.lock(pid):
        p = st.load(pid)
        d = p.setdefault("design", {})
        c = {"rev": rev, "ts": time.time(), "notes": (notes or "").strip()[:4000], **summary}
        d.setdefault("critiques", []).append(c)
        d["critiques"] = d["critiques"][-20:]
        st.save(p)
        return c


def needs_critique(p: dict) -> str | None:
    """The gate reason when a staged design's head revision has no recorded critique pass, else None."""
    d = p.get("design") or {}
    if not (d.get("brief") or d.get("plan")):
        return None
    if any(c.get("rev") == p["head"] for c in d.get("critiques", [])):
        return None
    return f"No design critique recorded for r{p['head']:02d} (critique(project) records one)."
