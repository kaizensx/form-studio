"""Post a GitHub event to the Form Studio Discord server, as the Form Studio bot.

    python scripts/discord/post.py event        # the event GitHub Actions is running for (GITHUB_EVENT_NAME/PATH)
    python scripts/discord/post.py digest       # the week on GitHub, for #announcements (scheduled)

Channels are found by name in DISCORD_GUILD_ID. Every message carries only what GitHub says: titles, numbers,
authors, links and the release notes' own words.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402
import server as S  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "kaizensx/form-studio")


def channel(name: str) -> str:
    for c in d.call("GET", f"/guilds/{os.environ['DISCORD_GUILD_ID']}/channels"):
        if c["name"] == name:
            return c["id"]
    raise SystemExit(f"#{name} is not on the server: run the server setup first")


def role(name: str) -> str | None:
    for r in d.call("GET", f"/guilds/{os.environ['DISCORD_GUILD_ID']}/roles"):
        if r["name"] == name:
            return r["id"]
    return None


def gh(path: str):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "form-studio-discord",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def author(u: dict) -> dict:
    return {"name": u.get("login", ""), "url": u.get("html_url", ""), "icon_url": u.get("avatar_url", "")}


def short(text: str, n: int = 600) -> str:
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def notes_to_fields(body: str) -> tuple[str, list]:
    """A release's notes as Discord markdown: '- **Title.** text' bullets become fields."""
    fields, rest = [], []
    for ln in (body or "").splitlines():
        m = re.match(r"\s*[-*]\s+\*\*(.+?)\*\*\s*(.*)", ln)
        if m and len(fields) < 9:
            fields.append({"name": m.group(1).rstrip(".")[:250], "value": short(m.group(2), 300) or "—", "inline": False})
        elif not ln.startswith("#"):
            rest.append(ln)
    return short("\n".join(rest), 400), fields


def release(ev):
    r = ev["release"]
    if ev.get("action") not in ("published", "released") or r.get("draft"):
        return
    intro, fields = notes_to_fields(r.get("body", ""))
    assets = {a["name"]: a["browser_download_url"] for a in r.get("assets", [])}
    pick = lambda k: next((u for n, u in assets.items() if k in n), None)  # noqa: E731
    dl = [(lbl, pick(k), e) for lbl, k, e in (("macOS (Apple silicon)", "macos-arm64", "🍎"), ("macOS (Intel)", "macos-x64", "🍏"),
                                              ("Windows", "windows", "🪟"), ("Linux", "linux", "🐧"))]
    buttons = [d.link_button(lbl, u, e) for lbl, u, e in dl if u]
    emb = {"color": d.VIOLET if r.get("prerelease") else d.DATUM, "author": author(r["author"]),
           "title": r.get("name") or r["tag_name"], "url": r["html_url"],
           "description": intro or ("A preview for the Preview update channel." if r.get("prerelease") else ""),
           "fields": fields, "thumbnail": {"url": f"https://raw.githubusercontent.com/{REPO}/main/form/app/assets/icon-256.png"},
           "footer": {"text": "Form Studio " + r["tag_name"] + (" · preview" if r.get("prerelease") else "")},
           "timestamp": r.get("published_at")}
    comps = [d.row(*buttons[:4])] if buttons else []
    comps.append(d.row(d.link_button("Release notes", r["html_url"], "📝"), d.link_button("Website", S.SITE, "🧊")))
    ping = role("Release pings")
    content = (f"<@&{ping}> " if ping and not r.get("prerelease") else "") + f"**Form Studio {r['tag_name']}** is out."
    for ch in ("releases", "announcements"):
        cid = channel(ch)
        m = d.call("POST", f"/channels/{cid}/messages", {"content": content, "embeds": [emb], "components": comps,
                                                          "allowed_mentions": {"roles": [ping] if ping else []}})
        if ch == "announcements":
            try:
                d.call("POST", f"/channels/{cid}/messages/{m['id']}/crosspost")   # out to servers that follow it
            except d.DiscordError:
                pass


def discussion(ev):
    if ev.get("action") != "created":
        return
    x = ev["discussion"]
    cat = x.get("category", {})
    emb = {"color": d.BLUEPRINT, "author": author(x["user"]), "title": f"{cat.get('emoji', '')} {x['title']}".strip()[:256],
           "url": x["html_url"], "description": short(x.get("body", ""), 500),
           "footer": {"text": f"Discussion #{x['number']} · {cat.get('name', '')}"}, "timestamp": x.get("created_at")}
    d.send(channel("github"), embeds=[emb], components=[d.row(d.link_button("Join the discussion", x["html_url"], "💬"))])
    if cat.get("slug") == "show-and-tell":
        _forum(channel("showcase"), x["title"], emb, x["html_url"], "Printed")
    elif cat.get("slug") == "ideas":
        _forum(channel("ideas"), x["title"], emb, x["html_url"], "Feature")


def _forum(forum_id, title, emb, url, tag):
    tags = {t["name"]: t["id"] for t in d.call("GET", f"/channels/{forum_id}").get("available_tags", [])}
    d.call("POST", f"/channels/{forum_id}/threads", {
        "name": title[:100], "applied_tags": [tags[tag]] if tag in tags else [],
        "message": {"embeds": [emb], "components": [d.row(d.link_button("On GitHub", url, "↗️"))],
                    "allowed_mentions": {"parse": []}}})


