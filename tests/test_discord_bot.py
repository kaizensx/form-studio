"""The Discord bot (scripts/discord) against a fake Discord: what each GitHub event posts, and the help desk."""
from __future__ import annotations

import json
import os
import sys
import tempfile
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

GUILD = "100"


def snowflake(when: datetime) -> str:
    return str((int(when.timestamp() * 1000) - 1420070400000) << 22)


class FakeDiscord:
    def __init__(self):
        self.sent, self.patched, self.puts = [], [], []
        self.channels = [{"id": str(10 + i), "name": S.N(n), "type": 0} for i, n in enumerate(
            ["releases", "announcements", "github", "ci", "contributing", "mod-log", "guides"])]
        self.channels.append({"id": "50", "name": S.N("help"), "type": 15, "available_tags": [
            {"id": "t1", "name": "Install"}, {"id": "t2", "name": "Bug"}, {"id": "t9", "name": "Solved"}]})
        self.roles = [{"id": "r1", "name": S.R["Release pings"]}, {"id": "r2", "name": S.R["Contributor"]}]
        self.threads, self.messages = [], {}

    def call(self, method, path, body=None, *, files=None, reason=""):
        if path == "/users/@me":
            return {"id": "bot"}
        if path.endswith("/channels") and method == "GET":
            return self.channels
        if path.endswith("/roles"):
            return self.roles
        if path.endswith("/threads/active"):
            return {"threads": self.threads}
        if "/threads/archived/public" in path:
            return {"threads": []}
        if path.startswith(f"/guilds/{GUILD}/members/") and method == "GET":
            return {"roles": []}
        if method == "GET" and path.startswith("/channels/") and "/messages" in path:
            return self.messages.get(path.split("/")[2], [])
        if method == "POST" and path.endswith("/messages"):
            self.sent.append((path.split("/")[2], body))
            return {"id": "m" + str(len(self.sent))}
        if method == "PATCH":
            self.patched.append((path, body))
            return {}
        if method == "PUT":
            self.puts.append(path)
            return None
        return {}

    def name_of(self, cid):
        n = next((c["name"] for c in self.channels if c["id"] == cid), cid)
        return next((k for k, v in S.NAMES.items() if v == n), n)


class BotTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDiscord()
        self.env = mock.patch.dict(os.environ, {"DISCORD_GUILD_ID": GUILD, "DISCORD_BOT_TOKEN": "x"})
        self.env.start()
        self.patch = mock.patch.object(d, "call", side_effect=self.fake.call)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.env.stop()

    def posted(self):
        return [(self.fake.name_of(c), b) for c, b in self.fake.sent]

    def test_stable_release_goes_to_releases_and_announcements_with_the_ping(self):
        post.release({"action": "published", "release": {
            "tag_name": "v1.1.0", "name": "Form Studio 1.1.0", "html_url": "https://x/r", "prerelease": False,
            "published_at": "2026-12-01T00:00:00Z", "author": {"login": "kaizensx"},
            "body": "Faster meshes.\n\n- **Imported meshes.** Build in seconds.\n\n### Verify the download\nsha",
            "assets": [{"name": "FormStudio-macos-arm64.dmg", "browser_download_url": "https://x/a.dmg"}]}})
        where = [c for c, _ in self.posted()]
        self.assertEqual(where, ["releases", "announcements"])
        body = self.posted()[0][1]
        self.assertIn("<@&r1>", body["content"])
        emb = body["embeds"][0]
        self.assertEqual(emb["fields"][0]["name"], "Imported meshes")
        self.assertEqual(emb["footer"]["text"], "Form Studio · Release v1.1.0")
        self.assertNotIn("Verify", json.dumps(emb))

    def test_preview_goes_to_releases_only_without_a_ping(self):
        post.release({"action": "published", "release": {
            "tag_name": "v1.1.0-preview.1", "html_url": "https://x/r", "prerelease": True, "author": {"login": "k"},
            "body": "", "assets": []}})
        self.assertEqual([c for c, _ in self.posted()], ["releases"])
        self.assertNotIn("<@&", self.posted()[0][1]["content"])

    def test_event_titles_carry_no_emoji(self):
        post.issue({"action": "opened", "issue": {"title": "Crash", "html_url": "u", "number": 3, "user": {"login": "a"},
                                                  "body": "b", "labels": []}})
        post.workflow_run({"action": "completed", "workflow_run": {
            "conclusion": "failure", "head_branch": "dev", "name": "CI", "html_url": "u", "head_sha": "abcdef1234",
            "run_number": 9, "head_commit": {"message": "x"}}})
        titles = [b["embeds"][0]["title"] for _, b in self.posted()]
        self.assertEqual(titles, ["New issue: Crash", "CI failed on dev"])
        self.assertTrue(all(t.isascii() for t in titles))

    def test_merged_pull_request_from_a_listed_contributor_gives_the_role(self):
        with mock.patch.dict(S.CONTRIBUTORS, {"octo": "u42"}):
            post.pull_request({"action": "closed", "pull_request": {
                "merged": True, "title": "Fix", "html_url": "u", "number": 7, "user": {"login": "octo"},
                "base": {"ref": "dev"}}})
        self.assertIn(f"/guilds/{GUILD}/members/u42/roles/r2", self.fake.puts)
        self.assertIn("contributing", [c for c, _ in self.posted()])

    def test_quiet_week_posts_no_digest(self):
        def gh(path):
            if "/commits" in path or "/releases" in path:
                return []
            if "/search/" in path:
                return {"total_count": 0}
            return {"html_url": "u", "stargazers_count": 1, "forks_count": 0}
        with mock.patch.object(post, "gh", side_effect=gh):
            post.digest()
        self.assertEqual(self.posted(), [])

    def test_help_desk_answers_a_new_post_once_and_archives_solved_ones(self):
        now = datetime.now(timezone.utc)
        new = {"id": snowflake(now - timedelta(hours=7)), "parent_id": "50", "name": "Install fails", "owner_id": "u1",
               "applied_tags": ["t1"], "last_message_id": snowflake(now - timedelta(hours=7))}
        solved = {"id": snowflake(now - timedelta(days=3)), "parent_id": "50", "name": "Done", "owner_id": "u2",
                  "applied_tags": ["t9"], "last_message_id": snowflake(now - timedelta(days=2))}
        guide = {"id": "g1", "parent_id": "16", "name": "Install and first start"}
        self.fake.threads = [new, solved, guide]
        self.fake.messages[new["id"]] = [{"author": {"id": "u1"}}]
        with mock.patch.object(sys, "argv", ["helpdesk.py"]):
            helpdesk.main()
        replies = [(c, b) for c, b in self.fake.sent if c == new["id"]]
        self.assertEqual(len(replies), 1)
        self.assertIn("<#g1>", json.dumps(replies[0][1]))
        self.assertIn((f"/channels/{solved['id']}", {"archived": True}), self.fake.patched)
        queue = [b for c, b in self.fake.sent if self.fake.name_of(c) == "mod-log"]
        self.assertIn(f"<#{new['id']}>", queue[0]["embeds"][0]["description"])


class LayoutTest(unittest.TestCase):
    def test_names_follow_the_design_system(self):
        for cat, chans in S.LAYOUT:
            emoji, _, words = cat.partition(" ")
            self.assertTrue(not emoji.isascii() and words.isupper(), cat)
            for key, name, type_, topic, opts in chans:
                if type_ not in (S.VOICE, S.STAGE):
                    self.assertTrue("・" in name and name == name.lower(), name)
                self.assertLessEqual(len(topic), 4096 if type_ == S.FORUM else 1024, name)
                self.assertLessEqual(len(name), 100)

    def test_onboarding_and_guides_point_at_what_exists(self):
        roles = {r[0] for r in S.ROLES}
        chans = {k for _, cs in S.LAYOUT for k, *_ in cs}
        for _, options in S.ONBOARDING:
            for _, _, _, rs, cs in options:
                self.assertTrue(set(rs) <= roles and set(cs) <= chans, (rs, cs))
        for _, _, names in S.ROLE_PICKER:
            self.assertTrue(set(names) <= roles)
        self.assertTrue({n for _, n in S.LEVELS} <= roles)
        titles = {g[0] for g in S.GUIDES}
        for guides in S.HELP_GUIDES.values():
            self.assertTrue(set(guides) <= titles)
        for i in range(1, len(S.GUIDES) + 1):
            self.assertTrue((HERE / "art" / "guides" / f"{i:02d}.png").exists())


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
