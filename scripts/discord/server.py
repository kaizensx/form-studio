"""The Form Studio Discord server, as data: roles, channels, forums, onboarding, moderation, levels and the posts.

setup_server.py makes the server match this, as often as it is run. Nothing with history is deleted: a channel that
is no longer used moves to the hidden, read-only ARCHIVE category, and only an empty one is removed. snapshot.py
records the server before and after every setup (Actions artifacts) for rollback. The interactive bot (slash
commands, buttons, role pickers, levels, weekly challenges) is the Cloudflare Worker in scripts/discord/worker/; it
reads the channel names and roles from here (worker/config.json, written by export_config.py).

The design system:
- Names. Categories are upper case, channels are short, lower case and plain: "show-and-tell". Roles are plain
  words. Code refers to a channel by its key ("showcase"); NAMES maps a key to the name shown.
- One place for each thing. Every build is posted in #releases and nowhere else; stable releases are also announced
  in #announcements; everything GitHub does (issues, pull requests, discussions, failed runs, the weekly digest)
  goes to #github.
- Text in the chat. Posts are plain messages in Discord markdown (headings, lists, code blocks), split at the
  2000-character limit. No embeds and no quote blocks. The guides are the files in docs/community/.
"""
from pathlib import Path

SITE = "https://kaizensx.github.io/form-studio/"
DOCS = SITE + "docs/"
REPO = "https://github.com/kaizensx/form-studio"
BLOB = REPO + "/blob/main/"
RAW = "https://raw.githubusercontent.com/kaizensx/form-studio/main/"
ICON = RAW + "form/app/assets/icon-64.png"
GUILD_DESCRIPTION = ("Form Studio: describe anything, and an engineer-grade agent builds it as real, editable CAD. "
                     "Open source. 3D printing is optional.")
BOT_DESCRIPTION = ("The Form Studio bot. Posts releases and GitHub activity, answers new help posts with the right "
                   "guides, and keeps the server in shape. "
                   "Source: github.com/kaizensx/form-studio/tree/main/scripts/discord")

# The permanent invite (to #welcome) that the README and the website link to. setup_server.py creates it when it is
# missing and prints the code; keep the code here so the links stay the same.
INVITE_CODE = "b6ZgyndkmS"
INVITE = "https://discord.gg/" + INVITE_CODE

ROOT = Path(__file__).resolve().parents[2]
GUIDE_DIR = ROOT / "docs" / "community"

# ---- permissions ---------------------------------------------------------------------------------------------------
P = {"invite": 1 << 0, "kick": 1 << 1, "ban": 1 << 2, "react": 1 << 6, "audit_log": 1 << 7, "stream": 1 << 9,
     "view": 1 << 10, "send": 1 << 11, "manage_messages": 1 << 13, "embed_links": 1 << 14, "attach": 1 << 15,
     "history": 1 << 16, "mention_everyone": 1 << 17, "external_emoji": 1 << 18, "connect": 1 << 20,
     "speak": 1 << 21, "voice_activity": 1 << 25, "nickname": 1 << 26, "manage_nicknames": 1 << 27,
     "commands": 1 << 31, "manage_threads": 1 << 34, "public_threads": 1 << 35, "private_threads": 1 << 36,
     "send_in_threads": 1 << 38, "timeout": 1 << 40, "polls": 1 << 49}


def perms(*names: str) -> int:
    out = 0
    for n in names:
        out |= P[n]
    return out


# What every member may do. No @everyone or @here, no private threads, no text-to-speech, no voice messages.
EVERYONE = perms("invite", "react", "stream", "view", "send", "embed_links", "attach", "history", "external_emoji",
                 "connect", "speak", "voice_activity", "nickname", "commands", "public_threads", "send_in_threads",
                 "polls")
MODERATE = perms("kick", "audit_log", "manage_messages", "manage_threads", "timeout", "manage_nicknames")

# ---- roles -------------------------------------------------------------------------------------------------------
# name, colour, hoist, mentionable, permissions. Listed top to bottom; setup orders them so (under the bot's own role).
ROLES = [
    ("Maintainer", 0xA9B8FF, True, False, MODERATE | perms("ban", "mention_everyone")),   # keeps Form Studio
    ("Moderator", 0x86D9AD, True, False, MODERATE),                 # keeps the server: timeouts, kicks, tidying
    ("Contributor", 0x86A8FF, True, False, 0),                      # has a merged pull request
    ("Recipe author", 0xC7B2FF, True, False, 0),                    # kept for the people who earned it; no longer given
    ("Challenge winner", 0xE9B860, True, False, 0),                 # won a weekly challenge (the bot gives it)
    # levels: earned by talking, sharing and helping (the bot counts it; /rank shows yours)
    ("Architect", 0xFF6F51, True, False, 0),                        # level 40
    ("Assembly", 0xC7B2FF, True, False, 0),                         # level 25
    ("Solid", 0x86A8FF, True, False, 0),                            # level 15
    ("Extrude", 0x86D9AD, True, False, 0),                          # level 8
    ("Sketch", 0xD8D3C8, False, False, 0),                          # level 3
    # picked in onboarding or #roles
    ("macOS", 0, False, False, 0), ("Windows", 0, False, False, 0), ("Linux", 0, False, False, 0),
    ("Claude Code", 0, False, False, 0), ("Codex", 0, False, False, 0), ("Gemini CLI", 0, False, False, 0),
    ("Model API", 0, False, False, 0), ("Local models", 0, False, False, 0),
    ("Game dev", 0, False, False, 0), ("3D printing", 0, False, False, 0),
    ("Release pings", 0, False, True, 0),                           # mentioned for every stable release
    ("Challenge pings", 0, False, True, 0),                         # mentioned when a weekly challenge starts
]
LEVELS = [(3, "Sketch"), (8, "Extrude"), (15, "Solid"), (25, "Assembly"), (40, "Architect")]
# the emoji a role is shown with in the role picker and in onboarding (names stay plain)
ROLE_EMOJI = {"macOS": "🍎", "Windows": "🪟", "Linux": "🐧", "Claude Code": "🧡", "Codex": "⚪", "Gemini CLI": "🔷",
              "Model API": "🔑", "Local models": "🖥️", "Game dev": "🎮", "3D printing": "🖨️", "Release pings": "🔔",
              "Challenge pings": "🏁"}
