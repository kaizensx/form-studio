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
copies them onto the project as p["design"] = {"brief", "plan", "critiques"}. The brief file stays (with the
conversation it belongs to and `used_by`), so one brief serves every design its request makes.
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


#: words that ask for an object to look special, in English, Portuguese and Spanish, without accents. A word matches
#: when it starts with a stem (beaut-: beauty, beautiful, beautifully) or equals a whole word; a misspelling of a long
#: word ("beatiful", "gorgous", "impresive") matches it by similarity.
#: Generic praise ("awesome, now make the hole bigger") is left out on purpose, and so is Portuguese "impressão"
#: (a print) and "impressora" (a printer): impress- only counts as impressi- (impressive, impressiona) or impress/ed/es.
AESTHETIC_STEMS = ("beaut", "gorgeous", "stunning", "impressi", "exquisit", "luxur", "elegan", "sophistic", "breathtak",
                   "jaw-drop", "eye-catch", "spectacular", "magnific", "striking",
                   "bonit", "lind", "maravilh", "deslumbr", "sofistic", "luxuos", "espetacul", "espectacul",
                   "caprich", "hermos", "precios", "esplend")
AESTHETIC_WORDS = ("wow", "premium", "luxo", "belo", "bela", "belos", "belas", "chique", "chic", "sleek", "iconic",
                   "stylish", "aesthetic", "aesthetics", "estetico", "estetica", "gorgeous", "impress", "impressed",
                   "impresses")
AESTHETIC_PHRASES = ("really nice", "look nice", "looks nice", "look good", "looks good", "look great", "high-end",
                     "high end", "top notch", "top-notch", "world class", "world-class", "best looking", "best-looking",
                     "well designed", "well-designed", "nicely designed", "design bonito", "bem desenhad", "bem feito",
                     "de cair o queixo", "que impressione", "show de bola", "muito bom aspeto", "muito bom aspecto",
                     "bom aspeto", "bom aspecto", "make it nice", "faz bonito", "mais bonit", "really good looking")
_AESTHETIC_FUZZY = ("beautiful", "gorgeous", "stunning", "impressive", "premium", "elegant", "exquisite",
                    "luxury", "luxurious", "sophisticated", "spectacular", "magnificent", "bonito", "bonita", "lindo",
                    "linda", "lindissimo", "maravilhoso", "maravilhosa", "deslumbrante", "impressionante", "elegante",
                    "sofisticado", "sofisticada", "espetacular", "hermoso", "precioso", "stylish", "aesthetic")


