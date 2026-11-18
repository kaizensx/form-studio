"""Write site/recipes/index.json: every recipe the gallery and the app's community browser list. Standard library only.

    python site/tools/build_recipe_index.py [--check]

Sources:
- the built-in recipes in form/recipes/*.py (read with `ast`, so the CAD kernel is not needed): builtin = true
- community/recipes/<id>/ with recipe.py or recipe.scad, meta.json and preview.png: builtin = false

The app fetches https://kaizensx.github.io/form-studio/recipes/index.json, so the path and this schema are an interface:

    {"version": 1, "generated": ISO-8601,
     "recipes": [{"id", "title", "summary", "author", "tags": [], "kind": "python" | "scad", "builtin": bool,
                  "url": raw.githubusercontent.com URL of the recipe file on main, or null for built-in recipes,
                  "sha256": hex digest of that file, or null,
                  "preview": URL of a picture on the website, or null,
                  "discussion"?: its GitHub Discussions thread, "added"?: YYYY-MM-DD}]}

Community previews are copied to site/recipes/previews/community-<id>.png.

--check exits 1 if a community recipe is malformed, without writing anything.
"""
from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
OUT = SITE / "recipes" / "index.json"
BASE = "https://kaizensx.github.io/form-studio/"
RAW = "https://raw.githubusercontent.com/kaizensx/form-studio/main/"
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
# Optional: the recipe's thread in GitHub Discussions, and the date it joined the gallery (for "newest" sorting).
OPTIONAL = {"discussion": re.compile(r"^https://github\.com/kaizensx/form-studio/discussions/\d+$"),
            "added": re.compile(r"^\d{4}-\d{2}-\d{2}$")}
FIELDS = {"id": str, "title": str, "summary": str, "author": str, "tags": list, "kind": str, "params_count": int}

# The order of the built-in recipes in the gallery (form/recipes/__init__.py registry order); others follow by id.
ORDER = ["dock", "gridfinity", "hook", "planter", "coupon", "enclosure", "gear_pair", "knob", "hinged_box"]

# Built-in recipes carry no tags in code; these are for search in the gallery.
BUILTIN_TAGS = {
    "dock": ["phone", "desk", "fit", "cable"],
    "gridfinity": ["storage", "gridfinity", "organiser", "magnets"],
    "hook": ["wall", "load", "screws", "strength model"],
    "planter": ["home", "vase", "twist"],
    "coupon": ["calibration", "fit", "tolerance"],
    "enclosure": ["electronics", "pcb", "heat-set inserts", "lid"],
    "gear_pair": ["mechanism", "gears", "involute"],
    "knob": ["control", "shaft", "set screw"],
    "hinged_box": ["box", "hinge", "assembly", "lid"],
}


def _const(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def builtin() -> list[dict]:
    """Classes in form/recipes/*.py with a non-empty `id`, `title` and `summary`."""
    out = []
    for f in sorted((ROOT / "form" / "recipes").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            attrs, params = {}, 0
            for st in cls.body:
                if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                    name = st.targets[0].id
                    if name in ("id", "title", "summary"):
                        attrs[name] = _const(st.value)
                    elif name == "params" and isinstance(st.value, (ast.List, ast.Tuple)):
                        params = sum(1 for e in st.value.elts if isinstance(e, ast.Call))
            if attrs.get("id") and attrs.get("title") and attrs.get("summary"):
                rid = attrs["id"]
                preview = SITE / "recipes" / "previews" / f"{rid}.webp"
                out.append({"id": rid, "title": attrs["title"], "summary": attrs["summary"], "author": "Form Studio",
                            "tags": BUILTIN_TAGS.get(rid, []), "kind": "python", "builtin": True, "url": None,
                            "sha256": None, "params_count": params,
                            "preview": f"{BASE}recipes/previews/{rid}.webp" if preview.is_file() else None})
    return sorted(out, key=lambda r: (ORDER.index(r["id"]) if r["id"] in ORDER else len(ORDER), r["id"]))


def community(errors: list[str]) -> list[dict]:
    out = []
    base = ROOT / "community" / "recipes"
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        where = f"community/recipes/{d.name}"
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"{where}/meta.json: {e}")
            continue
        bad = [k for k, t in FIELDS.items() if not isinstance(meta.get(k), t)]
        if bad:
            errors.append(f"{where}/meta.json: missing or wrong type: {', '.join(bad)}")
            continue
        if meta["id"] != d.name or not ID.match(d.name):
            errors.append(f"{where}: id must equal the folder name and use a-z, 0-9 and hyphens")
            continue
        if meta["kind"] not in ("python", "scad"):
            errors.append(f"{where}/meta.json: kind must be \"python\" or \"scad\"")
            continue
        src = d / ("recipe.py" if meta["kind"] == "python" else "recipe.scad")
        if not src.is_file():
            errors.append(f"{where}: {src.name} is missing")
            continue
        if not all(isinstance(t, str) for t in meta["tags"]):
            errors.append(f"{where}/meta.json: tags must be strings")
            continue
        rel = src.relative_to(ROOT).as_posix()
        prev = d / "preview.png"
        if prev.is_file():                        # served next to the gallery, so the site loads nothing from another host
            (SITE / "recipes" / "previews").mkdir(parents=True, exist_ok=True)
            shutil.copy(prev, SITE / "recipes" / "previews" / f"community-{d.name}.png")
        out.append({"id": meta["id"], "title": meta["title"], "summary": meta["summary"], "author": meta["author"],
                    "tags": meta["tags"], "kind": meta["kind"], "builtin": False, "url": RAW + rel,
                    "sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "params_count": meta["params_count"],
                    "preview": f"{BASE}recipes/previews/community-{d.name}.png" if prev.is_file() else None,
                    **{k: meta[k] for k in OPTIONAL if isinstance(meta.get(k), str) and OPTIONAL[k].match(meta[k])}})
    return out


def main(argv: list[str]) -> int:
    errors: list[str] = []
    recipes = builtin()
    seen = {r["id"] for r in recipes}
    for r in community(errors):
        if r["id"] in seen:
            errors.append(f"community/recipes/{r['id']}: the id is already used by a built-in recipe")
            continue
        seen.add(r["id"])
        recipes.append(r)
    for e in errors:
        print("FAIL", e)
    if errors:
        return 1
    if "--check" in argv:
        print(f"ok: {len(recipes)} recipes")
        return 0
    index = {"version": 1, "generated": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
             "recipes": recipes}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {sum(r['builtin'] for r in recipes)} built-in, "
          f"{sum(not r['builtin'] for r in recipes)} community")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
