"""Sharing recipes: one-file packages, community submissions, and a design turned into a recipe.

A recipe you installed ("Mine") can leave this computer three ways, and each one is started by the person:

    package      <id>.formrecipe, a zip with recipe.py (or recipe.scad), meta.json and preview.png. meta.json carries
                 the code's SHA-256; the preview is drawn from the real build at the recipe's defaults.
    submission   the folder the community gallery reads, community/recipes/<id>/ (recipe file, meta.json in the
                 gallery's schema, preview.png), saved where the person chooses, plus a link that opens GitHub's
                 recipe issue form with the fields filled in. Nothing is sent: the browser shows the form and the
                 person presses Submit there, or not.
    design       a project's current code, rewritten so its parameters default to the design's values, with ranges
                 the person may narrow. It is built once to check it reproduces the design before it is offered.

Importing a package is the same two steps as a community recipe: ``inspect_package`` reads the zip without running
anything, checks the code against the checksum in meta.json and keeps the file aside; ``install_package`` installs
exactly that file, by its hash, after the person pressed Install. The code runs only when a design is created.

    form recipes export ID [--out FILE] [--author NAME] [--tags a,b]
    form recipes import FILE.formrecipe [--sha256 HEX]
    form recipes submit ID [--out DIR] [--author NAME] [--tags a,b]     prints the pre-filled issue link; opens nothing
    form recipes derive PROJECT [--title T] [--summary S] [--range key=min:max ...] [--install --sha256 HEX]
"""
from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import io
import json
import re
import time
import urllib.parse
import zipfile
from pathlib import Path

from . import recipe_lib as lib

EXT = ".formrecipe"
FORMAT = "formrecipe"
VERSION = 1
GITHUB = "https://github.com/kaizensx/form-studio"
ISSUE_TEMPLATE = "3-recipe.yml"
ISSUE_KIND = "A recipe I am submitting for the community gallery"
URL_LIMIT = 7800                      # GitHub answers 414 a little above 8 kB
PKG_MAX = 4_000_000
META_MAX = 64_000
PREVIEW_MAX = 3_000_000
PREVIEW_SIZE = (960, 560)
PNG = b"\x89PNG\r\n\x1a\n"
COMMUNITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")          # site/tools/build_recipe_index.py
AUTHOR = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")       # a GitHub username
SHARE = ".share"
PROFILE = ".share-profile.json"
PARAM_KEYS = ("key", "label", "default", "min", "max", "step", "unit", "group")


class ShareError(lib.LibraryError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(round(v, 6))


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t).strip().lower())[:24]
        if t and t not in out:
            out.append(t)
    return out[:8]


def _cid(title: str) -> str:
    """A gallery id: lowercase letters, digits and hyphens."""
    s = lib._slug(title)
    return s if COMMUNITY_ID.match(s) else (s + "-recipe")[:48]


# ---- the person's sharing profile: their GitHub username, remembered -----------------------------------------

def profile(root) -> dict:
    try:
        p = json.loads((Path(root) / lib.DIR / PROFILE).read_text(encoding="utf-8"))
        return p if isinstance(p, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_profile(root, **kw):
    p = {**profile(root), **{k: v for k, v in kw.items() if v}}
    d = Path(root) / lib.DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / PROFILE).write_text(json.dumps(p), encoding="utf-8")


# ---- an installed recipe: its entry, its meta, its preview -----------------------------------------------------

def _entry_file(root, rid: str) -> Path:
    return lib.folder(root) / f"{rid}.json"


def _update_entry(root, rid: str, **fields) -> dict:
    f = _entry_file(root, rid)
    e = json.loads(f.read_text(encoding="utf-8"))
    e.update(fields)
    f.write_text(json.dumps(e, indent=1, ensure_ascii=False), encoding="utf-8")
    return e


def edit_meta(root, rid: str, title=None, summary=None, author=None, tags=None) -> dict:
    """Change what an installed recipe says about itself before it is shared (not its code)."""
    lib._entry(root, rid)
    fields = {}
    if title is not None:
        t = str(title).strip()[:80]
        if not t:
            raise ShareError("A recipe needs a title.")
        fields["title"] = t
    if summary is not None:
        fields["summary"] = str(summary).strip()[:300]
    if author is not None:
        a = str(author).strip().lstrip("@")
        if a and not AUTHOR.match(a):
            raise ShareError("That is not a GitHub username.", "Letters, digits and single hyphens, up to 39 characters.")
        fields["author"] = a
        _save_profile(root, author=a)
    if tags is not None:
        fields["tags"] = _clean_tags(tags)
    e = _update_entry(root, rid, **fields)
    _drop_package(root, rid)
    return {**e, "section": "mine", "installed": True}