def _plain(text: str) -> str:
    """Lower case without accents ("lindíssimo" -> "lindissimo")."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def aesthetic_intent(text: str) -> dict:
    """Does this message ask for something that looks special ("make it really beautiful", "quero algo lindo que
    impressione")? {"aesthetic": bool, "words": [the words that matched]}. Heuristic keyword and spelling match; it
    decides whether the agent gets the beauty protocol (form/chat.py), nothing more."""
    import difflib
    low = _plain(text)
    words = re.findall(r"[a-z][a-z\-']*", low)
    found = []
    for w in words:
        w = w.strip("-'")
        if not w:
            continue
        if w in AESTHETIC_WORDS or any(w.startswith(s) for s in AESTHETIC_STEMS):
            found.append(w)
        elif len(w) >= 6 and difflib.get_close_matches(w, _AESTHETIC_FUZZY, n=1, cutoff=0.84):
            found.append(w)
    for ph in AESTHETIC_PHRASES:
        if ph in low:
            found.append(ph)
    # "impression" of a stamp, "lindane", "linden": not about looks
    found = [f for f in found if f not in ("linden", "lindane")]
    return {"aesthetic": bool(found), "words": sorted(dict.fromkeys(found)), "evidence": "heuristic"}


def assess(brief: str = "", source: str = "") -> dict:
    """Is this brief complex enough to need a plan? Heuristic, and said to be: keywords by family, a long brief, or
    source that declares several solids or an assembly. The aesthetic family also takes aesthetic_intent()'s words
    (Portuguese and Spanish, misspellings)."""
    brief = _NOT.sub(" ", brief or "")
    w = _words(brief)
    low = (brief or "").lower()
    hits = {fam: sorted({k for k in kws if (k in w if " " not in k and "-" not in k else k in low)}) for fam, kws in COMPLEX.items()}
    ai = aesthetic_intent(brief)
    if ai["aesthetic"]:
        hits["aesthetic"] = sorted(set(hits.get("aesthetic", [])) | set(ai["words"]))
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
    if {"organic", "texture"} & set(families):          # a construction route per feature (kernel, subd, sculpt...)
        out.append("hybrid")
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
               style: str = "", purpose: str | None = None, references=None, project: str | None = None,
               assertions=None) -> dict:
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
    # the brief as kernel-checkable assertions, and what is wrong with its numbers before any code (form/contract.py)
    from . import contract
    b["contract"] = contract.compile_brief(b, _clean_list(assertions, "assertions"))
    from .conversations import env_conversation
    cid = env_conversation()
    if cid:                                       # the brief belongs to the conversation that asked for it
        b["conversation"] = cid
        from .conversations import ConversationError, Conversations
        try:
            Conversations(st.root).add_brief(cid, b["id"])
        except (ConversationError, OSError):
            pass
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
    if re.fullmatch(r"b-[0-9a-f]{8}", str(ref or "")):
        # a brief used before briefs were kept (its file was deleted when the first design took it): find that design
        for row in st.list():
            try:
                d = (st.load(row["id"]).get("design") or {}) if not row.get("error") else {}
            except StudioError:
                continue
            if (d.get("brief") or {}).get("id") == ref:
                b = {**d["brief"], "plan": d.get("plan")}
                f.write_text(json.dumps(b, indent=1), encoding="utf-8")    # kept from now on
                return b
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
              risks=None, approach: str = "", references_used=None, product_class: str = "", clearances=None,
              magnets=None) -> dict:
    """Store the feature plan. Refused when a `how` names a helper that does not exist (with the closest real
    names) and when a multi-part brief does not declare its parts, clearances and magnet stock. The stored plan
    carries its route and executable steps (advice()). A feature may state its construction route (`route`: kernel,
    subd_cage, sculpt_recon or procedural); otherwise form/router.py reads it from the feature's words (heuristic).
    plan["feature_routes"] holds each route with the words that chose it, plan["route_warnings"] each mechanical
    interface on a mesh-only route, and a feature whose route could not be read is added to the brief's unknowns."""
    b = load_brief(st, ref)
    from . import product_classes as pc
    if product_class and product_class not in pc.CLASSES:
        raise StudioError(f"Unknown product class “{product_class}”.", "Classes: " + ", ".join(pc.CLASSES)
                          + ". Leave it empty when the object is none of them.")
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
    prts = _clean_list(parts, "parts")
    cl, mags, warns = _check_plan(b, feats, prts, clearances, magnets)
    adv = advice(" ".join([b.get("goal", ""), b.get("name", ""), b.get("style", "") or ""]), feats)
    from . import router
    froutes = {f["id"]: router.feature_route(f) for f in feats}
    unread = [u for u in router.unknowns(feats) if u not in (b.get("unknowns") or [])]
    if unread:                                  # what the router could not read goes back into the brief
        b["unknowns"] = list(b.get("unknowns") or []) + unread
    plan = {"features": feats, "parts": prts, "clearances": cl, "magnets": mags,
            "route": adv["route"], "feature_routes": froutes, "route_warnings": warns, "steps": adv["steps"],
            "key_dimensions": key_dimensions or {},
            "mechanisms": _clean_list(mechanisms, "mechanisms"), "textures": _clean_list(textures, "textures"),
            "risks": rk, "approach": approach, "references_used": _clean_list(references_used, "references_used"),
            "product_class": product_class or pc.detect(" ".join([b.get("goal", ""), b.get("name", "")])) or "",
            "ts": time.time()}
    f = _dir(st) / f"{ref}.json"
    if f.is_file():
        b["plan"] = plan
        f.write_text(json.dumps(b, indent=1), encoding="utf-8")
    elif unread:
        attach(st, ref, brief={**b, "plan": plan})
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
    """Copy a brief (and its plan) onto a project created from it. The brief stays: it belongs to the request (and
    its conversation), and one brief can serve every design that request makes (three parts of one product, a
    replacement after a failed attempt). The brief file lists the projects that used it in `used_by`."""
    f = _dir(st) / f"{ref}.json"
    if not f.is_file():
        raise StudioError(f"Unknown brief {ref!r}.", "Pass the id design_brief returned.")
    b = json.loads(f.read_text(encoding="utf-8"))
    d = attach(st, pid, brief=b)
    used = [u for u in b.get("used_by") or [] if u != pid] + [pid]
    b["used_by"] = used
    f.write_text(json.dumps(b, indent=1), encoding="utf-8")
    return d


def require_plan(st, brief: str, source: str, plan_ref: str = "") -> dict:
    """Raise unless a complex brief comes with a plan. Returns the assessment (and the plan's brief when given)."""
    a = assess(brief, source)
    if plan_ref:
        b = load_brief(st, plan_ref)
        au = (b.get("contract") or {}).get("audit") or {}
        if au.get("conflicting") or au.get("impossible") or au.get("invalid"):
            from . import contract
            raise StudioError(f"Brief {plan_ref} has numbers that cannot all hold, so there is nothing to build to yet.",
                              contract.audit_text({k: au.get(k, []) for k in ("conflicting", "impossible", "invalid")})
                              + " Settle them with the person (ask_user, once, with all of them), then write the "
                              "brief again with design_brief.", status=409, audit=au)
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


# ---- route, helper registry and executable plan ------------------------------------------------------------------
#
# design_brief returns a route (how the skeleton is built); plan_design checks every `how` against the helpers that
# really exist and returns the plan as ordered steps an agent can execute one call at a time: the first step is the
# skeleton (create_design with only that feature), each later one is add_feature(kind="code"), with a risk class, a
# fallback made of real helper names, and the retry cap.

ROUTES = ("prismatic", "revolve", "skin+features", "mechanism")
RETRIES = 2                       # tries per feature after the first fails; then it is deferred and the build goes on

#: words that pick a route, strongest family first (skin, then mechanism, then revolve; prismatic otherwise)
_ROUTE_WORDS = {
    "skin+features": ("helmet", "mask", "mouse", "ergonomic", "organic", "sculpted", "creature", "horn", "shell",
                      "pebble", "wearable", "controller", "figure", "character", "flowing", "aerodynamic",
                      "streamlined", "drone", "visor", "faceplate", "boat", "car"),
    "mechanism": ("gear", "gearbox", "planetary", "ratchet", "hinge", "hinged", "cam", "lever", "linkage", "four-bar",
                  "slide", "slider", "sliding", "bayonet", "latch", "detent", "pivot", "articulated", "pawl", "clamp",
                  "quick-release", "chain", "trigger"),
    "revolve": ("vase", "pot", "planter", "bottle", "cup", "knob", "lamp", "shade", "turned", "lathe", "spindle",
                "round", "cylindrical", "coupler", "pulley", "wheel", "handle", "cap", "bowl", "screwdriver"),
}
#: route -> how its skeleton is built (real helper names; checked by tests/test_creation_guidance.py)
SKELETON = {
    "prismatic": "Box / extrude of the plan outline (build123d), fillets and holes as later features",
    "revolve": "craft.revolve_profile of the side outline (or a build123d revolve), grooves, flats and textures later",
    "skin+features": "one skin first: craft.checked_body or craft.section_shell through sections (craft.subd for a "
                     "NURBS cage), then openings, parts and details one feature at a time",
    "mechanism": "the fixed part first as its own solid, then each moving part with its clearance; joints in "
                 "assembly(), gears and pins with form.parts, craft.planetary or craft.pin_hinge",
}
#: words that make a brief multi-part: it must then declare its parts, the clearances between them and magnet stock
MULTI_PART = ("magnet", "magnets", "magnetic", "separate", "two-part", "multi-part", "detachable", "removable", "lid",
              "faceplate", "assembly", "assembled")
#: standard disc magnet stock (diameter x thickness, mm); form.craft may publish its own table as MAGNETS
MAGNET_STOCK = ("6x2", "6x3", "8x3", "10x3")

#: helpers whose step is risky (skins, booleans on skins, B-rep textures, sweeps) or medium (mechanisms, shells,
#: fillets, booleans); everything else is low
_HIGH = ("loft_sections", "section_body", "section_shell", "inset_body", "checked_body", "helmet_shell",
         "helmet_fullface", "helmet_open", "sweep_spline", "safe_loft", "safe_sweep", "surface_band", "offset_body",
         "two_view_cutter", "thicken", "inflate", "knurl", "emboss_cells", "wrapped_ribs", "spiral_ribbed_body",
         "variable_fillet", "split_with_magnets", "slot_grille", "skin_from_sections", "split", "lens")
_MEDIUM = ("fuse", "cut", "safe_union", "safe_cut", "shell", "safe_shell", "safe_fillet", "safe_chamfer", "pin_hinge",
           "living_hinge", "cantilever_snap", "annular_snap", "bayonet", "dovetail", "detent", "ratchet", "cam",
           "four_bar", "gear_train", "planetary", "thread", "spur_gear", "gear_pair", "magnet_pocket", "magnet_boss",
           "revolve_profile", "mouse_form", "grip", "handle", "magnet_pair", "parts")
#: helper -> the real helpers to fall back to (only names that exist are offered)
_FALLBACK = {
    "fuse": ["craft.safe_union"], "cut": ["craft.safe_cut"], "loft_sections": ["craft.safe_loft", "craft.checked_body"],
    "section_body": ["craft.safe_loft"], "checked_body": ["craft.safe_loft"],
    "section_shell": ["craft.inset_body", "craft.safe_shell"], "inset_body": ["craft.safe_shell"],
    "shell": ["craft.safe_shell", "craft.inset_body"], "safe_fillet": ["craft.safe_chamfer"],
    "variable_fillet": ["craft.safe_fillet"], "sweep_spline": ["craft.safe_sweep"],
    "knurl": ["craft.MeshTexture"], "emboss_cells": ["craft.MeshTexture"], "wrapped_ribs": ["craft.MeshTexture"],
    "spiral_ribbed_body": ["craft.MeshTexture"], "surface_band": ["craft.offset_body"],
    "two_view_cutter": ["craft.safe_cut"], "thicken": ["craft.safe_shell"],
    "skin_from_sections": ["craft.checked_body", "craft.section_shell"], "split": ["craft.split_with_magnets"],
}
_REF = re.compile(r"\b(?:form\.)?(craft|parts|patterns|marks)\.([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?")
_REG: dict = {}


def _public_names(path: Path) -> set:
    """Top-level public names of one module, read with ast (nothing is imported, so OCCT is not needed)."""
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, ast.ImportFrom):
            out |= {a.asname or a.name for a in n.names}
    return {x for x in out if not x.startswith("_")}