def issue(ev):
    if ev.get("action") not in ("opened", "closed"):
        return
    i = ev["issue"]
    if i.get("pull_request"):
        return
    closed = ev["action"] == "closed"
    labels = ", ".join(l["name"] for l in i.get("labels", [])) or "—"
    emb = {"color": d.PASS if closed else d.AMBER, "author": author(i["user"]), "url": i["html_url"],
           "title": f"{'✅ Closed' if closed else '🟠 New issue'}: {i['title']}"[:256],
           "description": "" if closed else short(i.get("body", ""), 400),
           "fields": [{"name": "Labels", "value": labels, "inline": True}],
           "footer": {"text": f"Issue #{i['number']}"}, "timestamp": i.get("closed_at") if closed else i.get("created_at")}
    d.send(channel("github"), embeds=[emb])


def pull_request(ev):
    pr = ev["pull_request"]
    if ev.get("action") == "opened":
        title, colour = f"🔀 Pull request: {pr['title']}", d.BLUEPRINT
    elif ev.get("action") == "closed" and pr.get("merged"):
        title, colour = f"🟣 Merged: {pr['title']}", d.VIOLET
    else:
        return
    emb = {"color": colour, "author": author(pr["user"]), "title": title[:256], "url": pr["html_url"],
           "description": short(pr.get("body", ""), 300) if ev["action"] == "opened" else "",
           "fields": [{"name": "Changes", "value": f"+{pr.get('additions', 0)} −{pr.get('deletions', 0)} · {pr.get('changed_files', 0)} files", "inline": True},
                      {"name": "Into", "value": f"`{pr['base']['ref']}`", "inline": True}],
           "footer": {"text": f"#{pr['number']}"}}
    d.send(channel("github"), embeds=[emb])


def workflow_run(ev):
    w = ev["workflow_run"]
    if ev.get("action") != "completed" or w.get("conclusion") not in ("failure", "timed_out"):
        return
    if w.get("head_branch") not in ("main", "dev"):
        return
    emb = {"color": d.SIGNAL, "title": f"❌ {w['name']} failed on {w['head_branch']}"[:256], "url": w["html_url"],
           "description": f"`{w['head_sha'][:7]}` {short((w.get('head_commit') or {}).get('message', '').splitlines()[0] if w.get('head_commit') else '', 200)}",
           "footer": {"text": f"run {w['run_number']} · attempt {w.get('run_attempt', 1)}"}, "timestamp": w.get("updated_at")}
    d.send(channel("ci"), embeds=[emb], components=[d.row(d.link_button("Open the run", w["html_url"], "🔎"))])


def star(ev):
    if ev.get("action") != "created":
        return
    n = ev["repository"]["stargazers_count"]
    if n in (10, 25, 50, 100, 250, 500) or (n >= 1000 and n % 1000 == 0):
        d.send(channel("announcements"), embeds=[{"color": d.AMBER, "title": f"⭐ {n} stars on GitHub",
                                                   "description": f"Thank you. Most recent: **{ev['sender']['login']}**.",
                                                   "url": ev["repository"]["html_url"] + "/stargazers"}])


def digest():
    since = datetime.now(timezone.utc) - timedelta(days=7)
    iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = gh(f"/repos/{REPO}")
    commits = gh(f"/repos/{REPO}/commits?sha=dev&since={iso}&per_page=100")
    merged = [c for c in commits if len(c.get("parents", [])) == 1]
    issues = gh(f"/search/issues?q=repo:{REPO}+is:issue+created:>={since.date()}")["total_count"]
    closed = gh(f"/search/issues?q=repo:{REPO}+is:issue+closed:>={since.date()}")["total_count"]
    prs = gh(f"/search/issues?q=repo:{REPO}+is:pr+is:merged+merged:>={since.date()}")["total_count"]
    rels = [r for r in gh(f"/repos/{REPO}/releases?per_page=10") if r.get("published_at", "") >= iso and not r["draft"]]
    lines = [f"• {c['commit']['message'].splitlines()[0][:110]}" for c in merged[:8]]
    emb = {"color": d.DATUM, "title": "🧊 The week in Form Studio", "url": repo["html_url"],
           "fields": [{"name": "Commits", "value": str(len(merged)), "inline": True},
                      {"name": "Releases", "value": ", ".join(r["tag_name"] for r in rels) or "—", "inline": True},
                      {"name": "Stars", "value": f"{repo['stargazers_count']} ⭐", "inline": True},
                      {"name": "Issues opened / closed", "value": f"{issues} / {closed}", "inline": True},
                      {"name": "Pull requests merged", "value": str(prs), "inline": True},
                      {"name": "Forks", "value": str(repo["forks_count"]), "inline": True}],
           "description": "\n".join(lines) or "A quiet week.", "footer": {"text": "Every Monday"},
           "timestamp": datetime.now(timezone.utc).isoformat()}
    d.send(channel("announcements"), embeds=[emb],
           components=[d.row(d.link_button("Changelog", f"https://github.com/{REPO}/blob/main/CHANGELOG.md", "📝"),
                             d.link_button("Website", S.SITE, "🧊"))])


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "event"
    if what == "digest":
        return digest()
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    ev = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")) if os.environ.get("GITHUB_EVENT_PATH") else {}
    handler = {"release": release, "discussion": discussion, "issues": issue, "pull_request_target": pull_request,
               "pull_request": pull_request, "workflow_run": workflow_run, "watch": star}.get(name)
    if handler:
        handler(ev)


if __name__ == "__main__":
    main()
