"""Starters: the prompts and brief templates Home offers, learned from what this person actually designs.

Nothing here calls a model. The ranking is plain arithmetic over local facts:

- the recipes (or "designed as code") and brief templates of the projects in the data folder, newer ones counting more
  (half-life 30 days);
- the briefs written for those projects;
- the printer and material selected in the slicer;
- what was clicked, pinned, edited, removed or added on Home.

A brand-new data folder has no history, so it gets a short list of sensible defaults. Once there is history the
defaults that have nothing to do with it drop out, and starters learned from the person's own designs take their
place. Pinned starters always come first. Everything the person changes is kept in ``<data>/.form-starters.json``.

    form starters                         the ranked starters as JSON (what Home shows)
    form starters add "A cable clip for 6 mm cords"
    form starters pin ID | unpin ID | remove ID | edit ID "new text" | restore
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

from . import fsutil

FILE = ".form-starters.json"
HALF_LIFE_DAYS = 30.0
MAX_TEXT = 300
MAX_CUSTOM = 60
MIN_PROMPTS = 3

# Defaults for a new data folder. `recipes` and `presets` say which kinds of design each one is about, so a default
# survives into a person's history only when it matches what they make.
DEFAULT_PROMPTS = [
    {"id": "d-pi5-case", "text": "A case for a Raspberry Pi 5 with a snap-on lid",
     "recipes": ["enclosure", "storage_box", "hinged_box"], "presets": ["enclosure"]},
    {"id": "d-gridfinity", "text": "A Gridfinity bin, 3 × 1, for screwdrivers",
     "recipes": ["gridfinity_bin", "gridfinity_baseplate", "gridfinity"], "presets": ["organizer"]},
    {"id": "d-hook", "text": "The lightest wall hook that safely holds 5 kg",
     "recipes": ["pegboard", "shelf_bracket", "hook"], "presets": ["bathroom-mount"]},
    {"id": "d-dock", "text": "A phone stand for video calls, with a slot for the charging cable",
     "recipes": ["device_stand", "dock"], "presets": ["desk-accessory"]},
    {"id": "d-skadis", "text": "A SKÅDIS pegboard cup for pens and screwdrivers",
     "recipes": ["pegboard"], "presets": []},
    {"id": "d-remote", "text": "A holder for the TV remote that screws under the coffee table",
     "recipes": ["device_stand", "dock"], "presets": ["remote-holder"]},
    {"id": "d-planter", "text": "A self-watering pot for a 9 cm nursery pot, for herbs on the windowsill",
     "recipes": ["plant_pot", "planter"], "presets": []},
    {"id": "d-hose", "text": "An adapter from my 35 mm vacuum hose to a 32 mm tool",
     "recipes": ["hose_adapter"], "presets": []},
    {"id": "d-car", "text": "A cable clip for the car's air vent that survives a hot summer",
     "recipes": ["cable_organizer"], "presets": ["automotive-accessory"]},
]


_LOCK = threading.Lock()


class StarterError(ValueError):
    pass


# ---- state ------------------------------------------------------------------

def _empty() -> dict:
    return {"version": 1, "custom": [], "templates": [], "hidden": [], "pinned": {}, "uses": {}}


def path(root) -> Path:
    return Path(root) / FILE


def load(root) -> dict:
    try:
        s = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(s, dict):
        return _empty()
    out = _empty()
    for k, v in out.items():
        if isinstance(s.get(k), type(v)):
            out[k] = s[k]
    return out


def _save(root, s: dict) -> dict:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    fsutil.replace(tmp, p)
    return s


def _clean(text) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        raise StarterError("A starter needs some words.")
    if len(t) > MAX_TEXT:
        raise StarterError(f"Keep a starter under {MAX_TEXT} characters.")
    return t


# ---- history: what this person designs ---------------------------------------

def history(st) -> list[dict]:
    """Facts about every readable project in a Studio: recipe kind, brief template, brief text, last change."""
    out = []
    for row in st.list():
        if row.get("error"):
            continue
        try:
            p = st.load(row["id"])
        except Exception:
            continue
        rid = str(p.get("recipe") or "")
        brief = p.get("brief") or {}
        out.append({"id": p["id"], "name": p.get("name") or p["id"], "recipe": rid,
                    "kind": "code" if rid.startswith(("src:", "scad:")) else rid,
                    "preset": brief.get("preset") or "", "brief": str(brief.get("text") or ""),
                    "updated": float(p.get("updated") or p.get("created") or 0)})
    return out


def context(st) -> dict:
    """The printer and material selected in the slicer, if one is known. Never raises."""
    try:
        s = st.slicer_info()
    except Exception:
        return {}
    if not s or not s.get("available"):
        name = ((getattr(st, "cfg", None) or {}).get("printer") or {}).get("name")
        return {"printer": name} if name else {}
    pr = s.get("presets") or {}
    return {"printer": _printer_name((pr.get("machine") or {}).get("name", "")),
            "material": material_of((pr.get("filament") or {}).get("name", ""))}


def _printer_name(name: str) -> str:
    return re.sub(r"\s+\d+(\.\d+)?\s*nozzle$", "", str(name or "")).strip()


_MATERIALS = ("PETG", "PLA", "ABS", "ASA", "TPU", "PC", "PA", "PVA", "HIPS")


def material_of(filament: str) -> str:
    """'Bambu PLA Basic @BBL A1M' → 'PLA'. Empty when no common material name is in it."""
    words = re.findall(r"[A-Za-z]+", str(filament or "").upper())
    for m in _MATERIALS:
        if m in words:
            return m
    return ""


def _weight(updated: float, now: float) -> float:
    age_days = max(0.0, (now - float(updated or 0)) / 86400.0)
    return max(0.25, 0.5 ** (age_days / HALF_LIFE_DAYS))


def affinity(hist: list[dict], now: float | None = None) -> tuple[dict, dict]:
    """(recipe kind → weight, brief template → weight), newer projects weighing more."""
    now = time.time() if now is None else now
    kinds, presets = {}, {}
    for h in hist:
        w = _weight(h.get("updated", 0), now)
        if h.get("kind"):
            kinds[h["kind"]] = kinds.get(h["kind"], 0.0) + w
        if h.get("preset"):
            presets[h["preset"]] = presets.get(h["preset"], 0.0) + w
    return kinds, presets


def _brief_line(text: str) -> str:
    """A brief as a starter: without the template token, one line, at most 140 characters."""
    t = re.sub(r"\((?:Form Studio|FORM) brief b-[0-9a-f]{8}\)", "", text or "")
    t = re.sub(r"\s+", " ", t).strip(" .")
    if len(t) < 12:
        return ""
    return t if len(t) <= 140 else t[:137].rsplit(" ", 1)[0] + "…"


def _hid(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:10]


def learned(hist: list[dict], titles: dict, ctx: dict | None = None, now: float | None = None) -> list[dict]:
    """Starters made from the person's own designs: their most used kinds and their recent briefs."""
    now = time.time() if now is None else now
    ctx = ctx or {}
    kinds, _ = affinity(hist, now)
    out = []
    where = ""
    if ctx.get("material") and ctx.get("printer"):
        where = f", in {ctx['material']} for the {ctx['printer']}"
    elif ctx.get("material"):
        where = f", in {ctx['material']}"
    for kind, w in sorted(kinds.items(), key=lambda kv: -kv[1])[:3]:
        latest = max((h for h in hist if h["kind"] == kind), key=lambda h: h["updated"])
        if kind == "code":
            text = f"Something like “{latest['name']}”, for a new use{where}"
        else:
            title = titles.get(kind, kind.replace("_", " "))
            text = f"Another {title[0].lower() + title[1:]} like “{latest['name']}”{where}"
        out.append({"id": "l-kind-" + _hid(kind), "text": text, "source": "learned", "score": 30 + 12 * w,
                    "why": f"You made {sum(1 for h in hist if h['kind'] == kind)} of these", "recipes": [kind]})
    seen = set()
    for h in sorted(hist, key=lambda h: -h["updated"]):
        line = _brief_line(h.get("brief", ""))
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        out.append({"id": "l-brief-" + _hid(line), "text": line, "source": "learned", "score": 24 + 6 * _weight(h["updated"], now),
                    "why": f"Your brief for “{h['name']}”", "recipes": [h["kind"]]})
        if len(seen) >= 3:
            break
    return out