def registry() -> dict:
    """The helpers a plan may name, read from the code as it is now: {"craft": its top-level names, "craft.<module>":
    that module's names for every module in form/craft, "parts" / "patterns" / "marks": theirs}. Cached until a file
    changes, so helpers added to form.craft are known without touching this list."""
    from . import craft
    here = Path(__file__).resolve().parent
    files = sorted((here / "craft").glob("*.py")) + [here / f"{m}.py" for m in ("parts", "patterns", "marks",
                                                                                 "feature_helpers")]
    stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files if f.is_file())
    if _REG.get("stamp") == stamp:
        return _REG["reg"]
    mods = {f.stem: _public_names(f) for f in sorted((here / "craft").glob("*.py")) if not f.stem.startswith("_")}
    top = {x for x in set(dir(craft)) | set(mods) if not x.startswith("_")}
    reg = {"craft": top, **{f"craft.{m}": names for m, names in mods.items()}}
    for m in ("parts", "patterns", "marks"):
        reg[m] = _public_names(here / f"{m}.py")
    reg["craft.patterns"], reg["craft.features"] = reg["patterns"], _public_names(here / "feature_helpers.py")
    _REG.update(stamp=stamp, reg=reg)
    return reg


def _universe(reg: dict) -> list[str]:
    return [f"{ns}.{n}" for ns, names in reg.items() for n in names]


