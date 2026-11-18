"""Make the Form Studio Discord server match scripts/discord/server.py.

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/setup_server.py [--dry-run]

Idempotent. Roles, categories and channels are matched by name and created, renamed, moved or updated. Only what
server.RETIRE lists is deleted, and only while it is empty. The pinned posts (#welcome, #rules, #contributing) and the
forum posts (#guides, #recipes) are edited in place when their content changes. Runs in GitHub Actions
(.github/workflows/discord.yml, "setup"), between a before and an after snapshot.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402
import server as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "scripts" / "discord" / "art"
RECIPES = ROOT / "site" / "recipes" / "index.json"

VIEW = 1 << 10
SEND = 1 << 11
ADD_REACTIONS = 1 << 6
HISTORY = 1 << 16
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_THREADS = 1 << 38
POSTING = SEND | SEND_THREADS | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS
STAFF_ALLOW = VIEW | SEND | SEND_THREADS | HISTORY
REQUIRE_TAG, PINNED = 1 << 4, 1 << 1


def log(*a):
    print(*a, flush=True)


def sig_of(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


def current_sig(msg) -> str:
    for e in msg.get("embeds", []):
        url = (e.get("footer") or {}).get("icon_url", "")
        if "?v=" in url:
            return url.rsplit("?v=", 1)[1]
    return ""


class Setup:
    def __init__(self, guild: str, dry: bool):
        self.g, self.dry = guild, dry
        self.me = d.call("GET", "/users/@me")
        self.guild = d.call("GET", f"/guilds/{guild}?with_counts=true")
        self.roles = {r["name"]: r for r in d.call("GET", f"/guilds/{guild}/roles")}
        self.channels = d.call("GET", f"/guilds/{guild}/channels")
        self.everyone = guild                                   # @everyone's role id is the guild id
        self.notes: list[str] = []                              # what a person still has to do, for the summary

    def _do(self, method, path, body=None, what="", files=None):
        log(("would " if self.dry else "") + what)
        if self.dry:
            return {"id": "0", **(body if isinstance(body, dict) else {})}
        return d.call(method, path, body, files=files, reason="Form Studio server setup")

    def _try(self, what, fn):
        try:
            return fn()
        except d.DiscordError as e:
            log(f"{what}: {e}")
            self.notes.append(f"{what}: {str(e)[:200]}")

    # ---- roles ---------------------------------------------------------------------------------------
    def ensure_roles(self):
        for old, new in S.ROLE_RENAMES.items():
            r = self.roles.get(old)
            if r and new not in self.roles:
                self._do("PATCH", f"/guilds/{self.g}/roles/{r['id']}", {"name": new}, f"rename role {old} to {new}")
                self.roles[new] = {**r, "name": new}
                del self.roles[old]
        for name, colour, hoist, mention in S.ROLES:
            body = {"name": name, "color": colour, "hoist": hoist, "mentionable": mention}
            r = self.roles.get(name)
            if r is None:
                self.roles[name] = self._do("POST", f"/guilds/{self.g}/roles", {**body, "permissions": "0"},
                                            f"create role {name}")
            elif (r["color"], r["hoist"], r["mentionable"]) != (colour, hoist, mention) and not r.get("managed"):
                self._do("PATCH", f"/guilds/{self.g}/roles/{r['id']}", body, f"update role {name}")
        # order: the bot's own role on top, then the list as written; other roles keep their place below
        mine = [r for r in self.roles.values() if r.get("managed") and r.get("tags", {}).get("bot_id") == self.me["id"]]
        named = [self.roles[n] for n, *_ in S.ROLES if n in self.roles]
        others = [r for r in self.roles.values() if r not in named and r not in mine and r["id"] != self.everyone]
        order = list(reversed(named)) + others
        want = [{"id": r["id"], "position": i} for i, r in enumerate(order, 1)]
        if any(self.roles_by_id().get(w["id"], {}).get("position") != w["position"] for w in want):
            self._try("role order", lambda: self._do("PATCH", f"/guilds/{self.g}/roles", want, "order the roles"))
            if mine and mine[0]["position"] <= len(order) and not self.dry:
                fresh = {r["id"]: r for r in d.call("GET", f"/guilds/{self.g}/roles")}
                if fresh[mine[0]["id"]]["position"] <= max(fresh[r["id"]]["position"] for r in named):
                    self.notes.append("Drag the Form Studio role to the top of Server Settings › Roles, "
                                      "so the bot can give and order the roles below it.")

    def roles_by_id(self):
        return {r["id"]: r for r in self.roles.values()}

    def ensure_members(self):
        """Recognition: the owner and MAINTAINERS are Maintainers; CONTRIBUTORS and RECIPE_AUTHORS get their roles."""
        give = [(self.guild["owner_id"], "Maintainer")] + [(u, "Maintainer") for u in S.MAINTAINERS]
        give += [(u, "Contributor") for u in S.CONTRIBUTORS.values()]
        give += [(u, "Recipe author") for u in S.RECIPE_AUTHORS.values()]
        for user, role in give:
            r = self.roles.get(role)
            if not r or not user:
                continue
            try:
                m = d.call("GET", f"/guilds/{self.g}/members/{user}")
            except d.DiscordError:
                continue                                          # not on the server (yet)
            if r["id"] not in m.get("roles", []):
                self._try(f"give {role}", lambda: self._do(
                    "PUT", f"/guilds/{self.g}/members/{user}/roles/{r['id']}", None, f"give {role} to {user}"))

    # ---- channels ------------------------------------------------------------------------------------
    def find(self, name, type_=None):
        for c in self.channels:
            if c["name"] == name and (type_ is None or c["type"] == type_ or {c["type"], type_} <= {S.TEXT, S.NEWS}):
                return c
        return None

    def overwrites(self, opts):
        access = opts.get("access")
        m = self.roles.get("Maintainer")
        staff = [{"id": self.me["id"], "type": 1, "allow": str(STAFF_ALLOW), "deny": "0"}]
        if m:
            staff.insert(0, {"id": m["id"], "type": 0, "allow": str(STAFF_ALLOW), "deny": "0"})
        if access == "read_only":
            return [{"id": self.everyone, "type": 0, "allow": str(ADD_REACTIONS), "deny": str(POSTING)}] + staff
        if access == "replies":                                   # a forum where members reply but do not post
            return [{"id": self.everyone, "type": 0, "allow": str(SEND_THREADS | ADD_REACTIONS),
                     "deny": str(SEND | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS)}] + staff
        if access == "private":
            return [{"id": self.everyone, "type": 0, "allow": "0", "deny": str(VIEW)}] + staff
        return []

    def rename_channels(self):
        for old, new in S.CHANNEL_RENAMES.items():
            c = self.find(old)
            if c and not self.find(new):
                self._do("PATCH", f"/channels/{c['id']}", {"name": new}, f"rename {old} to {new}")
                c["name"] = new

    def ensure_channels(self):
        for pos, (cat_name, chans) in enumerate(S.LAYOUT):
            cat = self.find(cat_name, S.CATEGORY)
            if cat is None:
                cat = self._do("POST", f"/guilds/{self.g}/channels", {"name": cat_name, "type": S.CATEGORY, "position": pos},
                               f"create category {cat_name}")
                self.channels.append(cat)
            elif cat.get("position") != pos:
                self._do("PATCH", f"/channels/{cat['id']}", {"position": pos}, f"move category {cat_name}")
            for i, (name, type_, topic, opts) in enumerate(chans):
                body = {"name": name, "type": type_, "parent_id": cat["id"], "position": i,
                        "permission_overwrites": self.overwrites(opts)}
                if type_ in (S.TEXT, S.NEWS, S.FORUM):
                    body["topic"] = topic
                    body["rate_limit_per_user"] = opts.get("slowmode", 0)
                if type_ == S.FORUM:
                    body["default_reaction_emoji"] = {"emoji_name": opts.get("emoji", "👍")}
                    body["default_sort_order"] = 0
                    body["default_forum_layout"] = 2 if opts.get("layout") == "gallery" else 1
                    body["flags"] = REQUIRE_TAG if opts.get("require_tag") else 0
                    body["default_auto_archive_duration"] = 10080
                c = self.find(name, type_)
                tags = opts.get("tags", [])
                if c is None:
                    if type_ == S.NEWS and "COMMUNITY" not in self.guild.get("features", []):
                        body["type"] = S.TEXT                             # announcement channels need a community server
                    if type_ == S.FORUM:
                        body["available_tags"] = [{"name": t} for t in tags]
                    c = self._do("POST", f"/guilds/{self.g}/channels", body, f"create #{name}")
                    self.channels.append(c)
                else:
                    if type_ == S.FORUM:      # keep the tags that exist (posts carry their ids), in the listed order
                        have = {t["name"]: t for t in c.get("available_tags", [])}
                        body["available_tags"] = [have.get(t, {"name": t}) for t in tags] + \
                            [t for n, t in have.items() if n not in tags]
                    body.pop("type")
                    if self._differs(c, body):
                        self._do("PATCH", f"/channels/{c['id']}", body, f"update #{name}")
                        c.update(body)

    @staticmethod
    def _differs(c, body):
        for k, v in body.items():
            if k == "permission_overwrites":
                norm = lambda o: sorted((x["id"], str(x["allow"]), str(x["deny"])) for x in o)  # noqa: E731
                if norm(c.get(k, [])) != norm(v):
                    return True
            elif k == "available_tags":
                if [t["name"] for t in c.get(k, [])] != [t["name"] for t in v]:
                    return True
            elif k == "default_reaction_emoji":
                if (c.get(k) or {}).get("emoji_name") != v["emoji_name"]:
                    return True
            elif c.get(k) != v:
                return True
        return False

    def retire(self):
        """Delete what server.RETIRE lists, only while it is empty."""
        for name, type_ in S.RETIRE:
            c = next((x for x in self.channels if x["name"] == name and x["type"] == type_), None)
            if c is None:
                continue
            if type_ == S.CATEGORY:
                empty = not any(x.get("parent_id") == c["id"] for x in self.channels)
            elif type_ in (S.TEXT, S.NEWS):
                empty = not d.call("GET", f"/channels/{c['id']}/messages?limit=1")
            else:
                empty = True                                      # voice: nothing is kept in it
            if empty:
                self._do("DELETE", f"/channels/{c['id']}", None, f"delete the empty {name}")
                self.channels.remove(c)
            else:
                log(f"keep {name}: it is not empty")

    def channel(self, name):
        c = self.find(name)
        if c is None:
            raise SystemExit(f"no #{name}")
        return c

    def mention(self, name):
        return f"<#{self.channel(name)['id']}>"

    # ---- community settings, onboarding, AutoMod, invite --------------------------------------------
    def ensure_community(self):
        feats = set(self.guild.get("features", []))
        log_ch = self.channel("mod-log")["id"]
        body = {"rules_channel_id": self.channel("rules")["id"], "public_updates_channel_id": log_ch,
                "safety_alerts_channel_id": log_ch, "system_channel_id": self.channel("general")["id"],
                "system_channel_flags": 0b1100, "default_message_notifications": 1,
                "verification_level": max(1, self.guild.get("verification_level", 0)),
                "explicit_content_filter": 2, "description": S.GUILD_DESCRIPTION}
        if "COMMUNITY" not in feats:
            body["features"] = sorted(feats | {"COMMUNITY"})
        icon = ART / "icon.png"
        if icon.exists() and not self.guild.get("icon"):
            body["icon"] = "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode()
        if any(self.guild.get(k) != v for k, v in body.items() if k not in ("features", "icon")) or "features" in body \
                or "icon" in body:
            g = self._try("community settings", lambda: self._do("PATCH", f"/guilds/{self.g}", body,
                                                                 "community settings, channels for rules and updates"))
            if g and not self.dry:
                self.guild = g
        a = self.channel("announcements")
        if a["type"] != S.NEWS and "COMMUNITY" in self.guild.get("features", []):
            self._try("announcements", lambda: self._do("PATCH", f"/channels/{a['id']}", {"type": S.NEWS},
                                                        "#announcements as an announcement channel"))

    def ensure_onboarding(self):
        try:
            have = {p["title"]: p for p in d.call("GET", f"/guilds/{self.g}/onboarding").get("prompts", [])}
        except d.DiscordError:
            have = {}
        base = int(self.g) + 1                                    # new prompts and options need snowflake-shaped ids
        prompts = []
        for i, (title, options) in enumerate(S.ONBOARDING):
            old = {o["title"]: o["id"] for o in have.get(title, {}).get("options", [])}
            opts = []
            for j, (label, desc, roles, chans) in enumerate(options):
                role_ids = [self.roles[r]["id"] for r in roles if r in self.roles]
                chan_ids = [self.channel(c)["id"] for c in chans if self.find(c)]
                if role_ids or chan_ids:
                    opts.append({"id": old.get(label, str(base + 1000 + 100 * i + j)), "title": label,
                                 "description": desc, "role_ids": role_ids, "channel_ids": chan_ids})
            prompts.append({"id": have.get(title, {}).get("id", str(base + 10 + i)), "type": 0, "title": title,
                            "options": opts, "single_select": False, "required": False, "in_onboarding": True})
        defaults = [self.channel(n)["id"] for _, chans in S.LAYOUT for n, t, _, o in chans
                    if o.get("default") and t in (S.TEXT, S.NEWS, S.FORUM) and self.find(n)]
        self._try("onboarding", lambda: self._do(
            "PUT", f"/guilds/{self.g}/onboarding",
            {"prompts": prompts, "default_channel_ids": defaults, "enabled": True, "mode": 0},
            f"onboarding: {len(prompts)} questions, {len(defaults)} default channels"))

    def ensure_automod(self):
        rules = d.call("GET", f"/guilds/{self.g}/auto-moderation/rules")
        log_ch = self.channel("mod-log")["id"]
        m = self.roles.get("Maintainer")
        for name, trigger, meta, block in S.AUTOMOD:
            actions = ([{"type": 1, "metadata": {"custom_message": "Blocked by the server's rules (#rules)."}}]
                       if block else []) + [{"type": 2, "metadata": {"channel_id": log_ch}}]
            body = {"name": name, "event_type": 1, "trigger_type": trigger, "trigger_metadata": meta,
                    "actions": actions, "enabled": True, "exempt_roles": [m["id"]] if m else [],
                    "exempt_channels": [log_ch]}
            # one rule per guild for spam (3), keyword presets (4) and mention spam (5): match those by type
            have = next((r for r in rules if (r["trigger_type"] == trigger and trigger in (3, 4, 5))
                         or r["name"] == name), None)
            if have is None:
                self._try(f"automod {name}", lambda: self._do("POST", f"/guilds/{self.g}/auto-moderation/rules",
                                                              body, f"AutoMod: {name}"))
            else:
                patch = {k: v for k, v in body.items() if k not in ("trigger_type",)}
                if trigger == 3:
                    patch.pop("trigger_metadata")
                cur = {k: have.get(k) for k in patch}
                if json.dumps(cur, sort_keys=True) != json.dumps(patch, sort_keys=True):
                    self._try(f"automod {name}", lambda: self._do(
                        "PATCH", f"/guilds/{self.g}/auto-moderation/rules/{have['id']}", patch, f"AutoMod: update {name}"))

    def ensure_invite(self):
        welcome = self.channel("welcome")["id"]
        invites = d.call("GET", f"/guilds/{self.g}/invites")
        inv = next((i for i in invites if i.get("code") == S.INVITE_CODE), None) or \
            next((i for i in invites if (i.get("inviter") or {}).get("id") == self.me["id"]
                  and i.get("channel", {}).get("id") == welcome and i.get("max_age") == 0), None)
        if inv is None:
            inv = self._do("POST", f"/channels/{welcome}/invites", {"max_age": 0, "max_uses": 0, "unique": True},
                           "a permanent invite to #welcome") or {}
        code = inv.get("code", "")
        log(f"invite: https://discord.gg/{code}")
        if code and code != S.INVITE_CODE:
            self.notes.append(f"Set INVITE_CODE = \"{code}\" in scripts/discord/server.py.")
        return code

    def ensure_profile(self):
        body = {}
        if not self.me.get("avatar") and (ART / "icon.png").exists():
            body["avatar"] = "data:image/png;base64," + base64.b64encode((ART / "icon.png").read_bytes()).decode()
        if not self.me.get("banner") and (ART / "profile-banner.png").exists():
            body["banner"] = "data:image/png;base64," + base64.b64encode((ART / "profile-banner.png").read_bytes()).decode()
        if body:
            self._try("profile", lambda: self._do("PATCH", "/users/@me", body, "bot avatar and banner"))
        app = self._try("application", lambda: d.call("GET", "/applications/@me")) or {}
        if app and app.get("description") != S.BOT_DESCRIPTION:
            self._try("bot description", lambda: self._do("PATCH", "/applications/@me",
                                                          {"description": S.BOT_DESCRIPTION}, "the bot's About me"))

    # ---- pinned posts, edited in place --------------------------------------------------------------
    def _bot_messages(self, ch):
        try:
            return [m for m in d.call("GET", f"/channels/{ch}/messages?limit=50") if m["author"]["id"] == self.me["id"]]
        except d.DiscordError:
            return []

    def pinned_post(self, ch_name, section, embeds, components=None, files=None, legacy=None):
        """One pinned post per section: created once, then edited in place when its content changes."""
        ch = self.channel(ch_name)["id"]
        sig = sig_of(embeds, components, {n: hashlib.sha1(b).hexdigest() for n, b in (files or {}).items()})
        for e in embeds:
            e["footer"] = d.footer(section, sig) if e is embeds[-1] else None
            if e["footer"] is None:
                del e["footer"]
        mine = self._bot_messages(ch)
        old = next((m for m in mine if any((e.get("footer") or {}).get("text", "") in
                                           (f"Form Studio · {section}",) or
                                           (legacy and (e.get("footer") or {}).get("text", "").startswith(legacy + " · "))
                                           for e in m.get("embeds", []))), None)
        body = {"content": "", "embeds": embeds, "components": components or [], "allowed_mentions": {"parse": []}}
        if old and current_sig(old) == sig:
            log(f"#{ch_name}: {section} is current")
            return
        if old:
            m = self._do("PATCH", f"/channels/{ch}/messages/{old['id']}", body, f"#{ch_name}: edit {section}", files=files)
        else:
            m = self._do("POST", f"/channels/{ch}/messages", body, f"#{ch_name}: post {section}", files=files)
        if not self.dry and not (old or {}).get("pinned"):
            self._try("pin", lambda: d.call("PUT", f"/channels/{ch}/pins/{m['id']}"))
        for x in self._bot_messages(ch) if not self.dry else []:  # Discord's "pinned a message" notices
            if x.get("type") == 6:
                self._try("tidy", lambda: d.call("DELETE", f"/channels/{ch}/messages/{x['id']}"))

    def welcome(self):
        files = {}
        for name in ("welcome.gif", "banner.png"):
            if (ART / name).exists():
                files[name] = (ART / name).read_bytes()
                break
        c = self.mention
        hero = {"color": d.DATUM, "title": "Form Studio",
                "description": ("Describe a part and get a file you can print. **Form Studio** is an open-source desktop "
                                "app where an AI agent designs parts in a real CAD kernel. It checks every revision on "
                                "the solid, slices it with your own slicer and plays the print back before you start it.\n\n"
                                "Describe it, drop a photo with a coin for scale, sketch it or bring a part. "
                                "It comes back as real CAD you can measure, prove and release.")}
        if files:
            hero["image"] = {"url": "attachment://" + next(iter(files))}
        where = {"color": d.PLATE, "title": "Where things are", "fields": [
            {"name": "Show what you made", "value": c("showcase"), "inline": True},
            {"name": "Learn the app", "value": c("guides"), "inline": True},
            {"name": "Find a recipe", "value": c("recipes"), "inline": True},
            {"name": "Ask for help", "value": c("help"), "inline": True},
            {"name": "Propose an idea", "value": c("ideas"), "inline": True},
            {"name": "Talk", "value": c("general"), "inline": True},
            {"name": "Follow releases", "value": f"{c('announcements')} · {c('releases')}", "inline": True},
            {"name": "Build it with us", "value": c("contributing"), "inline": True},
            {"name": "Your channels and roles", "value": "<id:customize>", "inline": True}]}
        how = {"color": d.BLUEPRINT, "title": "How a design goes", "description":
               "`1` **Start**  words, a photo, a sketch, a STEP, STL or 3MF part, a PDF or a link\n"
               "`2` **Concepts**  three or four genuinely different designs, each real CAD\n"
               "`3` **Shape and fit**  parameters that say how they are known, fits modelled for your printer\n"
               "`4` **Prove**  checks on the solid, the slice from your slicer, the print played back\n"
               "`5` **Release**  you approve; STEP, STL, 3MF and G-code frozen with SHA-256 hashes"}
        buttons = [d.row(d.link_button("Download", S.REPO + "/releases/latest"),
                         d.link_button("Try it in your browser", S.SITE + "#try"),
                         d.link_button("Docs", S.DOCS),
                         d.link_button("GitHub", S.REPO),
                         d.link_button("Discussions", S.REPO + "/discussions"))]
        self.pinned_post("welcome", "Welcome", [hero, where, how], buttons, files or None, legacy="welcome")

    def rules(self):
        files = {"rules.png": (ART / "cards" / "rules.png").read_bytes()} if (ART / "cards" / "rules.png").exists() else None
        fields = [{"name": f"`{i}`  {t}", "value": v, "inline": False} for i, (t, v) in enumerate(S.RULES, 1)]
        emb = {"color": d.AMBER, "title": "Rules", "fields": fields,
               "description": "Short, so they get read. Moderators may remove what breaks them. "
                              "The full [code of conduct](" + S.REPO + "/blob/main/CODE_OF_CONDUCT.md) applies here too."}
        if files:
            emb["image"] = {"url": "attachment://rules.png"}
        self.pinned_post("rules", "Rules", [emb], None, files, legacy="rules")

    def contributing(self):
        files = {"contributing.png": (ART / "cards" / "contributing.png").read_bytes()} \
            if (ART / "cards" / "contributing.png").exists() else None
        emb = {"color": d.BLUEPRINT, "title": "Build Form Studio with us",
               "description": ("Form Studio is open source: the app, the engine, recipes, docs and the website.\n\n"
                               "`1` Read **CONTRIBUTING.md** for the setup and the tests, and **AGENTS.md** if an agent "
                               "helps you.\n"
                               "`2` Pick an issue: *good first issue* and *help wanted* are a good start, or say here what "
                               "you want to work on.\n"
                               "`3` Open a pull request into `dev`. CI runs the tests; a maintainer reviews.\n\n"
                               f"Merged pull requests appear in {self.mention('github')}. Add your GitHub login and Discord "
                               "id to `CONTRIBUTORS` in `scripts/discord/server.py` in your pull request, and the "
                               "Contributor role follows when it merges."),
               "fields": [{"name": "Failed runs", "value": self.mention("ci"), "inline": True},
                          {"name": "Security issues", "value": "[Report privately](" + S.REPO + "/security)", "inline": True}]}
        if files:
            emb["image"] = {"url": "attachment://contributing.png"}
        buttons = [d.row(d.link_button("CONTRIBUTING.md", S.REPO + "/blob/main/CONTRIBUTING.md"),
                         d.link_button("Good first issues", S.REPO + "/issues?q=is%3Aopen+label%3A%22good+first+issue%22"),
                         d.link_button("Architecture", S.DOCS + "architecture.html"))]
        self.pinned_post("contributing", "Contributing", [emb], buttons, files)

    # ---- forum posts, edited in place ---------------------------------------------------------------
    def forum_threads(self, forum_id):
        if forum_id == "0":                                       # a forum this dry run would create
            return {}
        active = [t for t in d.call("GET", f"/guilds/{self.g}/threads/active").get("threads", [])
                  if t.get("parent_id") == forum_id]
        archived = d.call("GET", f"/channels/{forum_id}/threads/archived/public?limit=100").get("threads", [])
        return {t["name"]: t for t in active + archived}

    def forum_post(self, forum, threads, title, tag, embed, components, files=None, pin=False):
        tags = {t["name"]: t["id"] for t in forum.get("available_tags", [])}
        applied = [tags[tag]] if tag in tags else []
        sig = sig_of(embed, components, {n: hashlib.sha1(b).hexdigest() for n, b in (files or {}).items()}, applied)
        embed["footer"] = d.footer(forum["name"].capitalize(), sig)
        msg = {"embeds": [embed], "components": components, "allowed_mentions": {"parse": []}}
        t = threads.get(title[:100])
        if t is None:
            body = {"name": title[:100], "applied_tags": applied, "message": msg, "auto_archive_duration": 10080}
            t = self._do("POST", f"/channels/{forum['id']}/threads", body, f"#{forum['name']}: post {title}", files=files)
        else:
            starter = self._try("starter", lambda: d.call("GET", f"/channels/{t['id']}/messages/{t['id']}")) or {}
            if current_sig(starter) == sig:
                return
            if (t.get("thread_metadata") or {}).get("archived"):
                self._do("PATCH", f"/channels/{t['id']}", {"archived": False}, f"#{forum['name']}: reopen {title}")
            self._do("PATCH", f"/channels/{t['id']}", {"applied_tags": applied}, f"#{forum['name']}: tag {title}")
            self._do("PATCH", f"/channels/{t['id']}/messages/{t['id']}", msg, f"#{forum['name']}: edit {title}", files=files)
        if pin and not self.dry and not (t.get("flags", 0) & PINNED):
            self._try("pin post", lambda: d.call("PATCH", f"/channels/{t['id']}", {"flags": PINNED}))

    def guides(self):
        forum = self.channel("guides")
        threads = self.forum_threads(forum["id"])
        # newest first in the forum: post the last guide first so Guide 01 ends up on top
        for i, (title, tag, _art, text, links) in reversed(list(enumerate(S.GUIDES, 1))):
            files, emb = None, {"color": d.DATUM, "title": title, "description": text}
            img = ART / "guides" / f"{i:02d}.png"
            if img.exists():
                files = {f"guide-{i:02d}.png": img.read_bytes()}
                emb["image"] = {"url": f"attachment://guide-{i:02d}.png"}
            buttons = [d.row(*[d.link_button(lbl, url) for lbl, url in links[:5]])]
            self.forum_post(forum, threads, title, tag, emb, buttons, files, pin=(i == 1))

    def recipes(self):
        if not RECIPES.exists():
            log("no site/recipes/index.json: recipes skipped")
            return
        forum = self.channel("recipes")
        threads = self.forum_threads(forum["id"])
        for r in reversed(json.loads(RECIPES.read_text(encoding="utf-8"))["recipes"]):
            src = (f"{S.REPO}/blob/main/form/recipes/{r['id']}.py" if r.get("builtin")
                   else (r.get("url") or "").replace("raw.githubusercontent.com/kaizensx/form-studio/main/",
                                                     "github.com/kaizensx/form-studio/blob/main/"))
            emb = {"color": d.VIOLET, "title": r["title"], "url": S.SITE + "recipes/",
                   "description": r.get("summary", ""),
                   "fields": [{"name": "Parameters", "value": str(r.get("params_count", "—")), "inline": True},
                              {"name": "Author", "value": r.get("author", "—"), "inline": True},
                              {"name": "Tags", "value": ", ".join(r.get("tags", [])[:6]) or "—", "inline": False}]}
            if r.get("preview") and self._reachable(r["preview"]):
                emb["image"] = {"url": r["preview"]}
            buttons = [d.row(d.link_button("Open the gallery", S.SITE + "recipes/"),
                             *([d.link_button("Source", src)] if src.startswith("https://") else []))]
            self.forum_post(forum, threads, r["title"], "Built-in" if r.get("builtin") else "Community", emb, buttons)

    @staticmethod
    def _reachable(url):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def run(self):
        log(f"server: {self.guild['name']} · bot: {self.me['username']}")
        self.ensure_profile()
        self.ensure_roles()
        self.rename_channels()
        self.ensure_channels()
        self.retire()
        self.ensure_community()
        self.ensure_onboarding()
        self.ensure_automod()
        self.ensure_members()
        self.welcome()
        self.rules()
        self.contributing()
        self.guides()
        self.recipes()
        code = self.ensure_invite()
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        lines = [f"Invite: https://discord.gg/{code}"] + [f"- {n}" for n in self.notes]
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("\n".join(["### Discord setup"] + lines) + "\n")
        log("\n".join(lines))
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
