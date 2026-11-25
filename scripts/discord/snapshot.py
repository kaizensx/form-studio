"""Write the Discord server's live configuration to a JSON file, so a change can be compared or rolled back.

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/snapshot.py OUT.json

It records the guild settings, roles (with permissions), categories and channels (with overwrites, topics and
forum tags), onboarding, rules screening, AutoMod rules, scheduled events, invites, webhooks, and the recent messages
of every text channel and forum post (who wrote each, how it starts, whether it still carries an embed). It reads
only; nothing on the server changes.
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
    def recent(cid):
        msgs = safe(f"/channels/{cid}/messages?limit=50")
        if not isinstance(msgs, list):
            return msgs
        return [{"id": m["id"], "author": m["author"]["username"], "bot": m["author"]["id"] == me["id"],
                 "pinned": m.get("pinned"), "at": m["timestamp"], "type": m.get("type", 0),
                 "starts": (m.get("content") or "")[:90], "chars": len(m.get("content") or ""),
                 "embeds": len(m.get("embeds", [])), "attachments": [a.get("filename") for a in m.get("attachments", [])],
                 "components": sum(len(r.get("components", [])) for r in m.get("components", []))}
                for m in msgs]
    posts = {c["name"]: recent(c["id"]) for c in channels if c["type"] in (0, 5)}
    threads = safe(f"/guilds/{g}/threads/active")
    names = {c["id"]: c["name"] for c in channels}
    forum_posts = {}
    for t in threads.get("threads", []) if isinstance(threads, dict) else []:
        forum_posts.setdefault(names.get(t.get("parent_id"), t.get("parent_id")), {})[t["name"]] = recent(t["id"])
    snap = {
        "taken": datetime.now(timezone.utc).isoformat(),
        "bot": {"id": me["id"], "username": me["username"]},
        "guild": safe(f"/guilds/{g}?with_counts=true"),
        "bot_member": safe(f"/guilds/{g}/members/{me['id']}"),
        "roles": safe(f"/guilds/{g}/roles"),
        "channels": channels,
        "active_threads": threads,
        "onboarding": safe(f"/guilds/{g}/onboarding"),
        "rules_screening": safe(f"/guilds/{g}/member-verification"),
        "automod": safe(f"/guilds/{g}/auto-moderation/rules"),
        "events": safe(f"/guilds/{g}/scheduled-events"),
        "invites": safe(f"/guilds/{g}/invites"),
        "emojis": safe(f"/guilds/{g}/emojis"),
        "stickers": safe(f"/guilds/{g}/stickers"),
        "webhooks": safe(f"/guilds/{g}/webhooks"),
        "integrations": safe(f"/guilds/{g}/integrations"),
        "posts": posts,
        "forum_posts": forum_posts,
    }
    out.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    roles = snap["roles"] if isinstance(snap["roles"], list) else []
    print(f"{out}: {len(roles)} roles, {len(channels)} channels, {sum(len(v) for v in posts.values() if isinstance(v, list))} recent messages")


if __name__ == "__main__":
    main()
