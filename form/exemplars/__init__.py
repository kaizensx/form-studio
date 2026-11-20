"""Exemplar designs: complete, high-quality Form Studio designs for the agent to learn construction from.

Each file here is a full design source (one Recipe subclass, build123d algebra API, form.craft helpers) that builds in
the kernel, plus META: {"title", "tags", "lessons"}. They are served to the agent by the MCP tool design_examples and
are never projects: nothing here appears in the app's library or project list.

    from form import exemplars
    exemplars.catalogue()            # [{name, title, tags, lessons, summary}]
    exemplars.search("helmet texture")
    exemplars.get("helmet")          # + "source"
    exemplars.load("helmet")         # the Design instance (needs build123d)

Reading the catalogue parses the files (ast) and imports nothing, so the MCP server stays importable without OCCT.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _files() -> list[Path]:
    return sorted(p for p in HERE.glob("*.py") if not p.name.startswith("_"))


def _meta(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
    return {"name": path.stem, "title": meta.get("title") or title, "summary": summary, "tags": list(meta.get("tags", [])),
            "lessons": list(meta.get("lessons", [])), "techniques": list(meta.get("techniques", []))}


def catalogue() -> list[dict]:
    return [_meta(p) for p in _files()]


def search(query: str, limit: int = 5) -> list[dict]:
    words = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    scored = []
    for e in catalogue():
        hay = " ".join([e["name"], e["title"], e["summary"], " ".join(e["tags"]), " ".join(e["techniques"])]).lower()
        toks = set(re.findall(r"[a-z0-9]+", hay))
        score = sum(3 if w in e["tags"] or w in e["name"] else 1 for w in words if w in toks)
        score += sum(0.5 for w in words for t in toks if len(w) > 3 and w != t and (t.startswith(w) or w.startswith(t)))
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def get(name: str) -> dict:
    p = HERE / f"{name}.py"
    if not re.fullmatch(r"[a-z0-9_]+", name or "") or not p.is_file():
        raise KeyError(name)
    return {**_meta(p), "source": p.read_text(encoding="utf-8"),
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
