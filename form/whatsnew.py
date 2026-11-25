"""What's New: the running version's section of the bundled CHANGELOG.md, shown once after each update.

The notes come from the CHANGELOG.md shipped with this copy of Form Studio (next to this file in the packaged app,
at the top of a checkout), so they are offline and describe exactly the version that is running. A section starts
with a line ``## <version>`` and ends at the next ``## `` heading. A section with a ``### Details`` heading shows only
what is above it: the short summary for people, not every change (the release notes on GitHub do the same).

When is it shown? ``<data>/.form-whatsnew.json`` remembers the last version whose notes were shown. A different
running version shows its notes once. A new data folder (first run) is not shown notes about changes it never saw;
its version is recorded silently. From Help (About), the notes can be opened at any time.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

FILE = ".form-whatsnew.json"


def changelog_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for p in (here / "CHANGELOG.md", here.parent / "CHANGELOG.md"):
        if p.is_file():
            return p
    return None


def sections(text: str) -> dict[str, str]:
    """version → its Markdown (without the ## heading), in file order."""
    out: dict[str, str] = {}
    cur, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+v?([0-9][0-9A-Za-z.\-+]*|Unreleased)\s*(?:[-—(].*)?$", line)
        if m or (line.startswith("## ") and cur is not None):
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = (m.group(1) if m else None), []
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def summary(md: str) -> str:
    """A section's summary: the text above its "### Details" heading (all of it when it has none)."""
    m = re.search(r"^###\s+Details\s*$", md, re.M)
    return md[: m.start()].rstrip() if m else md


def highlights(md: str, limit: int = 6) -> list[dict]:
    """The section's bold-led bullets ("- **Title.** Detail") as {title, text}, for the modal's list."""
    out = []
    group = ""
    for line in md.splitlines():
        h = re.match(r"^###\s+(.*)", line)
        if h:
            group = h.group(1).strip()
            continue
        m = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*(.*)$", line)
        if m:
            title = m.group(1).strip().rstrip(":")
            text = m.group(2).strip()
            text = text[:1].upper() + text[1:] if text[:1].islower() else text
            out.append({"title": title.rstrip("."), "text": text, "group": group})
    return out[:limit]


def notes(version: str, path: Path | None = None) -> dict:
    from . import __version__
    version = version or __version__
    p = path or changelog_path()
    if not p:
        return {"version": version, "found": False, "markdown": "", "highlights": []}
    sec = sections(p.read_text(encoding="utf-8"))
    md = sec.get(version) or sec.get(version.lstrip("vV")) or ""
    if not md and re.search(r"-(dev|preview)", version):   # a build of dev or a preview: what it has that the
        md = sec.get("Unreleased", "")                     # last release does not
    md = summary(md)
    return {"version": version, "found": bool(md), "markdown": md, "highlights": highlights(md),
            "versions": list(sec)[:12]}


def _read(root) -> dict:
    try:
        r = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(root, version: str) -> None:
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        (Path(root) / FILE).write_text(json.dumps({"seen": version, "ts": time.time()}), encoding="utf-8")
    except OSError:
        pass


def due(root, version: str | None = None, first_run: bool = False, setup_version: str | None = None,
        path: Path | None = None) -> dict:
    """Whether to show the notes now: {"show": bool, ...notes}. Does not mark them seen (see seen())."""
    from . import __version__
    version = version or __version__
    n = notes(version, path)
    rec = _read(root)
    last = rec.get("seen")
    from .updates import newer
    if last is None:
        # no record yet: a brand-new data folder (or one set up on this very version) has nothing to catch up on;
        # a folder set up with an older release has
        if first_run or not newer(version, str(setup_version or "")):
            _write(root, version)
            return {**n, "show": False, "last": None}
        last = setup_version
    return {**n, "show": bool(n["found"]) and last != version, "last": last}


def seen(root, version: str | None = None) -> dict:
    from . import __version__
    _write(root, version or __version__)
    return {"seen": version or __version__}


def for_cfg(cfg: dict) -> dict:
    from . import setup_app
    root = cfg["data"]["dir"]
    try:
        sv = json.loads((Path(root) / setup_app.MARKER).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        sv = None
    return due(root, first_run=setup_app.first_run(cfg), setup_version=sv)
