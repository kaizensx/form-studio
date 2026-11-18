"""Open a pull request to `dev` that adds a checked community recipe, when a maintainer labels its issue recipe:accept.

    python scripts/ci/recipe_accept.py --issue 42 --sender LOGIN --repo-dir . [--base dev] [--dry-run]

Preconditions, each checked here:
- the person who added the label has write, maintain or admin permission;
- the issue carries recipe:valid, and the bundle stored by the recipe check is on the ci-assets branch;
- the recipe in the issue today has the same SHA-256 as the one that was checked (an edit after the check needs a new
  check first);
- the recipe id is not already in community/recipes on the base branch, and no pull request for it is open.

The commit is made by the automation and credits the submitter with a Co-authored-by trailer; meta.json names them as
author. No submitted code runs in this job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402
import issue_recipe  # noqa: E402
from common import BOT_EMAIL, BOT_NAME, SIGNATURE, GitHub, log, md, run_url  # noqa: E402

MARKER = "form-studio:recipe-accept"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}[a-z0-9]$")


def fail(gh: GitHub, issue: int, why: str, dry: bool) -> int:
    body = f"### Not added to the gallery yet\n\n{why}\n\n<sub>{SIGNATURE} · [workflow run]({run_url()})</sub>"
    if dry:
        print(body)
    else:
        gh.upsert_comment(issue, MARKER, body)
        gh.remove_label(issue, "recipe:accept")
    log(why)
    return 1


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL,
           "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, text=True, capture_output=True).stdout.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--sender", required=True)
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--base", default="dev")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bundle-dir", help="read the bundle from this folder instead of ci-assets (tests)")
    ap.add_argument("--event", help="read the issue from this event file instead of the API (tests)")
    a = ap.parse_args(argv)
    gh = GitHub(dry_run=a.dry_run)
    repo = Path(a.repo_dir).resolve()

    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}(\[bot\])?", a.sender):
        return 2
    if not a.dry_run and gh.permission(a.sender) not in ("admin", "maintain", "write"):
        return fail(gh, a.issue, f"Only maintainers can accept a recipe; {md(a.sender, 40)} does not have write access.", a.dry_run)
    issue = json.loads(Path(a.event).read_text(encoding="utf-8"))["issue"] if a.event else gh.issue(a.issue)
    labels = {lb.get("name") for lb in issue.get("labels") or []}
    if "recipe:valid" not in labels:
        return fail(gh, a.issue, "The issue does not have a passing recipe check (`recipe:valid`). Edit the issue to run "
                    "the check, then add `recipe:accept` again.", a.dry_run)

    # the bundle the recipe check stored
    bdir = Path(a.bundle_dir) if a.bundle_dir else Path(tempfile.mkdtemp(prefix="bundle-"))
    if not a.bundle_dir:
        for name in ("submission.json", "meta.json", "preview.png", "recipe.py", "recipe.scad"):
            data = assets.get(f"recipes/issue-{a.issue}/{name}")
            if data is not None:
                (bdir / name).write_bytes(data)
    try:
        subm = json.loads((bdir / "submission.json").read_text(encoding="utf-8"))
        meta = json.loads((bdir / "meta.json").read_text(encoding="utf-8"))
        src_file = bdir / subm["file"]
        assert src_file.name in ("recipe.py", "recipe.scad") and src_file.exists() and (bdir / "preview.png").exists()
    except Exception:
        return fail(gh, a.issue, "The checked recipe was not found. Edit the issue to run the check again.", a.dry_run)

    # the issue today must hold exactly what was checked
    now = issue_recipe.extract(issue, Path(tempfile.mkdtemp(prefix="now-")), allow_download=True)
    stored_sha = hashlib.sha256(src_file.read_bytes()).hexdigest()
    if not now["found"] or now["sha256"] != subm.get("sha256") or stored_sha != subm.get("sha256"):
        return fail(gh, a.issue, "The recipe in the issue changed after it was checked. Wait for the new check to pass, "
                    "then add `recipe:accept` again.", a.dry_run)
    rid = meta.get("id", "")
    if not ID_RE.match(rid):
        return fail(gh, a.issue, "The recipe id is not valid.", a.dry_run)
    if (repo / "community" / "recipes" / rid).exists():
        return fail(gh, a.issue, f"`community/recipes/{rid}` already exists on `{a.base}`. Choose another **Recipe id**.", a.dry_run)
    author = issue.get("user") or {}
    login, uid = author.get("login") or meta.get("author") or "", author.get("id")
    meta["author"] = login

    branch = f"recipes/issue-{a.issue}-{rid}"
    title = f"Community recipe: {meta.get('title') or rid}"[:120]
    if not a.dry_run:
        open_prs = gh.request("GET", gh.r(f"/pulls?state=open&head={gh.repo.split('/')[0]}:{branch}"))
        if open_prs:
            return fail(gh, a.issue, f"A pull request for this recipe is already open: #{open_prs[0]['number']}.", a.dry_run)

    dest = repo / "community" / "recipes" / rid
    dest.mkdir(parents=True)
    (dest / src_file.name).write_bytes(src_file.read_bytes())
    (dest / "preview.png").write_bytes((bdir / "preview.png").read_bytes())
    (dest / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    trailer = f"\n\nCo-authored-by: {login} <{uid}+{login}@users.noreply.github.com>" if login and uid else ""
    msg = f"Add community recipe {rid}\n\nSubmitted in #{a.issue} and checked by the recipe pipeline.{trailer}"
    git(repo, "checkout", "-q", "-B", branch)
    git(repo, "add", f"community/recipes/{rid}")
    git(repo, "commit", "-q", "-m", msg)
    pr_body = (f"Adds `community/recipes/{rid}/` ({md(meta.get('title'), 80)}), submitted by @{login} in #{a.issue}.\n\n"
               f"- `{src_file.name}`: the file from the issue, SHA-256 `{subm['sha256'][:16]}`, the same one the recipe check "
               f"built ({subm.get('run', '')})\n- `meta.json`: id, title and summary from the recipe, tags from the issue\n"
               f"- `preview.png`: rendered by the recipe check at the default values\n\n"
               f"Accepted by @{a.sender}. Closes #{a.issue}.\n\n<sub>{SIGNATURE}</sub>")
    if a.dry_run:
        print(git(repo, "show", "--stat", "HEAD"))
        print(pr_body)
        return 0
    git(repo, "push", "-q", "--force", "origin", f"HEAD:refs/heads/{branch}")
    pr = gh.request("POST", gh.r("/pulls"), {"title": title, "head": branch, "base": a.base, "body": pr_body,
                                             "maintainer_can_modify": True})
    gh.ensure_label("area:recipes", "0e8a16", "Recipes")
    gh.add_labels(pr["number"], ["area:recipes"])
    gh.upsert_comment(a.issue, MARKER, f"### Added to the gallery\n\nPull request #{pr['number']} adds this recipe to "
                      f"`community/recipes/{rid}/`, credited to @{login}. It appears in the gallery and in the app with the "
                      f"next release.\n\n<sub>{SIGNATURE}</sub>")
    print(pr["html_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
