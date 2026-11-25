"""The help desk: keep #help moving. Runs every two hours from GitHub Actions (and on demand).

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/helpdesk.py [--dry-run]

- A new post in #help gets one reply, in plain text: the guides for its tags and what to add so a person can answer.
- A post tagged Solved and quiet for a day is archived (anyone can reopen it by writing in it).
- A post that is not solved and has been quiet for 7 days gets one reminder; quiet for 14 days, it is archived.
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

QUEUE = "**Help desk**"                      # how the queue message in #mod-log starts
NUDGE = "**Still stuck?**"                   # how the reminder in a quiet post starts
WAITING_AFTER = timedelta(hours=6)
NUDGE_AFTER = timedelta(days=7)
CLOSE_AFTER = timedelta(days=14)

CHECKLIST = ("- your system and your Form Studio version (About, or `form update --check`)\n"
             "- your agent and model, and what you asked for\n"
             "- what you did, what you expected and what happened\n"
             "- for setup problems: the output of `form setup --check`\n"
             "- a screenshot, when it is about something you see")


def snowflake_time(sid: str) -> datetime:
    return datetime.fromtimestamp(((int(sid) >> 22) + 1420070400000) / 1000, tz=timezone.utc)


def first_reply(names: list[str], guide_links: dict) -> str:
    links = list(dict.fromkeys(guide_links[x] for n in names for x in S.HELP_GUIDES.get(n, []) if x in guide_links))
    text = ("**Thanks for the post.** A person will answer here. So they can help at once, add whatever is missing:\n"
            + CHECKLIST)
    if links:
        text += "\n\n**Guides that may already answer it**\n" + "\n".join(f"- {x}" for x in links)
    if "Bug" in names:
        text += (f"\n\n**A bug you can reproduce?** [Open an issue on GitHub]({S.REPO}/issues/new?template=1-bug.yml) and "
                 "link it here, so it is tracked until it is fixed. `/bug` shows what a good report holds.")
    text += "\n\nWhen it is fixed, right-click the answer › **Apps › Mark as solved**."
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run
    g = os.environ["DISCORD_GUILD_ID"]
    me = d.call("GET", "/users/@me")
    chans = {c["name"]: c for c in d.call("GET", f"/guilds/{g}/channels")}
    pick = lambda k: chans.get(S.N(k)) or chans.get(k)  # noqa: E731
    helpf, guides, modlog = pick("help"), pick("guides"), pick("mod-log")
    if not helpf:
        raise SystemExit("#help is not on the server: run the server setup first")
    tags = {t["id"]: t["name"] for t in helpf.get("available_tags", [])}
    solved = next((i for i, n in tags.items() if n == "Solved"), None)
    active = d.call("GET", f"/guilds/{g}/threads/active").get("threads", [])
    guide_links = {}
    if guides:
        for t in active + d.call("GET", f"/channels/{guides['id']}/threads/archived/public?limit=100").get("threads", []):
            if t.get("parent_id") == guides["id"]:
                guide_links[t["name"]] = f"<#{t['id']}>"
    now = datetime.now(timezone.utc)
    waiting = []
    for t in (t for t in active if t.get("parent_id") == helpf["id"]):
        msgs = d.call("GET", f"/channels/{t['id']}/messages?limit=50")
        names = [tags.get(i, "") for i in t.get("applied_tags", [])]
        last = snowflake_time(t.get("last_message_id") or t["id"])
        if solved in t.get("applied_tags", []):
            if now - last > timedelta(hours=24):
                print(("would " if dry else "") + f"archive solved: {t['name']}")
                if not dry:
                    d.call("PATCH", f"/channels/{t['id']}", {"archived": True}, reason="solved and quiet for a day")
            continue
        mine = [m for m in msgs if m["author"]["id"] == me["id"]]
        if not mine:
            print(("would " if dry else "") + f"answer new post: {t['name']}")
            if not dry:
                d.send_text(t["id"], first_reply(names, guide_links))
        nudged = any((m.get("content") or "").startswith(NUDGE) for m in mine)
        if nudged and now - last > CLOSE_AFTER - NUDGE_AFTER:
            print(("would " if dry else "") + f"archive quiet post: {t['name']}")
            if not dry:
                d.call("PATCH", f"/channels/{t['id']}", {"archived": True}, reason="quiet for two weeks")
            continue
        if mine and not nudged and now - last > NUDGE_AFTER:
            print(("would " if dry else "") + f"remind quiet post: {t['name']}")
            if not dry:
                d.send_text(t["id"], f"{NUDGE} <@{t.get('owner_id')}>, this post has been quiet for a week. If it is "
                                     "solved, right-click the answer › **Apps › Mark as solved**. If not, say what you "
                                     "tried since and it comes back to the top. Without an answer it is archived in a "
                                     "week; writing in it reopens it.",
                            mentions={"users": [t["owner_id"]]} if t.get("owner_id") else None)
            continue
        others = {m["author"]["id"] for m in msgs} - {t.get("owner_id"), me["id"]}
        if not others and now - snowflake_time(t["id"]) > WAITING_AFTER:
            waiting.append(t)
    if not modlog:
        return
    lines = [f"- <#{t['id']}> · waiting {(now - snowflake_time(t['id'])).days}d {((now - snowflake_time(t['id'])).seconds // 3600)}h"
             f"{' · ' + ', '.join(n for n in (tags.get(i, '') for i in t.get('applied_tags', [])) if n) if t.get('applied_tags') else ''}"
             for t in sorted(waiting, key=lambda t: t["id"])[:25]]
    text = QUEUE + " · " + (f"{len(waiting)} waiting for an answer\n" + "\n".join(lines) if lines
                            else "every post in #help has an answer.")
    mine = [m for m in d.call("GET", f"/channels/{modlog['id']}/messages?limit=50") if m["author"]["id"] == me["id"]
            and (m.get("content") or "").startswith(QUEUE)]
    if mine and mine[0].get("content") == text:
        print("queue is current")
        return
    print(("would " if dry else "") + f"queue: {len(lines)} waiting")
    if dry:
        return
    if mine:
        d.call("PATCH", f"/channels/{modlog['id']}/messages/{mine[0]['id']}", {"content": text[:d.LIMIT]})
    else:
        d.send_text(modlog["id"], text)


if __name__ == "__main__":
    main()
