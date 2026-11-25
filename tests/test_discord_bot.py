"""The Discord bot (scripts/discord) against a fake Discord: the server setup, what each GitHub event posts, and the
help desk. Everything the bot writes is plain text: no embeds, no quote blocks, nothing over 2000 characters."""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "scripts" / "discord"
sys.path.insert(0, str(HERE))
import discord_api as d  # noqa: E402
import helpdesk  # noqa: E402
import post  # noqa: E402
import server as S  # noqa: E402
import setup_server  # noqa: E402

GUILD = "100"
BOT = "900"


def snowflake(when: datetime) -> str:
    return str((int(when.timestamp() * 1000) - 1420070400000) << 22)


class FakeDiscord:
    """A Discord server in memory: channels, roles, messages, forum posts, AutoMod. `seed` is a snapshot.py file."""

    def __init__(self, seed: dict | None = None):
        self.n = 10 ** 6
        self.log: list[tuple] = []                      # every call that changed something
        self.roles = [{"id": GUILD, "name": "@everyone", "permissions": "0", "position": 0, "color": 0, "hoist": False,
                       "mentionable": False},
                      {"id": "1", "name": "Form Studio", "managed": True, "tags": {"bot_id": BOT}, "position": 1,
                       "permissions": "8", "color": 0, "hoist": False, "mentionable": False}]
        self.channels, self.threads, self.messages, self.automod = [], [], {}, []
        self.guild = {"id": GUILD, "name": "Form Studio", "owner_id": "u-owner", "features": ["COMMUNITY"],
                      "verification_level": 1, "icon": "x"}
        self.onboarding, self.screening, self.members = {"prompts": []}, {"form_fields": []}, {}
        if seed:
            self.guild = seed["guild"]
            self.roles = seed["roles"]
            self.channels = seed["channels"]
            self.automod = seed["automod"]
            self.onboarding = seed["onboarding"]
            self.threads = seed["active_threads"]["threads"]
            for t in self.threads:                      # every forum post starts with the bot's old embed message
                self.messages[t["id"]] = [{"id": t["id"], "author": {"id": BOT}, "type": 0, "content": "",
                                           "embeds": [{"title": t["name"]}], "attachments": [], "components": []}]
            names = {c["name"]: c["id"] for c in self.channels}
            for name, msgs in seed["posts"].items():
                self.messages[names[name]] = [
                    {"id": m["id"], "author": {"id": BOT if m["bot"] else "u-" + m["author"]}, "type": 0, "content": "",
                     "embeds": [{"title": x} for x in m["titles"]], "attachments": [], "components": [],
                     "pinned": m["pinned"]} for m in msgs]

    def new_id(self) -> str:
        self.n += 1
        return str(self.n)

    def chan(self, cid):
        return next((c for c in self.channels + self.threads if c["id"] == cid), None)

    def call(self, method, path, body=None, *, files=None, reason=""):
        out = self._call(method, path, json.loads(json.dumps(body)) if body is not None else None, files)
        return json.loads(json.dumps(out))              # the caller never holds the server's own objects

    def _call(self, method, path, body, files):
        p = path.split("?")[0].strip("/").split("/")
        if method != "GET":
            self.log.append((method, path, body))
        if path == "/users/@me":
            return {"id": BOT, "username": "Form Studio", "avatar": "a", "banner": "b"}
        if path == "/applications/@me":
            return {"description": S.BOT_DESCRIPTION}
        if p[0] == "guilds":
            rest = p[2:]
            if not rest:
                if method == "PATCH":
                    self.guild.update(body)
                return self.guild
            if rest == ["roles"]:
                if method == "POST":
                    r = {"id": self.new_id(), "position": 1, **body}
                    self.roles.append(r)
                    return r
                if method == "PATCH":
                    for w in body:
                        next(r for r in self.roles if r["id"] == w["id"])["position"] = w["position"]
                return self.roles
            if rest[0] == "roles":
                r = next(x for x in self.roles if x["id"] == rest[1])
                if method == "DELETE":
                    self.roles.remove(r)
                    return None
                r.update(body)
                return r
            if rest == ["channels"]:
                if method == "POST":
                    c = {"id": self.new_id(), "permission_overwrites": [], **body}
                    for t in c.get("available_tags", []):
                        t["id"] = self.new_id()
                    self.channels.append(c)
                    return c
                return self.channels
            if rest == ["threads", "active"]:
                return {"threads": [t for t in self.threads if not (t.get("thread_metadata") or {}).get("archived")]}
            if rest == ["onboarding"]:
                if method == "PUT":
                    self.onboarding = body
                return self.onboarding
            if rest == ["member-verification"]:
                if method == "PATCH":
                    fields = body["form_fields"]
                    self.screening = {**body, "form_fields": json.loads(fields) if isinstance(fields, str) else fields}
                    self.guild["features"] = sorted(set(self.guild["features"]) | {"MEMBER_VERIFICATION_GATE_ENABLED"})
                return self.screening
            if rest[:2] == ["auto-moderation", "rules"]:
                if method == "POST":
                    r = {"id": self.new_id(), "creator_id": BOT, **body}
                    self.automod.append(r)
                    return r
                if method == "PATCH":
                    r = next(x for x in self.automod if x["id"] == rest[2])
                    r.update(body)
                    return r
                return self.automod
            if rest == ["invites"]:
                return [{"code": S.INVITE_CODE}]
            if rest[0] == "members":
                have = self.members.setdefault(rest[1], [])
                if method == "PUT":
                    have.append(rest[3])
                return {"roles": have}
        if p[0] == "channels":
            cid, rest = p[1], p[2:]
            c = self.chan(cid)
            if not rest:
                if method == "DELETE":
                    (self.threads if c in self.threads else self.channels).remove(c)
                    return None
                if method == "PATCH":
                    for t in body.get("available_tags", []):
                        t.setdefault("id", self.new_id())
                    meta = {k: body.pop(k) for k in ("archived", "locked") if k in body}
                    c.update(body)
                    if meta:
                        c["thread_metadata"] = {**(c.get("thread_metadata") or {}), **meta}
                return c
            if rest == ["threads", "archived", "public"]:
                return {"threads": [t for t in self.threads if t.get("parent_id") == cid
                                    and (t.get("thread_metadata") or {}).get("archived")]}
            if rest == ["threads"]:
                t = {"id": self.new_id(), "parent_id": cid, "name": body["name"], "applied_tags": body["applied_tags"],
                     "owner_id": BOT}
                self.threads.append(t)
                self.messages[t["id"]] = [self._msg(t["id"], body["message"], files)]
                return t
            if rest == ["pins"]:
                return [m for m in self.messages.get(cid, []) if m.get("pinned")]
            if rest[0] == "pins":
                next(m for m in self.messages[cid] if m["id"] == rest[1])["pinned"] = True
                return None
            if rest == ["messages"]:
                if method == "POST":
                    m = self._msg(self.new_id(), body, files)
                    self.messages.setdefault(cid, []).append(m)
                    return m
                msgs = sorted(self.messages.get(cid, []), key=lambda m: int(m["id"]))
                return msgs if "after=" in path else list(reversed(msgs))
            if rest[0] == "messages":
                msgs = self.messages.get(cid, [])
                m = next((x for x in msgs if x["id"] == rest[1]), None)
                if method == "DELETE":
                    msgs.remove(m)
                    return None
                if method == "PATCH":
                    m.update({k: v for k, v in body.items() if k != "attachments"})
                    if files is not None or "attachments" in body:
                        m["attachments"] = [{"filename": n, "size": len(b)} for n, b in (files or {}).items()]
                return m
            if rest == ["invites"]:
                return {"code": S.INVITE_CODE}
        return {}

    def _msg(self, mid, body, files):
        return {"id": mid, "author": {"id": BOT}, "type": 0, "content": body.get("content", ""),
                "embeds": body.get("embeds", []), "components": body.get("components", []), "flags": body.get("flags", 0),
                "allowed_mentions": body.get("allowed_mentions"),
                "attachments": [{"filename": n, "size": len(b)} for n, b in (files or {}).items()]}

    def named(self, key):
        return next(c for c in self.channels if c["name"] == S.N(key))

    def texts(self, key) -> list[str]:
        return [m["content"] for m in self.messages.get(self.named(key)["id"], [])]


