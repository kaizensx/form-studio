"""Exemplar designs: complete, high-quality Form Studio designs for the agent to learn construction from.

Each file here is a full design source (one Recipe subclass, build123d algebra API, form.craft helpers) that builds in
the kernel, plus META: {"title", "category", "tags", "techniques", "lessons", "product_class"?}. They are served to the
agent by the MCP tool design_examples and are never projects: nothing here appears in the app's library or project
list. Categories: mechanical, consumer, organic, textured, assembly, helmet, enclosure.

    from form import exemplars
    exemplars.catalogue()            # [{name, title, category, tags, techniques, lessons, summary, snippets}]
    exemplars.search("helmet texture")          # ranked (BM25 over name, tags, title, techniques, lessons ...)
    exemplars.snippets("loft a shell and keep it one solid")   # technique snippets: just the block that does it
    exemplars.get("helmet")          # + "source"
    exemplars.load("helmet")         # the Design instance (needs build123d)

A technique snippet is a block of an exemplar's build() between `# --- snippet: <title>` and `# --- end snippet`.

Every exemplar is also exposed as decomposed steps (steps(name), in get() and in search hits): its features in build
order, each with the form.craft helpers it calls and its lines, so an agent can rebuild it skeleton first, one feature
per call. For a FeatureDesign they are its @feature methods; for a plain Recipe, the Stage("id", ...) calls of build()
in order, with the helpers called since the stage before. META "steps" overrides them.

Routing: search() puts an exemplar first when the query names its product and one of its distinguishing parts
(ROUTES, or the exemplar's own META "route": {"all": [...], "any": [...]}), e.g. a full-face helmet with separate
parts, magnets or lenses goes to hero_helmet when that exemplar is present.

An exemplar whose META says "retrieval": False is kept in the repo (it still builds and is tested) but search,
snippets and the listing never offer it, so the agent does not learn from it; get(name) still returns it, with the
reason. character_mask, prop_mask and scifi_helmet are flagged so until they are redone: they read as eggs.

Reading the catalogue parses the files (ast) and imports nothing, so the MCP server stays importable without OCCT.
The packaged app ships these files as source (packaging/form.spec); tests/test_packaging_data.py checks it.
"""
from __future__ import annotations

import ast
import importlib.util
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = ("mechanical", "consumer", "organic", "textured", "assembly", "helmet", "enclosure")
_SNIP = re.compile(r"^([ \t]*)# --- snippet:\s*(.+?)\s*$(.*?)^[ \t]*# --- end snippet\s*$", re.M | re.S)
_CACHE: dict = {}


def _files() -> list[Path]:
    return sorted(p for p in HERE.glob("*.py") if not p.name.startswith("_"))


def _snippets_of(src: str, name: str) -> list[dict]:
    out = []
    for m in _SNIP.finditer(src):
        ind = len(m.group(1))
        lines = [ln[ind:] if ln[:ind].strip() == "" else ln for ln in m.group(3).strip("\n").splitlines()]
        out.append({"exemplar": name, "title": m.group(2), "code": "\n".join(lines).rstrip()})
    return out


def _meta(path: Path) -> dict:
    key = (str(path), path.stat().st_mtime_ns)
    if key in _CACHE:
        return _CACHE[key]
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    meta, summary, title = {}, "", ""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "META" for t in node.targets):
            meta = ast.literal_eval(node.value)
        if isinstance(node, ast.ClassDef):
            for b in node.body:
                if isinstance(b, ast.Assign) and len(b.targets) == 1 and isinstance(b.targets[0], ast.Tuple):
                    names = [getattr(t, "id", "") for t in b.targets[0].elts]
                    if names[:2] == ["title", "summary"] and isinstance(b.value, ast.Tuple):
                        title, summary = (ast.literal_eval(x) for x in b.value.elts[:2])
    craft_calls = sorted(set(re.findall(r"\bcraft\.([a-z_]+)\(", src)))
    out = {"name": path.stem, "title": meta.get("title") or title, "summary": summary,
           "category": meta.get("category", ""), "product_class": meta.get("product_class"),
           "tags": list(meta.get("tags", [])), "lessons": list(meta.get("lessons", [])),
           "techniques": list(meta.get("techniques", [])), "craft": craft_calls,
           "retrieval": bool(meta.get("retrieval", True)), "retrieval_note": meta.get("retrieval_note", ""),
           "snippets": [s["title"] for s in _snippets_of(src, path.stem)],
           "steps": list(meta["steps"]) if isinstance(meta.get("steps"), list) else _steps_of(tree),
           **({"route": meta["route"]} if isinstance(meta.get("route"), dict) else {})}
    _CACHE[key] = out
    return out


def _craft_name(call) -> str:
    """craft.x or craft.module.x when this ast Call calls a form.craft helper, else ""."""
    f, parts = call.func, []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name) and f.id == "craft" and parts:
        return "craft." + ".".join(reversed(parts))
    return ""


