"""Before and after pictures for a pull request: affected recipes, and the interface when QML changes.

Unprivileged steps (pr-preview.yml, run on the pull request's code with a read-only token):

    python scripts/ci/pr_preview.py affected --base SHA --head SHA            # prints and outputs what to build
    python scripts/ci/pr_preview.py recipes --affected A.json --base-root DIR --head-root . --python PY --out OUT
    python scripts/ci/pr_preview.py ui --shots DIR --baseline DIR --out OUT   # pick and compare screenshots

Privileged step (pr-preview-comment.yml, after the run finished; runs none of the pull request's code):

    python scripts/ci/pr_preview.py comment --dir ARTIFACTS --head-sha SHA [--dry-run]

The comment step reads only JSON and PNG files, checks that the pull request named in them really has the head commit
the workflow run was for, and writes the Markdown itself from validated values.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SIGNATURE, GitHub, code, load_json, log, md, num, png_info, run_url,  # noqa: E402
                    safe_name, set_output, summary)

MARKER = "form-studio:pr-preview"
CORE = {"form/kernel.py", "form/worker.py", "form/checks.py", "form/render.py", "form/parts.py", "form/patterns.py",
        "form/marks.py", "form/fit.py", "form/recipes/base.py", "form/recipes/__init__.py", "form/recipes/assembly.py",
        "form/recipes/meshsolid.py", "pyproject.toml", "requirements.lock"}
MAX_UI_SHOTS = 8


# ---- affected ------------------------------------------------------------------------------------------------------

def builtin_ids(root: Path) -> dict[str, str]:
    """{module file name: recipe id} for form/recipes/*.py, read as text."""
    out = {}
    for f in sorted((root / "form" / "recipes").glob("*.py")):
        m = re.search(r'^\s+id\s*=\s*"([a-z0-9_]+)"', f.read_text(encoding="utf-8"), re.M)
        if m:
            out[f.name] = m.group(1)
    return out


def affected(changed: list[str], root: Path) -> dict:
    ids = builtin_ids(root)
    recipes, reasons = set(), {}
    qml = any(p.startswith("form/app/") and p.endswith((".qml", ".js", ".py")) for p in changed)
    core = sorted(p for p in changed if p in CORE)
    if core:
        recipes |= set(ids.values())
        reasons["all built-in recipes"] = core[:5]
    for p in changed:
        if p.startswith("form/recipes/") and Path(p).name in ids:
            recipes.add(ids[Path(p).name])
            reasons.setdefault(ids[Path(p).name], []).append(p)
    return {"recipes": sorted(recipes), "ui": qml, "reasons": reasons}


def changed_files(base: str, head: str) -> list[str]:
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True, check=True)
    return [x for x in r.stdout.splitlines() if x]


# ---- recipes -------------------------------------------------------------------------------------------------------

def build_side(python: str, root: Path, kind: str, rid: str, out: Path, data: Path) -> None:
    script = Path(__file__).resolve().parent / "build_recipe.py"
    args = [python, str(script), "--repo-root", str(root), "--out", str(out)]
    args += ["--builtin", rid]
    env = {**os.environ, "FORM_DATA": str(data), "PYTHONPATH": str(root), "FORM_NO_UPDATE_CHECK": "1"}
    t = subprocess.run(args, env=env, capture_output=True, text=True, timeout=900)
    if t.returncode:
        log(t.stdout[-2000:], t.stderr[-4000:])


def cmd_recipes(a) -> int:
    aff = json.loads(Path(a.affected).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = [("builtin", r) for r in aff.get("recipes", [])]
    tmp = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "pr-preview-data"
    for kind, rid in items:
        for side, root in (("before", Path(a.base_root)), ("after", Path(a.head_root))):
            if kind == "builtin" and rid not in builtin_ids(root).values():
                continue
            log(f"building {kind} {rid} ({side})")
            build_side(a.python, root.resolve(), kind, rid, out / f"{kind}-{rid}" / side, tmp / f"{kind}-{rid}-{side}")
    (out / "recipes.json").write_text(json.dumps({"items": [f"{k}-{r}" for k, r in items], "reasons": aff.get("reasons", {})},
                                                 indent=1), encoding="utf-8")
    return 0


# ---- interface screenshots -----------------------------------------------------------------------------------------

def diff_ratio(a: Path, b: Path) -> float | None:
    """Share of pixels that differ noticeably (Pillow); None when the sizes differ or Pillow is missing."""
    try:
        from PIL import Image, ImageChops
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if ia.size != ib.size:
            return 1.0
        d = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 24 else 0)
        return round(sum(d.histogram()[255:]) / (ia.size[0] * ia.size[1]), 4)
    except Exception:
        return None


def cmd_ui(a) -> int:
    shots, base, out = Path(a.shots), Path(a.baseline), Path(a.out)
    (out / "after").mkdir(parents=True, exist_ok=True)
    (out / "before").mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(shots.glob("*.png")):
        if not safe_name(f.name):
            continue
        b = base / f.name
        ratio = diff_ratio(b, f) if b.exists() else None
        rows.append({"name": f.name, "baseline": b.exists(), "diff": ratio, "failed": f.name.startswith("fail-")})
    # failures first, then the most changed, then new screens
    rows.sort(key=lambda r: (not r["failed"], -(r["diff"] or 0) if r["baseline"] else 0.5, r["name"]))
    picked = [r for r in rows if r["failed"] or not r["baseline"] or (r["diff"] or 0) > 0.002][:MAX_UI_SHOTS]
    for r in picked:
        shutil.copyfile(shots / r["name"], out / "after" / r["name"])
        if r["baseline"]:
            shutil.copyfile(base / r["name"], out / "before" / r["name"])
        r["shown"] = True
    (out / "ui.json").write_text(json.dumps({"shots": rows, "journeys": a.journeys, "baseline_count": len(list(base.glob('*.png')))}, indent=1),
                                 encoding="utf-8")
    log(f"{len(rows)} screenshots, {len(picked)} shown")
    return 0


# ---- comment (privileged) ------------------------------------------------------------------------------------------

def _res(p: Path) -> dict | None:
    try:
        return load_json(p / "result.json")
    except (ValueError, OSError):
        return None


def _d0(r: dict | None) -> dict:
    s = (r or {}).get("sets") or []
    return s[0] if s and isinstance(s[0], dict) else {}


def _delta(a, b, fmt="{:+.1f}", pct=True) -> str:
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
        return "—"
    if pct and a:
        return f"{(b - a) / a * 100:+.1f}%"
    return fmt.format(b - a)


def recipe_section(adir: Path, urls: dict) -> list[str]:
    meta = load_json(adir / "recipes.json")
    items = [i for i in meta.get("items", []) if isinstance(i, str) and re.fullmatch(r"builtin-[a-z0-9_-]{1,48}", i)]
    if not items:
        return []
    changed_rows, same = [], []
    for item in items[:20]:
        before, after = _res(adir / item / "before"), _res(adir / item / "after")
        b, a = _d0(before), _d0(after)
        name = md(((after or before or {}).get("recipe") or {}).get("title") or item.split("-", 1)[1], 60)
        if after is None or a.get("state") != "built":
            err = (a.get("error") or {}).get("message") or ("; ".join(map(str, (after or {}).get("problems", [])[:2])) or "no result")
            changed_rows.append((item, name, f"**does not build:** {md(err, 200)}"))
            continue
        if before is None:
            changed_rows.append((item, name, "new recipe"))
            continue
        bs = {c.get("id"): c.get("status") for c in b.get("checks") or [] if isinstance(c, dict)}
        as_ = {c.get("id"): c.get("status") for c in a.get("checks") or [] if isinstance(c, dict)}
        lab = {c.get("id"): c.get("label") for c in a.get("checks") or [] if isinstance(c, dict)}
        moved = [f"{md(lab.get(k) or k, 40)}: {md(bs.get(k), 5)} → {md(as_.get(k), 5)}" for k in as_ if bs.get(k) != as_.get(k)]
        geom_same = b.get("volume_mm3") == a.get("volume_mm3") and b.get("bbox_mm") == a.get("bbox_mm")
        if geom_same and not moved:
            same.append(name)
            continue
        parts = [f"volume {_delta(b.get('volume_mm3'), a.get('volume_mm3'))} ({num(a.get('volume_mm3'), '{:,.0f}')} mm³)",
                 f"mass {_delta(b.get('solid_mass_g'), a.get('solid_mass_g'), '{:+.2f} g', False)}"]
        if b.get("bbox_mm") != a.get("bbox_mm") and isinstance(a.get("bbox_mm"), list):
            parts.append("size " + " × ".join(num(x) for x in a["bbox_mm"][:3]) + " mm")
        if moved:
            parts.append("checks: " + "; ".join(moved[:4]))
        changed_rows.append((item, name, " · ".join(parts)))
    lines = ["### Recipes", ""]
    if changed_rows:
        lines += ["| Recipe | Before | After | Change |", "|---|---|---|---|"]
        for item, name, text in changed_rows:
            bu, au = urls.get(f"{item}/before"), urls.get(f"{item}/after")
            bi = f'<img src="{bu}" width="300" alt="before">' if bu else "—"
            ai = f'<img src="{au}" width="300" alt="after">' if au else "—"
            lines.append(f"| {name} | {bi} | {ai} | {text} |")
    if same:
        lines += ["", "Unchanged geometry and checks: " + ", ".join(same) + "."]
    lines += ["", "<sub>Built in the CAD kernel at default values with the base branch and with this pull request. Mass is "
              "the solid in PLA, before infill. Not sliced.</sub>"]
    return lines


def ui_section(udir: Path, urls: dict) -> list[str]:
    data = load_json(udir / "ui.json")
    shots = [s for s in data.get("shots", []) if isinstance(s, dict) and safe_name(str(s.get("name")))]
    lines = ["### Interface", ""]
    status = data.get("journeys")
    if status in ("passed", "failed"):
        lines.append(f"Interface journeys on Linux: **{status}**.")
    shown = [s for s in shots if s.get("shown")]
    if shown:
        lines += ["", "| Screen | Before (dev) | After |", "|---|---|---|"]
        for s in shown:
            n = s["name"]
            bu, au = urls.get(f"ui/before/{n}"), urls.get(f"ui/after/{n}")
            label = md(n[:-4].replace("-", " "), 60) + (" (failure)" if s.get("failed") else "")
            if s.get("baseline") and isinstance(s.get("diff"), (int, float)):
                label += f"<br><sub>{s['diff'] * 100:.1f}% of pixels differ</sub>"
            elif not s.get("baseline") and not s.get("failed"):
                label += "<br><sub>new screen</sub>"
            lines.append(f"| {label} | " + (f'<img src="{bu}" width="380" alt="before">' if bu else "—") + " | "
                         + (f'<img src="{au}" width="380" alt="after">' if au else "—") + " |")
    rest = len(shots) - len(shown)
    if rest > 0:
        lines += ["", f"{rest} other screenshot{'s match' if rest != 1 else ' matches'} the `dev` baseline."]
    if not shots:
        lines.append("No screenshots were produced.")
    return lines


def cmd_comment(a) -> int:
    root = Path(a.dir)
    pr = load_json(root / "pr" / "pr.json")
    number, sha = pr.get("number"), pr.get("head_sha")
    if not isinstance(number, int) or number <= 0 or sha != a.head_sha:
        raise SystemExit("pr.json does not match the workflow run")
    gh = GitHub(dry_run=a.dry_run)
    if not a.dry_run:
        live = gh.request("GET", gh.r(f"/pulls/{number}"))
        if live.get("head", {}).get("sha") != a.head_sha:
            log("the pull request has moved on since this run; a newer run will comment")
            return 0
    files, keys = {}, {}
    month = dt.date.today().strftime("%Y-%m")
    dest = f"media/{month}/pr-{number}-{a.head_sha[:10]}"
    rdir, udir = root / "recipes", root / "ui"
    if (rdir / "recipes.json").exists():
        for item in [i for i in load_json(rdir / "recipes.json").get("items", []) if isinstance(i, str)][:20]:
            if not re.fullmatch(r"builtin-[a-z0-9_-]{1,48}", item):
                continue
            for side in ("before", "after"):
                f = rdir / item / side / "preview.png"
                if png_info(f):
                    files[f"{dest}/{item}-{side}.png"] = f
                    keys[f"{item}/{side}"] = f"{dest}/{item}-{side}.png"
    if (udir / "ui.json").exists():
        for side in ("before", "after"):
            for f in sorted((udir / side).glob("*.png"))[:12]:
                if safe_name(f.name) and png_info(f, limit=4_000_000):
                    files[f"{dest}/ui-{side}-{f.name}"] = f
                    keys[f"ui/{side}/{f.name}"] = f"{dest}/ui-{side}-{f.name}"
    urls = {}
    if files and not a.dry_run:
        import assets
        pub = assets.put(files, f"Pictures for pull request #{number}")
        urls = {k: pub[p] for k, p in keys.items()}
    elif files:
        urls = {k: f"https://example.invalid/{p}" for k, p in keys.items()}
    body = ["## Preview", ""]
    if (rdir / "recipes.json").exists():
        body += recipe_section(rdir, urls) + [""]
    if (udir / "ui.json").exists():
        body += ui_section(udir, urls) + [""]
    if len(body) == 2:
        log("nothing to show")
        return 0
    body.append(f"<sub>{SIGNATURE} · commit {code(a.head_sha[:10], 12)} · [workflow run]({run_url()})</sub>")
    text = "\n".join(body)
    if a.dry_run:
        print(text)
        return 0
    gh.upsert_comment(number, MARKER, text)
    summary(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("affected")
    s.add_argument("--base", required=True)
    s.add_argument("--head", default="HEAD")
    s.add_argument("--out", default="affected.json")
    s.add_argument("--files", help="a file with one changed path per line, instead of git (tests)")
    s = sub.add_parser("recipes")
    s.add_argument("--affected", required=True)
    s.add_argument("--base-root", required=True)
    s.add_argument("--head-root", default=".")
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--out", required=True)
    s = sub.add_parser("ui")
    s.add_argument("--shots", required=True)
    s.add_argument("--baseline", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--journeys", choices=["passed", "failed", "unknown"], default="unknown")
    s = sub.add_parser("comment")
    s.add_argument("--dir", required=True)
    s.add_argument("--head-sha", required=True)
    s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "affected":
        files = Path(a.files).read_text().split() if a.files else changed_files(a.base, a.head)
        res = affected(files, Path("."))
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res, indent=1))
        set_output("recipes", "true" if res["recipes"] else "false")
        set_output("ui", "true" if res["ui"] else "false")
        return 0
    return {"recipes": cmd_recipes, "ui": cmd_ui, "comment": cmd_comment}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
