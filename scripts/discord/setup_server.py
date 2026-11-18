"""Make the Form Studio Discord server match scripts/discord/server.py.

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/setup_server.py [--dry-run]

Idempotent: roles, categories and channels are matched by name and created or updated; nothing is deleted.
Welcome and rules posts are written once (and replaced when their text changes). Runs in GitHub Actions
(.github/workflows/discord.yml, "Set up the server").
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402
import server as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "scripts" / "discord" / "art"

SEND = 1 << 11
SEND_THREADS = 1 << 38
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
ADD_REACTIONS = 1 << 6
READ_ONLY_DENY = SEND | SEND_THREADS | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS


def log(*a):
    print(*a, flush=True)


class Setup:
    def __init__(self, guild: str, dry: bool):
        self.g, self.dry = guild, dry
        self.me = d.call("GET", "/users/@me")
        self.guild = d.call("GET", f"/guilds/{guild}?with_counts=true")
        self.roles = {r["name"]: r for r in d.call("GET", f"/guilds/{guild}/roles")}
        self.channels = d.call("GET", f"/guilds/{guild}/channels")
        self.everyone = guild                                   # @everyone's role id is the guild id

    def _do(self, method, path, body=None, what=""):
        log(("would " if self.dry else "") + what)
        if self.dry:
            return {"id": "0", **(body or {})}
        return d.call(method, path, body, reason="Form Studio server setup")

    # ---- roles ---------------------------------------------------------------------------------------
    def ensure_roles(self):
        for name, colour, hoist, mention, _ in S.ROLES:
            body = {"name": name, "color": colour, "hoist": hoist, "mentionable": mention}
            r = self.roles.get(name)
            if r is None:
                self.roles[name] = self._do("POST", f"/guilds/{self.g}/roles", {**body, "permissions": "0"}, f"create role {name}")
            elif (r["color"], r["hoist"], r["mentionable"]) != (colour, hoist, mention) and not r.get("managed"):
                self._do("PATCH", f"/guilds/{self.g}/roles/{r['id']}", body, f"update role {name}")

    # ---- channels ------------------------------------------------------------------------------------
    def find(self, name, type_, parent=None):
        for c in self.channels:
            if c["name"] == name and c["type"] == type_ and (parent is None or c.get("parent_id") == parent):
                return c
        # a text channel that should be news (or the reverse) is still the same channel
        for c in self.channels:
            if c["name"] == name and {c["type"], type_} <= {S.TEXT, S.NEWS}:
                return c
        return None

    def overwrites(self, opts):
        out = []
        if opts.get("read_only"):
            out.append({"id": self.everyone, "type": 0, "allow": str(ADD_REACTIONS), "deny": str(READ_ONLY_DENY)})
            m = self.roles.get("Maintainer")
            if m:
                out.append({"id": m["id"], "type": 0, "allow": str(SEND | SEND_THREADS), "deny": "0"})
            out.append({"id": self.me["id"], "type": 1, "allow": str(SEND | SEND_THREADS), "deny": "0"})
        return out

    def ensure_channels(self):
        pos = 0
        for cat_name, chans in S.LAYOUT:
            cat = self.find(cat_name, S.CATEGORY)
            if cat is None:
                cat = self._do("POST", f"/guilds/{self.g}/channels", {"name": cat_name, "type": S.CATEGORY, "position": pos},
                               f"create category {cat_name}")
                self.channels.append(cat)
            pos += 1
            for i, (name, type_, topic, opts) in enumerate(chans):
                body = {"name": name, "type": type_, "parent_id": cat["id"], "position": i,
                        "permission_overwrites": self.overwrites(opts)}
                if type_ in (S.TEXT, S.NEWS, S.FORUM):
                    body["topic"] = topic
                    body["rate_limit_per_user"] = opts.get("slowmode", 0)
                if type_ == S.FORUM:
                    body["available_tags"] = [{"name": t} for t in opts.get("tags", [])]
                    body["default_reaction_emoji"] = {"emoji_name": opts.get("emoji", "👍")}
                    body["default_sort_order"] = 0
                    body["default_forum_layout"] = 2 if name == "showcase" else 1   # gallery for the showcase
                c = self.find(name, type_)
                if c is None:
                    if type_ == S.NEWS and "COMMUNITY" not in self.guild.get("features", []):
                        body["type"] = S.TEXT                             # announcement channels need a community server
                    c = self._do("POST", f"/guilds/{self.g}/channels", body, f"create #{name}")
                    self.channels.append(c)
                else:
                    if type_ == S.FORUM:                                  # keep tags that exist (posts use their ids)
                        have = {t["name"]: t for t in c.get("available_tags", [])}
                        body["available_tags"] = [have.get(t, {"name": t}) for t in opts.get("tags", [])] + \
                            [t for n, t in have.items() if n not in opts.get("tags", [])]
                    body.pop("type")
                    self._do("PATCH", f"/channels/{c['id']}", body, f"update #{name}")

    def channel(self, name):
        for c in self.channels:
            if c["name"] == name:
                return c
        raise SystemExit(f"no #{name}")

    # ---- community, onboarding, icon ---------------------------------------------------------------
    def ensure_community(self):
        feats = set(self.guild.get("features", []))
        body = {"rules_channel_id": self.channel("rules")["id"], "public_updates_channel_id": self.channel("ci")["id"],
                "system_channel_id": self.channel("general")["id"], "system_channel_flags": 0b1100,
                "verification_level": max(1, self.guild.get("verification_level", 0)),
                "explicit_content_filter": 2, "description":
                "Form Studio: describe a part, get a file you can print. Open-source AI to CAD."}
        if "COMMUNITY" not in feats:
            body["features"] = sorted(feats | {"COMMUNITY"})
        icon = ART / "icon.png"
        if icon.exists() and not self.guild.get("icon"):
            body["icon"] = "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode()
        try:
            self.guild = self._do("PATCH", f"/guilds/{self.g}", body, "community server, rules, updates channel, icon")
        except d.DiscordError as e:
            log(f"community: {e}")
        # #announcements becomes an announcement channel once the server is a community
        a = self.channel("announcements")
        if a["type"] != S.NEWS and "COMMUNITY" in self.guild.get("features", []):
            try:
                self._do("PATCH", f"/channels/{a['id']}", {"type": S.NEWS}, "#announcements as an announcement channel")
            except d.DiscordError as e:
                log(f"announcements: {e}")

    def ensure_onboarding(self):
        prompts = []
        try:
            have = {p["title"]: p for p in d.call("GET", f"/guilds/{self.g}/onboarding").get("prompts", [])}
        except d.DiscordError:
            have = {}
        base = int(self.g) + 1                                    # new prompts and options need snowflake-shaped ids
        for i, (title, names, emoji) in enumerate(S.ONBOARDING):
            old = {o["title"]: o["id"] for o in have.get(title, {}).get("options", [])}
            opts = [{"id": old.get(n, str(base + 100 * (i + 1) + j)), "title": n, "emoji": {"name": e},
                     "role_ids": [self.roles[n]["id"]], "channel_ids": []}
                    for j, (n, e) in enumerate(zip(names, emoji)) if n in self.roles]
            prompts.append({"id": have.get(title, {}).get("id", str(base + i)), "type": 0, "title": title,
                            "options": opts, "single_select": False,
                            "required": False, "in_onboarding": True})
        # default channels must be open to @everyone: the ones without an @everyone overwrite (not read-only)
        self.channels = d.call("GET", f"/guilds/{self.g}/channels")
        defaults = [c["id"] for c in self.channels if c["type"] in (S.TEXT, S.NEWS, S.FORUM)
                    and not any(o["id"] == self.everyone for o in c.get("permission_overwrites", []))]
        try:
            self._do("PUT", f"/guilds/{self.g}/onboarding",
                     {"prompts": prompts, "default_channel_ids": defaults, "enabled": True, "mode": 0},
                     "onboarding questions (printer, agent, release pings)")
        except d.DiscordError as e:
            log(f"onboarding: {e}")

    # ---- the posts that make the server ---------------------------------------------------------------
    def _bot_messages(self, ch):
        try:
            return [m for m in d.call("GET", f"/channels/{ch}/messages?limit=50") if m["author"]["id"] == self.me["id"]]
        except d.DiscordError:
            return []

    def post_once(self, ch_name, key, embeds, components=None, files=None):
        """Post a set of embeds once; when their text changes, the old post is removed and the new one pinned."""
        ch = self.channel(ch_name)["id"]
        sig = hashlib.sha1(repr((embeds, components)).encode()).hexdigest()[:10]
        stamp = f"{key} · {sig}"
        old = [m for m in self._bot_messages(ch) if any((e.get("footer") or {}).get("text", "") == stamp
                                                          for e in m.get("embeds", []))]
        if old:
            log(f"#{ch_name}: {key} is current")
            return
        for m in self._bot_messages(ch):
            if any((e.get("footer") or {}).get("text", "").startswith(key + " · ") for e in m.get("embeds", [])):
                self._do("DELETE", f"/channels/{ch}/messages/{m['id']}", None, f"#{ch_name}: remove the old {key}")
        embeds[-1]["footer"] = {"text": stamp}
        log(("would post " if self.dry else "post ") + f"#{ch_name}: {key}")
        if self.dry:
            return
        m = d.send(ch, embeds=embeds, components=components, files=files)
        try:
            d.call("PUT", f"/channels/{ch}/pins/{m['id']}")
        except d.DiscordError:
            pass

    def welcome(self):
        files = {}
        for name in ("welcome.gif", "banner.png"):                  # the animated one when it is there
            if (ART / name).exists():
                files[name] = (ART / name).read_bytes()
                break
        c = lambda n: f"<#{self.channel(n)['id']}>"   # noqa: E731
        hero = {"color": d.DATUM, "image": {"url": "attachment://" + next(iter(files))} if files else None,
                "title": "What are we making?",
                "description": ("**Form Studio** is an open-source desktop app where an AI agent designs parts in a real "
                                "CAD kernel. Form Studio checks every revision on the solid, slices it with your own slicer "
                                "and plays the print back before you start it.\n\n"
                                "Describe it, drop a photo with a coin for scale, sketch it or bring a part. "
                                "It comes back as real CAD you can measure, prove and release.")}
        hero = {k: v for k, v in hero.items() if v is not None}
        where = {"color": d.PLATE, "title": "Where things are", "fields": [
            {"name": "🧊 Show what you made", "value": f"{c('showcase')} · {c('prints')}", "inline": True},
            {"name": "🛟 Get help", "value": f"{c('help')} · {c('printers-and-slicers')} · {c('agents-and-models')}", "inline": True},
            {"name": "💡 Ideas", "value": c("ideas"), "inline": True},
            {"name": "🧩 Recipes", "value": c("recipes"), "inline": True},
            {"name": "🚀 Releases", "value": f"{c('releases')} · {c('announcements')}", "inline": True},
            {"name": "🛠 Build it with us", "value": f"{c('contributing')} · {c('github')}", "inline": True}]}
        how = {"color": d.BLUEPRINT, "title": "How a design goes", "description":
               "`1` **Start** — words, a photo, a sketch, a STEP/STL/3MF part, a PDF or a link\n"
               "`2` **Concepts** — three or four genuinely different designs, each real CAD\n"
               "`3` **Shape & fit** — parameters with provenance, fits modelled against your printer\n"
               "`4` **Prove** — checks on the solid, the slice from your slicer, the print played back\n"
               "`5` **Release** — you approve; STEP, STL, 3MF and G-code frozen with SHA-256 hashes"}
        buttons = [d.row(d.link_button("Download", S.REPO + "/releases/latest", "⬇️"),
                         d.link_button("Try it in your browser", S.SITE + "#try", "🧊"),
                         d.link_button("GitHub", S.REPO, "⭐"),
                         d.link_button("Docs", S.SITE + "docs/", "📘"))]
        self.post_once("welcome", "welcome", [hero, where, how], buttons, files or None)

    def rules(self):
        fields = [{"name": f"`{i}`  {t}", "value": v, "inline": False} for i, (t, v) in enumerate(S.RULES, 1)]
        self.post_once("rules", "rules", [{"color": d.AMBER, "title": "Rules", "fields": fields,
                                           "description": "Short, so they get read. Moderators may remove what breaks them."}])

    def ensure_profile(self):
        """The bot's own picture and profile banner, once."""
        body = {}
        if not self.me.get("avatar") and (ART / "icon.png").exists():
            body["avatar"] = "data:image/png;base64," + base64.b64encode((ART / "icon.png").read_bytes()).decode()
        if not self.me.get("banner") and (ART / "profile-banner.png").exists():
            body["banner"] = "data:image/png;base64," + base64.b64encode((ART / "profile-banner.png").read_bytes()).decode()
        if body:
            try:
                self._do("PATCH", "/users/@me", body, "bot avatar and banner")
            except d.DiscordError as e:
                log(f"profile: {e}")

    def run(self):
        log(f"server: {self.guild['name']} · bot: {self.me['username']}")
        self.ensure_profile()
        self.ensure_roles()
        self.ensure_channels()
        self.ensure_community()
        self.ensure_onboarding()
        self.welcome()
        self.rules()
        log("done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    guild = os.environ.get("DISCORD_GUILD_ID", "").strip()
    if not guild:
        raise SystemExit("DISCORD_GUILD_ID is not set")
    Setup(guild, a.dry_run).run()


if __name__ == "__main__":
    main()