class Base(unittest.TestCase):
    seed = None

    def setUp(self):
        self.fake = FakeDiscord(self.seed)
        self.env = mock.patch.dict(os.environ, {"DISCORD_GUILD_ID": self.fake.guild["id"], "DISCORD_BOT_TOKEN": "x"})
        self.env.start()
        self.patch = mock.patch.object(d, "call", side_effect=self.fake.call)
        self.patch.start()
        post._CHANNELS.clear()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.env.stop)

    def setup_server(self):
        with mock.patch.object(setup_server, "log", lambda *a: None):
            s = setup_server.Setup(self.fake.guild["id"], False)
            s.run()
        return s

    def assert_plain(self, msgs):
        """What the owner asked for: text in the chat. No embeds, no quote blocks, nothing over the limit."""
        for m in msgs:
            self.assertFalse(m.get("embeds"), m)
            self.assertLessEqual(len(m["content"]), d.LIMIT, m["content"][:80])
            self.assertIsNone(re.search(r"^>", m["content"], re.M), m["content"][:200])
            self.assertTrue(m.get("flags", 0) & d.NO_LINK_PREVIEWS or not m["content"], m["content"][:80])


class SetupTest(Base):
    def test_a_new_server_gets_the_whole_structure_and_a_second_run_changes_nothing(self):
        s = self.setup_server()
        self.assertEqual([n for n in s.notes if "role" not in n], [])       # the bot cannot lift its own role: a person does
        cats = [c["name"] for c in sorted((c for c in self.fake.channels if c["type"] == S.CATEGORY),
                                          key=lambda c: c["position"])]
        self.assertEqual(cats, [c for c, _ in S.LAYOUT])
        for cat, chans in S.LAYOUT:
            cid = next(c["id"] for c in self.fake.channels if c["name"] == cat)
            self.assertEqual({c["name"] for c in self.fake.channels if c.get("parent_id") == cid}, {n for _, n, *_ in chans})
        self.assertEqual({r["name"] for r in self.fake.roles} - {"@everyone", "Form Studio"}, {r[0] for r in S.ROLES})
        self.assertEqual(len(self.fake.automod), len(S.AUTOMOD))
        self.assertEqual(self.fake.guild["verification_level"], S.VERIFICATION_LEVEL)
        self.assertEqual(self.fake.screening["form_fields"][0]["values"], S.SCREENING["rules"])
        self.assertEqual(len(self.fake.onboarding["prompts"]), len(S.ONBOARDING))
        self.assertTrue(all(o["emoji_name"] for p in self.fake.onboarding["prompts"] for o in p["options"]))
        self.fake.log.clear()
        self.setup_server()
        again = [c for c in self.fake.log if not (c[0] == "PUT" and c[1].endswith("/onboarding"))
                 and not (c[0] == "PATCH" and c[1].endswith("/roles"))]
        self.assertEqual(again, [], "a second setup must change nothing")

    def test_every_post_is_plain_text_and_the_guides_are_whole(self):
        self.setup_server()
        for key in ("welcome", "rules", "roles", "contributing", "mod-log"):
            msgs = self.fake.messages[self.fake.named(key)["id"]]
            self.assertTrue(msgs, key)
            self.assert_plain(msgs)
        welcome = self.fake.messages[self.fake.named("welcome")["id"]]
        self.assertEqual(welcome[0]["attachments"][0]["filename"], "form-studio.jpg")
        self.assertIn(f"<#{self.fake.named('guides')['id']}>", "".join(m["content"] for m in welcome))
        self.assertNotIn("{", "".join(m["content"] for m in welcome))
        self.assertEqual(len(self.fake.messages[self.fake.named("roles")["id"]][-1]["components"]), len(S.ROLE_PICKER))
        guides = self.fake.named("guides")
        posts = {t["name"]: t for t in self.fake.threads if t["parent_id"] == guides["id"]}
        self.assertEqual(set(posts), {g[1] for g in S.GUIDES})
        for slug, title, *_ in S.GUIDES:
            msgs = self.fake.messages[posts[title]["id"]]
            self.assert_plain(msgs)
            self.assertGreaterEqual(len(msgs), 3, title)                     # real guides, not a paragraph
            self.assertEqual(msgs[0]["attachments"][0]["filename"], f"{slug}.png")
            said = "\n\n".join(m["content"] for m in msgs)
            source = S.guide_text(slug)
            for heading in re.findall(r"^## .+$", source, re.M):
                self.assertIn(heading, said, title)
            self.assertGreater(len(said), 0.95 * len(source), title)          # nothing was cut
            self.assertEqual(said.count("```") % 2, 0)
            for m in msgs:
                self.assertEqual(m["content"].count("```") % 2, 0, "a code block is never split across messages")
            self.assertEqual(len(posts[title]["applied_tags"]), 1)

    def test_a_changed_guide_is_edited_in_place(self):
        self.setup_server()
        guides = self.fake.named("guides")
        before = {t["id"] for t in self.fake.threads if t["parent_id"] == guides["id"]}
        real = S.guide_text
        self.fake.log.clear()
        with mock.patch.object(S, "guide_text", lambda slug: real(slug).replace("## What you need", "## What you will need")):
            self.setup_server()
        self.assertEqual({t["id"] for t in self.fake.threads if t["parent_id"] == guides["id"]}, before)
        edits = [c for c in self.fake.log if c[0] == "PATCH" and "/messages/" in c[1]]
        self.assertIn(len(edits), (1, 2))                                   # the changed message, and at most its neighbour
        self.assertFalse([c for c in self.fake.log if c[0] in ("POST", "DELETE")])

    def test_channels_with_history_are_archived_and_empty_ones_removed(self):
        old = [("🧯・ci", True), ("📅・events", True), ("🙋・introductions", False), ("🎲・off-topic", True)]
        for name, has_history in old:
            c = {"id": self.fake.new_id(), "name": name, "type": S.TEXT, "permission_overwrites": [], "topic": "t"}
            self.fake.channels.append(c)
            if has_history:
                self.fake.messages[c["id"]] = [{"id": "5", "author": {"id": "u1"}, "type": 0, "content": "hello"}]
        self.setup_server()
        names = {c["name"]: c for c in self.fake.channels}
        self.assertNotIn("🙋・introductions", names)                          # empty: removed
        archive = names[S.ARCHIVE_CATEGORY]
        for name in ("archive-ci", "archive-events", "archive-off-topic"):   # history: kept, hidden, read-only
            c = names[name]
            self.assertEqual(c["parent_id"], archive["id"])
            everyone = next(o for o in c["permission_overwrites"] if o["id"] == GUILD)
            self.assertTrue(int(everyone["deny"]) & S.P["view"] and int(everyone["deny"]) & S.P["send"])
            self.assertEqual(len(self.fake.messages[c["id"]]), 1)
        self.assertFalse([c for c in self.fake.log if c[0] == "DELETE" and "/messages/" in c[1]])

    def test_an_old_guide_with_replies_is_closed_not_deleted(self):
        self.setup_server()
        guides = self.fake.named("guides")
        for name, author in (("Checks and evidence", "u1"), ("Release a design", BOT)):
            t = {"id": self.fake.new_id(), "parent_id": guides["id"], "name": name, "applied_tags": []}
            self.fake.threads.append(t)
            self.fake.messages[t["id"]] = [{"id": t["id"], "author": {"id": BOT}, "type": 0, "content": ""},
                                           {"id": self.fake.new_id(), "author": {"id": author}, "type": 0, "content": "?"}]
        self.setup_server()
        left = {t["name"]: t for t in self.fake.threads if t["parent_id"] == guides["id"]}
        self.assertNotIn("Release a design", left)
        self.assertEqual(left["Checks and evidence"]["thread_metadata"], {"archived": True, "locked": True})