# old name -> new name (same role, same members)
ROLE_RENAMES = {
    "🛠️ Maintainer": "Maintainer", "🧑‍💻 Contributor": "Contributor", "🧩 Recipe author": "Recipe author",
    "🏆 Challenge winner": "Challenge winner", "🏗️ Architect": "Architect", "⚙️ Assembly": "Assembly",
    "🧊 Solid": "Solid", "🧱 Extrude": "Extrude", "📐 Sketch": "Sketch", "🍎 macOS": "macOS", "🪟 Windows": "Windows",
    "🐧 Linux": "Linux", "🧡 Claude Code": "Claude Code", "⚪ Codex": "Codex", "🔷 Gemini CLI": "Gemini CLI",
    "🔑 Model API": "Model API", "🖥️ Local models": "Local models", "🔔 Release pings": "Release pings",
    "🏁 Challenge pings": "Challenge pings",
    "🖨️ Other printer": "3D printing", "Other printer": "3D printing",   # one role for everyone who prints
}
# Roles that are gone: printing is one role, not one per brand, and there is no events channel to ping for.
ROLE_RETIRE = ["🟢 Bambu Lab", "🟠 Prusa", "🔵 Creality", "🎨 I don't print", "📅 Event pings",
               "Bambu Lab", "Prusa", "Creality", "No printer yet", "Event pings"]
R = {k: k for k, *_ in ROLES}
R.update({old: new for old, new in ROLE_RENAMES.items()})

# self-assigned in #roles (the bot's role picker) as well as in onboarding: (group, placeholder, [roles])
ROLE_PICKER = [
    ("system", "Your system", ["macOS", "Windows", "Linux"]),
    ("agent", "Your agent or model", ["Claude Code", "Codex", "Gemini CLI", "Model API", "Local models"]),
    ("make", "What you make", ["Game dev", "3D printing"]),
    ("pings", "Notifications", ["Release pings", "Challenge pings"]),
]

# Recognition. Discord user ids (Developer Mode › right-click a name › Copy User ID).
# The server owner is always a Maintainer. To get the Contributor role, add your GitHub login and Discord id here in
# a pull request; it is given when the pull request merges (and on every setup).
MAINTAINERS: list[str] = []
MODERATORS: list[str] = []
CONTRIBUTORS: dict[str, str] = {}     # GitHub login -> Discord user id

# ---- channels ----------------------------------------------------------------------------------------------------
TEXT, VOICE, CATEGORY, NEWS, STAGE, FORUM = 0, 2, 4, 5, 13, 15

