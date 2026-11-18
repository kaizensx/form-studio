"""The `ci-assets` branch: an orphan branch only the automation writes. It holds the pictures embedded in bot comments
(GitHub comments cannot show images from workflow artifacts), validated community-recipe bundles waiting for a
maintainer, the compatibility matrix, benchmark history and the interface screenshot baselines.

    python scripts/ci/assets.py put --src DIR --dest media/2026-11/pr-12-abc1234 [--message M]
    python scripts/ci/assets.py get --path compat/latest.json --out FILE        # read a file (no token needed)
    python scripts/ci/assets.py prune --keep-days 120                           # drop old media, squash history

Layout:
    media/<YYYY-MM>/<what>/...        images for comments; pruned after --keep-days
    recipes/issue-<n>/                recipe.py|recipe.scad, meta.json, preview.png, result.json (submission pipeline)
    compat/latest.json badge.json history.json
    bench/history.json
    ui/baseline/<shot>.png

Writes need GITHUB_TOKEN with contents: write. The token is passed to git as an HTTP header, never in a URL.
Pushing retries on a race with another job, rebasing onto the newer tip.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ASSETS_BRANCH, BOT_EMAIL, BOT_NAME, REPO, SERVER, log, raw_url  # noqa: E402

KEEP = ("recipes/", "compat/", "bench/", "ui/")


def _git(cwd: Path, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL,
           "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    pre = []
    if token:
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        pre = ["-c", f"http.{SERVER}/.extraheader=AUTHORIZATION: basic {auth}"]
    return subprocess.run(["git", *pre, *args], cwd=cwd, env=env, check=check, text=True,
                          capture_output=capture)


def remote() -> str:
    return os.environ.get("CI_ASSETS_REMOTE") or f"{SERVER}/{REPO}.git"


def checkout(depth: int = 1) -> Path:
    """A working copy of ci-assets in a temp folder; a fresh orphan when the branch does not exist yet."""
    d = Path(tempfile.mkdtemp(prefix="ci-assets-"))
    _git(d, "init", "-q")
    _git(d, "remote", "add", "origin", remote())
    r = _git(d, "fetch", "-q", f"--depth={depth}", "origin", ASSETS_BRANCH, check=False, capture=True)
    if r.returncode == 0:
        _git(d, "checkout", "-q", "-B", ASSETS_BRANCH, "FETCH_HEAD")
    else:
        _git(d, "checkout", "-q", "--orphan", ASSETS_BRANCH)
        (d / "README.md").write_text(
            "# ci-assets\n\nWritten only by Form Studio's GitHub automation: pictures for bot comments, validated "
            "community-recipe submissions, the slicer compatibility matrix, benchmark history and interface "
            "baselines. Old media is pruned and the history squashed from time to time.\n", encoding="utf-8")
        _git(d, "add", "README.md")
        _git(d, "commit", "-q", "-m", "Start the ci-assets branch")
    return d


def push(d: Path, message: str, apply) -> None:
    """Commit what apply(d) wrote and push; on a race, refetch, re-apply and try again."""
    for attempt in range(6):
        apply(d)
        _git(d, "add", "-A")
        if _git(d, "diff", "--cached", "--quiet", check=False).returncode == 0:
            log("ci-assets: nothing changed")
            return
        _git(d, "commit", "-q", "-m", message)
        if _git(d, "push", "-q", "origin", f"HEAD:{ASSETS_BRANCH}", check=False).returncode == 0:
            log(f"ci-assets: pushed ({message})")
            return
        log(f"ci-assets: push raced, retrying ({attempt + 1})")
        _git(d, "fetch", "-q", "--depth=1", "origin", ASSETS_BRANCH)
        _git(d, "reset", "-q", "--hard", "FETCH_HEAD")
    raise SystemExit("ci-assets: could not push after 6 attempts")


def put(files: dict[str, Path], message: str, replace: str | None = None) -> dict[str, str]:
    """files: {path in the branch: local file}. Returns {path: raw URL}. replace: a folder emptied first."""
    for k in files:
        if k.startswith("/") or ".." in Path(k).parts:
            raise ValueError(f"unsafe path {k}")
    d = checkout()

    def apply(root: Path):
        if replace and (root / replace).is_dir() and ".." not in Path(replace).parts and replace.strip("/"):
            shutil.rmtree(root / replace)
        for k, src in files.items():
            dest = root / k
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    try:
        push(d, message, apply)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return {k: raw_url(k) for k in files}


def get(path: str) -> bytes | None:
    """A file from ci-assets, or None. Uses git, so it also works for a private fork."""
    d = Path(tempfile.mkdtemp(prefix="ci-assets-r-"))
    try:
        _git(d, "init", "-q")
        r = _git(d, "fetch", "-q", "--depth=1", remote(), ASSETS_BRANCH, check=False, capture=True)
        if r.returncode != 0:
            return None
        r = subprocess.run(["git", "show", f"FETCH_HEAD:{path}"], cwd=d, capture_output=True)
        return r.stdout if r.returncode == 0 else None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def prune(keep_days: int, dry_run: bool = False) -> list[str]:
    """Remove media months older than keep_days, then replace the history with one commit."""
    d = checkout()
    try:
        cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).strftime("%Y-%m")
        gone = []
        media = d / "media"
        if media.is_dir():
            for month in sorted(media.iterdir()):
                if month.is_dir() and month.name < cutoff:
                    gone.append(f"media/{month.name}")
                    if not dry_run:
                        shutil.rmtree(month)
        if dry_run:
            return gone
        _git(d, "checkout", "-q", "--orphan", "squashed")
        _git(d, "add", "-A")
        _git(d, "commit", "-q", "-m", f"ci-assets as of {dt.date.today().isoformat()}")
        _git(d, "push", "-q", "--force", "origin", f"HEAD:{ASSETS_BRANCH}")
        return gone
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put")
    p.add_argument("--src", required=True, help="a folder; its files keep their relative paths under --dest")
    p.add_argument("--dest", required=True)
    p.add_argument("--message", default="Update assets")
    p.add_argument("--replace", action="store_true", help="remove what is under --dest first")
    p.add_argument("--exclude", default="", help="skip files whose name starts with this")
    g = sub.add_parser("get")
    g.add_argument("--path", required=True)
    g.add_argument("--out", required=True)
    pr = sub.add_parser("prune")
    pr.add_argument("--keep-days", type=int, default=120)
    pr.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "put":
        src = Path(a.src)
        files = {f"{a.dest.strip('/')}/{f.relative_to(src).as_posix()}": f for f in sorted(src.rglob("*"))
                 if f.is_file() and not (a.exclude and f.name.startswith(a.exclude))}
        for k, url in put(files, a.message, a.dest.strip("/") if a.replace else None).items():
            print(url)
    elif a.cmd == "get":
        data = get(a.path)
        if data is None:
            log(f"ci-assets: {a.path} not found")
            return 1
        Path(a.out).write_bytes(data)
    else:
        for x in prune(a.keep_days, a.dry_run):
            print("removed", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
