"""The recipe library: built-in recipes and recipes installed on this computer ("Mine").

Recipes are building blocks agents may start a design from. They are not offered to people as a library: there is no
public gallery or community index any more, and nothing here goes to the network.

A recipe is code. Nothing here runs it: installing a recipe writes its file to ``<data>/.recipes/`` and reads its
title and summary without executing anything (Python is parsed with ``ast``; OpenSCAD's header comment is read). The
code runs only when a design is created from it, which builds it in the kernel worker like any design written as code.

    form recipes [list] [--q words] [--section builtin|mine] [--tag t] [--sort name|recent]
    form recipes inspect FILE            what installing FILE would install: source hash, title, problems
    form recipes install FILE --sha256 HEX
    form recipes uninstall ID
    form recipes export|import|derive ...   packages and a design as a recipe; see form/recipe_share.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path

DIR = ".recipes"
PENDING = ".pending"
MAX_SOURCE = 200_000
KINDS = {"python": ".py", "scad": ".scad"}
SECTIONS = ("builtin", "mine")

# Built-in recipes carry their category and tags (Recipe.category, Recipe.tags); this is the fallback for one that does not.
BUILTIN_TAGS: dict = {}


class LibraryError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def folder(root) -> Path:
    return Path(root) / DIR


def kind_for(name: str) -> str:
    ext = Path(str(name or "")).suffix.lower()
    for k, e in KINDS.items():
        if ext == e:
            return k
    raise LibraryError("A recipe is a .py (build123d) or .scad (OpenSCAD) file.", "Choose a file that ends in .py or .scad.")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:48] or "recipe"


# ---- reading a recipe without running it ---------------------------------------------------------------------

def _const_str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, (ast.Tuple, ast.JoinedStr)):
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):     # "a" "b" split over lines is one Constant already
        a, b = _const_str(node.left), _const_str(node.right)
        return a + b if a is not None and b is not None else None
    return None


def _is_recipe_base(b) -> bool:
    return (isinstance(b, ast.Name) and b.id == "Recipe") or (isinstance(b, ast.Attribute) and b.attr == "Recipe")


def read_python(source: str) -> dict:
    """Title, summary, parameter count and problems of a Python recipe, from its syntax tree only."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"title": "", "summary": "", "params": 0, "problems": [f"Python syntax error on line {e.lineno}: {e.msg}"]}
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and any(_is_recipe_base(b) for b in n.bases)]
    if len(classes) != 1:
        return {"title": "", "summary": "", "params": 0,
                "problems": [f"A recipe file defines exactly one subclass of Recipe; this one has {len(classes)}."]}
    c = classes[0]
    out = {"title": "", "summary": "", "params": 0, "problems": [], "class": c.name}
    for st in c.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            name = st.targets[0].id
            if name in ("title", "summary"):
                v = _const_str(st.value)
                if v is not None:
                    out[name] = v.strip()
            elif name == "params" and isinstance(st.value, (ast.List, ast.Tuple)):
                out["params"] = sum(1 for e in st.value.elts if isinstance(e, ast.Call))
    if not out["title"]:
        out["title"] = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", c.name)
    return out


def read_scad(source: str) -> dict:
    from .cad_bridges import parse_scad_params, scad_title
    title, summary = scad_title(source)
    try:
        n = len(parse_scad_params(source))
    except Exception:
        n = 0
    return {"title": title, "summary": summary, "params": n, "problems": [] if source.strip() else ["The file is empty."]}


def inspect(data: bytes, filename: str) -> dict:
    """What installing this file would install. Nothing is written and nothing is run."""
    kind = kind_for(filename)
    if len(data) > MAX_SOURCE:
        raise LibraryError(f"A recipe file is at most {MAX_SOURCE // 1000} kB.", "This file is larger; it is probably not a recipe.")
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        raise LibraryError("The file is not UTF-8 text.", "A recipe is a plain .py or .scad text file.") from None
    meta = read_python(source) if kind == "python" else read_scad(source)
    return {"kind": kind, "source": source, "sha256": sha256(source), "size": len(data), "lines": source.count("\n") + 1,
            "filename": Path(filename).name, "title": meta["title"] or Path(filename).stem, "summary": meta["summary"],
            "params": meta["params"], "problems": meta["problems"]}