# (key, name shown, type, topic, options). options:
#   access    "read_only" (members react and read), "replies" (forum: members reply, only staff post),
#             "private" (Maintainers, Moderators and the bot only); default: open
#   default   in every member's channel list from the start (onboarding); the others are picked in onboarding
#   tags      forum tags; "!Name" is a tag only moderators may apply
#   emoji, layout ("list"/"gallery"), require_tag
#   slowmode  seconds between a member's messages (a forum: between new posts); reply_slowmode: inside a forum's posts
LAYOUT = [
    ("START HERE", [
        ("welcome", "welcome", TEXT, "What Form Studio is, how a design goes and where everything is.",
         {"access": "read_only", "default": True}),
        ("rules", "rules", TEXT, "The rules of this server and how they are kept. Read them once.",
         {"access": "read_only", "default": True}),
        ("guides", "guides", FORUM, (
            "Complete guides, one per post: installing, your first design, agents and MCP, mesh to CAD, game assets, "
            "optional engines, 3D printing, troubleshooting and contributing.\n\n"
            "Reply in a guide to ask about it. `/guide` shows one from anywhere. The same text is in the repository "
            "under docs/community, where you can improve it with a pull request."),
         {"access": "replies", "tags": ["🚀 Start", "🤖 Agents", "🧊 Create", "📖 Reference", "🖨️ 3D printing", "🛟 Help",
                                        "🧑‍💻 Project"],
          "emoji": "👍", "default": True, "reply_slowmode": 10}),
        ("roles", "roles", TEXT, "Pick your system, your agent, what you make and the pings you want. Change them any time.",
         {"access": "read_only", "default": True}),
    ]),
    ("COMMUNITY", [
        ("general", "general", TEXT, "Talk about designing anything with Form Studio. Try /guide, /docs or /download.",
         {"default": True, "slowmode": 2}),
        ("showcase", "show-and-tell", FORUM, (
            "What you made with Form Studio: a part, a product, a mechanism, a game asset, a textured shell. One post "
            "per design, or use `/showcase`.\n\n"
            "A good post has a render or a photo, what you asked for, how the agent built it and what you changed. "
            "Attach the .formstudio file or the STEP if others may remix it, with its licence."),
         {"tags": ["🧊 3D model", "⚙️ Mechanism", "🎨 Organic & textured", "🧩 Assembly", "🧬 From a mesh", "🎮 Game asset",
                   "🔁 Remix", "🖨️ Printed", "💡 Lessons learned"],
          "emoji": "🔥", "layout": "gallery", "default": True, "slowmode": 60}),
        ("help", "help", FORUM, (
            "Stuck? One post per question, with a tag.\n\n"
            "Say your system and Form Studio version (About, or `form update --check`), your agent and model, what you "
            "asked for, what you expected and what happened, and the output of `form setup --check` for setup problems.\n\n"
            "The bot answers with the guides for your tag; a person follows. When it is solved, right-click the "
            "answer › Apps › Mark as solved. `/bug` shows how to report a bug on GitHub."),
         {"tags": ["📥 Setup", "🤖 Agents & models", "🧠 Designing", "🧬 Mesh to CAD", "🎮 Game assets",
                   "📤 Export & CAD exchange", "🖨️ 3D printing", "🐞 Bug", "✅ Solved"],
          "emoji": "👍", "require_tag": True, "default": True, "slowmode": 60}),
        ("ideas", "ideas", FORUM, (
            "What Form Studio should do next. One idea per post: the problem first, then what you would want. "
            "Vote with the reaction. Maintainers tag what is Planned and what Shipped."),
         {"tags": ["✨ Feature", "🧠 Design intelligence", "🔧 Agent tool", "🧬 Mesh to CAD", "🎮 Game assets",
                   "🖨️ 3D printing", "!🗺️ Planned", "!🚢 Shipped"],
          "emoji": "👍", "default": True, "slowmode": 120}),
        ("challenges", "weekly-challenge", FORUM, (
            "A new design brief every week. Reply in its post with your design: a render or a photo, and how you "
            "made it. Star (⭐) the entries you like. On Sunday at 21:00 UTC the most starred entry wins the "
            "Challenge winner role and the next brief opens. `/challenge` shows this week's brief."),
         {"access": "replies", "tags": ["🟢 Open", "🏆 Closed"], "emoji": "⭐", "layout": "gallery", "default": True}),
        ("lounge", "Lounge", VOICE, "", {"default": True}),
    ]),
    ("BUILD", [
        ("agents", "agents-and-models", TEXT,
         "Claude Code, Codex, Gemini CLI, other MCP agents, model APIs and local models: which design best, and how "
         "to connect them. The guide: Agents and MCP in #guides.", {"default": True}),
        ("mesh-to-cad", "mesh-to-cad", TEXT,
         "Turning STL, OBJ and 3MF meshes into editable CAD: results, reports, deviation maps and edge cases.",
         {"default": True}),
        ("game-assets", "game-assets", TEXT,
         "Game assets (Beta): LODs, UVs, baked maps and collision for Unreal, Unity, Godot and glTF.", {}),
        ("printers", "printing", TEXT,
         "For people who print (optional): slicers, printers, presets, filaments, fit coupons and measured results. "
         "Turn printing on in Settings › General › Set up for.", {}),
    ]),
    ("PROJECT", [
        ("announcements", "announcements", NEWS,
         "Stable releases and project news only. Follow it to get them in your own server.",
         {"access": "read_only", "default": True}),
        ("releases", "releases", TEXT,
         "Every build with its full notes and downloads: stable releases, patches and previews. The only channel "
         "that posts releases.", {"access": "read_only", "default": True}),
        ("github", "github", TEXT,
         "GitHub activity, posted by the bot: issues, pull requests, discussions, failed runs on main and dev, and "
         "the week in numbers.", {"access": "read_only"}),
        ("contributing", "contributing", TEXT,
         "Working on Form Studio's code, docs or the website. Start with the pinned post.", {"slowmode": 2}),
    ]),
    ("STAFF", [
        ("mod-log", "mod-log", TEXT, "AutoMod alerts, reports from members, Discord's community updates and the help desk queue.",
         {"access": "private"}),
    ]),
]
NAMES = {k: n for _, chans in LAYOUT for k, n, *_ in chans}

