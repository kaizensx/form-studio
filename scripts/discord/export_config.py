"""Write scripts/discord/worker/config.json from server.py, so the worker and the server setup share one source.

    python scripts/discord/export_config.py          # tests/test_discord_bot.py fails when the file is stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server as S  # noqa: E402

OUT = HERE / "worker" / "config.json"


def config() -> dict:
    return {
        "site": S.SITE, "docs": S.DOCS, "repo": S.REPO, "icon": S.ICON, "invite": S.INVITE,
        "names": S.NAMES,
        "roles": S.R,
        "role_emoji": S.ROLE_EMOJI,
        "staff": ["Maintainer", "Moderator"],
        "levels": [[lv, name] for lv, name in S.LEVELS],
        "picker": [[k, p, names] for k, p, names in S.ROLE_PICKER],
        "guides": [[title, tag, summary, S.GUIDE_URL + slug + ".md"] for slug, title, tag, _, summary in S.GUIDES],
        "help_guides": S.HELP_GUIDES,
        "docs_pages": [[name, url] for name, url in S.DOC_PAGES],
        "xp": S.XP,
        "challenges": S.CHALLENGES,
    }


def render() -> str:
    return json.dumps(config(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(OUT.relative_to(HERE.parents[1]))
