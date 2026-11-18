"""Release notes.

    python scripts/ci/release_notes.py changelog --tag v1.1.0 [--changelog CHANGELOG.md] [--out notes.md]
    python scripts/ci/release_notes.py draft [--base dev] [--dry-run]

`changelog` writes the notes for a version tag from its CHANGELOG.md section ("## 1.0.0"). A pre-release tag such as
v1.1.0-preview.2 uses the section of 1.1.0, or "## Unreleased" when that does not exist yet. The notes end with how to
verify the download (SHA256SUMS and the build attestations).

`draft` keeps one draft release named "Unreleased" up to date with the pull requests merged into dev since the latest
published release, grouped by their type: label. It never publishes anything; maintainers turn it into the CHANGELOG.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, SERVER, GitHub, log  # noqa: E402

GROUPS = [("type:feature", "New"), ("enhancement", "New"), ("type:bug", "Fixed"), ("bug", "Fixed"),
          ("type:performance", "Faster"), ("type:docs", "Documentation"), ("documentation", "Documentation")]
DRAFT_NAME = "Unreleased"
DRAFT_TAG = "unreleased"


def section(text: str, version: str) -> str | None:
    """The body under '## <version>' up to the next '## ' heading."""
    m = re.search(rf"^##\s+v?{re.escape(version)}\s*(?:\(.*\))?\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r"^##\s", rest, re.M)
    return rest[: n.start() if n else len(rest)].strip()


def notes_for(tag: str, changelog: str) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    base = version.split("-", 1)[0]
    body = section(changelog, version) or section(changelog, base)
    pre = version != base
    if body is None and pre:
        body = section(changelog, "Unreleased")
    if body is None:
        body = f"See the [changelog]({SERVER}/{REPO}/blob/main/CHANGELOG.md)."
    head = "A preview from the `dev` branch, for the Preview update channel.\n\n" if pre else ""
    verify = (
        "\n\n### Verify the download\n\n"
        "`SHA256SUMS` lists the SHA-256 of every file attached here. Each app bundle also carries a signed build "
        "provenance attestation from the GitHub Actions run that built it:\n\n"
        "```bash\n"
        f"gh attestation verify FORM-macos-arm64.zip --repo {REPO}\n"
        "```\n\n"
        "`form-studio-sbom.spdx.json` is the software bill of materials (SPDX) of this release's source tree."
    )
    return head + body + verify


def pr_line(pr: dict) -> str:
    title = re.sub(r"\s+", " ", pr.get("title") or "").strip()
    user = (pr.get("user") or {}).get("login", "")
    by = f" by @{user}" if user and not user.endswith("[bot]") else ""
    return f"- {title} (#{pr['number']}){by}"


def draft_body(prs: list[dict], since: str | None) -> str:
    groups: dict[str, list[str]] = {}
    for pr in prs:
        names = {lb.get("name") for lb in pr.get("labels") or []}
        group = next((g for lab, g in GROUPS if lab in names), "Other changes")
        groups.setdefault(group, []).append(pr_line(pr))
    order = ["New", "Fixed", "Faster", "Documentation", "Other changes"]
    out = [f"Pull requests merged into `dev` since {since or 'the start'}. Kept up to date by Form Studio's "
           "automation; the CHANGELOG is written from it at release time.", ""]
    for g in order:
        if groups.get(g):
            out += [f"### {g}", ""] + groups[g] + [""]
    if not prs:
        out.append("Nothing merged yet.")
    return "\n".join(out).strip() + "\n"


def cmd_draft(a) -> int:
    gh = GitHub(dry_run=a.dry_run)
    releases = gh.paginate(gh.r("/releases"), 200)
    published = [r for r in releases if not r.get("draft") and r.get("published_at")]
    since_tag = published[0]["tag_name"] if published else None
    since_date = published[0]["published_at"] if published else "1970-01-01T00:00:00Z"
    q = f"repo:{gh.repo} is:pr is:merged base:{a.base} merged:>{since_date}"
    import urllib.parse
    prs = []
    for page in range(1, 6):
        res = gh.request("GET", f"/search/issues?q={urllib.parse.quote(q)}&per_page=100&page={page}&sort=created&order=asc")
        items = (res or {}).get("items") or []
        prs += items
        if len(items) < 100:
            break
    body = draft_body(prs, since_tag)
    existing = next((r for r in releases if r.get("draft") and r.get("name") == DRAFT_NAME), None)
    if a.dry_run:
        print(body)
        return 0
    if existing:
        gh.request("PATCH", gh.r(f"/releases/{existing['id']}"), {"body": body})
    else:
        gh.request("POST", gh.r("/releases"), {"tag_name": DRAFT_TAG, "target_commitish": a.base, "name": DRAFT_NAME,
                                               "body": body, "draft": True})
    log(f"draft release updated: {len(prs)} pull requests since {since_tag}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("changelog")
    c.add_argument("--tag", required=True)
    c.add_argument("--changelog", default="CHANGELOG.md")
    c.add_argument("--out")
    d = sub.add_parser("draft")
    d.add_argument("--base", default="dev")
    d.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "changelog":
        text = notes_for(a.tag, Path(a.changelog).read_text(encoding="utf-8"))
        if a.out:
            Path(a.out).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    return cmd_draft(a)


if __name__ == "__main__":
    sys.exit(main())