# Channels that are no longer used but have history: moved here, hidden from members, read-only, never deleted.
ARCHIVE_CATEGORY = "ARCHIVE"
# name on the server (old or current) -> name in the archive
ARCHIVE = {
    "🧯・ci": "archive-ci",              # failed runs now go to #github
    "📅・events": "archive-events",      # challenge results stay in the challenge's own post
    "recipes": "archive-recipes",        # recipes are engine building blocks now, not a public library
}


def N(key: str) -> str:
    """The name a channel is shown with, from its key."""
    return NAMES.get(key, key)


# Renamed: old name -> new name (the channel, its id and its history are kept).
CHANNEL_RENAMES = {
    "📌 START HERE": "START HERE", "💬 COMMUNITY": "COMMUNITY", "⚙️ BUILD": "BUILD", "🔒 STAFF": "STAFF",
    "👋・welcome": "welcome", "📜・rules": "rules", "🎭・roles": "roles", "📘・guides": "guides",
    "📣・announcements": "announcements", "🚀・releases": "releases", "🧊・showcase": "show-and-tell",
    "🧬・mesh-to-cad": "mesh-to-cad", "🤖・agents-and-models": "agents-and-models", "💬・general": "general",
    "🧩・recipes": "archive-recipes", "🛟・help": "help", "💡・ideas": "ideas", "🏁・weekly-challenge": "weekly-challenge",
    "🔊 Lounge": "Lounge", "🧑‍💻・contributing": "contributing", "🐙・github": "github",
    "🖨️・printers-and-slicers": "printing", "🔒・mod-log": "mod-log",
}

# Forum tags renamed in place (the tag keeps its id, so posts keep it): forum key -> {old name: new name}
TAG_RENAMES = {
    "guides": {"Design": "Create", "App": "Project"},
}

# Removed by setup while empty (no messages, no channels inside); one that has messages moves to the archive instead.
RETIRE = [
    ("🙋・introductions", TEXT), ("🍝・wins-and-fails", TEXT), ("🎲・off-topic", TEXT),
    ("🧠・design-and-engineering", TEXT), ("🧪・calibration", TEXT), ("🗳️・polls", TEXT), ("🎙️ Live builds", STAGE),
    ("✨ CREATE", CATEGORY), ("📚 LIBRARY", CATEGORY), ("🛟 HELP & FEEDBACK", CATEGORY),
    ("🏁 CHALLENGES & EVENTS", CATEGORY), ("🖨️ 3D PRINTING (OPTIONAL)", CATEGORY),
]

# ---- server settings -----------------------------------------------------------------------------------------------
VERIFICATION_LEVEL = 2          # medium: a verified email and an account older than five minutes
EXPLICIT_CONTENT_FILTER = 2     # scan media from every member
NOTIFICATIONS = 1               # only @mentions by default

# ---- onboarding (Server Settings › Onboarding) ---------------------------------------------------------------------
# (question, [(option, description, emoji, roles, channels)])
ONBOARDING = [
    ("What brings you here?", [
        ("Designing with an agent", "Agents, models and how to get good designs", "🤖", [], ["agents"]),
        ("Mesh to editable CAD", "Rebuild STL, OBJ and 3MF files as CAD", "🧬", [], ["mesh-to-cad"]),
        ("Game assets", "LODs, UVs, bakes and collision for game engines", "🎮", ["Game dev"], ["game-assets"]),
        ("3D printing", "Slicers, printers and fit (optional)", "🖨️", ["3D printing"], ["printers"]),
        ("Contributing", "The code, the docs and GitHub activity", "🧑‍💻", [], ["contributing", "github"]),
    ]),
    ("Which system do you use?", [
        ("macOS", "", "🍎", ["macOS"], []), ("Windows", "", "🪟", ["Windows"], []), ("Linux", "", "🐧", ["Linux"], []),
    ]),
    ("Which agent or model do you use?", [
        ("Claude Code", "", "🧡", ["Claude Code"], []), ("Codex", "", "⚪", ["Codex"], []),
        ("Gemini CLI", "", "🔷", ["Gemini CLI"], []),
        ("A model API", "Anthropic, OpenAI, OpenRouter…", "🔑", ["Model API"], []),
        ("Local models", "Ollama, LM Studio, llama.cpp", "🖥️", ["Local models"], []),
    ]),
    ("What should we ping you for?", [
        ("Stable releases", "In #announcements, every few weeks", "🔔", ["Release pings"], []),
        ("Weekly challenges", "Every Sunday night, when a new brief opens", "🏁", ["Challenge pings"], []),
    ]),
]
ONBOARDING_SHOWN = 4            # questions asked while joining; the rest are in Channels & Roles

# Rules screening (Server Settings › Safety Setup › Rules Screening): what a new member agrees to before posting.
SCREENING = {
    "description": "Form Studio: an open-source AI CAD studio. Read the rules, then say hello.",
    "rules": [
        "Be kind. Critique designs, not people.",
        "No spam, advertising, invite links or unsolicited DMs.",
        "Share only what you may share, with its licence.",
        "Report security problems privately on GitHub, never in a channel.",
        "Follow Discord's Terms of Service and Community Guidelines.",
    ],
}

