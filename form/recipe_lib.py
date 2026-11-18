"""The recipe library: built-in recipes, recipes you installed ("Mine"), and community recipes from the website.

A recipe is code. Nothing here runs it: installing a recipe writes its file to ``<data>/.recipes/`` and reads its
title and summary without executing anything (Python is parsed with ``ast``; OpenSCAD's header comment is read). The
code runs only when you create a design from it, which builds it in the kernel worker like any design written as code.

Community recipes come from a public index on the project website:

    https://kaizensx.github.io/form-studio/recipes/index.json
    {"version": 1, "generated": ISO, "recipes": [{"id", "title", "summary", "author", "tags": [], "kind": "python"|"scad",
                                                  "builtin": bool, "url": raw URL or null, "sha256": hex or null,
                                                  "preview": URL or null}]}

Installing one is two steps, never one: ``community_preview`` downloads the file, checks its SHA-256 against the
index and returns the source for a person to read; ``install_community`` installs exactly that file (same hash) after
they press Install. An unreachable or empty index is not an error: the Community section is simply empty.

    form recipes [list] [--q words] [--section builtin|mine|community] [--tag t] [--sort name|recent]
    form recipes inspect FILE            what installing FILE would install: source hash, title, problems
    form recipes install FILE --sha256 HEX
    form recipes community [--refresh]
    form recipes uninstall ID
    form recipes export|import|submit|derive ...   sharing; see form/recipe_share.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DIR = ".recipes"
PENDING = ".pending"
INDEX_URL = "https://kaizensx.github.io/form-studio/recipes/index.json"
REPO = "https://github.com/kaizensx/form-studio"
DISCUSSIONS = REPO + "/discussions"
CACHE = ".form-community.json"
TTL = 3600
MAX_SOURCE = 200_000
MAX_INDEX = 2_000_000
TIMEOUT = 8.0
KINDS = {"python": ".py", "scad": ".scad"}
SECTIONS = ("builtin", "mine", "community")

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


# ---- community ---------------------------------------------------------------------------------------------------

def _local(url: str, limit: int) -> bytes | None:
    """Development and the interface tests: FORM_RECIPES_INDEX names a local index.json; "file:" urls in it are
    files next to it. Never used unless that variable is set."""
    idx = os.environ.get("FORM_RECIPES_INDEX", "").strip()
    if not idx:
        return None
    base = Path(idx).resolve().parent
    if url == INDEX_URL:
        f = Path(idx)
    elif str(url).startswith("file:"):
        f = (base / str(url)[5:].lstrip("/")).resolve()
        if not f.is_relative_to(base):
            raise LibraryError("A local recipe file must be next to the local index.")
    else:
        return None
    data = f.read_bytes()
    if len(data) > limit:
        raise LibraryError("The file is larger than a recipe can be, so it was not read.")
    return data


def _download(url: str, limit: int, opener=None) -> bytes:
    if opener is None:
        data = _local(url, limit)
        if data is not None:
            return data
    if not str(url).startswith("https://"):
        raise LibraryError("Community files are only read over https.")
    if opener is not None:
        data = opener(url, TIMEOUT)
    else:
        from . import __version__, net
        req = urllib.request.Request(url, headers={"User-Agent": f"FormStudio/{__version__} recipes"})
        with net.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(limit + 1)
    if len(data) > limit:
        raise LibraryError("The file is larger than a recipe can be, so it was not read.")
    return data


def _norm(e) -> dict | None:
    if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e.get("title"):
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", e["id"]):
        return None
    kind = e.get("kind") if e.get("kind") in KINDS else "python"
    sha = str(e.get("sha256") or "").lower()
    local = os.environ.get("FORM_RECIPES_INDEX") and isinstance(e.get("url"), str) and e["url"].startswith("file:")
    url = e.get("url") if isinstance(e.get("url"), str) and (e["url"].startswith("https://") or local) else None
    prev = e.get("preview") if isinstance(e.get("preview"), str) and e["preview"].startswith("https://") else None
    disc = e.get("discussion") if isinstance(e.get("discussion"), str) and e["discussion"].startswith(DISCUSSIONS) else None
    added = e.get("added") if isinstance(e.get("added"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["added"]) else None
    n = e.get("params_count") if isinstance(e.get("params_count"), int) and 0 <= e["params_count"] < 1000 else None
    title = str(e["title"])[:80]
    return {"id": e["id"], "title": title, "summary": str(e.get("summary") or "")[:300],
            "author": str(e.get("author") or "")[:80], "tags": [str(t)[:24] for t in (e.get("tags") or []) if isinstance(t, str)][:8],
            "kind": kind, "builtin": bool(e.get("builtin")), "url": url,
            "sha256": sha if re.fullmatch(r"[0-9a-f]{64}", sha) else None, "preview": prev, "params": n, "added": added,
            # ratings need a server; the conversation about a recipe lives in the repository's Discussions
            "discussion": disc or DISCUSSIONS + "?discussions_q=" + urllib.parse.quote(f'"{title}"'),
            "page": None if e.get("builtin") else f"{REPO}/tree/main/community/recipes/{e['id']}"}


def parse_index(data: bytes) -> list[dict]:
    try:
        idx = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LibraryError("The community index is not valid JSON.") from None
    if not isinstance(idx, dict) or idx.get("version") != 1 or not isinstance(idx.get("recipes"), list):
        raise LibraryError("The community index has a format this version does not read.")
    out = [r for r in (_norm(e) for e in idx["recipes"]) if r]
    return out


def community(root, force: bool = False, opener=None, url: str = INDEX_URL) -> dict:
    """The community index, cached for an hour. Never raises: offline means an empty list and a reason."""
    cache = Path(root) / CACHE
    cached = None
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    now = time.time()
    if isinstance(cached, dict) and not force and now - float(cached.get("fetched", 0)) < TTL:
        return {"recipes": cached.get("recipes") or [], "fetched": cached.get("fetched"), "url": url, "error": None}
    try:
        recipes = parse_index(_download(url, MAX_INDEX, opener))
    except Exception as e:
        reason = str(e) if isinstance(e, LibraryError) else "The recipe index could not be reached."
        if isinstance(cached, dict):
            return {"recipes": cached.get("recipes") or [], "fetched": cached.get("fetched"), "url": url, "error": reason, "stale": True}
        return {"recipes": [], "fetched": None, "url": url, "error": reason}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fetched": now, "recipes": recipes}), encoding="utf-8")
    except OSError:
        pass
    return {"recipes": recipes, "fetched": now, "url": url, "error": None}


def _community_entry(root, cid: str, opener=None) -> dict:
    for e in community(root, opener=opener)["recipes"]:
        if e["id"] == cid:
            return e
    raise LibraryError("That recipe is not in the community index.", "Refresh the Community list and try again.")


def community_preview(root, cid: str, opener=None) -> dict:
    """Download a community recipe and verify it, for a person to read. Nothing is installed or run."""
    e = _community_entry(root, cid, opener)
    if e["builtin"]:
        raise LibraryError("This recipe is already part of Form Studio.")
    if not e["url"] or not e["sha256"]:
        raise LibraryError("The index does not give this recipe a file and a checksum, so it cannot be installed safely.")
    data = _download(e["url"], MAX_SOURCE, opener)
    got = hashlib.sha256(data).hexdigest()
    if got != e["sha256"]:
        raise LibraryError("The downloaded file does not match the checksum in the index, so it was not installed.",
                           f"Expected {e['sha256']}, got {got}.")
    info = inspect(data, "recipe" + KINDS[e["kind"]])
    pend = folder(root) / PENDING
    pend.mkdir(parents=True, exist_ok=True)
    (pend / f"{got}{KINDS[e['kind']]}").write_bytes(data)
    return {**info, "entry": e, "verified": True}


def install_community(root, cid: str, sha: str, opener=None) -> dict:
    """Install the file community_preview verified and showed, identified by its hash."""
    e = _community_entry(root, cid, opener)
    sha = str(sha or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or sha != e["sha256"]:
        raise LibraryError("The checksum does not match the community index; nothing was installed.")
    f = folder(root) / PENDING / f"{sha}{KINDS[e['kind']]}"
    if not f.is_file():
        raise LibraryError("Review the recipe's source first.", "Open it from the Community list; Install appears under its source.")
    data = f.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise LibraryError("The reviewed file changed on disk; nothing was installed.")
    out = install(root, data.decode("utf-8"), e["kind"], sha,
                  {"title": e["title"], "summary": e["summary"], "author": e["author"], "tags": e["tags"], "origin": "community",
                   "url": e["url"], "community_id": e["id"], "preview": e["preview"]})
    try:
        f.unlink()
    except OSError:
        pass
    return out


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


def cached_community(root) -> dict:
    """What the last fetch of the index found, without going to the network."""
    try:
        c = json.loads((Path(root) / CACHE).read_text(encoding="utf-8"))
        return {"recipes": c.get("recipes") or [], "fetched": c.get("fetched"), "error": None}
    except (OSError, ValueError, AttributeError):
        return {"recipes": [], "fetched": None, "error": None}


def everything(root, recipes: dict, opener=None, refresh: bool = False, online: bool = True) -> dict:
    """online=False lists the community recipes from the cache only: browsing built-in and your own recipes never
    waits for the network."""
    com = community(root, force=refresh, opener=opener) if online or refresh else cached_community(root)
    mine_ = mine(root)
    have = {m.get("community_id") for m in mine_ if m.get("community_id")}
    cs = []
    for e in com["recipes"]:
        cs.append({**e, "section": "community", "installed": e["builtin"] or e["id"] in have,
                   "category": "Included" if e["builtin"] else (e["tags"][0].capitalize() if e["tags"] else "Community")})
    for m in mine_:
        m.setdefault("category", m["tags"][0].capitalize() if m.get("tags") else "Mine")
    return {"items": builtins(recipes) + mine_ + cs, "community_error": com["error"], "community_fetched": com["fetched"]}


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
    elif sort == "added":                    # newest in the gallery first (the date its folder was added), then installed
        out.sort(key=lambda i: (i.get("added") or "", i.get("installed_at") or 0), reverse=True)
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
    ap = argparse.ArgumentParser(prog="form recipes", description="The recipe library: built-in, installed, community.")
    if argv and argv[0] in ("export", "import", "submit", "derive"):          # sharing: form/recipe_share.py
        from .recipe_share import main as share_main
        return share_main(argv[0], argv[1:])
    ap.add_argument("verb", nargs="?", default="list", choices=["list", "inspect", "install", "uninstall", "community", "source"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--q", default="")
    ap.add_argument("--section", default="", choices=["", *SECTIONS])
    ap.add_argument("--tag", default="")
    ap.add_argument("--sort", default="name", choices=["name", "recent", "added", "author", "params"])
    ap.add_argument("--sha256", default="", help="the hash `inspect` printed; install refuses anything else")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    root = config.load()["data"]["dir"]
    try:
        if a.verb == "list":
            from .recipes import listed
            lib = everything(root, listed(), refresh=a.refresh)
            out = {"recipes": search(lib["items"], a.q, a.section, a.tag, a.sort), "community_error": lib["community_error"]}
        elif a.verb == "community":
            out = community(root, force=a.refresh)
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