def check_how(how: str) -> dict:
    """Every helper reference in a `how` (craft.x, craft.module.x, parts.x, patterns.x, marks.x) checked against the
    registry: {"helpers": [real names], "unknown": [{"name", "closest": [real names]}]}."""
    import difflib
    reg = registry()
    found, unknown = [], []
    for m in _REF.finditer(how or ""):
        ns, a, b = m.group(1), m.group(2), m.group(3)
        if ns == "craft" and b and f"craft.{a}" in reg:          # craft.organic.magnet_pocket
            name, ok = f"craft.{a}.{b}", b in reg[f"craft.{a}"]
        else:
            name, ok = f"{ns}.{a}", a in reg.get(ns, set())
        if ok:
            found.append(name)
            continue
        bare = name.rsplit(".", 1)[-1]
        where = sorted(f"{k}.{bare}" for k, v in reg.items() if bare in v)
        close = where + [c for c in difflib.get_close_matches(name, _universe(reg), n=4, cutoff=0.6) if c not in where]
        unknown.append({"name": name, "closest": close[:4]})
    return {"helpers": list(dict.fromkeys(found)), "unknown": unknown}


def is_multi_part(text: str, parts=None) -> bool:
    """Does this brief describe separate parts (magnets, a lid, a faceplate, "separate parts"), or does its plan
    list two or more parts?"""
    return bool(set(MULTI_PART) & _words(text or "")) or len(parts or []) >= 2