class BotTest(Base):
    def setUp(self):
        super().setUp()
        for i, key in enumerate(["releases", "announcements", "github", "contributing", "mod-log", "guides", "showcase",
                                 "ideas", "roles"]):
            self.fake.channels.append({"id": str(10 + i), "name": S.N(key), "type": 15 if key in ("showcase", "ideas") else 0})
        self.fake.channels.append({"id": "50", "name": S.N("help"), "type": 15, "available_tags": [
            {"id": "t1", "name": "Setup"}, {"id": "t2", "name": "Bug"}, {"id": "t9", "name": "Solved"}]})
        self.fake.roles += [{"id": "r1", "name": "Release pings"}, {"id": "r2", "name": "Contributor"}]

    def said(self, key):
        return self.fake.messages.get(self.fake.named(key)["id"], [])

    def everything(self):
        return [m for msgs in self.fake.messages.values() for m in msgs]

    RELEASE = {"tag_name": "v1.1.0", "name": "Form Studio 1.1.0", "html_url": "https://x/r", "prerelease": False,
               "published_at": "2026-12-01T00:00:00Z", "author": {"login": "kaizensx"},
               "body": ("Faster meshes, and game assets.\n\n### New\n\n- **Imported meshes.** Build in seconds,\n  even the "
                        "large ones.\n- **Game assets (Beta).** LODs and UVs.\n\n### Verify the download\n\nsha256sum -c"),
               "assets": [{"name": "FORM-macos-arm64.zip", "browser_download_url": "https://x/a.zip"},
                          {"name": "FORM-windows-x64.zip", "browser_download_url": "https://x/w.zip"},
                          {"name": "SHA256SUMS", "browser_download_url": "https://x/sums"}]}

    def test_stable_release_is_full_text_in_releases_and_announced_with_one_ping(self):
        post.release({"action": "published", "release": self.RELEASE})
        rel, ann = self.said("releases"), self.said("announcements")
        self.assert_plain(rel + ann)
        text = "\n".join(m["content"] for m in rel)
        self.assertTrue(text.startswith("# Form Studio 1.1.0"))
        self.assertIn("### New", text)
        self.assertIn("- **Imported meshes.** Build in seconds, even the large ones.", text)     # whole, line wraps undone
        self.assertIn("[FORM-macos-arm64.zip](https://x/a.zip)", text)
        self.assertIn("[SHA256SUMS](https://x/sums)", text)
        self.assertNotIn("sha256sum -c", text)
        self.assertIn(f"<#{self.fake.named('guides')['id']}>", text)
        self.assertNotIn("<@&", text)                                        # no ping in #releases
        pings = [m for m in ann if "<@&r1>" in m["content"]]
        self.assertEqual(len(pings), 1)
        self.assertEqual(pings[0]["allowed_mentions"], {"roles": ["r1"]})
        self.assertEqual([m["content"] for m in ann[:-1]], [m["content"] for m in rel])
        self.assertEqual(len([c for c in self.fake.log if c[1].endswith("/crosspost")]), len(ann) - 1)
        self.assertEqual({k for k, v in ((self.fake.chan(c)["name"], v) for c, v in self.fake.messages.items()) if v},
                         {"releases", "announcements"})

    def test_preview_goes_to_releases_only_without_a_ping(self):
        post.release({"action": "published", "release": {**self.RELEASE, "tag_name": "v1.2.0-preview.1",
                                                          "name": "Form Studio 1.2.0 preview 1", "prerelease": True}})
        self.assertEqual(self.said("announcements"), [])
        text = "\n".join(m["content"] for m in self.said("releases"))
        self.assertIn("**Preview.**", text)
        self.assertNotIn("<@&", text)

    def test_long_notes_are_split_and_capped_with_a_link(self):
        body = "\n\n".join(f"### Part {n}\n\n" + "\n".join(f"- **Change {n}.{k}.** " + "word " * 40 for k in range(8))
                           for n in range(20))
        post.post_release({**self.RELEASE, "prerelease": True, "body": body})
        msgs = self.said("releases")
        self.assert_plain(msgs)
        self.assertGreater(len(msgs), 3)
        self.assertLessEqual(len(msgs), post.NOTES_MESSAGES + 3)
        self.assertIn("The notes continue on GitHub", "\n".join(m["content"] for m in msgs))

    def test_a_release_by_tag_can_be_posted_by_hand(self):
        with mock.patch.object(post, "gh", return_value={**self.RELEASE, "prerelease": True}) as gh, \
                mock.patch.object(sys, "argv", ["post.py", "release", "v1.1.0-preview.1"]):
            post.main()
        self.assertIn("/releases/tags/v1.1.0-preview.1", gh.call_args[0][0])
        self.assertTrue(self.said("releases"))

    def test_github_activity_goes_to_one_channel_as_plain_text(self):
        post.issue({"action": "opened", "issue": {"title": "Crash", "html_url": "u", "number": 3, "user": {"login": "a"},
                                                  "body": "# Steps\n> quoted\n@everyone look", "labels": [{"name": "type:bug"}]}})
        post.workflow_run({"action": "completed", "workflow_run": {
            "conclusion": "failure", "head_branch": "dev", "name": "CI", "html_url": "u", "head_sha": "abcdef1234",
            "run_number": 9, "head_commit": {"message": "x"}}})
        post.pull_request({"action": "opened", "pull_request": {
            "title": "Fix", "html_url": "u", "number": 7, "user": {"login": "octo"}, "base": {"ref": "dev"}, "body": "b"}})
        post.discussion({"action": "created", "discussion": {"title": "How?", "html_url": "u", "number": 4, "body": "q",
                                                             "user": {"login": "a"}, "category": {"name": "Q&A", "slug": "q-a"}}})
        post.star({"action": "created", "repository": {"stargazers_count": 100, "html_url": "u"}, "sender": {"login": "z"}})
        msgs = self.said("github")
        self.assert_plain(msgs)
        self.assertEqual([m["content"].split("**")[1] for m in msgs],
                         ["Issue opened", "CI failed", "Pull request opened", "Discussion", "100 stars on GitHub."])
        self.assertNotIn("@everyone", msgs[0]["content"])
        self.assertEqual({self.fake.chan(c)["name"] for c, v in self.fake.messages.items() if v}, {"github"})

    def test_a_release_announcement_discussion_is_not_mirrored(self):
        post.discussion({"action": "created", "discussion": {
            "title": "Form Studio 1.1.0 is out", "html_url": "u", "number": 9, "body": "notes", "user": {"login": "a"},
            "category": {"name": "Announcements", "slug": "announcements"}}})
        self.assertEqual(self.everything(), [])

    def test_merged_pull_request_from_a_listed_contributor_gives_the_role(self):
        with mock.patch.dict(S.CONTRIBUTORS, {"octo": "u42"}):
            post.pull_request({"action": "closed", "pull_request": {
                "merged": True, "title": "Fix", "html_url": "u", "number": 7, "user": {"login": "octo"},
                "base": {"ref": "dev"}}})
        self.assertIn(("PUT", f"/guilds/{GUILD}/members/u42/roles/r2", None), self.fake.log)
        self.assertIn("<@u42>", self.said("contributing")[0]["content"])

    def test_the_digest_goes_to_github_and_a_quiet_week_posts_nothing(self):
        def gh(path, commits=()):
            if "/commits" in path:
                return list(commits)
            if "/releases" in path:
                return []
            if "/search/" in path:
                return {"total_count": 2 if commits else 0}
            return {"html_url": "u", "stargazers_count": 1, "forks_count": 0}
        with mock.patch.object(post, "gh", side_effect=gh):
            post.digest()
        self.assertEqual(self.everything(), [])
        c = [{"parents": [1], "commit": {"message": "Home: calmer copy\n\nbody"}}]
        with mock.patch.object(post, "gh", side_effect=lambda p: gh(p, c)):
            post.digest()
        self.assert_plain(self.said("github"))
        self.assertIn("- Home: calmer copy", self.said("github")[0]["content"])
        self.assertEqual(self.said("announcements"), [])

    def help_post(self, age: timedelta, quiet: timedelta, tags=("t1",), msgs=()):
        now = datetime.now(timezone.utc)
        t = {"id": snowflake(now - age), "parent_id": "50", "name": "Install fails", "owner_id": "u1",
             "applied_tags": list(tags), "last_message_id": snowflake(now - quiet)}
        self.fake.threads.append(t)
        self.fake.messages[t["id"]] = [{"id": "1", "author": {"id": "u1"}, "content": "help"}, *msgs]
        return t

    def run_helpdesk(self):
        with mock.patch.object(sys, "argv", ["helpdesk.py"]):
            helpdesk.main()

    def test_help_desk_answers_a_new_post_once_in_plain_text_and_lists_it(self):
        guide = {"id": "777", "parent_id": self.fake.named("guides")["id"], "name": "Getting started"}
        self.fake.threads.append(guide)
        new = self.help_post(timedelta(hours=7), timedelta(hours=7), ("t1", "t2"))
        solved = self.help_post(timedelta(days=3), timedelta(days=2), ("t9",))
        self.run_helpdesk()
        replies = [m for m in self.fake.messages[new["id"]] if m["author"]["id"] == BOT]
        self.assertEqual(len(replies), 1)
        self.assert_plain(replies)
        self.assertIn("<#777>", replies[0]["content"])
        self.assertIn("template=1-bug.yml", replies[0]["content"])
        self.assertTrue(self.fake.chan(solved["id"])["thread_metadata"]["archived"])
        queue = self.said("mod-log")
        self.assert_plain(queue)
        self.assertIn(f"<#{new['id']}>", queue[0]["content"])
        self.run_helpdesk()                                                 # again: no second reply, no second queue
        self.assertEqual(len([m for m in self.fake.messages[new["id"]] if m["author"]["id"] == BOT]), 1)
        self.assertEqual(len(self.said("mod-log")), 1)

    def test_help_desk_reminds_a_quiet_post_then_archives_it(self):
        answered = [{"id": "2", "author": {"id": BOT}, "content": "**Thanks for the post.**"},
                    {"id": "3", "author": {"id": "u2"}, "content": "try this"}]
        t = self.help_post(timedelta(days=9), timedelta(days=8), msgs=answered)
        self.run_helpdesk()
        nudge = self.fake.messages[t["id"]][-1]
        self.assertTrue(nudge["content"].startswith(helpdesk.NUDGE))
        self.assertEqual(nudge["allowed_mentions"], {"users": ["u1"]})
        self.assertFalse((self.fake.chan(t["id"]).get("thread_metadata") or {}).get("archived"))
        t["last_message_id"] = snowflake(datetime.now(timezone.utc) - timedelta(days=8))
        self.run_helpdesk()
        self.assertTrue(self.fake.chan(t["id"])["thread_metadata"]["archived"])