# ---- the Server Guide (Server Settings › Onboarding › Server Guide) ---------------------------------------------------
# Applied in the browser (the API has no endpoint a bot may use); kept here so it can be set again the same way.
SERVER_GUIDE = {
    "author": "the server owner",
    "welcome": ("Hi [@username], welcome to Form Studio: describe anything, and an engineer-grade agent builds it as "
                "real, editable CAD. Start with the guides below, show what you make, and ask when you are stuck."),
    # (task, channel, done when: "visit" or "post"); Discord adds "Read the rules" itself
    "todos": [
        ("Read Getting started", "guides", "visit"),
        ("Show something you designed", "showcase", "post"),
        ("Ask when you are stuck", "help", "visit"),
    ],
    # (title, channel, description); a resource channel leaves the channel list for the guide
    "resources": [
        ("About Form Studio", "welcome", "What Form Studio is, how a design goes, and where everything is."),
    ],
}

# ---- AutoMod -----------------------------------------------------------------------------------------------------
# (name, trigger_type, trigger_metadata, actions). Actions: "block" (with the message shown to the member), "alert"
# (to #mod-log), ("timeout", seconds), "block_profile" (member profile rules). Maintainers and Moderators are exempt.
# Discord allows one rule each for spam (3), keyword presets (4) and mention spam (5), and six keyword rules (1).
KEYWORD, SPAM, PRESET, MENTION_SPAM, PROFILE = 1, 3, 4, 5, 6
AUTOMOD = [
    ("Mention spam", MENTION_SPAM, {"mention_total_limit": 6, "mention_raid_protection_enabled": True},
     ["block", "alert", ("timeout", 600)]),
    ("Suspected spam", SPAM, {}, ["block", "alert"]),
    ("Profanity, slurs and sexual content", PRESET, {"presets": [1, 2, 3], "allow_list": []}, ["block", "alert"]),
    ("Invite links to other servers", KEYWORD,
     {"regex_patterns": [r"(?i)(discord\.gg|discord(app)?\.com/invite|discord\.me|dsc\.gg)/[a-z0-9-]+"],
      "allow_list": ["*discord.gg/" + INVITE_CODE + "*"]}, ["block", "alert"]),
    ("Scams and phishing", KEYWORD,
     {"keyword_filter": ["free nitro*", "nitro for free*", "*nitro giveaway*", "*discord-nitro*", "*discordgift*",
                         "*dlscord*", "*disc0rd*", "*steamcommunlty*", "*steamcomunity*", "crypto giveaway*",
                         "claim your airdrop*", "*airdrop is live*", "*double your crypto*", "*seed phrase*",
                         "*wallet connect to claim*", "*t.me/+*"],
      "regex_patterns": [r"(?i)\b(free|claim)\b.{0,40}\b(nitro|robux|v-?bucks|skins?)\b.{0,60}https?://",
                         r"(?i)https?://[^\s/]*(nitro|steam)[^\s/]*\.(ru|tk|ml|ga|cf|gq|xyz|top|click)\b"]},
     ["block", "alert", ("timeout", 3600)]),
    ("Everyone and here pings", KEYWORD, {"regex_patterns": [r"@(everyone|here)\b"]}, ["block", "alert"]),
    ("Link shorteners and IP loggers", KEYWORD,
     {"keyword_filter": ["*grabify.link*", "*iplogger.*", "*2no.co*", "*blasze.*", "*bit.ly/*", "*tinyurl.com/*",
                         "*cutt.ly/*", "*is.gd/*", "*shorturl.at/*", "*rb.gy/*"]}, ["block", "alert"]),
    ("Zalgo text", KEYWORD, {"regex_patterns": [r"[\x{0300}-\x{036F}\x{0489}]{6,}"]}, ["block", "alert"]),
    ("Names that advertise or impersonate", PROFILE,
     {"keyword_filter": ["*discord.gg/*", "*.gg/*", "*free nitro*", "form studio support*", "form studio staff*",
                         "*official support*"]}, ["block_profile", "alert"]),
]
AUTOMOD_BLOCK_MESSAGE = "Blocked by this server's rules. If that was a mistake, ask a moderator in #general."
# Rules the bot made under an older name: kept and renamed, never duplicated.
AUTOMOD_RENAMES = {"Block Mention Spam": "Mention spam", "Block suspected spam": "Suspected spam",
                   "Block slurs and sexual content": "Profanity, slurs and sexual content"}