def preview_file(root, rid: str) -> Path:
    return lib.folder(root) / f"{rid}.png"


def preview_api(rid: str) -> str:
    return f"/api/recipes/mine/{rid}/preview.png"


def _load(st, entry: dict):
    """The installed code as a design source: (recipe id, Recipe). Loading reads its parameters."""
    s = lib.source(st.root, entry["id"])
    if s["sha256_now"] != s["sha256"]:
        raise ShareError("The installed file was changed after it was installed, so it is not shared.",
                         "Uninstall it and install it again so you can review what it now contains.")
    rid = st._load_design(s["source"], "openscad" if entry["kind"] == "scad" else "python")
    return rid, st.recipes[rid], s["source"]


def _params(recipe) -> list[dict]:
    return [{k: getattr(p, k) for k in PARAM_KEYS} for p in recipe.params]


def render_png(st, rid: str, values: dict) -> tuple[bytes, dict]:
    """A picture of the real build, the way the share card draws parts. Returns (PNG bytes, the kernel's view)."""
    from . import share
    from .studio import H
    v = st._k("view", key="rv-" + H(rid, values), recipe_id=rid, values=values, tol=0.08, timeout=180)
    lo, hi = share._bbox(v)
    im = share.Scene(lo, hi, PREVIEW_SIZE, pad=0.16).render(v)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue(), v


def ensure_preview(st, rid: str) -> dict:
    """Draw (once per version of the code) the installed recipe at its defaults. This builds it in the kernel."""
    e = lib._entry(st.root, rid)
    f = preview_file(st.root, rid)
    if e.get("preview_of") == e["sha256"] and f.is_file():
        return e
    srid, recipe, _ = _load(st, e)
    png, _ = render_png(st, srid, recipe.defaults())
    f.write_bytes(png)
    return _update_entry(st.root, rid, preview=preview_api(rid), preview_of=e["sha256"], params=len(recipe.params))


# ---- packages ---------------------------------------------------------------------------------------------------

def package_meta(e: dict, params: list[dict], code_sha: str, preview: bytes | None) -> dict:
    from . import __version__
    return {"format": FORMAT, "version": VERSION, "id": e["id"], "title": e["title"], "summary": e.get("summary") or "",
            "author": e.get("author") or "", "tags": e.get("tags") or [], "kind": e["kind"],
            "params": params, "params_count": len(params), "sha256": code_sha,
            "preview_sha256": _sha(preview) if preview else None, "made_with": f"Form Studio {__version__}",
            "created": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()}


def _code_name(kind: str) -> str:
    return "recipe.py" if kind == "python" else "recipe.scad"


