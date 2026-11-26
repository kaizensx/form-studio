"""Make the Form Studio Discord server match scripts/discord/server.py.

    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/discord/setup_server.py [--dry-run]

Idempotent. Roles, categories and channels are matched by name and created, renamed, moved or updated. Nothing with
history is deleted: a channel that is no longer used moves to the hidden ARCHIVE category, and only an empty one is
removed. The posts (#welcome, #rules, #roles, #contributing, the staff handbook) and the forum posts (#guides)
are plain messages, edited in place when their text changes. Runs in GitHub Actions
(.github/workflows/discord.yml, "setup"), between a before and an after snapshot.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_api as d  # noqa: E402
import server as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "scripts" / "discord" / "art"
WELCOME_ART = ROOT / "docs" / "readme" / "banner.png"

VIEW, SEND, ADD_REACTIONS, HISTORY = S.P["view"], S.P["send"], S.P["react"], S.P["history"]
CREATE_PUBLIC_THREADS, CREATE_PRIVATE_THREADS, SEND_THREADS = S.P["public_threads"], S.P["private_threads"], S.P["send_in_threads"]
POSTING = SEND | SEND_THREADS | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS
STAFF_ALLOW = VIEW | SEND | SEND_THREADS | HISTORY
REQUIRE_TAG, PINNED = 1 << 4, 1 << 1


def tag(t: str) -> dict:
    """ "🖨️ Printed" -> a forum tag named Printed with its emoji; "!🗺️ Planned" -> one only moderators may apply."""
    moderated = t.startswith("!")
    t = t.lstrip("!")
    first, _, rest = t.partition(" ")
    out = {"name": rest, "emoji_name": first} if rest and not first.isascii() else {"name": t}
    return {**out, "moderated": moderated}


def log(*a):
    print(*a, flush=True)


def comp_sig(components) -> list:
    """What a message's buttons and menus are, without the ids and defaults Discord adds."""
    out = []
    for row in components or []:
        for c in row.get("components", []):
            out.append((c.get("type"), c.get("style"), c.get("label"), c.get("url"), c.get("custom_id"),
                        c.get("placeholder"), (c.get("emoji") or {}).get("name"),
                        tuple((o.get("label"), str(o.get("value")), (o.get("emoji") or {}).get("name"))
                              for o in c.get("options", []))))
    return out


