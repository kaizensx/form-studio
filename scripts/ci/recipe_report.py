"""Post the result of a recipe check on its issue: one comment kept up to date, pictures, checks, slice and labels.

    python scripts/ci/recipe_report.py --issue 42 --result DIR [--build-outcome success|failure|cancelled] [--dry-run]

Runs in the privileged job of recipe-check.yml, after the unprivileged job built the submission in a sandbox.
Everything in DIR came from that job and is treated as data: JSON is size-limited and type-checked, pictures must be
real PNGs, every string is escaped before it reaches Markdown. The issue number comes from the workflow, not from DIR.

The recipe file itself is extracted again here, from the issue as it is now (scripts/ci/issue_recipe.py, no code is
run); when its SHA-256 matches what was built and the verdict is valid, the bundle a maintainer can accept is stored
on the ci-assets branch under recipes/issue-<n>/.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402
import issue_recipe  # noqa: E402
from common import (SIGNATURE, GitHub, code, load_json, log, md, num, png_info, run_url,  # noqa: E402
                    summary)

MARKER = "form-studio:recipe-check"
ROOT = Path(__file__).resolve().parents[2]
BUILTIN_IDS = {"dock", "gridfinity", "hook", "planter", "coupon", "enclosure", "gear_pair", "knob", "hinged_box"}
LABELS = {
    "recipe:valid": ("1f7f52", "Builds at its defaults and passes Form Studio's checks (automated)"),
    "recipe:needs-changes": ("cc3f22", "The automated recipe check found something to fix"),
    "recipe:accept": ("3a5fd0", "Maintainers: add to open a pull request adding this recipe to the gallery"),
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:42].strip("-")


def ast_meta(source: str) -> dict:
    """Title, summary and parameter count from the syntax tree; the code is not run."""
    out = {"title": "", "summary": "", "params": 0}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for c in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        if not any(getattr(b, "id", getattr(b, "attr", "")) == "Recipe" for b in c.bases):
            continue
        for st in c.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                k = st.targets[0].id
                if k in ("title", "summary"):
                    try:
                        v = ast.literal_eval(st.value)
                        out[k] = v.strip() if isinstance(v, str) else ""
                    except Exception:
                        pass
                elif k == "params" and isinstance(st.value, (ast.List, ast.Tuple)):
                    out["params"] = sum(1 for e in st.value.elts if isinstance(e, ast.Call))
        if not out["title"]:
            out["title"] = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", c.name)
        break
    return out


def checks_table(checks: list) -> list[str]:
    rows = ["| Result | Check | Value | Evidence |", "|---|---|---|---|"]
    for c in checks[:30]:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status", ""))
        status = {"PASS": "Pass", "WARN": "**Warning**", "FAIL": "**Fail**"}.get(status, md(status, 10))
        rows.append(f"| {status} | {md(c.get('label'), 80)} | {md(c.get('value'), 60)} | {md(c.get('evidence'), 20)} |")
    return rows


def fmt_time(seconds) -> str:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return "—"
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def compose(issue: dict, sub: dict, res: dict | None, urls: dict, outcome: str, problems_extra: list[str],
            accept_ready: bool) -> tuple[str, str]:
    """Markdown and verdict ("valid" | "needs-changes" | "error")."""
    lines = []
    if res is None:
        lines += ["### Recipe check could not finish",
                  "",
                  f"The build job ended with `{md(outcome, 20)}` before it produced a result. This is usually the CI "
                  "machine, not the recipe; a maintainer can re-run it from the workflow run below, and editing the issue "
                  "starts a new check.",
                  "", f"[Workflow run]({run_url()})"]
        return "\n".join(lines), "error"
    verdict = res.get("verdict") if res.get("verdict") in ("valid", "needs-changes") else "needs-changes"
    problems = [p for p in res.get("problems", []) if isinstance(p, str)][:12] + problems_extra
    if problems_extra:
        verdict = "needs-changes"
    recipe = res.get("recipe") if isinstance(res.get("recipe"), dict) else {}
    title = recipe.get("title") or issue.get("title") or "Recipe"
    head = "Builds and passes its checks" if verdict == "valid" else "Needs changes"
    lines += [f"### Recipe check: {md(title, 80)}", "", f"**{head}.** Built in Form Studio's CAD kernel at its default "
              "values" + (" and two other parameter sets" if len(res.get("sets", [])) > 1 else "") + ", checked, and "
              "sliced with a real slicer."]
    if problems:
        lines += ["", "**To fix:**", ""] + [f"- {md(p, 400)}" for p in problems]
    if urls.get("preview"):
        lines += ["", f"![Preview at the default values]({urls['preview']})"]
    sets = [s for s in res.get("sets", []) if isinstance(s, dict)][:3]
    if sets:
        names = [md(s.get("name"), 20).capitalize() for s in sets]
        lines += ["", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(sets)]
        if len(sets) > 1:
            pics = []
            for s in sets:
                u = urls.get(f"set:{s.get('name')}")
                pics.append(f'<img src="{u}" width="260" alt="{md(s.get("name"), 20)}">' if u else "")
            lines.append("| Picture | " + " | ".join(pics) + " |")
        def row(label, fn):
            lines.append(f"| {label} | " + " | ".join(fn(s) for s in sets) + " |")
        def state(s):
            st = s.get("state")
            if st == "built":
                ro = s.get("rollup") or {}
                return f"built · {num(ro.get('PASS'), '{:.0f}')} pass, {num(ro.get('WARN'), '{:.0f}')} warn, {num(ro.get('FAIL'), '{:.0f}')} fail"
            if st == "rejected":
                return "refused by its constraints: " + md((s.get("error") or {}).get("message"), 140)
            return "**failed**: " + md((s.get("error") or {}).get("message"), 140)
        row("Result", state)
        row("Changed", lambda s: ", ".join(f"{code(k, 30)} = {num(v, '{:g}')}" for k, v in list((s.get("values") or {}).items())[:6]) or "defaults")
        row("Size (mm)", lambda s: " × ".join(num(x) for x in s.get("bbox_mm", [])[:3]) if isinstance(s.get("bbox_mm"), list) else "—")
        row("Volume", lambda s: num(s.get("volume_mm3"), "{:,.0f} mm³"))
        row("Solid mass, PLA", lambda s: num(s.get("solid_mass_g"), "{:.1f} g"))
        row("Build time", lambda s: num(sum(v for v in (s.get("seconds") or {}).values() if isinstance(v, (int, float))), "{:.1f} s"))
    d0 = sets[0] if sets else {}
    sl = d0.get("slice") if isinstance(d0.get("slice"), dict) else None
    env = res.get("environment") if isinstance(res.get("environment"), dict) else {}
    if sl and sl.get("ok"):
        pre = sl.get("presets") if isinstance(sl.get("presets"), dict) else {}
        lines += ["", "**Slice (simulated):** " + " · ".join(x for x in [
            f"{md(sl.get('slicer'), 30)} {md(sl.get('slicer_version'), 20)}",
            f"{fmt_time(sl.get('time_s'))} print time", num(sl.get("filament_g"), "{:.1f} g filament"),
            num(sl.get("layers"), "{:.0f} layers"), "supports" if sl.get("supports") else "no supports"] if x),
            f"<sub>Presets: {md(pre.get('machine'), 60)} / {md(pre.get('process'), 60)} / {md(pre.get('filament'), 60)}</sub>"]
    elif sl:
        lines += ["", "**Slice:** not sliced: " + md((sl.get("error") or {}).get("message"), 300)]
    if d0.get("checks"):
        lines += ["", "<details><summary>Checks at the default values</summary>", ""] + checks_table(d0["checks"]) + ["", "</details>"]
    if urls.get("sheet"):
        lines += ["", "<details><summary>Four views</summary>", "", f"![Four views]({urls['sheet']})", "", "</details>"]
    params = recipe.get("params") if isinstance(recipe.get("params"), list) else []
    if params:
        lines += ["", f"<details><summary>{len(params)} parameters</summary>", "", "| Key | Label | Default | Range | Group |",
                  "|---|---|---|---|---|"]
        for q in params[:60]:
            if isinstance(q, dict):
                lines.append(f"| {code(q.get('key'), 40)} | {md(q.get('label'), 60)} | {num(q.get('default'), '{:g}')} {md(q.get('unit'), 8)} "
                             f"| {num(q.get('min'), '{:g}')} to {num(q.get('max'), '{:g}')} | {md(q.get('group'), 12)} |")
        lines += ["", "</details>"]
    lines.append("")
    if verdict == "valid" and accept_ready:
        lines.append("A maintainer can add the `recipe:accept` label to open a pull request that adds this recipe to the "
                     "community gallery, credited to its author.")
    elif verdict == "valid" and sub.get("mode") == "archive":
        lines.append("This is a design archive, not a recipe file, so it cannot be added to the gallery as it is.")
    elif verdict != "valid":
        lines.append("Edit the issue with a corrected file and the check runs again. "
                     "[Writing a recipe](https://kaizensx.github.io/form-studio/docs/recipes.html) explains each check.")
    sha = res.get("source_sha256") or sub.get("sha256") or ""
    kern = md(env.get("kernel"), 60)
    lines += ["", f"<sub>{SIGNATURE} · Form Studio {md(env.get('form'), 20)} · kernel {kern} · "
              f"source SHA-256 {code(str(sha)[:16], 20)} · [workflow run]({run_url()}) · "
              f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</sub>"]
    return "\n".join(lines), verdict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--result", required=True, help="the artifact folder from the build job")
    ap.add_argument("--build-outcome", default="success")
    ap.add_argument("--dry-run", action="store_true", help="print the comment; change nothing on GitHub")
    ap.add_argument("--event", help="read the issue from this event file instead of the API (tests)")
    a = ap.parse_args(argv)
    gh = GitHub(dry_run=a.dry_run)
    issue = json.loads(Path(a.event).read_text(encoding="utf-8"))["issue"] if a.event else gh.issue(a.issue)
    rdir = Path(a.result)

    # The submission, extracted again from the issue as it is now. No code runs here.
    tmp = Path(tempfile.mkdtemp(prefix="recipe-sub-"))
    sub = issue_recipe.extract(issue, tmp, allow_download=True)
    res = None
    try:
        res = load_json(rdir / "out" / "result.json")
    except (ValueError, OSError) as e:
        log(f"no usable result: {e}")
    if not sub["found"]:
        if not sub["wants_check"]:
            log("not a submission; nothing to post")
            return 0
        body = ("### Recipe check\n\nThe automation could not find a recipe in this issue. Paste the whole `recipe.py` "
                "into **Recipe source**, link to it on GitHub or in a gist, or attach it (renamed to `recipe.py.txt`, or "
                "in a `.zip`)." + ("\n\n" + "\n".join(f"- {md(n, 300)}" for n in sub["notes"]) if sub["notes"] else "")
                + f"\n\n<sub>{SIGNATURE} · [workflow run]({run_url()})</sub>")
        verdict = "needs-changes"
        urls: dict = {}
        accept_ready = False
    else:
        extra = []
        if res is not None and res.get("source_sha256") and sub["sha256"] and sub["mode"] == "source" \
                and res.get("source_sha256") != sub["sha256"]:
            extra.append("The issue changed while it was being checked; the new version is checked in the next run.")
        rid = sub.get("recipe_id") or slug(issue_recipe.sections(issue.get("body") or "").get("Recipe id", ""))
        src_text = (tmp / sub["file"]).read_text(encoding="utf-8") if sub["mode"] == "source" else ""
        meta = ast_meta(src_text) if sub.get("language") == "python" else {"title": "", "summary": "", "params": 0}
        if sub["mode"] == "source":
            if not rid:
                rid = slug(meta.get("title") or re.sub(r"^\[Recipe\]\s*", "", issue.get("title") or ""))
            if sub.get("id_problem"):
                extra.append(sub["id_problem"])
            elif rid in BUILTIN_IDS or (ROOT / "community" / "recipes" / rid).exists():
                extra.append(f"The recipe id {rid} is already taken in the gallery; choose another in **Recipe id**.")
        # pictures: real PNGs only, published under a path this run owns
        month = dt.date.today().strftime("%Y-%m")
        import os
        dest = f"media/{month}/issue-{a.issue}-{os.environ.get('GITHUB_RUN_ID', 'local')}"
        files, keys = {}, {}
        if res is not None:
            imgs = res.get("images") if isinstance(res.get("images"), dict) else {}
            want = {"preview": imgs.get("preview"), "sheet": imgs.get("sheet")}
            for s in [s for s in res.get("sets", []) if isinstance(s, dict)][1:3]:
                want[f"set:{s.get('name')}"] = s.get("image")
            for k, name in want.items():
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}\.png", name):
                    continue
                f = rdir / "out" / name
                if png_info(f):
                    files[f"{dest}/{name}"] = f
                    keys[k] = f"{dest}/{name}"
            if "set:defaults" not in keys and "preview" in keys:
                keys["set:defaults"] = keys["preview"]
        urls = {}
        if files and not a.dry_run:
            pub = assets.put(files, f"Pictures for issue #{a.issue}")
            urls = {k: pub[p] for k, p in keys.items()}
        elif files:
            urls = {k: f"https://example.invalid/{p}" for k, p in keys.items()}
        accept_ready = False
        body, verdict = compose(issue, sub, res, urls, a.build_outcome, extra, accept_ready=False)
        if verdict == "valid" and sub["mode"] == "source" and not extra:
            meta_json = {"id": rid, "title": (meta.get("title") or (res.get("recipe") or {}).get("title") or rid)[:80],
                         "summary": (meta.get("summary") or "")[:300], "author": sub["issue"]["author"],
                         "tags": sub["tags"], "kind": "scad" if sub["language"] == "openscad" else "python",
                         "params_count": int(meta.get("params") or len((res.get("recipe") or {}).get("params") or []))}
            bundle = Path(tempfile.mkdtemp(prefix="recipe-bundle-"))
            shutil.copyfile(tmp / sub["file"], bundle / sub["file"])
            (bundle / "meta.json").write_text(json.dumps(meta_json, indent=2) + "\n", encoding="utf-8")
            (bundle / "submission.json").write_text(json.dumps(
                {"issue": a.issue, "sha256": sub["sha256"], "file": sub["file"], "author": sub["issue"]["author"],
                 "run": run_url(), "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, indent=1),
                encoding="utf-8")
            if "preview" in keys:
                shutil.copyfile(files[keys["preview"]], bundle / "preview.png")
                accept_ready = True
            log(f"bundle: {bundle}")
            if accept_ready and not a.dry_run:
                assets.put({f"recipes/issue-{a.issue}/{f.name}": f for f in bundle.iterdir()},
                           f"Validated recipe from issue #{a.issue}")
            body, verdict = compose(issue, sub, res, urls, a.build_outcome, extra, accept_ready=accept_ready)

    if a.dry_run:
        print(body)
        print(f"\nverdict: {verdict}")
        return 0
    gh.upsert_comment(a.issue, MARKER, body)
    for name, (color, desc) in LABELS.items():
        gh.ensure_label(name, color, desc)
    if verdict == "valid":
        gh.add_labels(a.issue, ["recipe:valid"])
        gh.remove_label(a.issue, "recipe:needs-changes")
    elif verdict == "needs-changes":
        gh.add_labels(a.issue, ["recipe:needs-changes"])
        gh.remove_label(a.issue, "recipe:valid")
    summary(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