def route(text: str) -> dict:
    """The construction route for a brief: prismatic, revolve, skin+features or mechanism (heuristic, and said to be),
    with the words that chose it and how its skeleton is built."""
    w = _words(_NOT.sub(" ", text or ""))
    hits = {r: sorted(k for k in kws if k in w) for r, kws in _ROUTE_WORDS.items()}
    pick = next((r for r in ("skin+features", "mechanism", "revolve") if hits[r]), "prismatic")
    # a turned part with one mechanism word (a knob with a pointer, a cap with a bayonet) stays revolve when its
    # revolve words outnumber the mechanism ones; a styled skin always wins
    if pick == "mechanism" and len(hits["revolve"]) > len(hits["mechanism"]):
        pick = "revolve"
    return {"route": pick, "because": hits.get(pick, []), "skeleton": SKELETON[pick], "multi_part": is_multi_part(text),
            "evidence": "heuristic"}


def magnet_stock() -> tuple:
    """Magnet sizes a plan may name: form.craft's MAGNETS table when a module has one (read without importing),
    else MAGNET_STOCK."""
    import ast
    for f in sorted((Path(__file__).resolve().parent / "craft").glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MAGNETS" for t in n.targets):
                try:
                    v = ast.literal_eval(n.value)
                except ValueError:
                    continue
                keys = [str(k) for k in (v.keys() if isinstance(v, dict) else v)]
                if keys:
                    return tuple(keys)
    return MAGNET_STOCK


def _risk(helpers: list, how: str, i: int, route_: str) -> tuple[str, str]:
    bare = {h.rsplit(".", 1)[-1] for h in helpers}
    low = (how or "").lower()
    words = ("loft", "sweep", "texture", "skin", "nurbs")
    if bare & set(_HIGH) or any(k in low for k in words):
        why = sorted(bare & set(_HIGH)) or [k for k in words if k in low]
        return "high", "skin, sweep or texture work: " + ", ".join(why)
    if bare & set(_MEDIUM) or any(k in low for k in ("fillet", "shell", "boolean", "hinge", "snap", "thread", "gear",
                                                     "magnet", "split")):
        return "medium", "booleans, fillets, shells or a mechanism"
    if i > 0 and route_ == "skin+features":
        return "medium", "a boolean on a free-form skin"
    return "low", "primitives and flat-face operations"


def _fallback(helpers: list, risk: str) -> list[str]:
    reg = registry()
    out = []
    for h in helpers:
        for f in _FALLBACK.get(h.rsplit(".", 1)[-1], []):
            ns, name = f.rsplit(".", 1)
            if name in reg.get(ns, set()) and f not in out:
                out.append(f)
    if risk == "high":
        out.append("build_candidates with 2-3 feature-level versions of this step")
    out.append(f"defer it after {RETRIES} retries and go on with the next feature")
    return out


def steps(features: list, route_: str = "prismatic") -> list[dict]:
    """The plan as executable steps, in build order: the call to make, the feature's construction route (router:
    kernel, subd_cage, sculpt_recon or procedural) with the real helpers and tools for it, the helpers its how uses,
    the risk class, the fallback (real helper names only) and the retry cap."""
    from . import router
    out = []
    for i, f in enumerate(features):
        how = str(f.get("how", ""))
        c = check_how(how)
        risk, why = _risk(c["helpers"], how, i, route_)
        if i == 0:
            call = {"tool": "create_design", "with": "a FeatureDesign whose only @feature method is this one (the "
                    "skeleton); look at the sheet before adding more"}
        else:
            call = {"tool": "add_feature", "with": f"kind=\"code\", feature=\"{f['id']}\", "
                    f"code=\"def {f['id']}(self, v, body): ...\""}
            if risk == "high":
                call["alternative"] = {"tool": "build_candidates", "with": "project=..., candidates=[{label, feature: "
                                       f"\"{f['id']}\", code}}, ...]: built on the shared checkpoint of the features "
                                       "before it"}
        fr = router.feature_route(f)
        rp = router.plan_for(fr["route"])
        if fr["route"] != "kernel" and any(t["available"] for t in rp["tools"]):
            call["mesh"] = {"tool": "model_mesh", "with": f"the {fr['route']} ops for {f['id']}; the result is "
                            "written back into the design source"}
        out.append({"step": i + 1, "id": f["id"], "label": f.get("label", f["id"]), "how": how,
                    **({"part": f["part"]} if f.get("part") else {}), "route": fr, "route_plan": rp,
                    "helpers": c["helpers"], "risk": risk,
                    "risk_why": why, "fallback": _fallback(c["helpers"], risk), "retries": RETRIES, "call": call,
                    "then": "render(view=\"sheet\") and look" if i == 0 or risk != "low" else "next step"})
    return out


def advice(text: str, features: list | None = None) -> dict:
    """What design_brief and plan_design return besides the record: the route and, given a plan, its steps."""
    r = route(text)
    out = {"route": r["route"], "route_because": r["because"], "skeleton": r["skeleton"], "multi_part": r["multi_part"],
           "retries_per_feature": RETRIES,
           "loop": "skeleton first (create_design with the main body only), then one feature per call "
                   "(add_feature(kind=\"code\") or update_design(feature=, code=)); render and look after each; a "
                   f"feature that still fails after {RETRIES} retries is deferred, listed at the end, and never "
                   "blocks the design",
           "evidence": "heuristic"}
    if features is not None:
        out["steps"] = steps(features, r["route"])
    return out


def _check_plan(b: dict, feats: list, parts: list, clearances, magnets) -> tuple[dict, list, list]:
    """Refuse a plan naming helpers that do not exist or a route that is not one of router.ROUTES; a multi-part brief
    must declare its parts, the clearances between them and, when it has magnets, their stock. Warn (not refuse)
    when a mechanical interface (hole, thread, magnet pocket, snap, bearing seat, mating face) sits on a mesh-only
    route. Returns (clearances, magnets) normalised and the warnings."""
    from . import router
    badr = router.validate(feats)
    if badr:
        raise StudioError("Unknown construction route: " + "; ".join(badr) + ".",
                          "route is one of " + ", ".join(router.ROUTES) + ", or leave it out to have it read from "
                          "the feature's words (design_guide topic \"hybrid\").", status=422)
    bad = []
    for f in feats:
        for u in check_how(str(f.get("how", "")))["unknown"]:
            bad.append(f"{f['id']}: {u['name']}" + (f" (closest: {', '.join(u['closest'])})" if u["closest"] else
                                                    " (no close helper)"))
    if bad:
        raise StudioError("The plan names helpers that do not exist: " + "; ".join(bad[:8]) + ".",
                          "Use the real names (the closest ones are listed), or describe the construction in words. "
                          "design_guide(topic=...) documents form.craft.", status=422, unknown=bad)
    text = " ".join([b.get("goal", ""), b.get("name", ""), " ".join(map(str, b.get("requirements") or [])),
                     b.get("style", "") or ""] + [str(f.get("how", "")) + " " + str(f.get("label", "")) for f in feats])
    cl = clearances or {}
    if not isinstance(cl, dict):
        raise StudioError("clearances must be an object: {\"faceplate/shell\": 0.3} (mm per side).")
    for p in parts:
        if isinstance(p, dict) and isinstance(p.get("clearance"), (int, float)):
            cl.setdefault(str(p.get("id")), p["clearance"])
    try:
        cl = {str(k): float(v) for k, v in cl.items()}
    except (TypeError, ValueError):
        raise StudioError("Every clearance must be a number in mm.")
    if any(not 0 <= v <= 5 for v in cl.values()):
        raise StudioError("A clearance is outside 0-5 mm.", "Clearances are the designed gap per side, in mm.")
    mags = magnets or []
    if not isinstance(mags, list):
        raise StudioError("magnets must be a list: [{\"stock\": \"8x3\", \"count\": 4, \"retention\": \"press\"}].")
    stock = magnet_stock()
    for m in mags:
        if not isinstance(m, dict) or str(m.get("stock", "")) not in stock:
            raise StudioError(f"Unknown magnet stock {m.get('stock') if isinstance(m, dict) else m!r}.",
                              "Stock: " + ", ".join(stock) + " (diameter x thickness, mm).")
    if is_multi_part(text, parts):
        missing = []
        if len([p for p in parts if isinstance(p, dict) and p.get("id")]) < 2:
            missing.append("parts (two or more {id, label})")
        if not cl:
            missing.append("clearances between them ({\"a/b\": mm per side})")
        if ({"magnet", "magnets", "magnetic"} & _words(text)) and not mags:
            missing.append("magnet stock ([{stock, count, retention}], stock one of " + ", ".join(stock) + ")")
        if missing:
            raise StudioError("This is a multi-part design; the plan must declare " + ", ".join(missing) + ".",
                              "Separate parts are modelled as separate solids with a designed gap; magnets are bought "
                              "stock with a pocket clearance. Pull force stays unknown without a datasheet value.",
                              status=422)
    return cl, mags, router.warnings(feats)