def guide_parts(text: str, mention) -> list[str]:
    """A guide from docs/community as Discord messages: "#help" becomes a link to the channel (outside code), the
    title and introduction are the first message, and the rest is cut at sections."""
    by_name = {name: key for key, name in S.NAMES.items()}

    def channels(seg: str) -> str:
        return re.sub(r"(?<![\w/#`(\[])#([a-z][a-z0-9-]+)\b",
                      lambda m: mention(by_name[m.group(1)]) if m.group(1) in by_name else m.group(0), seg)
    out, fenced = [], False
    for raw in text.splitlines():
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            out.append(raw)
        elif fenced or raw.startswith("#"):
            out.append(raw)
        else:
            out.append("`".join(seg if i % 2 else channels(seg) for i, seg in enumerate(raw.split("`"))))
    return d.split_text("\n".join(out), lead=True)


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
        for name in S.ROLE_RETIRE:
            r = self.roles.get(name)
            if r and not r.get("managed") and name not in S.R:
                self._try(f"remove role {name}", lambda: self._do("DELETE", f"/guilds/{self.g}/roles/{r['id']}", None,
                                                                  f"remove role {name}"))
                del self.roles[name]
        for name, colour, hoist, mention, perm in S.ROLES:
            body = {"name": name, "color": colour, "hoist": hoist, "mentionable": mention, "permissions": str(perm)}
            r = self.roles.get(name)
            if r is None:
                self.roles[name] = self._do("POST", f"/guilds/{self.g}/roles", body, f"create role {name}")
            elif (r["color"], r["hoist"], r["mentionable"], str(r.get("permissions"))) != (colour, hoist, mention, str(perm)) \
                    and not r.get("managed"):
                self._do("PATCH", f"/guilds/{self.g}/roles/{r['id']}", body, f"update role {name}")
        ev = next((r for r in self.roles.values() if r["id"] == self.everyone), None)
        if ev and str(ev.get("permissions")) != str(S.EVERYONE):
            self._try("@everyone", lambda: self._do("PATCH", f"/guilds/{self.g}/roles/{self.everyone}",
                                                    {"permissions": str(S.EVERYONE)}, "what every member may do"))
        # order: the bot's own role on top, then the list as written; other roles keep their place below
        mine = [r for r in self.roles.values() if r.get("managed") and r.get("tags", {}).get("bot_id") == self.me["id"]]
        named = [self.roles[n] for n, *_ in S.ROLES if n in self.roles]
        others = [r for r in self.roles.values() if r not in named and r not in mine and r["id"] != self.everyone]
        order = others + list(reversed(named))
        want = [{"id": r["id"], "position": i} for i, r in enumerate(order, 1) if r.get("id", "0") != "0"]
        if any(self.roles_by_id().get(w["id"], {}).get("position") != w["position"] for w in want):
            self._try("role order", lambda: self._do("PATCH", f"/guilds/{self.g}/roles", want, "order the roles"))
            if mine and not self.dry:
                fresh = {r["id"]: r for r in d.call("GET", f"/guilds/{self.g}/roles")}
                if fresh[mine[0]["id"]]["position"] <= max(fresh[r["id"]]["position"] for r in named if r["id"] in fresh):
                    self.notes.append("Drag the Form Studio role to the top of Server Settings › Roles, "
                                      "so the bot can give and order the roles below it.")

    def roles_by_id(self):
        return {r["id"]: r for r in self.roles.values()}

    def ensure_members(self):
        """Recognition: the owner and MAINTAINERS are Maintainers; MODERATORS and CONTRIBUTORS get their roles."""
        give = [(self.guild["owner_id"], "Maintainer")] + [(u, "Maintainer") for u in S.MAINTAINERS]
        give += [(u, "Moderator") for u in S.MODERATORS]
        give += [(u, "Contributor") for u in S.CONTRIBUTORS.values()]
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
        name = S.N(name)                                          # a key ("showcase") or a shown name
        for c in self.channels:
            if c["name"] == name and (type_ is None or c["type"] == type_ or {c["type"], type_} <= {S.TEXT, S.NEWS}):
                return c
        return None

    def staff(self, moderators=False, allow=STAFF_ALLOW, deny=0):
        out = [{"id": self.me["id"], "type": 1, "allow": str(STAFF_ALLOW), "deny": "0"}]
        for name in ("Maintainer",) + (("Moderator",) if moderators else ()):
            r = self.roles.get(name)
            if r and r.get("id", "0") != "0":
                out.insert(0, {"id": r["id"], "type": 0, "allow": str(allow), "deny": str(deny)})
        return out

    def overwrites(self, opts):
        access = opts.get("access")
        if access == "read_only":
            return [{"id": self.everyone, "type": 0, "allow": str(ADD_REACTIONS), "deny": str(POSTING)}] + self.staff()
        if access == "replies":                                   # a forum where members reply but do not post
            return [{"id": self.everyone, "type": 0, "allow": str(SEND_THREADS | ADD_REACTIONS),
                     "deny": str(SEND | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS)}] + self.staff()
        if access == "private":
            return [{"id": self.everyone, "type": 0, "allow": "0", "deny": str(VIEW)}] + self.staff(moderators=True)
        return []

    def archive_overwrites(self):
        """Hidden from members; staff read it; nobody writes in it."""
        return [{"id": self.everyone, "type": 0, "allow": "0", "deny": str(VIEW | POSTING)}] + \
            self.staff(moderators=True, allow=VIEW | HISTORY, deny=POSTING)

    def rename_channels(self):
        raw = lambda n: next((c for c in self.channels if c["name"] == n), None)  # noqa: E731  exact names here
        for old, new in S.CHANNEL_RENAMES.items():
            c = raw(old)
            if c and not raw(new):
                if c["type"] == S.CATEGORY or new not in S.NAMES.values():
                    self._do("PATCH", f"/channels/{c['id']}", {"name": new}, f"rename {old} to {new}")
                else:       # Discord allows two name or topic changes per channel in ten minutes: the new name goes
                    c["was"] = old                      # with the channel's update, as one request
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
                cat["position"] = pos
            for i, (key, name, type_, topic, opts) in enumerate(chans):
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
                    body["default_thread_rate_limit_per_user"] = opts.get("reply_slowmode", 0)
                c = self.find(name, type_)
                tags = opts.get("tags", [])
                if c is None:
                    if type_ == S.NEWS and "COMMUNITY" not in self.guild.get("features", []):
                        body["type"] = S.TEXT                             # announcement channels need a community server
                    if type_ == S.FORUM:
                        body["available_tags"] = [tag(t) for t in tags]
                    c = self._do("POST", f"/guilds/{self.g}/channels", body, f"create #{name}")
                    self.channels.append(c)
                else:
                    if type_ == S.FORUM:      # keep the tags that exist (posts carry their ids), in the listed order
                        have = {t["name"]: t for t in c.get("available_tags", [])}
                        for old, new in S.TAG_RENAMES.get(key, {}).items():      # same tag id, new name
                            if old in have and new not in have:
                                have[new] = {**have.pop(old), "name": new}
                        want = [tag(t) for t in tags]
                        names = {w["name"] for w in want}
                        extra = [t for n, t in have.items() if n not in names]
                        if extra and not self.dry:        # a tag no longer listed stays only while a post uses it
                            used = self.used_tags(c["id"])
                            extra = [t for t in extra if t.get("id") in used]
                        body["available_tags"] = [{**({"id": have[w["name"]]["id"]} if w["name"] in have else {}), **w}
                                                  for w in want] + extra
                    body.pop("type")
                    was = c.pop("was", None)
                    if was or self._differs(c, body):
                        self._do("PATCH", f"/channels/{c['id']}", body,
                                 f"rename #{was} to #{name} and update it" if was else f"update #{name}")
                        c.update(body)

    def used_tags(self, forum_id) -> set:
        active = d.call("GET", f"/guilds/{self.g}/threads/active").get("threads", [])
        archived = d.call("GET", f"/channels/{forum_id}/threads/archived/public?limit=100").get("threads", [])
        return {tid for t in active + archived if t.get("parent_id") == forum_id for tid in t.get("applied_tags", [])}

    @staticmethod
    def _differs(c, body):
        for k, v in body.items():
            if k == "permission_overwrites":
                norm = lambda o: sorted((x["id"], str(x["allow"]), str(x["deny"])) for x in o)  # noqa: E731
                if norm(c.get(k, [])) != norm(v):
                    return True
            elif k == "available_tags":
                sig = lambda ts: [(t["name"], t.get("emoji_name"), bool(t.get("moderated"))) for t in ts]  # noqa: E731
                if sig(c.get(k, [])) != sig(v):
                    return True
            elif k == "default_reaction_emoji":
                if (c.get(k) or {}).get("emoji_name") != v["emoji_name"]:
                    return True
            elif k in ("rate_limit_per_user", "default_thread_rate_limit_per_user", "flags"):
                if (c.get(k) or 0) != v:
                    return True
            elif c.get(k) != v:
                return True
        return False

    # ---- the archive: channels that are no longer used keep their history, out of sight ------------------
    def archive_category(self):
        cat = next((c for c in self.channels if c["name"] == S.ARCHIVE_CATEGORY and c["type"] == S.CATEGORY), None)
        body = {"name": S.ARCHIVE_CATEGORY, "type": S.CATEGORY, "position": len(S.LAYOUT),
                "permission_overwrites": self.archive_overwrites()}
        if cat is None:
            cat = self._do("POST", f"/guilds/{self.g}/channels", body, f"create category {S.ARCHIVE_CATEGORY}")
            self.channels.append(cat)
        else:
            body.pop("type")
            if self._differs(cat, body):
                self._do("PATCH", f"/channels/{cat['id']}", body, f"update category {S.ARCHIVE_CATEGORY}")
                cat.update(body)
        return cat

    def to_archive(self, c, new_name):
        cat = self.archive_category()
        body = {"name": new_name, "parent_id": cat["id"], "permission_overwrites": self.archive_overwrites()}
        if c["type"] in (S.TEXT, S.NEWS, S.FORUM):
            topic = c.get("topic") or ""
            body["topic"] = topic if topic.startswith("Archived.") else ("Archived. " + topic)[:1024]
        if self._differs(c, body):
            self._do("PATCH", f"/channels/{c['id']}", body, f"archive #{c['name']} as #{new_name} (hidden, read-only, kept)")
            c.update(body)

    def archive(self):
        for old, new in S.ARCHIVE.items():
            c = next((x for x in self.channels if x["name"] in (old, new) and x["type"] != S.CATEGORY), None)
            if c is not None:
                self.to_archive(c, new)

    def retire(self):
        """Remove what server.RETIRE lists while it is empty; a channel with messages moves to the archive instead."""
        for name, type_ in S.RETIRE:
            c = next((x for x in self.channels if x["name"] == name and x["type"] == type_), None)
            if c is None:
                continue
            if type_ == S.CATEGORY:
                empty = not any(x.get("parent_id") == c["id"] for x in self.channels)
            elif type_ in (S.TEXT, S.NEWS):
                empty = not d.call("GET", f"/channels/{c['id']}/messages?limit=1")
            else:
                empty = True                                      # voice and stage: nothing is kept in them
            if empty:
                self._do("DELETE", f"/channels/{c['id']}", None, f"remove the empty {name}")
                self.channels.remove(c)
            elif type_ == S.CATEGORY:
                log(f"keep {name}: it still holds channels")
            else:
                plain = re.sub(r"[^a-z0-9-]+", "", name.split("・")[-1].lower().replace(" ", "-")) or "channel"
                self.to_archive(c, "archive-" + plain)

    def channel(self, name):
        c = self.find(name)
        if c is None:
            raise SystemExit(f"no #{name}")
        return c

    def fresh(self, name):
        c = self.channel(name)
        return c if self.dry or c["id"] == "0" else d.call("GET", f"/channels/{c['id']}")

    def mention(self, name):
        return f"<#{self.channel(name)['id']}>"

    def fill(self, text: str) -> str:
        """{help} -> a link to the channel with that key; {levels} -> the level roles in order."""
        text = text.replace("{levels}", " → ".join(n for _, n in S.LEVELS))
        return re.sub(r"\{([a-z][a-z-]*)\}", lambda m: self.mention(m.group(1)) if m.group(1) in S.NAMES else m.group(0),
                      text)

    # ---- community settings, screening, onboarding, AutoMod, invite -------------------------------------
    def ensure_community(self):
        feats = set(self.guild.get("features", []))
        log_ch = self.channel("mod-log")["id"]
        body = {"rules_channel_id": self.channel("rules")["id"], "public_updates_channel_id": log_ch,
                "safety_alerts_channel_id": log_ch, "system_channel_id": self.channel("general")["id"],
                "system_channel_flags": 0b1100, "default_message_notifications": S.NOTIFICATIONS,
                "verification_level": S.VERIFICATION_LEVEL,
                "explicit_content_filter": S.EXPLICIT_CONTENT_FILTER, "description": S.GUILD_DESCRIPTION}
        if "COMMUNITY" not in feats:
            body["features"] = sorted(feats | {"COMMUNITY"})
        icon = ART / "icon.png"
        if icon.exists() and not self.guild.get("icon"):
            body["icon"] = "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode()
        if any(self.guild.get(k) != v for k, v in body.items() if k not in ("features", "icon")) or "features" in body \
                or "icon" in body:
            g = self._try("community settings", lambda: self._do(
                "PATCH", f"/guilds/{self.g}", body, "community settings: verification, media filter, rules and update channels"))
            if g and not self.dry:
                self.guild = g
        a = self.channel("announcements")
        if a["type"] != S.NEWS and "COMMUNITY" in self.guild.get("features", []):
            self._try("announcements", lambda: self._do("PATCH", f"/channels/{a['id']}", {"type": S.NEWS},
                                                        "#announcements as an announcement channel"))

    def ensure_screening(self):
        """Rules screening: a new member agrees to the rules before posting."""
        want = [{"field_type": "TERMS", "label": "Read and agree to the server rules", "values": S.SCREENING["rules"],
                 "required": True}]
        how = ("Server Settings › Safety Setup › DM and Spam Protection › Members must accept rules: turn it on and "
               "add the rules from SCREENING in scripts/discord/server.py.")
        try:
            have = d.call("GET", f"/guilds/{self.g}/member-verification")
        except d.DiscordError:
            have = {}
        cur = [(f.get("field_type"), f.get("values")) for f in have.get("form_fields", [])]
        on = "MEMBER_VERIFICATION_GATE_ENABLED" in self.guild.get("features", [])
        if on and cur == [("TERMS", S.SCREENING["rules"])] and have.get("description") == S.SCREENING["description"]:
            return
        if self.dry:
            log("would rules screening: a new member agrees to the rules before posting")
            return
        log("rules screening: a new member agrees to the rules before posting")
        for body in ({"enabled": True, "description": S.SCREENING["description"], "form_fields": json.dumps(want)},
                     {"enabled": True, "description": S.SCREENING["description"], "form_fields": want}):
            try:
                d.call("PATCH", f"/guilds/{self.g}/member-verification", body, reason="Form Studio server setup")
                return
            except d.DiscordError as e:
                err = str(e)
        log(f"rules screening: {err}")
        self.notes.append(f"Rules screening could not be set by the bot ({err[:120]}). By hand: {how}")

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
            for j, (label, desc, emoji, roles, chans) in enumerate(options):
                role_ids = [self.roles[r]["id"] for r in roles if r in self.roles and self.roles[r].get("id", "0") != "0"]
                chan_ids = [self.channel(c)["id"] for c in chans if self.find(c)]
                if role_ids or chan_ids or self.dry:
                    opts.append({"id": old.get(label, str(base + 2000 + 100 * i + j)), "title": label,
                                 "description": desc, "emoji_name": emoji, "role_ids": role_ids,
                                 "channel_ids": chan_ids})
            prompts.append({"id": have.get(title, {}).get("id", str(base + 50 + i)), "type": 0, "title": title,
                            "options": opts, "single_select": False, "required": False,
                            "in_onboarding": i < S.ONBOARDING_SHOWN})
        defaults = [self.channel(k)["id"] for _, chans in S.LAYOUT for k, _, t, _, o in chans
                    if o.get("default") and t in (S.TEXT, S.NEWS, S.FORUM) and self.find(k)]
        self._try("onboarding", lambda: self._do(
            "PUT", f"/guilds/{self.g}/onboarding",
            {"prompts": prompts, "default_channel_ids": defaults, "enabled": True, "mode": 0},
            f"onboarding: {len(prompts)} questions, {len(defaults)} default channels"))

    def automod_actions(self, spec, log_ch):
        out = []
        for a in spec:
            if a == "block":
                out.append({"type": 1, "metadata": {"custom_message": S.AUTOMOD_BLOCK_MESSAGE}})
            elif a == "alert":
                out.append({"type": 2, "metadata": {"channel_id": log_ch}})
            elif a == "block_profile":
                out.append({"type": 4, "metadata": {}})
            elif isinstance(a, tuple) and a[0] == "timeout":
                out.append({"type": 3, "metadata": {"duration_seconds": a[1]}})
        return out

    def ensure_automod(self):
        rules = d.call("GET", f"/guilds/{self.g}/auto-moderation/rules")
        log_ch = self.channel("mod-log")["id"]
        exempt = [self.roles[n]["id"] for n in ("Maintainer", "Moderator")
                  if n in self.roles and self.roles[n].get("id", "0") != "0"]
        old_names = {new: old for old, new in S.AUTOMOD_RENAMES.items()}
        for name, trigger, meta, spec in S.AUTOMOD:
            body = {"name": name, "event_type": 2 if trigger == S.PROFILE else 1, "trigger_type": trigger,
                    "trigger_metadata": meta, "actions": self.automod_actions(spec, log_ch), "enabled": True,
                    "exempt_roles": exempt, "exempt_channels": [] if trigger == S.PROFILE else [log_ch]}
            # one rule per guild for spam, keyword presets, mention spam and member profiles: match those by type
            one = trigger in (S.SPAM, S.PRESET, S.MENTION_SPAM, S.PROFILE)
            have = next((r for r in rules if (one and r["trigger_type"] == trigger)
                         or (not one and r["trigger_type"] == trigger and r["name"] in (name, old_names.get(name)))), None)
            if have is None:
                self._try(f"AutoMod {name}", lambda: self._do("POST", f"/guilds/{self.g}/auto-moderation/rules",
                                                              body, f"AutoMod: {name}"))
                continue
            patch = {k: v for k, v in body.items() if k not in ("trigger_type", "event_type")}
            if trigger == S.SPAM:
                patch.pop("trigger_metadata")
            cur = {k: have.get(k) for k in patch}
            if "trigger_metadata" in cur:          # Discord fills in the keys a rule does not use
                cur["trigger_metadata"] = {k: v for k, v in (cur["trigger_metadata"] or {}).items() if k in meta}
            cur["actions"] = [{"type": a["type"], "metadata": {k: v for k, v in (a.get("metadata") or {}).items()
                                                               if v not in ("", None, 0)}} for a in cur.get("actions") or []]
            norm = lambda x: json.dumps({**x, "actions": sorted(x["actions"], key=lambda a: a["type"]),  # noqa: E731
                                         "exempt_roles": sorted(x.get("exempt_roles") or []),
                                         "exempt_channels": sorted(x.get("exempt_channels") or [])}, sort_keys=True)
            if norm(cur) != norm(patch):
                self._try(f"AutoMod {name}", lambda: self._update_or_create(have, patch, body, name))

    def _update_or_create(self, have, patch, body, name):
        """Discord lists its own suggested rules (Block Mention Spam) before anyone has set them up; they have no rule
        behind them, so PATCH answers 404. Create the rule then."""
        try:
            return self._do("PATCH", f"/guilds/{self.g}/auto-moderation/rules/{have['id']}", patch,
                            f"AutoMod: update {name}")
        except d.DiscordError as e:
            if "404" not in str(e):
                raise
            return self._do("POST", f"/guilds/{self.g}/auto-moderation/rules", body, f"AutoMod: {name} (set up)")

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

    # ---- posts: plain messages, edited in place -----------------------------------------------------------
    def bot_messages(self, ch):
        """The bot's own ordinary messages in a channel or a forum post, oldest first."""
        if ch == "0":
            return []
        try:
            msgs = d.call("GET", f"/channels/{ch}/messages?limit=100&after=0")
        except d.DiscordError:
            return []
        return sorted((m for m in msgs if m["author"]["id"] == self.me["id"] and m.get("type", 0) == 0),
                      key=lambda m: int(m["id"]))

    @staticmethod
    def _same(m, part, comps, files):
        return ((m.get("content") or "") == part and not m.get("embeds")
                and comp_sig(m.get("components")) == comp_sig(comps)
                and [(a.get("filename"), a.get("size")) for a in m.get("attachments", [])]
                == [(n, len(b)) for n, b in (files or {}).items()])

    def sync(self, ch, where, parts, *, components=None, files=None, pinned_only=False, pin=False, have=None):
        """Make the bot's messages in `ch` be exactly `parts`, in order: edit what differs, post what is missing,
        remove its own extra ones. files ride on the first message, components on the last. pinned_only: the post
        is the bot's one pinned message (a channel where members and the bot also write)."""
        if pinned_only:
            try:
                pins = d.call("GET", f"/channels/{ch}/pins") if ch != "0" else []
            except d.DiscordError:
                pins = []
            mine = sorted((m for m in pins if m["author"]["id"] == self.me["id"]), key=lambda m: int(m["id"]))[:1]
            parts = parts[:1]
        else:
            mine = self.bot_messages(ch) if have is None else have
        changed = 0
        first = mine[0] if mine else None
        for i, part in enumerate(parts):
            comps = (components or []) if i == len(parts) - 1 else []
            fs = files if i == 0 else None
            body = {"content": part, "embeds": [], "components": comps, "flags": d.NO_LINK_PREVIEWS,
                    "allowed_mentions": {"parse": []}}
            if i < len(mine):
                if self._same(mine[i], part, comps, fs):
                    continue
                if not fs:
                    body["attachments"] = []
                self._do("PATCH", f"/channels/{ch}/messages/{mine[i]['id']}", body, f"{where}: edit message {i + 1}", files=fs)
            else:
                m = self._do("POST", f"/channels/{ch}/messages", body, f"{where}: post message {i + 1}", files=fs)
                first = first or m
            changed += 1
        for m in mine[len(parts):]:
            self._do("DELETE", f"/channels/{ch}/messages/{m['id']}", None, f"{where}: remove the bot's extra message")
            changed += 1
        if not changed:
            log(f"{where}: current")
        if pin and first and not first.get("pinned") and not self.dry:
            self._try("pin", lambda: d.call("PUT", f"/channels/{ch}/pins/{first['id']}"))
            for x in d.call("GET", f"/channels/{ch}/messages?limit=10"):          # Discord's "pinned a message" notice
                if x.get("type") == 6 and x["author"]["id"] == self.me["id"]:
                    self._try("tidy", lambda: d.call("DELETE", f"/channels/{ch}/messages/{x['id']}"))

    def text_parts(self, text):
        return [p for seg in self.fill(text).split("\n===\n") for p in d.split_text(seg)]

    def welcome(self):
        buttons = [d.row({"type": 2, "style": 1, "label": "Pick my roles", "custom_id": "open:roles"},
                         {"type": 2, "style": 2, "label": "Where do I start?", "custom_id": "open:start"},
                         d.link_button("Download", S.REPO + "/releases/latest"),
                         d.link_button("Docs", S.DOCS),
                         d.link_button("GitHub", S.REPO))]
        parts = self.text_parts(S.WELCOME)
        files = None
        if WELCOME_ART.exists():                                  # the picture is a message of its own, on top
            files = {"form-studio.png": WELCOME_ART.read_bytes()}
            parts = [""] + parts
        self.sync(self.channel("welcome")["id"], "#welcome", parts, components=buttons, files=files)

    def rules(self):
        self.sync(self.channel("rules")["id"], "#rules", self.text_parts(S.RULES_POST))

    def contributing(self):
        buttons = [d.row(d.link_button("CONTRIBUTING.md", S.BLOB + "CONTRIBUTING.md"),
                         d.link_button("Good first issues", S.REPO + "/issues?q=is%3Aopen+label%3A%22good+first+issue%22"),
                         d.link_button("Architecture", S.BLOB + "docs/ARCHITECTURE.md"))]
        self.sync(self.channel("contributing")["id"], "#contributing", self.text_parts(S.CONTRIBUTING_POST),
                  components=buttons, pinned_only=True, pin=True)

    def staff_post(self):
        self.sync(self.channel("mod-log")["id"], "#mod-log handbook", self.text_parts(S.STAFF_POST), pinned_only=True,
                  pin=True)

    def roles_post(self):
        """#roles: the text, then one select menu per group; the bot (worker) gives and removes the roles."""
        rows = []
        for key, placeholder, names in S.ROLE_PICKER:
            opts = [{"label": n, "value": self.roles[n]["id"], "emoji": {"name": S.ROLE_EMOJI[n]}}
                    for n in names if n in self.roles and (self.dry or self.roles[n].get("id", "0") != "0")]
            if opts:
                rows.append({"type": 1, "components": [{"type": 3, "custom_id": f"roles:{key}", "placeholder": placeholder,
                                                        "min_values": 0, "max_values": len(opts), "options": opts}]})
        self.sync(self.channel("roles")["id"], "#roles", self.text_parts(S.ROLES_POST), components=rows[:5])

    # ---- forum posts ---------------------------------------------------------------------------------------
    def forum_threads(self, forum_id):
        if forum_id == "0":                                       # a forum this dry run would create
            return {}
        active = [t for t in d.call("GET", f"/guilds/{self.g}/threads/active").get("threads", [])
                  if t.get("parent_id") == forum_id]
        archived = d.call("GET", f"/channels/{forum_id}/threads/archived/public?limit=100").get("threads", [])
        return {t["name"]: t for t in active + archived}

    def forum_post(self, forum, threads, title, tag_name, parts, components=None, files=None, pin=False):
        """One forum post whose messages are `parts`: made once, then edited in place."""
        tags = {t["name"]: t.get("id") for t in forum.get("available_tags", [])}
        applied = [tags[tag_name]] if tags.get(tag_name) else []
        where = f"#{forum['name']} › {title}"
        t = threads.get(title[:100])
        if t is None:
            one = len(parts) == 1
            msg = {"content": parts[0], "flags": d.NO_LINK_PREVIEWS, "allowed_mentions": {"parse": []},
                   "components": (components or []) if one else []}
            t = self._do("POST", f"/channels/{forum['id']}/threads",
                         {"name": title[:100], "applied_tags": applied, "message": msg, "auto_archive_duration": 10080},
                         f"{where}: post", files=files)
            starter = {**msg, "id": t.get("id"), "embeds": [], "attachments": [
                {"filename": n, "size": len(b)} for n, b in (files or {}).items()], "author": {"id": self.me["id"]}}
            if not one:
                self.sync(t.get("id", "0"), where, parts, components=components, files=files, have=[starter])
        else:
            if (t.get("thread_metadata") or {}).get("archived"):
                self._do("PATCH", f"/channels/{t['id']}", {"archived": False}, f"{where}: reopen")
            if sorted(t.get("applied_tags") or []) != sorted(applied):
                self._do("PATCH", f"/channels/{t['id']}", {"applied_tags": applied}, f"{where}: tag")
            self.sync(t["id"], where, parts, components=components, files=files)
        if pin and not self.dry and not (t.get("flags", 0) & PINNED):
            self._try("pin post", lambda: d.call("PATCH", f"/channels/{t['id']}", {"flags": PINNED}))

    def guides(self):
        forum = self.fresh("guides")
        threads = self.forum_threads(forum["id"])
        for old, new in S.GUIDE_RENAMES.items():                  # a renamed guide keeps its post and replies
            if old in threads and new not in threads:
                t = threads.pop(old)
                if (t.get("thread_metadata") or {}).get("archived"):
                    self._do("PATCH", f"/channels/{t['id']}", {"archived": False}, f"#guides: reopen {old}")
                self._do("PATCH", f"/channels/{t['id']}", {"name": new[:100]}, f"#guides: rename {old} to {new}")
                threads[new] = {**t, "name": new, "thread_metadata": {**(t.get("thread_metadata") or {}), "archived": False}}
        for title in S.GUIDE_RETIRE:                              # replaced by the new guides
            t = threads.pop(title, None)
            if t is None:
                continue
            msgs = d.call("GET", f"/channels/{t['id']}/messages?limit=100")
            if all(m["author"]["id"] == self.me["id"] for m in msgs):
                self._do("DELETE", f"/channels/{t['id']}", None, f"#guides: remove the old guide {title} (only the bot wrote in it)")
            elif not ((t.get("thread_metadata") or {}).get("archived") and (t.get("thread_metadata") or {}).get("locked")):
                self._do("PATCH", f"/channels/{t['id']}", {"archived": True, "locked": True},
                         f"#guides: close the old guide {title} (members wrote in it: kept)")
        # newest first in the forum: post the last guide first so the first one ends up on top
        for i, (slug, title, tag_name, _art, _summary) in reversed(list(enumerate(S.GUIDES, 1))):
            parts = guide_parts(S.guide_text(slug), self.mention)
            parts[-1] += f"\n\n-# This guide is [docs/community/{slug}.md]({S.GUIDE_URL}{slug}.md) in the repository. " \
                         "Found something wrong or missing? Reply here, or open a pull request."
            if len(parts[-1]) > d.LIMIT:
                parts[-1:] = d.split_text(parts[-1])
            img = ART / "guides" / f"{slug}.png"
            files = {f"{slug}.png": img.read_bytes()} if img.exists() else None
            buttons = [d.row(d.link_button("Download", S.REPO + "/releases/latest"), d.link_button("Docs", S.DOCS),
                             d.link_button("This guide on GitHub", f"{S.GUIDE_URL}{slug}.md"))]
            self.forum_post(forum, threads, title, tag_name, parts, buttons, files, pin=(i == 1))

    def run(self):
        log(f"server: {self.guild['name']} · bot: {self.me['username']}")
        self.ensure_profile()
        self.ensure_roles()
        self.rename_channels()
        self.archive()
        self.ensure_channels()
        self.retire()
        self.ensure_community()
        self.ensure_screening()
        self.ensure_onboarding()
        self.ensure_automod()
        self.ensure_members()
        self.welcome()
        self.rules()
        self.roles_post()
        self.contributing()
        self.staff_post()
        self.guides()
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
