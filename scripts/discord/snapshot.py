"""Write the Discord server's live configuration to a JSON file, so a change can be compared or rolled back.

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/snapshot.py OUT.json

It records the guild settings, roles (with permissions), categories and channels (with overwrites, topics and
forum tags), onboarding, the welcome screen, AutoMod rules, scheduled events, invites, and the bot's own posts
(ids and embed footers, not their text). It reads only; nothing on the server changes.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402


def safe(path):
    try:
        return d.call("GET", path)
    except d.DiscordError as e:
        return {"error": str(e)[:300]}


def main():
    g = os.environ.get("DISCORD_GUILD_ID", "").strip()
    if not g:
        raise SystemExit("DISCORD_GUILD_ID is not set")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "discord-snapshot.json")
    me = d.call("GET", "/users/@me")
    channels = d.call("GET", f"/guilds/{g}/channels")
    posts = {}
    for c in channels:
        if c["type"] in (0, 5):
            msgs = safe(f"/channels/{c['id']}/messages?limit=50")
            if isinstance(msgs, list):
                posts[c["name"]] = [{"id": m["id"], "author": m["author"]["username"], "bot": m["author"]["id"] == me["id"],
                                     "pinned": m.get("pinned"), "at": m["timestamp"],
                                     "footers": [(e.get("footer") or {}).get("text", "") for e in m.get("embeds", [])],
                                     "titles": [e.get("title", "") for e in m.get("embeds", [])]}
                                    for m in msgs]
    snap = {
        "taken": datetime.now(timezone.utc).isoformat(),
        "bot": {"id": me["id"], "username": me["username"]},
        "guild": safe(f"/guilds/{g}?with_counts=true"),
        "bot_member": safe(f"/guilds/{g}/members/{me['id']}"),
        "roles": safe(f"/guilds/{g}/roles"),
        "channels": channels,
        "active_threads": safe(f"/guilds/{g}/threads/active"),
        "onboarding": safe(f"/guilds/{g}/onboarding"),
        "welcome_screen": safe(f"/guilds/{g}/welcome-screen"),
        "automod": safe(f"/guilds/{g}/auto-moderation/rules"),
        "events": safe(f"/guilds/{g}/scheduled-events"),
        "invites": safe(f"/guilds/{g}/invites"),
        "emojis": safe(f"/guilds/{g}/emojis"),
        "stickers": safe(f"/guilds/{g}/stickers"),
        "webhooks": safe(f"/guilds/{g}/webhooks"),
        "integrations": safe(f"/guilds/{g}/integrations"),
        "posts": posts,
    }
    out.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    roles = snap["roles"] if isinstance(snap["roles"], list) else []
    print(f"{out}: {len(roles)} roles, {len(channels)} channels, {sum(len(v) for v in posts.values())} recent messages")


if __name__ == "__main__":
    main()