# ---- mine: installed recipes -----------------------------------------------------------------------------------

def mine(root) -> list[dict]:
    d = folder(root)
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = d / m.get("file", "")
        if not isinstance(m, dict) or not src.is_file():
            continue
        out.append({**m, "section": "mine", "installed": True})
    return out


def _entry(root, rid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", str(rid or "")):
        raise LibraryError("Unknown recipe.")
    for m in mine(root):
        if m["id"] == rid:
            return m
    raise LibraryError("Unknown recipe.", "List installed recipes with `form recipes --section mine`.")


def source(root, rid: str) -> dict:
    m = _entry(root, rid)
    text = (folder(root) / m["file"]).read_text(encoding="utf-8")
    return {**m, "source": text, "sha256_now": sha256(text)}


def install(root, source_text: str, kind: str, expected_sha256: str, meta: dict | None = None) -> dict:
    """Write a recipe the person has read into <data>/.recipes. The hash must match the one they were shown."""
    if kind not in KINDS:
        raise LibraryError("Unknown recipe kind.", "Use python or scad.")
    got = sha256(source_text)
    if not expected_sha256 or got != str(expected_sha256).lower():
        raise LibraryError("The file changed since it was shown, so it was not installed.",
                           f"Its SHA-256 is now {got}. Review it again before installing.")
    if len(source_text.encode("utf-8")) > MAX_SOURCE:
        raise LibraryError(f"A recipe file is at most {MAX_SOURCE // 1000} kB.")
    info = read_python(source_text) if kind == "python" else read_scad(source_text)
    if info["problems"]:
        raise LibraryError("This file is not a recipe Form Studio can use: " + info["problems"][0],
                           "A Python recipe defines one class that subclasses Recipe (see docs/RECIPES.md).")
    meta = dict(meta or {})
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    for m in mine(root):                                     # the same file again: keep the one already there
        if m.get("sha256") == got:
            return m
    title = str(meta.get("title") or info["title"] or "Recipe")[:80]
    base = _slug(meta.get("id") or title)
    rid, i = base, 2
    while (d / f"{rid}.json").exists():
        rid, i = f"{base}-{i}", i + 1
    f = d / f"{rid}{KINDS[kind]}"
    f.write_text(source_text, encoding="utf-8")
    entry = {"id": rid, "title": title, "summary": str(meta.get("summary") or info["summary"] or "")[:300],
             "author": str(meta.get("author") or "")[:80], "tags": [str(t)[:24] for t in (meta.get("tags") or [])][:8],
             "kind": kind, "file": f.name, "sha256": got, "params": info["params"],
             "origin": meta.get("origin") or "file", "url": meta.get("url"), "community_id": meta.get("community_id"),
             "preview": meta.get("preview"), "installed_at": time.time()}
    (d / f"{rid}.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
    return {**entry, "section": "mine", "installed": True}


def uninstall(root, rid: str) -> dict:
    m = _entry(root, rid)
    d = folder(root)
    for f in (d / m["file"], d / f"{rid}.json"):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
    return {"removed": rid, "title": m["title"]}


# ---- the whole library -----------------------------------------------------------------------------------------

def builtins(recipes: dict) -> list[dict]:
    out = []
    for rid, r in recipes.items():
        if getattr(r, "legacy", False):
            continue
        cat, tags = (r.category, list(r.tags)) if getattr(r, "category", "") else BUILTIN_TAGS.get(rid, ("Other", []))
        out.append({"id": rid, "title": r.title, "summary": r.summary, "author": "Form Studio", "tags": tags, "category": cat,
                    "kind": "python", "section": "builtin", "installed": True, "params": len(r.params), "preview": None})
    return out


def everything(root, recipes: dict) -> dict:
    """Built-in recipes and the ones installed on this computer. Nothing here goes to the network."""
    mine_ = mine(root)
    for m in mine_:
        m.setdefault("category", m["tags"][0].capitalize() if m.get("tags") else "Mine")
    return {"items": builtins(recipes) + mine_}


def search(items: list[dict], q: str = "", section: str = "", tag: str = "", sort: str = "name") -> list[dict]:
    """Every word of q in the title, summary, author or tags; one section; one tag; sorted by name or newest."""
    words = [w for w in re.split(r"\s+", (q or "").lower()) if w]
    out = []
    for it in items:
        if section and it.get("section") != section:
            continue
        if tag and tag.lower() not in [t.lower() for t in it.get("tags") or []] and tag.lower() != str(it.get("category", "")).lower():
            continue
        hay = " ".join([it.get("title", ""), it.get("summary", ""), it.get("author", ""), it.get("category", "")] + list(it.get("tags") or [])).lower()
        if all(w in hay for w in words):
            out.append(it)
    order = {s: i for i, s in enumerate(SECTIONS)}
    if sort == "recent":
        out.sort(key=lambda i: (-(i.get("installed_at") or 0), i.get("title", "").lower()))
    elif sort == "author":
        out.sort(key=lambda i: (str(i.get("author") or "~").lower(), i.get("title", "").lower()))
    elif sort == "params":
        out.sort(key=lambda i: (-(i.get("params") or 0), i.get("title", "").lower()))
    else:
        out.sort(key=lambda i: (order.get(i.get("section"), 9), i.get("title", "").lower()))
    return out


def tags(items: list[dict]) -> list[dict]:
    n = {}
    for it in items:
        for t in {str(x).lower() for x in [it.get("category", "")] + list(it.get("tags") or []) if x}:
            n[t] = n.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]


def create_from(st, rid: str, name: str = "", brief: str = "", purpose: str | None = None, process: str | None = None) -> dict:
    """A new project from an installed recipe. This runs the recipe's code in the kernel worker."""
    s = source(st.root, rid)
    if s["sha256_now"] != s["sha256"]:
        raise LibraryError("The installed file was changed after it was installed.",
                           "Uninstall it and install it again so you can review what it now contains.")
    return st.create_design(name.strip() or s["title"], s["source"], brief, language="openscad" if s["kind"] == "scad" else "python",
                            purpose=purpose, process=process)


# ---- command line ------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    import sys

    from . import config
    ap = argparse.ArgumentParser(prog="form recipes", description="The recipe library: built-in and installed.")
    if argv and argv[0] in ("export", "import", "derive"):          # sharing: form/recipe_share.py
        from .recipe_share import main as share_main
        return share_main(argv[0], argv[1:])
    ap.add_argument("verb", nargs="?", default="list", choices=["list", "inspect", "install", "uninstall", "source"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--q", default="")
    ap.add_argument("--section", default="", choices=["", *SECTIONS])
    ap.add_argument("--tag", default="")
    ap.add_argument("--sort", default="name", choices=["name", "recent", "author", "params"])
    ap.add_argument("--sha256", default="", help="the hash `inspect` printed; install refuses anything else")
    a = ap.parse_args(argv)
    root = config.load()["data"]["dir"]
    try:
        if a.verb == "list":
            from .recipes import listed
            lib = everything(root, listed())
            out = {"recipes": search(lib["items"], a.q, a.section, a.tag, a.sort)}
        elif a.verb == "inspect":
            p = Path(a.arg or "").expanduser()
            out = {k: v for k, v in inspect(p.read_bytes(), p.name).items() if k != "source"}
            out["install_with"] = f'form recipes install "{p}" --sha256 {out["sha256"]}'
        elif a.verb == "install":
            p = Path(a.arg or "").expanduser()
            info = inspect(p.read_bytes(), p.name)
            out = install(root, info["source"], info["kind"], a.sha256, {"title": info["title"], "summary": info["summary"]})
        elif a.verb == "uninstall":
            out = uninstall(root, a.arg or "")
        else:
            out = source(root, a.arg or "")
    except (LibraryError, OSError) as e:
        print(json.dumps({"error": e.public() if isinstance(e, LibraryError) else {"message": str(e)}}, ensure_ascii=False))
        return 2
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0