def _craft_calls(node) -> list[tuple]:
    """(line, helper) of every form.craft call inside an ast node, in source order."""
    out = [(n.lineno, _craft_name(n)) for n in ast.walk(node) if isinstance(n, ast.Call)]
    return sorted(x for x in out if x[1])


def _lit(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _is_feature_deco(d) -> bool:
    return getattr(d.func if isinstance(d, ast.Call) else d, "id", "") == "feature"


def _steps_of(tree: ast.Module) -> list[dict]:
    """The exemplar's features in build order with the helpers each uses (see the module docstring)."""
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Design"), None)
    if cls is None:
        return []
    labels = {}
    for b in cls.body:                                      # features = [Feature("id", "Label", "role"), ...]
        if isinstance(b, ast.Assign) and any(getattr(t, "id", "") == "features" for t in b.targets) \
                and isinstance(b.value, (ast.List, ast.Tuple)):
            for e in b.value.elts:
                if isinstance(e, ast.Call) and e.args:
                    a = [_lit(x) for x in e.args[:3]]
                    if isinstance(a[0], str):
                        labels[a[0]] = {"label": a[1] if len(a) > 1 else a[0], "role": a[2] if len(a) > 2 else ""}
    feats = []
    for b in cls.body:                                      # a FeatureDesign: one @feature method per feature
        if isinstance(b, ast.FunctionDef) and any(_is_feature_deco(d) for d in b.decorator_list):
            d = next(d for d in b.decorator_list if _is_feature_deco(d))
            lab = _lit(d.args[0]) if isinstance(d, ast.Call) and d.args else None
            role = next((_lit(k.value) for k in getattr(d, "keywords", []) if k.arg == "role"), "structure")
            feats.append({"id": b.name, "label": lab or b.name.replace("_", " ").capitalize(), "role": role,
                          "craft": list(dict.fromkeys(c for _, c in _craft_calls(b))), "lines": [b.lineno, b.end_lineno]})
    if feats:
        return feats
    build = next((b for b in cls.body if isinstance(b, ast.FunctionDef) and b.name == "build"), None)
    if build is None:
        return [{"id": k, **v, "craft": []} for k, v in labels.items()]
    marks = sorted((n.lineno, _lit(n.args[0])) for n in ast.walk(build) if isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "Stage" and n.args and isinstance(_lit(n.args[0]), str))
    calls = _craft_calls(build)
    out, seen, prev = [], set(), build.lineno
    for line, fid in marks:
        if fid not in seen:
            seen.add(fid)
            used = list(dict.fromkeys(c for ln, c in calls if prev < ln <= line))
            out.append({"id": fid, "label": labels.get(fid, {}).get("label", fid),
                        "role": labels.get(fid, {}).get("role", ""), "craft": used, "lines": [prev + 1, line]})
        prev = line
    out += [{"id": k, **v, "craft": []} for k, v in labels.items() if k not in seen]
    return out


def steps(name: str) -> list[dict]:
    """One exemplar as decomposed steps: [{"id", "label", "role", "craft": [helpers], "lines"}] in build order."""
    return list(get(name)["steps"])


def catalogue() -> list[dict]:
    """Every exemplar in the repo, the ones flagged not for retrieval included."""
    return [_meta(p) for p in _files()]


def retrievable() -> list[dict]:
    """The exemplars search, snippets and the listing offer: those not flagged "retrieval": False."""
    return [e for e in catalogue() if e.get("retrieval", True)]


def _hidden() -> set[str]:
    return {e["name"] for e in catalogue() if not e.get("retrieval", True)}


# ---- search: BM25 over weighted fields ------------------------------------------------------------------------------

_STOP = set("a an and the of for with to in on by or is it its as at be this that from into my me i want make".split())
_FIELDS = (("name", 3.0), ("tags", 3.0), ("title", 2.0), ("category", 2.0), ("snippets", 1.5), ("techniques", 1.5),
           ("craft", 1.0), ("summary", 1.0), ("lessons", 0.4))


def _stem(w: str) -> str:
    for suf in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower().replace("_", " ")) if w not in _STOP]


def _doc(e: dict) -> dict:
    """Weighted term frequencies of one exemplar."""
    tf: dict = {}
    for field, w in _FIELDS:
        v = e.get(field) or ""
        text = " ".join(v) if isinstance(v, list) else str(v)
        for t in _tokens(text):
            tf[t] = tf.get(t, 0.0) + w
    return tf