# ---- posts -------------------------------------------------------------------------------------------------------
# Every post is plain text in Discord markdown. A channel is written {welcome}, {help}… (its key) and becomes a link
# to the channel. "\n\n===\n\n" starts a new message.
WELCOME = """# Welcome to Form Studio

**Describe anything. An engineer-grade agent builds it as real, editable CAD.**

Form Studio is an open-source desktop app for macOS, Windows and Linux. You say what you need in words, with a photo, a sketch, a drawing or a part you already have. The agent of your choice writes a parametric design, and the CAD kernel builds it as a real solid while you watch: features you can click, parameters you can change, and every revision checked on the solid itself.

Take it out as STEP for your CAD program or a CNC shop, as meshes for renders and the web, as a game asset, or to your own slicer if you print. Everything runs on your computer, and 3D printing is optional.

===

## Start in three steps

1. **Read {rules}.** They are short.
2. **Open {guides} and read Getting started.** It takes you from the download to your first released design.
3. **Pick your roles in {roles}:** your system, your agent, what you make and the pings you want.

## Where things are

**Start here**
- {welcome}: this page.
- {rules}: the rules and how they are kept.
- {guides}: complete guides, one per post.
- {roles}: your roles and notifications.

**Community**
- {general}: talk about designing anything.
- {showcase}: what you made, one post per design.
- {help}: one post per question. The bot answers with the right guide, a person follows.
- {ideas}: what Form Studio should do next. Vote with a reaction.
- {challenges}: a new design brief every week.

**Build**
- {agents}: Claude Code, Codex, other MCP agents, model APIs and local models.
- {mesh-to-cad}: STL, OBJ and 3MF rebuilt as editable CAD.
- {game-assets}: game assets for Unreal, Unity, Godot and glTF (Beta).
- {printers}: slicers, printers and fit, for people who print.

**Project**
- {releases}: every build with its notes and downloads. The only channel that posts releases.
- {announcements}: stable releases and project news. Follow it to get them in your own server.
- {github}: issues, pull requests, discussions and failed runs.
- {contributing}: working on Form Studio itself.

===

## How a design goes

1. **Describe.** Words, a photo with a card or coin for scale, a sketch in millimetres, a STEP part, a PDF drawing, a link, or a mesh to rebuild as CAD.
2. **Concepts.** For a new idea the agent proposes several genuinely different concepts, each a real CAD model. You pick one.
3. **Build.** The design grows in front of you, feature by feature, as real CAD in the kernel.
4. **Review.** Every revision is checked on the solid. Each result says how it is known: computed, heuristic, simulated or measured.
5. **Release.** You approve. STEP, STL, OBJ, GLB and 3MF are frozen with SHA-256 hashes. No agent can approve a release.

## The bot

- `/guide` shows a guide. `/docs` finds a page of the documentation. `/download` gives the downloads for your system.
- `/bug` shows how to report a bug so it gets fixed. `/help` says where to ask what.
- `/showcase` posts a design. `/challenge` shows this week's brief.
- `/roles` changes your roles. `/rank` and `/leaderboard` show levels. `/thanks @someone` thanks a person who helped.
- Right-click a message › **Apps › Report to moderators** sends it to the moderators privately.

## Links

- Download: <https://github.com/kaizensx/form-studio/releases/latest>
- Website and docs: <https://kaizensx.github.io/form-studio/>
- Source: <https://github.com/kaizensx/form-studio>
- Invite a friend: <https://discord.gg/b6ZgyndkmS>"""

RULES_POST = """# Rules

This server is for people who design things with Form Studio, and for people who build Form Studio. The rules are few. The full [Code of Conduct](https://github.com/kaizensx/form-studio/blob/main/CODE_OF_CONDUCT.md) applies here too.

## 1. Be kind

Critique designs, not people. Everyone was a beginner once. No harassment, hate speech, slurs, sexual content or personal attacks, in channels or in direct messages.

## 2. Say how you know

Measured, computed, simulated or assumed: say which. A render is not a part, a slice is not a print, and a fit yield is a model. This is how Form Studio works, and it is how we talk about results here.

## 3. Ask in the right place

Questions go in {help}: one post per question, with a tag, your system, your version, your agent and your model. Ideas go in {ideas}. Bugs you can reproduce go to GitHub (`/bug` shows how). Please do not ask the same thing in several channels, and do not ping or DM maintainers for support.

## 4. Share what you may share

Post only designs and files you made or are allowed to share, and say their licence. Credit the work you built on.

## 5. No spam and no advertising

Your own work is welcome in {showcase}. Selling, invite links to other servers, referral links, mass mentions and DMs to strangers are not.

## 6. Keep security issues private

Never post a vulnerability in a channel. Report it at <https://github.com/kaizensx/form-studio/security/advisories/new>.

## 7. Keep it safe for work

Messages, pictures, names and avatars. People open this server at their desks.

## 8. Follow Discord's rules

The [Terms of Service](https://discord.com/terms) and the [Community Guidelines](https://discord.com/guidelines) apply. You must be old enough to use Discord in your country.

===

## How the rules are kept

- **AutoMod** blocks spam, mention spam, scam links, invite links to other servers and slurs before they are posted. If it blocked something by mistake, say so in {general}.
- **Report a message:** right-click it › **Apps › Report to moderators**. Only moderators see the report.
- **What moderators do:** a reminder first, then a timeout, then removal from the server. Spam, scams and hate skip the reminder.
- **Moderators may remove** anything that breaks these rules. Decisions about the project are made on GitHub, in the open.
- **Something wrong with a moderator's decision?** Write to a Maintainer."""

