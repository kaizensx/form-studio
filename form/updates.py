"""Is there a newer FORM? Reads the latest public GitHub release, at most once a day. Never downloads or installs.

The only network request is a GET of public release metadata:
    https://api.github.com/repos/kaizensx/form-studio/releases/latest
No token, no identifiers, 5 s timeout. Any failure (offline, rate limit, bad JSON) is silent: the result just
says no update is known. The answer is cached in the data folder (`.form-updates.json`) for a day.

Off switches: `[updates] check = false` in studio.toml, or the environment variable FORM_NO_UPDATE_CHECK=1.

Development only: FORM_FAKE_LATEST=10.1.0 pretends that version is the latest release (no network, no cache),
so the update notice and sheet can be seen and screenshotted.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from . import __version__

REPO = "kaizensx/form-studio"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
CACHE = ".form-updates.json"
DAY = 24 * 3600
TIMEOUT = 5.0
GIT_SOURCE = f"git+https://github.com/{REPO}"


# ---- versions ---------------------------------------------------------------

_PRE = {"dev": -4, "a": -3, "alpha": -3, "b": -2, "beta": -2, "rc": -1, "c": -1, "pre": -1, "preview": -1}


def parse(v: str) -> tuple | None:
    """'v10.1.0', '10.1', '10.1.0rc2', '10.1.0-beta.1' → comparable tuple; None when it is not a version.

    A pre-release sorts before its final release: 10.1.0rc1 < 10.1.0 < 10.1.1.
    """
    m = re.fullmatch(r"[vV]?(\d+(?:\.\d+)*)(?:[-_.]?([A-Za-z]+)[-_.]?(\d*))?(?:\+.*)?", (v or "").strip())
    if not m:
        return None
    rel = [int(x) for x in m.group(1).split(".")]
    rel = (rel + [0, 0, 0, 0])[:4]
    if m.group(2):
        tag = m.group(2).lower()
        if tag in ("post", "r", "rev"):
            return (*rel, 1, int(m.group(3) or 0))
        rank = _PRE.get(tag)
        if rank is None:
            return None
        return (*rel, rank, int(m.group(3) or 0))
    return (*rel, 0, 0)


def newer(latest: str, current: str) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


# ---- how this copy was installed -------------------------------------------

def install_kind() -> str:
    """packaged (PyInstaller app) | source (a git checkout) | tool (pip / uv tool install)."""
    if getattr(sys, "frozen", False):
        return "packaged"
    if (Path(__file__).resolve().parents[1] / ".git").exists():
        return "source"
    return "tool"


def upgrade_command(kind: str | None = None) -> str:
    kind = kind or install_kind()
    if kind == "source":
        root = Path(__file__).resolve().parents[1]
        py = ".venv" if Path(sys.prefix).resolve() == (root / ".venv").resolve() else f'"{sys.executable}"'
        return f'cd "{root}" && git pull && uv pip install --python {py} -e ".[app]"'
    if kind == "tool":
        if shutil.which("uv") or not shutil.which("pip"):
            return (f'uv tool install --force --refresh-package form-studio --python 3.12 '
                    f'"form-studio[app] @ {GIT_SOURCE}"')
        return f'pip install --upgrade "form-studio[app] @ {GIT_SOURCE}"'
    return ""


def asset_name() -> str:
    """The release asset built for this machine (names from .github/workflows/app.yml)."""
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if sys.platform == "darwin":
        return f"FORM-macos-{arch}.zip"
    if sys.platform.startswith("win"):
        return "FORM-windows-x64.zip"
    return "FORM-linux-x64.tar.gz"


# ---- the check --------------------------------------------------------------

def enabled(cfg: dict | None) -> bool:
    if os.environ.get("FORM_NO_UPDATE_CHECK", "").strip() not in ("", "0", "false", "no"):
        return False
    return bool(((cfg or {}).get("updates") or {}).get("check", True))


def _fetch() -> dict | None:
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"FORM/{__version__} update-check"})
    from . import net
    with net.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return {"version": str(data["tag_name"]).lstrip("vV"), "name": data.get("name") or data["tag_name"],
            "notes": data.get("body") or "", "url": data.get("html_url") or RELEASES,
            "published": data.get("published_at") or "", "prerelease": bool(data.get("prerelease")),
            "assets": [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": a.get("size", 0)}
                       for a in data.get("assets") or [] if isinstance(a, dict)]}


def _fake(v: str) -> dict:
    return {"version": v.lstrip("vV"), "name": f"Form Studio {v}", "url": RELEASES, "published": "", "prerelease": False,
            "notes": f"## Form Studio {v}\n\nThis is a **fake release** from `FORM_FAKE_LATEST` (development only).\n\n"
                     "- First-run setup inside the app\n- Update notices\n\nNothing was fetched from the network.",
            "assets": [{"name": asset_name(), "url": f"{RELEASES}/download/v{v}/{asset_name()}", "size": 0}],
            "fake": True}


def check(cfg: dict | None = None, force: bool = False, data_dir: str | None = None) -> dict:
    """What is known about updates. Never raises, never takes longer than about TIMEOUT seconds."""
    kind = install_kind()
    out = {"current": __version__, "enabled": enabled(cfg), "available": False, "kind": kind,
           "command": upgrade_command(kind), "releases": RELEASES}
    fake = os.environ.get("FORM_FAKE_LATEST", "").strip()
    if fake:
        out["enabled"] = True
        return _finish(out, _fake(fake), time.time())
    if not out["enabled"]:
        return out
    data = Path(data_dir or ((cfg or {}).get("data") or {}).get("dir") or Path.home() / "FORM")
    cache = data / CACHE
    cached = None
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    now = time.time()
    if isinstance(cached, dict) and not force and now - float(cached.get("checked", 0)) < DAY:
        return _finish(out, cached.get("latest"), cached.get("checked"))
    try:
        latest = _fetch()
    except Exception:                       # offline, DNS, HTTP 403 rate limit, timeout, bad JSON: say nothing
        latest = None
        if isinstance(cached, dict):        # keep what we knew; try again tomorrow
            return _finish(out, cached.get("latest"), cached.get("checked"))
    try:
        data.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked": now, "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return _finish(out, latest, now)


def _finish(out: dict, latest: dict | None, checked) -> dict:
    out["checked"] = checked
    if not isinstance(latest, dict) or not latest.get("version"):
        return out
    out["latest"] = latest["version"]
    out["available"] = newer(latest["version"], out["current"])
    if out["available"]:
        want = asset_name()
        asset = next((a for a in latest.get("assets") or [] if a.get("name") == want), None)
        out["release"] = {"name": latest.get("name"), "notes": latest.get("notes", ""), "url": latest.get("url") or RELEASES,
                          "published": latest.get("published", ""), "fake": bool(latest.get("fake"))}
        out["download"] = ({"name": asset["name"], "url": asset["url"]} if asset
                           else {"name": "", "url": latest.get("url") or RELEASES})
    return out


def install_now(cfg: dict, info: dict | None = None, echo=print) -> int:
    """Run the upgrade command and print its output. 0 when it finished; the new code runs after a restart."""
    import time as _t

    from . import installer
    info = info or check(cfg)
    if info["kind"] == "packaged":
        echo("This copy of Form Studio is updated by downloading the new app: " + (info.get("download") or {}).get("url", RELEASES))
        return 2
    try:
        job = installer.Installer(cfg).update(info["command"])
    except installer.InstallError as e:
        echo(e.public()["message"])
        return 2
    seen = 0
    while True:
        p = job.public(seen)
        for line in p["log"]:
            echo(("$ " if line["kind"] == "cmd" else "  ") + line["text"])
        seen = p["next"]
        if p["state"] != "running":
            break
        _t.sleep(0.3)
    echo("Upgraded. Restart Form Studio to use the new version." if p["state"] == "done" else "The upgrade did not finish: " + p["steps"][0]["message"])
    return 0 if p["state"] == "done" else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="form update", description="Is there a newer Form Studio? (checks only, unless --install)")
    ap.add_argument("--check", action="store_true", help="ask GitHub now and print JSON")
    ap.add_argument("--install", action="store_true", help="run the upgrade command now (pip / uv / source installs), "
                    "the same job the app's Update now button runs")
    a = ap.parse_args(argv)
    from . import config
    cfg = config.load()
    info = check(cfg, force=True)
    if a.install:
        return install_now(cfg, info)
    if a.check:
        print(json.dumps(info, indent=1, ensure_ascii=False))
        return 0
    if not info.get("enabled"):
        print("Update checks are off ([updates] check = false or FORM_NO_UPDATE_CHECK=1).")
    elif info.get("available"):
        print(f"Form Studio {info['latest']} is available (you have {info['current']}).\n")
        if info["kind"] == "packaged":
            print(f"Download: {info['download']['url']}")
        else:
            print(f"To upgrade, run:\n\n    {info['command']}\n")
        print(f"Release notes: {info['release']['url']}")
    elif info.get("latest"):
        print(f"Form Studio {info['current']} is up to date (latest release: {info['latest']}).")
    else:
        print(f"Form Studio {info['current']}. Could not reach GitHub to check; nothing changed.")
    return 0