def _rank(query: str, docs: list[tuple[dict, dict]], k1: float = 1.4, b: float = 0.6) -> list[tuple[float, dict]]:
    q = list(dict.fromkeys(_tokens(query)))
    if not q or not docs:
        return []
    n = len(docs)
    lens = [sum(tf.values()) for _, tf in docs]
    avg = sum(lens) / n or 1.0
    df = {t: sum(1 for _, tf in docs if t in tf) for t in q}
    out = []
    for (e, tf), ln in zip(docs, lens):
        s = 0.0
        for t in q:
            f = tf.get(t, 0.0)
            if not f:                                     # a prefix match counts a little ("gear" in "gearbox")
                f = 0.3 * sum(v for k, v in tf.items() if len(t) > 3 and (k.startswith(t) or t.startswith(k)))
                if not f:
                    continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * ln / avg))
        name = set(_tokens(e.get("name", ""))) if isinstance(e, dict) and "name" in e else set()
        if s > 0 and name and name <= set(q):           # the query names this exemplar outright
            s += 2.0
        if s > 0:
            out.append((s, e))
    out.sort(key=lambda x: -x[0])
    return out


#: product + distinguishing parts -> the exemplars to put first, when present and retrievable. An exemplar can
#: declare the same in its META as "route": {"all": [...], "any": [...]}.
ROUTES = [{"all": ["helmet"], "any": ["magnet", "separate", "part", "lens", "faceplate", "split", "detachable"],
           "prefer": ["hero_helmet"]}]


def routed(query: str, cat: list[dict] | None = None) -> list[str]:
    """Exemplar names the query is routed to, in order (ROUTES and META "route")."""
    cat = retrievable() if cat is None else cat
    q = set(_tokens(query))
    names = {e["name"] for e in cat}
    rules = list(ROUTES) + [{**e["route"], "prefer": [e["name"]]} for e in cat if e.get("route")]
    out = []
    for r in rules:
        need = {_stem(w) for w in r.get("all", [])}
        anyw = {_stem(w) for w in r.get("any", [])}
        if need and need <= q and (not anyw or anyw & q):
            out += [n for n in r["prefer"] if n in names and n not in out]
    return out


def search(query: str, limit: int = 5, category: str | None = None) -> list[dict]:
    """Exemplars ranked for the query (BM25 over name, tags, title, category, snippet titles, techniques, craft calls,
    summary and lessons); a query routed to an exemplar (routed()) puts it first. Each hit carries the technique
    snippets that match the query best (up to 2) and its decomposed steps."""
    cat = [e for e in retrievable() if not category or e.get("category") == category]
    ranked = [e for _, e in _rank(query, [(e, _doc(e)) for e in cat])]
    first = routed(query, cat)
    by = {e["name"]: e for e in cat}
    ranked = [by[n] for n in first] + [e for e in ranked if e["name"] not in first]
    hits = [dict(e) for e in ranked[:limit]]
    for h in hits:
        snips = snippets(query, limit=2, names=[h["name"]])
        if snips:
            h["matching_snippets"] = snips
    return hits


def snippets(query: str = "", limit: int = 4, names: list[str] | None = None) -> list[dict]:
    """Technique snippets ranked for the query: [{"exemplar", "title", "code"}]. The block of build() that does one
    thing well (hollow a lofted shell, cut a two-view opening, a snap fit with a named clearance)."""
    rows = []
    hidden = _hidden()
    for p in _files():
        if (names and p.stem not in names) or p.stem in hidden:
            continue
        src = p.read_text(encoding="utf-8")
        for s in _snippets_of(src, p.stem):
            tf: dict = {}
            for t in _tokens(s["title"]):
                tf[t] = tf.get(t, 0.0) + 3.0
            for t in _tokens(s["code"]):
                tf[t] = tf.get(t, 0.0) + 0.3
            rows.append((s, tf))
    if not query:
        return [s for s, _ in rows[:limit]]
    return [s for _, s in _rank(query, rows)[:limit]]


def coverage() -> dict:
    """How many exemplars each category has."""
    out = {c: 0 for c in CATEGORIES}
    for e in catalogue():
        out[e.get("category") or "uncategorised"] = out.get(e.get("category") or "uncategorised", 0) + 1
    return out


def get(name: str) -> dict:
    p = HERE / f"{name}.py"
    if not re.fullmatch(r"[a-z0-9_]+", name or "") or not p.is_file():
        raise KeyError(name)
    src = p.read_text(encoding="utf-8")
    meta = _meta(p)
    return {**meta, "source": src, "snippet_code": _snippets_of(src, name),
            "how_to_use": ("Not for learning from: " + meta["retrieval_note"]) if not meta.get("retrieval", True) else
                          "Learn the construction; write your own design for the person's brief. Exemplars are "
                          "references, not templates to hand over."}


def path(name: str) -> Path:
    p = HERE / f"{name}.py"
    if not p.is_file():
        raise KeyError(name)
    return p


def load(name: str):
    """The exemplar's Design instance (imports build123d)."""
    spec = importlib.util.spec_from_file_location(f"form_exemplar_{name}", path(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, "Design")
    inst = cls()
    inst.id = f"exemplar:{name}"
    return inst