ROLES_POST = """# Roles

Pick what fits. Roles help people with the same system, agent or interest find each other, and decide which pings reach you. Pick a role in a menu to add it; pick it again to remove it. `/roles` shows the ones you have.

- **Your system:** macOS, Windows or Linux.
- **Your agent or model:** Claude Code, Codex, Gemini CLI, a model API or local models.
- **What you make:** Game dev opens {game-assets}. 3D printing opens {printers}.
- **Notifications:** Release pings are sent for stable releases only, in {announcements}. Challenge pings are sent when a weekly brief opens.

## Roles you earn

- **Levels** come by themselves as you talk, share and help: {levels}. `/rank` shows yours.
- **Challenge winner:** the most starred entry of a weekly challenge.
- **Contributor:** a pull request of yours was merged. See the guide Contributing in {guides}.
- **Moderator** and **Maintainer** keep the server and the project."""

CONTRIBUTING_POST = """# Build Form Studio with us

Form Studio is open source under the MIT licence: the app, the engine, the docs and the website.

1. **Read the guide.** *Contributing* in {guides} has the setup, the branches and what a pull request needs. The same text is in [CONTRIBUTING.md](https://github.com/kaizensx/form-studio/blob/main/CONTRIBUTING.md). If an agent helps you, it reads [AGENTS.md](https://github.com/kaizensx/form-studio/blob/main/AGENTS.md).
2. **Pick an issue.** [good first issue](https://github.com/kaizensx/form-studio/labels/good%20first%20issue) and [help wanted](https://github.com/kaizensx/form-studio/labels/help%20wanted) are a good start, or say here what you want to work on.
3. **Open a pull request into `dev`.** CI runs the tests on the real CAD kernel; a maintainer reviews.

- Issues, pull requests, discussions and failed runs are posted in {github}.
- **The Contributor role:** add your GitHub login and your Discord user id to `CONTRIBUTORS` in `scripts/discord/server.py` in your pull request. The role is given when it merges.
- **Security issues** are reported privately: <https://github.com/kaizensx/form-studio/security/advisories/new>"""

STAFF_POST = """# Moderator handbook

**What runs by itself**
- AutoMod blocks spam, mention spam (6 or more mentions, with a 10 minute timeout), scam and phishing phrases (1 hour timeout), invite links to other servers, link shorteners, @everyone and @here, zalgo text, profanity, slurs and sexual content, and profile names that advertise or impersonate staff. Every block is logged here with the message.
- New members pass rules screening and onboarding. Verification is medium: a verified email and an account older than five minutes.
- The help desk answers every new post in {help} with the guides for its tag, lists posts nobody answered for six hours in this channel, reminds quiet posts after 7 days and archives them after 14, and archives solved posts after a day.
- Members report a message with right-click › Apps › Report to moderators. The report arrives here with a link.

**What a moderator does**
1. A first, small problem: reply with a reminder and a link to {rules}.
2. Repeated or deliberate: time the member out (right-click › Timeout). An hour, then a day.
3. Spam, scams, hate: remove the message, ban, and delete the last day of their messages.
4. Write one line here about what you did and why.

**What only a Maintainer does**
- Bans that are not spam, role changes, and anything about the server's structure. The structure is code: `scripts/discord/server.py`, applied by Actions › Discord › setup. Do not change channels, roles or AutoMod by hand: the next setup puts them back."""

# Guides: one forum post each in #guides, from docs/community/<slug>.md, as plain messages.
# (slug, title, tag, cover art, one-line summary for /guide)
GUIDES = [
    ("getting-started", "Getting started", "Start", "hero",
     "Install on macOS, Windows or Linux, the first start, and your first design from description to release."),
    ("agents-and-mcp", "Agents and MCP: Claude Code, Codex and others", "Agents", "talk",
     "Use Form Studio from Claude Code, Codex, Gemini CLI, Cursor or any MCP client, with a model API or a local model."),
    ("mesh-to-cad", "Mesh to editable CAD", "Create", "proved",
     "Turn an STL, OBJ or 3MF into CAD you can change, read the report, and know what it cannot do yet."),
    ("game-assets", "Game assets", "Create", "made-game-chest",
     "LODs, UVs, baked maps and collision for Unreal, Unity, Godot and glTF (Beta)."),
    ("optional-engines", "Optional engines and programs", "Reference", "shape",
     "CAD-Recode, CADFit, CoACD, the CADEvolve corpus, Blender, FreeCAD, OpenSCAD and slicers: what each does, its size "
     "and its licence."),
    ("printing", "3D printing (optional)", "3D printing", "slicer",
     "Your slicer and presets, checks for printed parts, fit, print simulation and comparing printers."),
    ("troubleshooting", "Troubleshooting and reporting bugs", "Help", "headless",
     "Fix the common problems, ask for help well, and write a bug report that gets fixed."),
    ("contributing", "Contributing", "Project", "release",
     "Where contributions go, the development setup, the engineering principles and pull requests."),
]
GUIDE_URL = REPO + "/blob/dev/docs/community/"
# a guide that was renamed keeps its forum post (and its replies): old title -> new title
GUIDE_RENAMES = {
    "Install and first start": "Getting started",
    "Install and choose what you make": "Getting started",
    "Agents and models": "Agents and MCP: Claude Code, Codex and others",
    "Your slicer, your printers": "3D printing (optional)",
    "3D printing (optional): slicers, printers and fit": "3D printing (optional)",
}
# Guide posts that the new guides replace. One that only the bot wrote in is removed; one with replies from members is
# closed and kept (archived and locked), so nothing a person wrote is lost.
GUIDE_RETIRE = [
    "Start a design from anything", "Design intelligence: brief, plan, critique", "Mechanisms, shapes and texture",
    "Linked conversations and forks", "Checks and evidence", "Revisions, compare and variants", "Release a design",
    "Move and share designs", "Headless: the CLI and MCP", "Recipes: use, write and share",
]


