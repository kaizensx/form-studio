"""Reply to a Show and tell post that carries a design: a turntable GIF, the four views, the checks and the slice.

    python scripts/ci/showcase.py --discussion-id NODE_ID --number 12 --result DIR [--dry-run]

Runs in the privileged job of show-and-tell.yml after the design was built in the sandbox. Like recipe_report.py it
reads DIR as untrusted data (JSON limits, real PNG/GIF files only, escaped text) and takes the discussion from the
workflow's event, not from DIR. One reply per discussion, edited in place when the post is edited.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SIGNATURE, GitHub, gif_info, load_json, log, md, num, png_info, run_url,  # noqa: E402
                    summary)
from recipe_report import checks_table, fmt_time  # noqa: E402

MARKER = "form-studio:showcase"


def compose(res: dict, urls: dict) -> str:
    recipe = res.get("recipe") if isinstance(res.get("recipe"), dict) else {}
    sets = [s for s in res.get("sets", []) if isinstance(s, dict)]
    d0 = sets[0] if sets else {}
    lines = [f"### {md(recipe.get('title') or 'Your design', 80)}, built by Form Studio's automation", ""]
    if urls.get("turntable"):
        lines += [f"![Turntable]({urls['turntable']})", ""]
    elif urls.get("preview"):
        lines += [f"![Preview]({urls['preview']})", ""]
    if d0.get("state") != "built":
        lines += ["It did not build here: " + md((d0.get("error") or {}).get("message"), 300), ""]
    else:
        ro = d0.get("rollup") or {}
        facts = [" × ".join(num(x) for x in d0.get("bbox_mm", [])[:3]) + " mm" if isinstance(d0.get("bbox_mm"), list) else "",
                 num(d0.get("volume_mm3"), "{:,.0f} mm³"),
                 f"{num(ro.get('PASS'), '{:.0f}')} checks pass, {num(ro.get('WARN'), '{:.0f}')} warn, {num(ro.get('FAIL'), '{:.0f}')} fail"]
        sl = d0.get("slice") if isinstance(d0.get("slice"), dict) else {}
        if sl.get("ok"):
            facts.append(f"{fmt_time(sl.get('time_s'))} and {num(sl.get('filament_g'), '{:.1f} g')} in "
                         f"{md(sl.get('slicer'), 30)} {md(sl.get('slicer_version'), 20)} (simulated)")
        lines += [" · ".join(f for f in facts if f), ""]
        if d0.get("checks"):
            lines += ["<details><summary>Checks</summary>", ""] + checks_table(d0["checks"]) + ["", "</details>", ""]
    if urls.get("sheet"):
        lines += ["<details><summary>Four views</summary>", "", f"![Four views]({urls['sheet']})", "", "</details>", ""]
    lines.append(f"<sub>{SIGNATURE} · rebuilt from the attached file in the CAD kernel · [workflow run]({run_url()}) · "
                 f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')}</sub>")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--discussion-id", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = load_json(Path(a.result) / "out" / "result.json")
    except (ValueError, OSError) as e:
        log(f"no result: {e}")
        return 0
    out = Path(a.result) / "out"
    imgs = res.get("images") if isinstance(res.get("images"), dict) else {}
    dest = f"media/{dt.date.today():%Y-%m}/discussion-{a.number}-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    files, keys = {}, {}
    for k in ("turntable", "preview", "sheet"):
        name = imgs.get(k)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}\.(png|gif)", name):
            continue
        f = out / name
        if (name.endswith(".png") and png_info(f)) or (name.endswith(".gif") and gif_info(f)):
            files[f"{dest}/{name}"] = f
            keys[k] = f"{dest}/{name}"
    urls = {}
    if files and not a.dry_run:
        import assets
        pub = assets.put(files, f"Pictures for discussion #{a.number}")
        urls = {k: pub[p] for k, p in keys.items()}
    elif files:
        urls = {k: f"https://example.invalid/{p}" for k, p in keys.items()}
    body = compose(res, urls) + f"\n\n<!-- {MARKER} -->"
    if a.dry_run:
        print(body)
        return 0
    gh = GitHub()
    q = """query($id: ID!) { node(id: $id) { ... on Discussion { comments(first: 100) { nodes { id body author { login } } } } } }"""
    nodes = (((gh.graphql(q, {"id": a.discussion_id}).get("node") or {}).get("comments") or {}).get("nodes")) or []
    mine = next((c for c in nodes if f"<!-- {MARKER} -->" in (c.get("body") or "")
                 and ((c.get("author") or {}).get("login") or "").startswith("github-actions")), None)
    if mine:
        gh.graphql("mutation($id: ID!, $body: String!) { updateDiscussionComment(input: {commentId: $id, body: $body}) { comment { id } } }",
                   {"id": mine["id"], "body": body})
    else:
        gh.graphql("mutation($id: ID!, $body: String!) { addDiscussionComment(input: {discussionId: $id, body: $body}) { comment { id } } }",
                   {"id": a.discussion_id, "body": body})
    summary(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
