"""The help desk: keep #help moving. Runs every two hours from GitHub Actions (and on demand).

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/helpdesk.py [--dry-run]

- A new post in #help gets one reply: the guides for its tags and what to add so a person can answer.
- A post tagged Solved and quiet for a day is archived (anyone can reopen it by writing in it).
- Posts nobody but their author has written in for six hours are listed in #mod-log, in one message kept current.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402
import server as S  # noqa: E402

QUEUE = "Help desk"


def snowflake_time(sid: str) -> datetime:
    return datetime.fromtimestamp(((int(sid) >> 22) + 1420070400000) / 1000, tz=timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run
    g = os.environ["DISCORD_GUILD_ID"]
    me = d.call("GET", "/users/@me")
    chans = {c["name"]: c for c in d.call("GET", f"/guilds/{g}/channels")}
    helpf, guides, modlog = chans[S.N("help")], chans.get(S.N("guides")), chans.get(S.N("mod-log"))
    tags = {t["id"]: t["name"] for t in helpf.get("available_tags", [])}
    solved = next((i for i, n in tags.items() if n == "Solved"), None)
    guide_links = {}
    if guides:
        for t in d.call("GET", f"/guilds/{g}/threads/active").get("threads", []) + \
                d.call("GET", f"/channels/{guides['id']}/threads/archived/public?limit=100").get("threads", []):
            if t.get("parent_id") == guides["id"]:
                guide_links[t["name"]] = f"<#{t['id']}>"
    now = datetime.now(timezone.utc)
    waiting = []
    threads = [t for t in d.call("GET", f"/guilds/{g}/threads/active").get("threads", []) if t.get("parent_id") == helpf["id"]]
    for t in threads:
        msgs = d.call("GET", f"/channels/{t['id']}/messages?limit=50")
        names = [tags.get(i, "") for i in t.get("applied_tags", [])]
        last = snowflake_time(t.get("last_message_id") or t["id"])
        if solved in t.get("applied_tags", []):
            if now - last > timedelta(hours=24):
                print(("would " if dry else "") + f"archive solved: {t['name']}")
                if not dry:
                    d.call("PATCH", f"/channels/{t['id']}", {"archived": True}, reason="solved and quiet for a day")
            continue
        if not any(m["author"]["id"] == me["id"] for m in msgs):
            links = [guide_links[x] for n in names for x in S.HELP_GUIDES.get(n, []) if x in guide_links]
            checklist = ("- your system and Form Studio version (Help › About)\n"
                         "- your printer and slicer, or that it is a 3D model\n"
                         "- what you did, what you expected and what happened\n"
                         "- for setup: the output of `form doctor`")
            emb = {"color": d.BLUEPRINT, "title": "🛟 Thanks for the post",
                   "description": "A person will answer here. So they can help at once, add whatever is missing:\n" + checklist
                   + "\n\nWhen it is fixed, right-click the answer › **Apps › Mark as solved** (or add the ✅ Solved tag).",
                   "footer": d.footer("Help desk")}
            if links:
                emb["fields"] = [{"name": "Guides that may help", "value": " · ".join(dict.fromkeys(links)), "inline": False}]
            if "Bug" in names:
                emb.setdefault("fields", []).append({"name": "A bug you can reproduce?", "inline": False,
                                                     "value": f"[Open an issue on GitHub]({S.REPO}/issues/new/choose) and "
                                                              "link it here."})
            print(("would " if dry else "") + f"answer new post: {t['name']}")
            if not dry:
                d.send(t["id"], embeds=[emb])
        others = {m["author"]["id"] for m in msgs} - {t.get("owner_id"), me["id"]}
        if not others and now - snowflake_time(t["id"]) > timedelta(hours=6):
            waiting.append(t)
    if not modlog:
        return
    lines = [f"<#{t['id']}> · {(now - snowflake_time(t['id'])).days}d {((now - snowflake_time(t['id'])).seconds // 3600)}h"
             for t in sorted(waiting, key=lambda t: t["id"])[:25]]
    emb = {"color": d.AMBER if lines else d.PASS, "title": "Waiting for an answer",
           "description": "\n".join(lines) or "Every post in #help has an answer.", "footer": d.footer(QUEUE)}
    mine = [m for m in d.call("GET", f"/channels/{modlog['id']}/messages?limit=50") if m["author"]["id"] == me["id"]
            and any((e.get("footer") or {}).get("text") == f"Form Studio · {QUEUE}" for e in m.get("embeds", []))]
    if mine and mine[0]["embeds"][0].get("description") == emb["description"]:
        print("queue is current")
        return
    print(("would " if dry else "") + f"queue: {len(lines)} waiting")
    if dry:
        return
    if mine:
        d.call("PATCH", f"/channels/{modlog['id']}/messages/{mine[0]['id']}", {"embeds": [emb]})
    else:
        d.send(modlog["id"], embeds=[emb])


if __name__ == "__main__":
    main()
