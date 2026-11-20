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
           "snippets": [s["title"] for s in _snippets_of(src, path.stem)]}
    _CACHE[key] = out
    return out


def catalogue() -> list[dict]:
    return [_meta(p) for p in _files()]


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


def search(query: str, limit: int = 5, category: str | None = None) -> list[dict]:
    """Exemplars ranked for the query (BM25 over name, tags, title, category, snippet titles, techniques, craft calls,
    summary and lessons). Each hit carries the technique snippets that match the query best (up to 2)."""
    cat = [e for e in catalogue() if not category or e.get("category") == category]
    hits = [dict(e) for _, e in _rank(query, [(e, _doc(e)) for e in cat])[:limit]]
    for h in hits:
        snips = snippets(query, limit=2, names=[h["name"]])
        if snips:
            h["matching_snippets"] = snips
    return hits


def snippets(query: str = "", limit: int = 4, names: list[str] | None = None) -> list[dict]:
    """Technique snippets ranked for the query: [{"exemplar", "title", "code"}]. The block of build() that does one
    thing well (hollow a lofted shell, cut a two-view opening, a snap fit with a named clearance)."""
    rows = []
    for p in _files():
        if names and p.stem not in names:
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
    return {**_meta(p), "source": src, "snippet_code": _snippets_of(src, name),
            "how_to_use": "Learn the construction; write your own design for the person's brief. Exemplars are "
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
