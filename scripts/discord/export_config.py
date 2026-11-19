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
        "levels": [[lv, name] for lv, name in S.LEVELS],
        "picker": [[k, p, names] for k, p, names in S.ROLE_PICKER],
        "guides": [[t, tag, links] for t, tag, _, _, links in S.GUIDES],
        "help_guides": S.HELP_GUIDES,
        "xp": S.XP,
        "challenges": S.CHALLENGES,
        "colors": {"datum": 0xB9E8D7, "blueprint": 0x86A8FF, "violet": 0xC7B2FF, "amber": 0xE9B860,
                   "signal": 0xFF6F51, "pass": 0x86D9AD, "plate": 0x0E1113},
    }


def render() -> str:
    return json.dumps(config(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(OUT.relative_to(HERE.parents[1]))
