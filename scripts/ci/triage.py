"""Pull request triage from the event payload alone (no code from the pull request is read or run).

    python scripts/ci/triage.py --event "$GITHUB_EVENT_PATH" [--dry-run]

- size/XS … size/XL from lines added plus removed (XS ≤ 10, S ≤ 60, M ≤ 250, L ≤ 800, XL above);
- a type: label from the title when the pull request has none ("Fix …" → type:bug, "Docs …" → type:docs,
  "Add …"/"New …" → type:feature, "Faster …"/"Speed up …" → type:performance);
- assigns the author when they are a member or collaborator and nobody is assigned.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GitHub, log  # noqa: E402

SIZES = [(10, "size/XS"), (60, "size/S"), (250, "size/M"), (800, "size/L"), (10**9, "size/XL")]
SIZE_COLORS = {"size/XS": "c2e0c6", "size/S": "a2d9b1", "size/M": "f9d0a0", "size/L": "f4a582", "size/XL": "d6604d"}
TITLE_TYPES = [(r"^(fix|fixes|fixed|bug)\b", "type:bug"), (r"^(docs?|documentation)\b", "type:docs"),
               (r"^(add|adds|new|support)\b", "type:feature"), (r"^(faster|speed up|perf|performance)\b", "type:performance")]


def plan(pr: dict) -> dict:
    changed = int(pr.get("additions") or 0) + int(pr.get("deletions") or 0)
    size = next(lbl for limit, lbl in SIZES if changed <= limit)
    labels = {lb.get("name") for lb in pr.get("labels") or []}
    add, remove = [], [lb for lb in labels if lb and lb.startswith("size/") and lb != size]
    if size not in labels:
        add.append(size)
    title = re.sub(r"^\W+", "", (pr.get("title") or "").strip().lower())
    m = re.match(r"^(\w+)(\([^)]*\))?!?:\s*(.*)$", title)          # "fix(slicer): …" style prefixes
    if m:
        title = {"fix": "fix ", "docs": "docs ", "doc": "docs ", "perf": "faster ", "feat": "add "}.get(m.group(1), "") + m.group(3)
    if not any(lb.startswith("type:") for lb in labels if lb):
        for pat, lbl in TITLE_TYPES:
            if re.match(pat, title):
                add.append(lbl)
                break
    assign = []
    if not pr.get("assignees") and pr.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR"):
        login = (pr.get("user") or {}).get("login")
        if login and not login.endswith("[bot]"):
            assign.append(login)
    return {"changed": changed, "add": add, "remove": remove, "assign": assign}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    ev = json.loads(Path(a.event).read_text(encoding="utf-8"))
    pr = ev.get("pull_request") or {}
    if not pr:
        return 0
    p = plan(pr)
    print(json.dumps(p))
    if a.dry_run:
        return 0
    gh = GitHub()
    n = pr["number"]
    for lbl in p["add"]:
        if lbl.startswith("size/"):
            gh.ensure_label(lbl, SIZE_COLORS[lbl], "Lines changed in this pull request")
    gh.add_labels(n, p["add"])
    for lbl in p["remove"]:
        gh.remove_label(n, lbl)
    if p["assign"]:
        gh.request("POST", gh.r(f"/issues/{n}/assignees"), {"assignees": p["assign"]})
    log("triaged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