def build_package(meta: dict, code: str, preview: bytes | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        z.writestr(_code_name(meta["kind"]), code.encode("utf-8"))
        if preview:
            z.writestr("preview.png", preview, compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


def _share_dir(root) -> Path:
    return lib.folder(root) / SHARE


def _drop_package(root, rid: str):
    for f in _share_dir(root).glob(f"{rid}.*"):
        f.unlink(missing_ok=True)


def prepare(st, rid: str, edits: dict | None = None) -> dict:
    """Everything the Share sheet shows: the package (built and kept for Save), the submission and its link."""
    if edits:
        edit_meta(st.root, rid, **{k: edits.get(k) for k in ("title", "summary", "author", "tags") if k in edits})
    e = ensure_preview(st, rid)
    if not e.get("author") and profile(st.root).get("author"):
        e = _update_entry(st.root, rid, author=profile(st.root)["author"])
    srid, recipe, code = _load(st, e)
    preview = preview_file(st.root, rid).read_bytes()
    meta = package_meta(e, _params(recipe), lib.sha256(code), preview)
    data = build_package(meta, code, preview)
    d = _share_dir(st.root)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rid}{EXT}").write_bytes(data)
    return {"id": rid, "meta": meta, "preview": preview_api(rid), "package": {"name": f"{rid}{EXT}", "bytes": len(data),
            "api": f"/recipes/share/{rid}{EXT}"}, "submission": submission(st.root, e, meta, code)}


def package_bytes(st, rid: str) -> bytes:
    f = _share_dir(st.root) / f"{rid}{EXT}"
    if not f.is_file():
        prepare(st, rid)
    return f.read_bytes()


def export(st, rid: str, out=None, author=None, tags=None) -> dict:
    edits = {k: v for k, v in (("author", author), ("tags", tags)) if v is not None}
    r = prepare(st, rid, edits or None)
    dest = Path(out).expanduser() if out else Path.cwd() / r["package"]["name"]
    if dest.is_dir():
        dest = dest / r["package"]["name"]
    dest.write_bytes(package_bytes(st, rid))
    return {"file": str(dest), "bytes": dest.stat().st_size, "sha256": r["meta"]["sha256"], "meta": r["meta"]}


def _read(z: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ShareError(f"{info.filename} in the package is larger than it can be, so the package was not read.")
    with z.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ShareError(f"{info.filename} in the package is larger than it can be, so the package was not read.")
    return data


def read_package(data: bytes) -> dict:
    """Read a .formrecipe without running anything: {meta, kind, code (bytes), preview (bytes or None)}."""
    if len(data) > PKG_MAX:
        raise ShareError(f"A recipe package is at most {PKG_MAX // 1_000_000} MB.", "This file is larger; it is probably not one.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        raise ShareError("This is not a recipe package.", "A .formrecipe file is exported from Form Studio's Share sheet.") from None
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        raise ShareError("The package lists a file twice, so it was not read.")
    extra = [n for n in names if n not in ("meta.json", "recipe.py", "recipe.scad", "preview.png")]
    if extra:
        raise ShareError("The package contains files a recipe package does not have, so it was not read.",
                         "Unexpected: " + ", ".join(sorted(extra)[:4]))
    by = {i.filename: i for i in infos}
    if "meta.json" not in by:
        raise ShareError("The package has no meta.json.")
    try:
        meta = json.loads(_read(z, by["meta.json"], META_MAX).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ShareError("The package's meta.json is not valid JSON.") from None
    if not isinstance(meta, dict) or meta.get("format") != FORMAT:
        raise ShareError("This is not a recipe package.")
    if meta.get("version") != VERSION:
        raise ShareError("The package was made by a newer Form Studio.", "Update Form Studio, then import it again.")
    kind = meta.get("kind") if meta.get("kind") in lib.KINDS else None
    codes = [n for n in ("recipe.py", "recipe.scad") if n in by]
    if not kind or codes != [_code_name(kind)]:
        raise ShareError("The package must hold exactly one recipe file that matches its kind.")
    code = _read(z, by[codes[0]], lib.MAX_SOURCE)
    preview = _read(z, by["preview.png"], PREVIEW_MAX) if "preview.png" in by else None
    if preview is not None and not preview.startswith(PNG):
        raise ShareError("The package's preview is not a PNG image, so the package was not read.")
    return {"meta": meta, "kind": kind, "code": code, "preview": preview}


def _clean_meta(m: dict) -> dict:
    params = []
    for p in m.get("params") or []:
        if isinstance(p, dict) and isinstance(p.get("key"), str):
            params.append({k: p.get(k) for k in PARAM_KEYS if isinstance(p.get(k), (str, int, float))})
    return {"id": lib._slug(m.get("id") or m.get("title") or "recipe"), "title": str(m.get("title") or "")[:80],
            "summary": str(m.get("summary") or "")[:300], "author": str(m.get("author") or "")[:80],
            "tags": _clean_tags(m.get("tags")), "params": params[:200], "made_with": str(m.get("made_with") or "")[:60],
            "created": str(m.get("created") or "")[:40]}


def _pending(root) -> Path:
    d = lib.folder(root) / lib.PENDING
    d.mkdir(parents=True, exist_ok=True)
    return d


def inspect_package(root, data: bytes, filename: str = "recipe" + EXT) -> dict:
    """What installing this package would install. Nothing is installed or run; the file is kept aside by its hash."""
    pkg = read_package(data)
    info = lib.inspect(pkg["code"], "recipe" + lib.KINDS[pkg["kind"]])
    meta = _clean_meta(pkg["meta"])
    declared = str(pkg["meta"].get("sha256") or "").lower()
    problems = list(info["problems"])
    if declared != info["sha256"]:
        problems.insert(0, "The recipe file does not match the checksum in the package's meta.json; it may have been changed.")
    pv_sha = pkg["meta"].get("preview_sha256")
    preview_ok = pkg["preview"] is not None and (not pv_sha or _sha(pkg["preview"]) == pv_sha)
    (_pending(root) / f"{info['sha256']}{EXT}").write_bytes(data)
    if pkg["preview"] is not None and preview_ok:
        (_pending(root) / f"{info['sha256']}.png").write_bytes(pkg["preview"])
    return {**info, "filename": Path(filename).name, "title": meta["title"] or info["title"],
            "summary": meta["summary"] or info["summary"], "package": True, "meta": meta, "entry": {**meta, "params": len(meta["params"]) or info["params"]},
            "declared_sha256": declared, "verified": declared == info["sha256"], "problems": problems,
            "preview": f"/api/recipes/pending/{info['sha256']}.png" if pkg["preview"] is not None and preview_ok else None}


def install_package(root, sha: str) -> dict:
    """Install the package inspect_package showed, identified by its code's hash."""
    sha = str(sha or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ShareError("Unknown package.", "Open the .formrecipe file again; Install appears under its code.")
    f = _pending(root) / f"{sha}{EXT}"
    if not f.is_file():
        raise ShareError("Review the package first.", "Open the .formrecipe file again; Install appears under its code.")
    data = f.read_bytes()
    pkg = read_package(data)
    code = pkg["code"].decode("utf-8")
    if lib.sha256(code) != sha or str(pkg["meta"].get("sha256") or "").lower() != sha:
        raise ShareError("The reviewed package changed on disk, or its code does not match its checksum; nothing was installed.")
    meta = _clean_meta(pkg["meta"])
    out = lib.install(root, code, pkg["kind"], sha, {**meta, "origin": "package"})
    fields = {"params": len(meta["params"]) or out.get("params", 0)}
    if pkg["preview"] is not None:
        preview_file(root, out["id"]).write_bytes(pkg["preview"])
        fields.update(preview=preview_api(out["id"]), preview_of=sha)
    out = _update_entry(root, out["id"], **fields)
    for p in (f, _pending(root) / f"{sha}.png"):
        p.unlink(missing_ok=True)
    return {**out, "section": "mine", "installed": True}


def import_file(root, path) -> dict:
    p = Path(path).expanduser()
    return inspect_package(root, p.read_bytes(), p.name)


# ---- community submissions --------------------------------------------------------------------------------------

def community_meta(e: dict, params_count: int) -> dict:
    """meta.json in the gallery's schema (community/recipes/README.md), in its order."""
    return {"id": _cid(e.get("community_id") or e["id"]), "title": e["title"], "summary": e.get("summary") or "",
            "author": e.get("author") or "", "tags": e.get("tags") or [], "kind": e["kind"], "params_count": params_count}


def submission_problems(cm: dict) -> list[str]:
    """What the gallery's index builder would refuse, said before anything leaves the computer."""
    out = []
    if not COMMUNITY_ID.match(cm["id"]):
        out.append("The id must be 2 to 49 lowercase letters, digits and hyphens.")
    if cm["id"] in lib.BUILTIN_TAGS or cm["id"].replace("-", "_") in lib.BUILTIN_TAGS:
        out.append(f"“{cm['id']}” is a built-in recipe's id. Change the title so the id differs.")
    if not cm["author"]:
        out.append("Add your GitHub username as the author.")
    if not cm["summary"]:
        out.append("Add a one-sentence summary: what it is and what makes it fit.")
    if not cm["tags"]:
        out.append("Add a few tags people would search for.")
    if cm["params_count"] < 1:
        out.append("A recipe exposes at least one parameter.")
    return out


def issue_fields(cm: dict, code: str, params: list[dict]) -> dict:
    """The fields of .github/ISSUE_TEMPLATE/3-recipe.yml, by id, as the link fills them in."""
    lines = [f"{p['group']}: {p['label']} ({p['key']}) {_num(p['default'])} {p['unit']}, range {_num(p['min'])} to {_num(p['max'])}".rstrip()
             for p in params]
    fence = "python" if cm["kind"] == "python" else "openscad"
    return {"title": f"[Recipe] {cm['title']}", "object": cm["summary"], "params": "\n".join(lines),
            "recipe_id": cm["id"], "recipe_meta": "```json\n" + json.dumps(cm, indent=1, ensure_ascii=False) + "\n```",
            "recipe_code": f"```{fence}\n{code.rstrip()}\n```"}


def issue_link(fields: dict) -> dict:
    """The new-issue URL. The code is left out (and said so) when the link would be too long for GitHub."""
    def url(f):
        q = {"template": ISSUE_TEMPLATE, **f}
        # "+" for spaces and bare punctuation that is safe in a query keep a typical recipe inside the limit
        return f"{GITHUB}/issues/new?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote_plus, safe="()[],:'*!~")
    u, omitted = url(fields), []
    if len(u) > URL_LIMIT:
        omitted = ["recipe_code"]
        u = url({**fields, "recipe_code": "The code is too long for a link. Drag recipe.py from the saved submission folder here."})
    if len(u) > URL_LIMIT:
        omitted.append("params")
        u = url({k: v for k, v in fields.items() if k not in ("recipe_code", "params")} |
                {"recipe_code": "The code is too long for a link. Drag recipe.py from the saved submission folder here."})
    return {"url": u, "chars": len(u), "omitted": omitted}


def submission(root, e: dict, meta: dict, code: str) -> dict:
    cm = community_meta(e, meta["params_count"])
    fields = issue_fields(cm, code, meta["params"])
    link = issue_link(fields)
    known = {r["id"] for r in lib.cached_community(root)["recipes"]}
    notes = [f"The gallery already has a recipe with the id “{cm['id']}”; this is a new version of it only if it is yours."] if cm["id"] in known else []
    return {"folder": f"community/recipes/{cm['id']}", "files": [_code_name(cm["kind"]), "meta.json", "preview.png"],
            "meta": cm, "meta_json": json.dumps(cm, indent=2, ensure_ascii=False) + "\n", "problems": submission_problems(cm),
            "notes": notes, "issue": {**link, "fields": {k: v for k, v in fields.items() if k not in link["omitted"]}},
            "guide": f"{GITHUB}/tree/main/community/recipes"}


def save_submission(st, rid: str, dest) -> dict:
    """Write community/recipes/<id>/ (recipe file, meta.json, preview.png) inside dest, for a pull request."""
    r = prepare(st, rid)
    sub = r["submission"]
    base = Path(str(dest or "")).expanduser()
    if not str(dest or "").strip() or not base.is_absolute() or not base.is_dir():
        raise ShareError("Choose a folder that exists.")
    out = base / sub["meta"]["id"]
    out.mkdir(exist_ok=True)
    code = lib.source(st.root, rid)["source"]
    written = []
    for name, data in ((_code_name(sub["meta"]["kind"]), code.encode("utf-8")), ("meta.json", sub["meta_json"].encode("utf-8")),
                       ("preview.png", preview_file(st.root, rid).read_bytes())):
        (out / name).write_bytes(data)
        written.append(str(out / name))
    return {"dir": str(out), "files": written, "problems": sub["problems"], "issue": sub["issue"]}


# ---- a design, as a recipe --------------------------------------------------------------------------------------

def _byte_offsets(src: str) -> list[int]:
    offs, n = [0], 0
    for line in src.encode("utf-8").splitlines(keepends=True):
        n += len(line)
        offs.append(n)
    return offs


def _call_arg(call: ast.Call, i: int, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return call.args[i] if len(call.args) > i else None


def _py_value(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def rewrite_python(src: str, values: dict, ranges: dict, title: str, summary: str, header: str) -> str:
    """The same code, with each parameter's default set to the design's value and its range narrowed where asked.
    Edits are made on the syntax tree's positions, so everything else stays byte for byte."""
    tree = ast.parse(src)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and any(lib._is_recipe_base(b) for b in n.bases)]
    if len(classes) != 1:
        raise ShareError("This design's code does not define exactly one Recipe class, so it cannot become a recipe.")
    cls = classes[0]
    offs = _byte_offsets(src)
    pos = lambda n, end=False: offs[(n.end_lineno if end else n.lineno) - 1] + (n.end_col_offset if end else n.col_offset)
    edits = []                                                        # (start, end, text) in UTF-8 bytes
    have = set()
    found = set()
    for stmt in cls.body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)):
            continue
        name = stmt.targets[0].id
        if name in ("title", "summary"):
            have.add(name)
            edits.append((pos(stmt.value), pos(stmt.value, True), json.dumps(title if name == "title" else summary, ensure_ascii=False)))
        elif name == "params":
            if not isinstance(stmt.value, (ast.List, ast.Tuple)):
                raise ShareError("This design builds its parameter list in code, so its defaults cannot be rewritten safely.")
            for call in stmt.value.elts:
                if not isinstance(call, ast.Call):
                    raise ShareError("This design builds some parameters in code, so its defaults cannot be rewritten safely.")
                key = _py_value(_call_arg(call, 0, "key"))
                if key not in values:
                    continue
                found.add(key)
                lo, hi = ranges.get(key, (None, None))
                for i, nm, new in ((2, "default", values[key]), (3, "min", lo), (4, "max", hi)):
                    node = _call_arg(call, i, nm)
                    if node is None or new is None:
                        continue
                    edits.append((pos(node), pos(node, True), _num(new)))
    missing = sorted(set(values) - found)
    if missing:
        raise ShareError("Some of the design's parameters are not written as Param(...) in its params list: " + ", ".join(missing[:6]) + ".")
    insert_at = pos(cls.body[0])
    indent = " " * cls.body[0].col_offset
    add = "".join(f"{nm} = {json.dumps(v, ensure_ascii=False)}\n{indent}" for nm, v in (("title", title), ("summary", summary)) if nm not in have)
    if add:
        edits.append((insert_at, insert_at, add))
    for stmt in tree.body:                                            # built-in recipes import their neighbours relatively
        if isinstance(stmt, ast.ImportFrom) and stmt.level:
            pkg = "form.recipes" if stmt.level == 1 else "form" if stmt.level == 2 else None
            if pkg is None:
                raise ShareError("This design imports from outside Form Studio's packages.")
            mod = pkg + ("." + stmt.module if stmt.module else "")
            seg = src.encode("utf-8")[pos(stmt):pos(stmt, True)].decode("utf-8")
            edits.append((pos(stmt), pos(stmt, True), re.sub(r"^from\s+\.+\s*[\w.]*\s+import", f"from {mod} import", seg, count=1)))
    b = src.encode("utf-8")
    for s, e, t in sorted(edits, key=lambda x: x[0], reverse=True):
        b = b[:s] + t.encode("utf-8") + b[e:]
    return header + b.decode("utf-8")


def rewrite_scad(src: str, values: dict, ranges: dict, header: str) -> str:
    from .cad_bridges import _ASSIGN, _RANGE
    out, found = [], set()
    for line in src.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = _ASSIGN.match(body)
        if m and m.group(1) in values and m.group(1) not in found:
            key = m.group(1)
            found.add(key)
            new = body[:m.start(2)] + _num(values[key]) + body[m.end(2):]
            c = m.group(3)
            lo, hi = ranges.get(key, (None, None))
            r = _RANGE.match(c or "")
            if r and lo is not None and hi is not None:
                a, b2, c3 = r.groups()
                rng = f"[{_num(lo)}:{b2}:{_num(hi)}]" if c3 is not None else f"[{_num(lo)}:{_num(hi)}]"
                cstart = new.rfind(c)
                new = new[:cstart] + rng + c[r.end():] + new[cstart + len(c):]
            line = new + line[len(body):]
        out.append(line)
    return header + "".join(out)


def derive(st, pid: str, title: str = "", summary: str = "", ranges: dict | None = None) -> dict:
    """The design's current code as a recipe whose defaults are the design's values. It is built at those defaults
    and compared with the design, then kept aside for review; install_derived installs it."""
    p = st.load(pid)
    head = st.rev(p)
    rid = st.rid(p)
    code = st.source_text(p)
    if code is None:
        raise ShareError("The code this design was built from is not on this computer.")
    recipe = st.recipe(p)
    kind = "scad" if rid.startswith("scad:") else "python"
    if getattr(recipe, "mesh", False) and kind == "python":
        raise ShareError("This design is an imported mesh, not code with parameters, so it cannot become a recipe.")
    values = {k: float(v) for k, v in head["values"].items() if k in {q.key for q in recipe.params}}
    narrowed, problems = {}, []
    for q in recipe.params:
        lo, hi = (ranges or {}).get(q.key) or (q.min, q.max)
        lo, hi, v = float(lo), float(hi), values[q.key]
        if lo >= hi:
            problems.append(f"{q.label}: the lowest value must be below the highest.")
        elif lo < q.min - 1e-9 or hi > q.max + 1e-9:
            problems.append(f"{q.label}: a range can be narrowed, not widened ({_num(q.min)} to {_num(q.max)} {q.unit}).".replace(" )", ")"))
        elif not lo - 1e-9 <= v <= hi + 1e-9:
            problems.append(f"{q.label}: the range must include the design's value, {_num(v)} {q.unit}.".replace(" ,", ","))
        if (lo, hi) != (q.min, q.max):
            narrowed[q.key] = (lo, hi)
    if problems:
        raise ShareError(problems[0], " ".join(problems[1:3]))
    title = (title or p["name"]).strip()[:80]
    summary = (summary or "").strip()[:300] or f"{recipe.summary}".strip()[:300]
    header = (f"# {title}: a recipe made in Form Studio from the design “{p['name']}” (r{head['n']:02d}).\n"
              f"# Its defaults are that design's values.\n")
    new = (rewrite_python(code, values, narrowed, title, summary, header) if kind == "python"
           else rewrite_scad(code, values, narrowed, header.replace("# ", "// ")))
    info = lib.inspect(new.encode("utf-8"), "recipe" + lib.KINDS[kind])
    if info["problems"]:
        raise ShareError("The rewritten code is not a recipe Form Studio can use: " + info["problems"][0])
    nrid = st._load_design(new, "openscad" if kind == "scad" else "python")
    nr = st.recipes[nrid]
    mismatch = [q.key for q in nr.params if q.key in values and abs(nr.defaults()[q.key] - values[q.key]) > 1e-9]
    if mismatch:
        raise ShareError("The rewritten recipe does not default to the design's values: " + ", ".join(mismatch[:6]) + ".")
    from .studio import H
    built = st._k("view", key="rv-" + H(nrid, nr.defaults()), recipe_id=nrid, values=nr.defaults(), tol=0.08, timeout=180)
    try:
        was = st.view(p)
    except Exception:
        was = None
    v0, v1 = (was or {}).get("volume_mm3"), built.get("volume_mm3")
    same = bool(v0 and v1 and abs(v0 - v1) <= max(1e-3, 1e-6 * abs(v0)))
    (_pending(st.root) / f"{info['sha256']}{lib.KINDS[kind]}").write_text(new, encoding="utf-8")
    params = [{**{k: getattr(q, k) for k in PARAM_KEYS}} for q in nr.params]
    return {**info, "title": title, "summary": summary, "project": pid, "rev": head["n"], "params": len(params),
            "param_list": params, "derived": True,
            "check": {"same_volume": same, "design_volume_mm3": v0, "recipe_volume_mm3": v1, "rev": head["n"]},
            "entry": {"title": title, "summary": summary, "author": profile(st.root).get("author", ""), "params": len(params)}}


def install_derived(root, sha: str, kind: str, title: str = "", summary: str = "", project: str = "", rev: int | None = None,
                    tags=None) -> dict:
    sha = str(sha or "").lower()
    if kind not in lib.KINDS or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ShareError("Unknown recipe.")
    f = _pending(root) / f"{sha}{lib.KINDS[kind]}"
    if not f.is_file():
        raise ShareError("Make the recipe from the design again, then install it.")
    text = f.read_text(encoding="utf-8")
    out = lib.install(root, text, kind, sha, {"title": title, "summary": summary, "author": profile(root).get("author", ""),
                                              "tags": _clean_tags(tags), "origin": "design"})
    out = _update_entry(root, out["id"], derived_from={"project": project, "rev": rev})
    f.unlink(missing_ok=True)
    return {**out, "section": "mine", "installed": True}


def derive_params(st, pid: str) -> dict:
    """What the Turn-into-a-recipe sheet starts from: each parameter's value in the design and its full range."""
    p = st.load(pid)
    head = st.rev(p)
    recipe = st.recipe(p)
    rows = [{**{k: getattr(q, k) for k in PARAM_KEYS}, "value": head["values"].get(q.key, q.default),
             "provenance": (head.get("provenance") or {}).get(q.key, {}).get("source", "assumed")} for q in recipe.params]
    rid = st.rid(p)
    ok, why = True, ""
    if getattr(recipe, "mesh", False) and not rid.startswith("scad:"):
        ok, why = False, "This design is an imported mesh, not code with parameters."
    elif st.source_text(p) is None:
        ok, why = False, "The code this design was built from is not on this computer."
    return {"project": pid, "name": p["name"], "rev": head["n"], "params": rows, "summary": recipe.summary,
            "kind": "scad" if rid.startswith("scad:") else "python", "ok": ok, "why": why}


# ---- HTTP routes (form/home_api.py hands /api/recipes/... here first) --------------------------------------------

def route_get(st, path: str, q: dict):
    m = re.fullmatch(r"/api/recipes/mine/([a-z0-9-]+)/preview\.png", path)
    if m:
        f = preview_file(st.root, m.group(1))
        if not f.is_file():
            raise ShareError("No preview yet.")
        return f.read_bytes(), "image/png", f.name
    m = re.fullmatch(r"/api/recipes/pending/([0-9a-f]{64})\.png", path)
    if m:
        f = _pending(st.root) / f"{m.group(1)}.png"
        if not f.is_file():
            raise ShareError("No preview.")
        return f.read_bytes(), "image/png", f.name
    m = re.fullmatch(r"/api/recipes/share/([a-z0-9-]+)\.formrecipe", path)
    if m:
        return package_bytes(st, m.group(1)), "application/zip", f"{m.group(1)}{EXT}"
    if path == "/api/recipes/share/profile":
        return profile(st.root)
    m = re.fullmatch(r"/api/recipes/derive/([a-z0-9-]+)", path)
    if m:
        return derive_params(st, m.group(1))
    return None


def route_post(st, path: str, body, q: dict):
    b = body if isinstance(body, dict) else {}
    if path == "/api/recipes/share/prepare":
        return prepare(st, str(b.get("id", "")), b.get("edits") or None)
    if path == "/api/recipes/share/meta":
        return edit_meta(st.root, str(b.get("id", "")), b.get("title"), b.get("summary"), b.get("author"), b.get("tags"))
    if path == "/api/recipes/share/submission":
        return save_submission(st, str(b.get("id", "")), str(b.get("dir", "")))
    if path == "/api/recipes/package/inspect":
        if not isinstance(body, bytes):
            raise ShareError("Send the package file itself.")
        return inspect_package(st.root, body, q.get("name") or "recipe" + EXT)
    if path == "/api/recipes/package/install":
        return install_package(st.root, str(b.get("sha256", "")))
    if path == "/api/recipes/derive":
        ranges = {k: (v[0], v[1]) for k, v in (b.get("ranges") or {}).items() if isinstance(v, (list, tuple)) and len(v) == 2}
        return derive(st, str(b.get("project", "")), str(b.get("title", "")), str(b.get("summary", "")), ranges)
    if path == "/api/recipes/derive/install":
        return install_derived(st.root, str(b.get("sha256", "")), str(b.get("kind", "")), str(b.get("title", "")),
                               str(b.get("summary", "")), str(b.get("project", "")), b.get("rev"), b.get("tags"))
    return None


# ---- command line (form recipes export|import|submit|derive) -----------------------------------------------------

def main(verb: str, argv: list[str]) -> int:
    import argparse
    import sys

    from . import config
    ap = argparse.ArgumentParser(prog=f"form recipes {verb}")
    ap.add_argument("arg")
    ap.add_argument("--out", default="")
    ap.add_argument("--author")
    ap.add_argument("--tags")
    ap.add_argument("--sha256", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--range", action="append", default=[], help="key=min:max (narrow a parameter's range)")
    ap.add_argument("--install", action="store_true")
    a = ap.parse_args(argv)
    cfg = config.load()
    root = cfg["data"]["dir"]
    st = None
    try:
        if verb == "import":
            info = import_file(root, a.arg)
            if a.sha256:
                if a.sha256.lower() != info["sha256"]:
                    raise ShareError("The package's code is not the one you reviewed; nothing was installed.",
                                     f"Its SHA-256 is {info['sha256']}.")
                if info["problems"]:
                    raise ShareError(info["problems"][0])
                out = install_package(root, info["sha256"])
            else:
                out = {k: v for k, v in info.items() if k not in ("source",)}
                out["install_with"] = f'form recipes import "{a.arg}" --sha256 {info["sha256"]}'
        else:
            from .studio import Studio
            st = Studio(cfg)
            if verb == "export":
                out = export(st, a.arg, a.out or None, a.author, a.tags)
            elif verb == "submit":
                if a.author is not None or a.tags is not None:
                    edit_meta(root, a.arg, author=a.author, tags=a.tags)
                r = prepare(st, a.arg)
                out = {"submission": {k: r["submission"][k] for k in ("folder", "meta", "problems", "notes")},
                       "issue_url": r["submission"]["issue"]["url"], "omitted_from_link": r["submission"]["issue"]["omitted"],
                       "note": "Nothing was sent. Open issue_url in a browser to see the pre-filled form; it is posted only if you submit it there."}
                if a.out:
                    out["saved"] = save_submission(st, a.arg, a.out)
            elif verb == "derive":
                ranges = {}
                for r in a.range:
                    k, _, mm = r.partition("=")
                    lo, _, hi = mm.partition(":")
                    ranges[k.strip()] = (float(lo), float(hi))
                d = derive(st, a.arg, a.title, a.summary, ranges)
                if a.install:
                    if a.sha256.lower() != d["sha256"]:
                        raise ShareError("Review the code first, then install it with the SHA-256 this prints.",
                                         f'form recipes derive {a.arg} --install --sha256 {d["sha256"]}')
                    out = install_derived(root, d["sha256"], d["kind"], d["title"], d["summary"], a.arg, d["rev"])
                else:
                    out = {k: v for k, v in d.items() if k != "param_list"}
                    out["install_with"] = f'form recipes derive {a.arg} --install --sha256 {d["sha256"]}'
            else:
                raise ShareError("Unknown verb.")
    except (lib.LibraryError, OSError) as e:
        print(json.dumps({"error": e.public() if isinstance(e, lib.LibraryError) else {"message": str(e)}}, ensure_ascii=False))
        return 2
    except Exception as e:                                   # StudioError and kernel failures
        pub = e.public() if hasattr(e, "public") else {"message": str(e)}
        print(json.dumps({"error": pub}, ensure_ascii=False, default=str))
        return 2
    finally:
        if st is not None:
            try:
                st.kernel.stop()
            except Exception:
                pass
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0