# ---- ranking ------------------------------------------------------------------

def rank_prompts(state: dict, hist: list[dict], titles: dict | None = None, ctx: dict | None = None,
                 limit: int = 8, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    kinds, presets = affinity(hist, now)
    uses = state.get("uses") or {}
    hidden = set(state.get("hidden") or [])
    pinned = state.get("pinned") or {}
    has_history = bool(hist) or any(u.get("n") for u in uses.values() if isinstance(u, dict))

    def usage(i):
        u = uses.get(i) or {}
        return 10 * min(int(u.get("n", 0)), 10) + (3 * _weight(u.get("last", 0), now) if u.get("last") else 0)

    items = []
    for c in state.get("custom") or []:
        items.append({"id": c["id"], "text": c["text"], "source": "mine", "score": 50 + usage(c["id"]), "why": "Added by you"})
    for c in learned(hist, titles or {}, ctx, now):
        c["score"] += usage(c["id"])
        items.append(c)
    spare = []
    for n, d in enumerate(DEFAULT_PROMPTS):
        aff = sum(kinds.get(r, 0) for r in d["recipes"]) + sum(presets.get(p, 0) for p in d["presets"])
        row = {"id": d["id"], "text": d["text"], "source": "suggested", "why": "Suggested",
               "score": (15 + 10 * aff if has_history else 10 - 0.1 * n) + usage(d["id"])}
        if not has_history or aff > 0 or usage(d["id"]):
            items.append(row)
        else:
            spare.append(row)
    items = [i for i in items if i["id"] not in hidden]
    # with a little history, the list still has something to offer
    for row in spare:
        if len(items) >= MIN_PROMPTS:
            break
        if row["id"] not in hidden:
            items.append(row)
    for i in items:
        i["pinned"] = i["id"] in pinned
        if i["pinned"]:
            i["score"] = 1000 + float(pinned[i["id"]]) / 1e10       # pinned first, in the order they were pinned
    items.sort(key=lambda i: -i["score"])
    out, seen = [], set()
    for i in items:
        k = i["text"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({k: v for k, v in i.items() if k != "recipes"} | {"score": round(i["score"], 3)})
    return out[:limit]


def rank_briefs(state: dict, presets: list[dict], hist: list[dict], ctx: dict | None = None,
                limit: int = 8, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    kinds, pw = affinity(hist, now)
    uses = state.get("uses") or {}
    hidden = set(state.get("hidden") or [])
    pinned = state.get("pinned") or {}
    material = (ctx or {}).get("material", "")
    items = []
    for t in state.get("templates") or []:
        items.append({"id": t["id"], "kind": "template", "preset": t["preset"], "title": t["title"],
                      "summary": t.get("summary") or "Your saved answers", "answers": t.get("answers") or {},
                      "measured": bool(t.get("measured")), "source": "mine",
                      "score": 40 + 10 * min(int((uses.get(t["id"]) or {}).get("n", 0)), 10)})
    for n, p in enumerate(presets):
        sc = 10 - 0.1 * n + 20 * pw.get(p["id"], 0) + 5 * kinds.get(p.get("closest_recipe") or "", 0)
        if material and (p.get("material") or {}).get("suggested", "").upper().startswith(material):
            sc += 1
        sc += 10 * min(int((uses.get("p-" + p["id"]) or {}).get("n", 0)), 10)
        items.append({"id": "p-" + p["id"], "kind": "preset", "preset": p["id"], "title": p["title"], "summary": p.get("summary", ""),
                      "source": "learned" if pw.get(p["id"]) else "related" if kinds.get(p.get("closest_recipe") or "") else "suggested",
                      "score": sc})
    items = [i for i in items if i["id"] not in hidden]
    for i in items:
        i["pinned"] = i["id"] in pinned
        if i["pinned"]:
            i["score"] = 1000 + float(pinned[i["id"]]) / 1e10
        i["score"] = round(i["score"], 3)
    items.sort(key=lambda i: -i["score"])
    return items[:limit]


def listing(root, hist: list[dict], presets: list[dict], titles: dict | None = None, ctx: dict | None = None,
            limit: int = 8, now: float | None = None) -> dict:
    s = load(root)
    return {"prompts": rank_prompts(s, hist, titles, ctx, limit, now),
            "briefs": rank_briefs(s, presets, hist, ctx, limit, now),
            "history": bool(hist), "hidden": len(s["hidden"]), "context": ctx or {}}


def for_studio(st, limit: int = 8) -> dict:
    from . import presets as presets_mod
    titles = {k: r.title for k, r in st.recipes.all_builtins().items()}     # legacy too: older designs name them
    return listing(st.root, history(st), presets_mod.all_presets(), titles, context(st), limit)


# ---- changes ------------------------------------------------------------------

def _known(s: dict, sid: str) -> bool:
    return (any(c["id"] == sid for c in s["custom"]) or any(t["id"] == sid for t in s["templates"])
            or any(d["id"] == sid for d in DEFAULT_PROMPTS) or bool(re.fullmatch(r"(l-(kind|brief)-[0-9a-f]{10}|p-[a-z0-9-]+)", sid)))


def _mutate(root, fn):
    with _LOCK:
        s = load(root)
        out = fn(s)
        _save(root, s)
        return out


def add(root, text: str) -> dict:
    text = _clean(text)

    def go(s):
        if len(s["custom"]) >= MAX_CUSTOM:
            raise StarterError(f"You have {MAX_CUSTOM} starters. Remove one first.")
        for c in s["custom"]:
            if c["text"].lower() == text.lower():
                return c
        c = {"id": "c-" + secrets.token_hex(4), "text": text, "created": time.time()}
        s["custom"].append(c)
        return c
    return _mutate(root, go)


def edit(root, sid: str, text: str) -> dict:
    """Change a starter's words. Editing a suggested or learned one keeps your version and hides the original."""
    text = _clean(text)

    def go(s):
        for c in s["custom"]:
            if c["id"] == sid:
                c["text"] = text
                return c
        if not _known(s, sid):
            raise StarterError("Unknown starter.")
        c = {"id": "c-" + secrets.token_hex(4), "text": text, "created": time.time()}
        s["custom"].append(c)
        if sid not in s["hidden"]:
            s["hidden"].append(sid)
        if sid in s["pinned"]:
            s["pinned"][c["id"]] = s["pinned"].pop(sid)
        return c
    return _mutate(root, go)


def remove(root, sid: str) -> dict:
    """Your own starters and templates are deleted; suggested and learned ones are hidden (restore brings them back)."""
    def go(s):
        before = len(s["custom"]) + len(s["templates"])
        s["custom"] = [c for c in s["custom"] if c["id"] != sid]
        s["templates"] = [t for t in s["templates"] if t["id"] != sid]
        s["pinned"].pop(sid, None)
        if len(s["custom"]) + len(s["templates"]) < before:
            return {"removed": sid, "how": "deleted"}
        if not _known(s, sid):
            raise StarterError("Unknown starter.")
        if sid not in s["hidden"]:
            s["hidden"].append(sid)
        return {"removed": sid, "how": "hidden"}
    return _mutate(root, go)


def pin(root, sid: str, on: bool = True) -> dict:
    def go(s):
        if not _known(s, sid):
            raise StarterError("Unknown starter.")
        if on:
            s["pinned"][sid] = time.time()
            s["hidden"] = [h for h in s["hidden"] if h != sid]
        else:
            s["pinned"].pop(sid, None)
        return {"id": sid, "pinned": bool(on)}
    return _mutate(root, go)


def used(root, sid: str) -> dict:
    def go(s):
        u = s["uses"].get(sid) or {}
        s["uses"][sid] = {"n": int(u.get("n", 0)) + 1, "last": time.time()}
        if len(s["uses"]) > 400:                       # forget the oldest
            keep = sorted(s["uses"].items(), key=lambda kv: -kv[1].get("last", 0))[:300]
            s["uses"] = dict(keep)
        return {"id": sid, **s["uses"][sid]}
    return _mutate(root, go)


def restore(root) -> dict:
    """Bring back every suggested and learned starter that was removed. Your own stay as they are."""
    def go(s):
        n = len(s["hidden"])
        s["hidden"] = []
        return {"restored": n}
    return _mutate(root, go)


def save_template(root, preset_id: str, answers: dict, title: str = "", measured: bool = False) -> dict:
    """Keep a filled-in brief as your own template. Answers are checked against the preset's questions."""
    from . import presets as presets_mod
    try:
        p = presets_mod.get(preset_id)
    except KeyError:
        raise StarterError("Unknown brief template.") from None
    keys = {q["key"]: q for q in p["questions"]}
    clean = {}
    for k, v in (answers or {}).items():
        if k in keys and str(v).strip():
            q = keys[k]
            v = str(v).strip()[:600]
            if q["kind"] == "choice" and v not in q.get("choices", []):
                raise StarterError(f"“{q['label']}”: pick one of the choices.")
            clean[k] = v
    if not clean:
        raise StarterError("Fill in at least one answer before saving it as a template.")
    title = re.sub(r"\s+", " ", str(title or "")).strip()[:80] or f"{p['title']} (mine)"
    summary = "; ".join(f"{keys[k]['label']}: {v}{' ' + keys[k]['unit'] if keys[k].get('unit') else ''}"
                        for k, v in list(clean.items())[:3])

    def go(s):
        t = {"id": "t-" + secrets.token_hex(4), "preset": p["id"], "title": title, "summary": summary[:120],
             "answers": clean, "measured": bool(measured), "created": time.time()}
        s["templates"].append(t)
        s["templates"] = s["templates"][-MAX_CUSTOM:]
        return t
    return _mutate(root, go)


# ---- command line ----------------------------------------------------------------

def main(argv=None) -> int:
    import sys

    from . import config
    from .studio import Studio
    argv = list(sys.argv[1:] if argv is None else argv)
    st = Studio(config.load())
    root = st.root
    verb = argv[0] if argv else "list"
    try:
        if verb == "list":
            out = for_studio(st)
        elif verb == "add" and len(argv) >= 2:
            out = add(root, " ".join(argv[1:]))
        elif verb == "edit" and len(argv) >= 3:
            out = edit(root, argv[1], " ".join(argv[2:]))
        elif verb in ("remove", "delete") and len(argv) == 2:
            out = remove(root, argv[1])
        elif verb in ("pin", "unpin") and len(argv) == 2:
            out = pin(root, argv[1], verb == "pin")
        elif verb == "restore":
            out = restore(root)
        else:
            print('usage: form starters [list] | add "text" | edit ID "text" | remove ID | pin ID | unpin ID | restore',
                  file=sys.stderr)
            return 2
    except StarterError as e:
        print(json.dumps({"error": {"message": str(e)}}, ensure_ascii=False))
        return 2
    finally:
        st.kernel.stop()
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0