class LayoutTest(unittest.TestCase):
    def test_names_are_plain(self):
        for cat, chans in S.LAYOUT:
            self.assertTrue(cat.isascii() and cat.isupper(), cat)
            for key, name, type_, topic, opts in chans:
                self.assertTrue(name.isascii(), name)
                if type_ != S.VOICE:
                    self.assertRegex(name, r"^[a-z][a-z0-9-]*$")
                self.assertLessEqual(len(topic), 4096 if type_ == S.FORUM else 1024, name)
        for name, *_ in S.ROLES:
            self.assertTrue(name.isascii(), name)

    def test_only_releases_posts_releases(self):
        topics = {k: t for _, cs in S.LAYOUT for k, _, _, t, _ in cs}
        self.assertIn("only channel that posts releases", topics["releases"])
        self.assertEqual([k for k, n in S.NAMES.items() if "release" in n], ["releases"])

    def test_onboarding_roles_and_guides_point_at_what_exists(self):
        roles = {r[0] for r in S.ROLES}
        chans = {k for _, cs in S.LAYOUT for k, *_ in cs}
        for _, options in S.ONBOARDING:
            for _, _, emoji, rs, cs in options:
                self.assertTrue(emoji and set(rs) <= roles and set(cs) <= chans and (rs or cs), (rs, cs))
        for _, _, names in S.ROLE_PICKER:
            self.assertTrue(set(names) <= roles and set(names) <= set(S.ROLE_EMOJI))
        self.assertLessEqual(len(S.ROLE_PICKER), 5)
        self.assertTrue({n for _, n in S.LEVELS} <= roles)
        self.assertFalse(set(S.ROLE_RETIRE) & roles)
        titles = {g[1] for g in S.GUIDES}
        tags = {setup_server.tag(t)["name"] for _, cs in S.LAYOUT for k, _, _, _, o in cs if k == "guides" for t in o["tags"]}
        help_tags = {setup_server.tag(t)["name"] for _, cs in S.LAYOUT for k, _, _, _, o in cs if k == "help" for t in o["tags"]}
        self.assertEqual(set(S.HELP_GUIDES) | {"Solved"}, help_tags)
        for guides in S.HELP_GUIDES.values():
            self.assertTrue(set(guides) <= titles)
        for slug, title, tag, *_ in S.GUIDES:
            self.assertIn(tag, tags)
            self.assertTrue((S.GUIDE_DIR / f"{slug}.md").exists(), slug)
            self.assertTrue((HERE / "art" / "guides" / f"{slug}.png").exists(), slug)
            self.assertTrue(S.guide_text(slug).startswith("# "))
        self.assertFalse(set(S.GUIDE_RETIRE) & titles)
        # onboarding needs seven default channels, five of them open to everyone
        defaults = [(k, o) for _, cs in S.LAYOUT for k, _, t, _, o in cs if o.get("default") and t != S.VOICE]
        self.assertGreaterEqual(len(defaults), 7)
        self.assertGreaterEqual(len([k for k, o in defaults if not o.get("access")]), 5)

    def test_guides_read_the_same_on_github_and_in_discord(self):
        names = set(S.NAMES.values())
        for slug, *_ in S.GUIDES:
            text = S.guide_text(slug)
            self.assertNotRegex(text, r"(?m)^\|", f"{slug}: no tables (Discord has none)")
            self.assertNotRegex(text, r"(?m)^>", f"{slug}: no quote blocks")
            self.assertNotRegex(text, r"<(p|img|details|br|sub)\b", f"{slug}: no HTML")
            self.assertNotRegex(text, r"!\[", f"{slug}: no pictures")
            self.assertNotRegex(text, r"\]\((?!https://)", f"{slug}: links carry their full address")
            prose = re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.S)
            for ch in re.findall(r"(?<![\w/#(\[])#([a-z][a-z0-9-]+)\b", prose):
                self.assertIn(ch, names, f"{slug}: #{ch} is not a channel")
            self.assertNotIn("Co-Authored", text)

    def test_automod_fits_discords_limits(self):
        kinds = [t for _, t, _, _ in S.AUTOMOD]
        for one in (S.SPAM, S.PRESET, S.MENTION_SPAM, S.PROFILE):
            self.assertEqual(kinds.count(one), 1)
        self.assertLessEqual(kinds.count(S.KEYWORD), 6)
        for name, _, meta, actions in S.AUTOMOD:
            self.assertLessEqual(len(meta.get("regex_patterns", [])), 10, name)
            for rx in meta.get("regex_patterns", []):
                self.assertLessEqual(len(rx), 260, name)
                self.assertNotRegex(rx, r"\\[1-9]", f"{name}: Discord's regex has no backreferences")
            for kw in meta.get("keyword_filter", []):
                self.assertLessEqual(len(kw), 60, name)
                self.assertNotIn("*", kw.strip("*"), f"{name}: a wildcard only starts or ends a keyword")
            self.assertIn("alert", actions)

    def test_posts_fit_and_say_nothing_about_who_wrote_them(self):
        for text in (S.WELCOME, S.RULES_POST, S.ROLES_POST, S.CONTRIBUTING_POST, S.STAFF_POST):
            for seg in text.split("\n===\n"):
                for part in d.split_text(seg):
                    self.assertLessEqual(len(part), d.LIMIT)
            self.assertNotRegex(text, r"(?m)^>")
        self.assertLessEqual(len(S.CONTRIBUTING_POST) + 200, d.LIMIT)       # one pinned message each, with channel links
        self.assertLessEqual(len(S.STAFF_POST) + 200, d.LIMIT)

    def test_split_text_keeps_code_blocks_whole(self):
        text = "# T\n\nintro\n\n## A\n\n" + "word " * 300 + "\n\n```bash\n" + "cmd\n\n" * 40 + "```\n\n## B\n\nend"
        parts = d.split_text(text, lead=True)
        self.assertEqual(parts[0], "# T\n\nintro")
        self.assertTrue(all(len(p) <= 1900 and p.count("```") % 2 == 0 for p in parts))
        self.assertEqual(re.sub(r"\s+", "", "".join(parts)), re.sub(r"\s+", "", text))


class WorkerTest(unittest.TestCase):
    def test_config_matches_server_py(self):
        import export_config
        self.assertEqual(export_config.OUT.read_text(encoding="utf-8"), export_config.render(),
                         "run python scripts/discord/export_config.py")

    def test_worker(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        r = subprocess.run([node, str(HERE / "worker" / "test.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
