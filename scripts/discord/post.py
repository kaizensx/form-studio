"""Post a GitHub event to the Form Studio Discord server, as the Form Studio bot.

    python scripts/discord/post.py event            # the event GitHub Actions is running for (GITHUB_EVENT_NAME/PATH)
    python scripts/discord/post.py digest           # the week on GitHub, for #github (scheduled)
    python scripts/discord/post.py release v1.1.0   # post one release by its tag (by hand, or again after a failure)

Channels are found by name in DISCORD_GUILD_ID. Every message is plain text and carries only what GitHub says: titles,
numbers, authors, links and the release notes' own words. A release goes to #releases, the only channel that posts
releases; a stable release is also announced in #announcements, with the Release pings role. Everything else GitHub
does goes to #github.
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
NOTES_MESSAGES = 8                 # a release's notes take at most this many messages; the rest is linked
DOWNLOADS = [("macOS, Apple silicon", "macos-arm64"), ("macOS, Intel", "macos-x64"), ("Windows 10 and 11", "windows"),
             ("Linux x64", "linux")]


def channel(name: str) -> str:
    name = S.N(name)                                   # a key ("releases") or the name shown
    for c in d.call("GET", f"/guilds/{os.environ['DISCORD_GUILD_ID']}/channels"):
        if c["name"] == name:
            return c["id"]
    raise SystemExit(f"#{name} is not on the server: run the server setup first")


def role(name: str) -> str | None:
    name = S.R.get(name, name)
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


def short(text: str, n: int = 600) -> str:
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def plain(text: str, n: int = 300) -> str:
    """Someone's text as one calm line: no markdown that could start a heading, a quote or a ping."""
    text = re.sub(r"```.*?```", " ", short(text, 4 * n), flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\s+", " ", re.sub(r"^[#>\-*\s]+", "", text, flags=re.M)).strip()
    text = text.replace("@", "@​")
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def link(text: str, url: str) -> str:
    return f"[{text.replace('[', '(').replace(']', ')')}]({url})"


def say(ch: str, text: str, **kw) -> list[dict]:
    return d.send_text(channel(ch), text, **kw)


# ---- releases ---------------------------------------------------------------------------------------------------
def notes_markdown(body: str) -> str:
    """A release's notes as Discord markdown, in full: GitHub's own words, its headings one level down, its line
    wraps undone. The part about verifying the download stays on GitHub (the post links to SHA256SUMS)."""
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S).replace("\r\n", "\n")
    out, para = [], []

    def flush():
        if para:
            out.append(" ".join(para))
            para.clear()
    fenced = False
    for ln in body.splitlines():
        if ln.lstrip().startswith("```"):
            flush()
            fenced = not fenced
            out.append(ln)
            continue
        if fenced:
            out.append(ln)
            continue
        h = re.match(r"(#{1,6})\s+(.*)", ln)
        if h:
            if re.match(r"verify the download", h.group(2), re.I):
                break
            flush()
            out += ["", "#" * min(3, max(2, len(h.group(1)))) + " " + h.group(2).strip(), ""]
        elif not ln.strip():
            flush()
            out.append("")
        elif re.match(r"\s*([-*+]|\d+\.)\s+", ln):
            flush()
            para.append(re.sub(r"^(\s*)[*+](\s+)", r"\1-\2", ln.rstrip()))
        elif ln.startswith(">"):                        # a GitHub note box: its text, without the quote
            if not re.match(r">\s*\[!", ln):
                para.append(ln.lstrip("> ").strip())
        else:
            para.append(ln.strip())
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def release_text(r: dict) -> str:
    """The whole post for one release: title, what it is, the notes in full, the downloads."""
    tag, pre = r["tag_name"], bool(r.get("prerelease"))
    version = tag[1:] if tag.startswith("v") else tag
    kind = "Preview" if pre else ("Patch" if not version.endswith(".0") else "Stable release")
    name = r.get("name") or f"Form Studio {version}"
    lines = [f"# {name}", ""]
    if pre:
        lines.append(f"**{kind}.** New features to try before the next stable release. It reaches the app through the "
                     "Preview update channel (Settings › Updates); the Stable channel is not offered it.")
    elif kind == "Patch":
        lines.append(f"**{kind}.** Fixes only, for everyone on the Stable channel. The app offers the update by itself.")
    else:
        lines.append(f"**{kind}.** For everyone: the app offers the update by itself, on the Stable and the Preview channel.")
    notes = notes_markdown(r.get("body", ""))
    parts = d.split_text(notes) if notes else []
    if len(parts) > NOTES_MESSAGES:
        notes = "\n\n".join(parts[:NOTES_MESSAGES]) + f"\n\nThe notes continue on GitHub: {link('full release notes', r['html_url'])}."
    if notes:
        lines += ["", notes]
    assets = {a["name"]: a["browser_download_url"] for a in r.get("assets", [])}
    pick = lambda k: next(((n, u) for n, u in assets.items() if k in n), None)  # noqa: E731
    dl = [(lbl, pick(k)) for lbl, k in DOWNLOADS]
    if any(a for _, a in dl):
        lines += ["", "## Download", ""]
        lines += [f"- **{lbl}:** {link(a[0], a[1])}" for lbl, a in dl if a]
        sums = pick("SHA256SUMS")
        if sums:
            lines.append(f"- **Check your download:** {link(sums[0], sums[1])}")
        lines += ["", "New here? The guide *Getting started* in #guides walks through installing on each system."]
    lines += ["", f"{link('Release notes on GitHub', r['html_url'])} · {link('Changelog', f'https://github.com/{REPO}/blob/main/CHANGELOG.md')}"
              f" · {link('Website', S.SITE)}"]
    return "\n".join(lines)


def post_release(r: dict):
    if r.get("draft"):
        return
    pre = bool(r.get("prerelease"))
    # docs/RELEASING.md: every build goes to #releases; only a stable release (or a patch) is also announced, with
    # the ping, and crossposted to the servers that follow #announcements
    say("releases", _channels(release_text(r)))
    if pre:
        return
    cid = channel("announcements")
    sent = d.send_text(cid, _channels(release_text(r)))
    for m in sent:
        try:
            d.call("POST", f"/channels/{cid}/messages/{m['id']}/crosspost")       # out to servers that follow it
        except d.DiscordError:
            pass
    ping = role("Release pings")
    if ping:                 # one ping, after the whole text is there; it is not crossposted
        d.call("POST", f"/channels/{cid}/messages", {
            "content": _channels(f"<@&{ping}> {r.get('name') or r['tag_name']} is out. You get this ping because you "
                                 "picked Release pings; change it in #roles."),
            "flags": d.NO_LINK_PREVIEWS, "allowed_mentions": {"roles": [ping]}})


_CHANNELS: dict[str, str] = {}


def _channels(text: str) -> str:
    """#guides, #roles… in a post become links to the channels."""
    if not _CHANNELS:
        by_name = {c["name"]: c["id"] for c in d.call("GET", f"/guilds/{os.environ['DISCORD_GUILD_ID']}/channels")}
        _CHANNELS.update({n: by_name[n] for n in S.NAMES.values() if n in by_name})
    return re.sub(r"(?<![\w/#`(\[<])#([a-z][a-z0-9-]+)\b",
                  lambda m: f"<#{_CHANNELS[m.group(1)]}>" if m.group(1) in _CHANNELS else m.group(0), text)


def release(ev):
    if ev.get("action") in ("published", "released"):
        post_release(ev["release"])


# ---- GitHub activity, all in #github ---------------------------------------------------------------------------------
def discussion(ev):
    if ev.get("action") != "created":
        return
    x = ev["discussion"]
    cat = x.get("category", {})
    if cat.get("slug") == "announcements":
        return                                          # a release's announcement: #releases already has the release
    who = x["user"]["login"]
    head = f"**Discussion** · {cat.get('name', '')} · {link('#%s %s' % (x['number'], x['title']), x['html_url'])} by {who}"
    body = plain(x.get("body", ""), 400)
    say("github", head + (f"\n{body}" if body else ""))
    if cat.get("slug") == "show-and-tell":
        _forum(channel("showcase"), x, "3D model")
    elif cat.get("slug") == "ideas":
        _forum(channel("ideas"), x, "Feature")


def _forum(forum_id, x, tag):
    tags = {t["name"]: t["id"] for t in d.call("GET", f"/channels/{forum_id}").get("available_tags", [])}
    text = f"{short(x.get('body', ''), 1500)}\n\nPosted on GitHub by {x['user']['login']}: {link('join the discussion', x['html_url'])}"
    d.call("POST", f"/channels/{forum_id}/threads", {
        "name": x["title"][:100], "applied_tags": [tags[tag]] if tag in tags else [],
        "message": {"content": text.replace("@", "@​")[:d.LIMIT], "flags": d.NO_LINK_PREVIEWS,
                    "allowed_mentions": {"parse": []}}})


def issue(ev):
    if ev.get("action") not in ("opened", "closed"):
        return
    i = ev["issue"]
    if i.get("pull_request"):
        return
    closed = ev["action"] == "closed"
    labels = ", ".join(l["name"] for l in i.get("labels", []))
    head = (f"**Issue {'closed' if closed else 'opened'}** · {link('#%s %s' % (i['number'], i['title']), i['html_url'])}"
            f" by {i['user']['login']}" + (f" · {labels}" if labels else ""))
    body = "" if closed else plain(i.get("body", ""), 400)
    say("github", head + (f"\n{body}" if body else ""))


def pull_request(ev):
    pr = ev["pull_request"]
    if ev.get("action") == "opened":
        what = "Pull request opened"
    elif ev.get("action") == "closed" and pr.get("merged"):
        what = "Pull request merged"
        recognise(pr["user"]["login"])
    else:
        return
    head = (f"**{what}** · {link('#%s %s' % (pr['number'], pr['title']), pr['html_url'])} by {pr['user']['login']}"
            f" · into `{pr['base']['ref']}` · +{pr.get('additions', 0)} −{pr.get('deletions', 0)} in "
            f"{pr.get('changed_files', 0)} files")
    body = plain(pr.get("body", ""), 300) if ev["action"] == "opened" else ""
    say("github", head + (f"\n{body}" if body else ""))


def recognise(login: str):
    """A merged pull request from someone listed in server.CONTRIBUTORS gives them the Contributor role."""
    user = S.CONTRIBUTORS.get(login)
    rid = role("Contributor")
    if not user or not rid:
        return
    g = os.environ["DISCORD_GUILD_ID"]
    try:
        if rid in d.call("GET", f"/guilds/{g}/members/{user}").get("roles", []):
            return
        d.call("PUT", f"/guilds/{g}/members/{user}/roles/{rid}", reason=f"merged pull request by {login}")
    except d.DiscordError as e:
        print(f"contributor role: {e}")
        return
    say("contributing", f"<@{user}> is a Contributor now: thank you for the merged pull request.")


def workflow_run(ev):
    w = ev["workflow_run"]
    if ev.get("action") != "completed" or w.get("conclusion") not in ("failure", "timed_out"):
        return
    if w.get("head_branch") not in ("main", "dev"):
        return
    msg = (w.get("head_commit") or {}).get("message", "").splitlines()[0] if w.get("head_commit") else ""
    say("github", f"**{w['name']} failed** on `{w['head_branch']}` · `{w['head_sha'][:7]}` {plain(msg, 160)} · "
                  f"{link('open the run', w['html_url'])}")


def star(ev):
    if ev.get("action") != "created":
        return
    n = ev["repository"]["stargazers_count"]
    if n in (10, 25, 50, 100, 250, 500) or (n >= 1000 and n % 1000 == 0):
        say("github", f"**{n} stars on GitHub.** Thank you. Most recent: {ev['sender']['login']}. "
                      f"{link('Everyone who starred it', ev['repository']['html_url'] + '/stargazers')}")


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
    if not merged and not rels and not prs:
        print("a quiet week: no digest")                           # nothing happened, so nothing is posted
        return
    lines = ["## The week in Form Studio", "",
             f"- **Commits on dev:** {len(merged)}",
             f"- **Pull requests merged:** {prs}",
             f"- **Issues opened / closed:** {issues} / {closed}",
             f"- **Releases:** {', '.join(link(r['tag_name'], r['html_url']) for r in rels) or 'none'}",
             f"- **Stars:** {repo['stargazers_count']} · **Forks:** {repo['forks_count']}"]
    if merged:
        lines += ["", "**What landed**"] + [f"- {plain(c['commit']['message'].splitlines()[0], 140)}" for c in merged[:12]]
        if len(merged) > 12:
            lines.append(f"- and {len(merged) - 12} more")
    lines += ["", f"{link('Changelog', f'https://github.com/{REPO}/blob/dev/CHANGELOG.md')} · {link('All commits', repo['html_url'] + '/commits/dev')}"]
    say("github", "\n".join(lines))


def retract(tag: str) -> int:
    """Remove the bot's own post of a release that was taken back (a tag withdrawn before anyone got it, see
    docs/RELEASING.md): in #releases and #announcements, every bot message from the minute around the one that
    names the tag. Messages written by people are never touched."""
    from datetime import datetime
    gone = 0
    for ch in ("releases", "announcements"):
        try:
            cid = channel(ch)
        except SystemExit:
            continue
        msgs = d.call("GET", f"/channels/{cid}/messages?limit=100") or []
        me = [m for m in msgs if (m.get("author") or {}).get("bot")]
        at = [datetime.fromisoformat(m["timestamp"]) for m in me if tag in (m.get("content") or "")]
        for m in me:
            t = datetime.fromisoformat(m["timestamp"])
            if any(abs((t - a).total_seconds()) <= 60 for a in at):
                d.call("DELETE", f"/channels/{cid}/messages/{m['id']}")
                gone += 1
    print(f"retracted {tag}: {gone} bot message(s) removed")
    return 0


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "event"
    if what == "retract":
        tag = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("RELEASE_TAG", "")).strip()
        if not tag:
            raise SystemExit("which release? python scripts/discord/post.py retract v1.1.0-preview.2")
        return retract(tag)
    if what == "digest":
        return digest()
    if what == "release":
        tag = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("RELEASE_TAG", "")).strip()
        if not tag:
            raise SystemExit("which release? python scripts/discord/post.py release v1.1.0")
        return post_release(gh(f"/repos/{REPO}/releases/tags/{tag}"))
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    ev = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")) if os.environ.get("GITHUB_EVENT_PATH") else {}
    handler = {"release": release, "discussion": discussion, "issues": issue, "pull_request_target": pull_request,
               "pull_request": pull_request, "workflow_run": workflow_run, "watch": star}.get(name)
    if handler:
        handler(ev)


if __name__ == "__main__":
    main()