def guide_text(slug: str) -> str:
    return (GUIDE_DIR / f"{slug}.md").read_text(encoding="utf-8")


# help forum tag -> the guides (by title) a new post with it is pointed to
HELP_GUIDES = {
    "Setup": ["Getting started", "Troubleshooting and reporting bugs"],
    "Agents & models": ["Agents and MCP: Claude Code, Codex and others"],
    "Designing": ["Getting started"],
    "Mesh to CAD": ["Mesh to editable CAD", "Optional engines and programs"],
    "Game assets": ["Game assets", "Optional engines and programs"],
    "Export & CAD exchange": ["Optional engines and programs"],
    "3D printing": ["3D printing (optional)"],
    "Bug": ["Troubleshooting and reporting bugs"],
}

# /docs: the documentation, by topic
DOC_PAGES = [
    ("Features: everything Form Studio does", BLOB + "docs/FEATURES.md"),
    ("The desktop app", BLOB + "docs/APP.md"),
    ("CLI: every form command", BLOB + "docs/CLI.md"),
    ("MCP: every agent tool", BLOB + "docs/MCP.md"),
    ("AGENTS.md: the guide for coding agents", BLOB + "AGENTS.md"),
    ("Architecture", BLOB + "docs/ARCHITECTURE.md"),
    ("Compatibility and testing", BLOB + "docs/VERIFICATION.md"),
    ("Releasing: channels and versions", BLOB + "docs/RELEASING.md"),
    ("Changelog", BLOB + "CHANGELOG.md"),
    ("Contributing", BLOB + "CONTRIBUTING.md"),
    ("Licences of everything shipped or installed", REPO + "/blob/dev/THIRD_PARTY_NOTICES.md"),
    ("The website and its docs", DOCS),
]

# ---- levels and challenges (run by the worker, scripts/discord/worker) -------------------------------------------------
# XP: one message earns 15–25 XP, at most once a minute; a /thanks gives 25; an answer marked solved gives 40;
# a /showcase post gives 30. XP for the next level from level n: 5n² + 50n + 100 (the usual curve).
XP = {"message": [15, 25], "cooldown_s": 60, "thanks": 25, "thanks_per_day": 3, "solved": 40, "showcase": 30}

# One brief a week: it closes on Sunday 21:00 UTC, the most ⭐ entry wins, and the next brief opens at once.
# (title, the brief, what makes an entry count)
CHALLENGES = [
    # week 1 opened with this brief; it stays first so the running challenge keeps its text
    ("Desk-edge cable clip", "A clip that holds three cables along the edge of a desk 18–25 mm thick.",
     "Show it on a desk, rendered or real, with the fit you chose."),
    ("A planetary gear stage", "A planetary stage with a 1:4 or 1:5 ratio that a hand crank can turn.",
     "Post the ratio, the tooth counts and the critique's numbers."),
    ("A textured grip", "A handle or grip with a texture you would want to hold: knurl, ribs or a fine mesh texture.",
     "Say which tier the texture is (CAD geometry or mesh texture) and why."),
    ("A product shell", "The housing of a small product: a remote, a speaker, a mouse. Lofted, not boxy.",
     "Show the six-view sheet and the section."),
    ("Mesh to CAD", "Take an STL you own and rebuild it as editable CAD with Make editable.",
     "Post the layer reached, the Hausdorff distance and one edit you made."),
    ("A print-in-place hinge", "A case or a box with a hinge that works straight out of the build.",
     "Show it opening, rendered or real. Say the clearance you used."),
    ("A replacement knob", "A knob for something you own whose knob broke or went missing.",
     "Measure the shaft and say how you measured it."),
    ("A camera mount", "An Arca-type plate or a clamp for a camera or a phone.",
     "Name the interface dimensions and where they come from."),
    ("A lamp", "A table lamp or a shade: a revolve, a loft or a lattice.",
     "A photoreal render counts as much as a photo."),
    ("A four-bar mechanism", "Anything that moves on a four-bar linkage: a gripper, a lid, a toy.",
     "Post the Grashof class and the transmission angle from form.craft."),
    ("A helmet or visor", "A shell for a head, a model or a toy: lofted from sections.",
     "Show the critique's symmetry and fillet numbers."),
    ("A drawer organiser from one number", "Dividers for a drawer, made from its inside width alone.",
     "Say the one number you measured."),
    ("A snap-fit enclosure", "An enclosure for a small board that closes with snap fits, no screws.",
     "Post the snap's strain from form.craft."),
    ("Something you fixed", "Free brief: a part that fixed something broken in your home.",
     "Tell the story: what broke, what you measured, how it fits now."),
]
