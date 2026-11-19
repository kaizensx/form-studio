"""The Form Studio Discord server, as data: roles, channels, forums, onboarding, levels, challenges and the posts.

setup_server.py makes the server match this, as often as it is run. It deletes only what RETIRE lists, and only while
it is empty. snapshot.py records the server before and after every setup (Actions artifacts) for rollback.
The interactive bot (slash commands, buttons, role pickers, levels, weekly challenges) is the Cloudflare Worker in
scripts/discord/worker/; it reads the channel names and roles from here (worker/config.json, written by setup).

The design system:
- Names. Every category and channel has one emoji and a short lowercase name: "🧊・showcase". Code refers to channels
  by their key ("showcase"); NAMES maps a key to the name shown.
- Colour carries meaning, as in the app (form/app/qml/Form/Theme.qml): datum = official, blueprint = discussion,
  violet = previews and recipes, amber = attention, signal = failed, pass = done.
- Embeds. One palette colour, a title with one emoji, short paragraphs, and the footer "Form Studio · Section".
"""

SITE = "https://kaizensx.github.io/form-studio/"
DOCS = SITE + "docs/"
FEATURES = DOCS + "features.html"
REPO = "https://github.com/kaizensx/form-studio"
RAW = "https://raw.githubusercontent.com/kaizensx/form-studio/main/"
ICON = RAW + "form/app/assets/icon-64.png"
GUILD_DESCRIPTION = "Form Studio: describe a part, get a file you can print. Open-source AI to CAD."
BOT_DESCRIPTION = ("The Form Studio bot. Posts releases, GitHub activity and the weekly digest, "
                   "answers new help posts with the right guides, and keeps the server in shape. "
                   "Source: github.com/kaizensx/form-studio/tree/main/scripts/discord")

# The permanent invite (to #welcome) that the README and the website link to. setup_server.py creates it when it is
# missing and prints the code; keep the code here so the links stay the same.
INVITE_CODE = "b6ZgyndkmS"
INVITE = "https://discord.gg/" + INVITE_CODE

# ---- roles -------------------------------------------------------------------------------------------------------
# name, colour, hoist, mentionable. Listed top to bottom; setup orders them so (under the bot's own role).
ROLES = [
    ("🛠️ Maintainer", 0xB9E8D7, True, False),          # keeps Form Studio
    ("🧑‍💻 Contributor", 0x86A8FF, True, False),         # has a merged pull request
    ("🧩 Recipe author", 0xC7B2FF, True, False),        # has a recipe in the community gallery
    ("🏆 Challenge winner", 0xE9B860, True, False),     # won a weekly challenge (the bot gives it)
    # levels: earned by talking, sharing and helping (the bot counts it; /rank shows yours)
    ("🏭 Print Farm", 0xFF6F51, True, False),           # level 40
    ("⚙️ Assembly", 0xC7B2FF, True, False),            # level 25
    ("🧊 Solid", 0x86A8FF, True, False),               # level 15
    ("📏 Calibrated", 0x86D9AD, True, False),           # level 8
    ("🧱 First Layer", 0xD8D3C8, False, False),         # level 3
    # picked in onboarding or #roles
    ("🍎 macOS", 0, False, False), ("🪟 Windows", 0, False, False), ("🐧 Linux", 0, False, False),
    ("🟢 Bambu Lab", 0, False, False), ("🟠 Prusa", 0, False, False), ("🔵 Creality", 0, False, False),
    ("🖨️ Other printer", 0, False, False), ("✏️ No printer yet", 0, False, False),
    ("🧡 Claude Code", 0, False, False), ("⚪ Codex", 0, False, False), ("🔷 Gemini CLI", 0, False, False),
    ("🔑 Model API", 0, False, False), ("🖥️ Local models", 0, False, False),
    ("🔔 Release pings", 0, False, True),               # mentioned for every stable release
    ("🏁 Challenge pings", 0, False, True),             # mentioned when a weekly challenge starts
    ("📅 Event pings", 0, False, True),                 # mentioned when a live session is scheduled
]
LEVELS = [(3, "🧱 First Layer"), (8, "📏 Calibrated"), (15, "🧊 Solid"), (25, "⚙️ Assembly"), (40, "🏭 Print Farm")]
# old name -> new name (same role, same members)
ROLE_RENAMES = {
    "Maintainer": "🛠️ Maintainer", "Contributor": "🧑‍💻 Contributor", "Recipe author": "🧩 Recipe author",
    "macOS": "🍎 macOS", "Windows": "🪟 Windows", "Linux": "🐧 Linux", "Bambu Lab": "🟢 Bambu Lab",
    "Prusa": "🟠 Prusa", "Creality": "🔵 Creality", "Other printer": "🖨️ Other printer",
    "No printer yet": "✏️ No printer yet", "Claude Code": "🧡 Claude Code", "Codex": "⚪ Codex",
    "Gemini CLI": "🔷 Gemini CLI", "Model API": "🔑 Model API", "Local models": "🖥️ Local models",
    "Release pings": "🔔 Release pings",
    "Creality / Elegoo / other": "🖨️ Other printer", "Just designing": "✏️ No printer yet",
}
R = {k: k for k, *_ in ROLES}
R.update({old: new for old, new in ROLE_RENAMES.items()})   # code may say R["Maintainer"]

# self-assigned in #roles (the bot's role picker) as well as in onboarding: (group, placeholder, [roles])
ROLE_PICKER = [
    ("system", "Your system", ["🍎 macOS", "🪟 Windows", "🐧 Linux"]),
    ("printer", "What you print with", ["🟢 Bambu Lab", "🟠 Prusa", "🔵 Creality", "🖨️ Other printer", "✏️ No printer yet"]),
    ("agent", "Your agent or model", ["🧡 Claude Code", "⚪ Codex", "🔷 Gemini CLI", "🔑 Model API", "🖥️ Local models"]),
    ("pings", "Notifications", ["🔔 Release pings", "🏁 Challenge pings", "📅 Event pings"]),
]

# Recognition. Discord user ids (Developer Mode › right-click a name › Copy User ID).
# The server owner is always a Maintainer. To get the Contributor role, add your GitHub login and Discord id here in
# a pull request; it is given when the pull request merges (and on every setup).
MAINTAINERS: list[str] = []
CONTRIBUTORS: dict[str, str] = {}     # GitHub login -> Discord user id
RECIPE_AUTHORS: dict[str, str] = {}   # GitHub login -> Discord user id

# ---- channels ----------------------------------------------------------------------------------------------------
TEXT, VOICE, CATEGORY, NEWS, STAGE, FORUM = 0, 2, 4, 5, 13, 15

# (key, name shown, type, topic, options). options:
#   access    "read_only" (members react and read), "replies" (forum: members reply, only staff post),
#             "private" (Maintainers and the bot only); default: open
#   default   in every member's channel list from the start (onboarding)
#   tags, emoji, layout ("list"/"gallery"), require_tag, slowmode
LAYOUT = [
    ("📌 START HERE", [
        ("welcome", "👋・welcome", TEXT, "What Form Studio is and where everything is. Start here.",
         {"access": "read_only", "default": True}),
        ("rules", "📜・rules", TEXT, "Six short rules. Read them once.", {"access": "read_only", "default": True}),
        ("roles", "🎭・roles", TEXT, "Pick your system, printer, agent and pings with the menus below. Change them any time.",
         {"access": "read_only", "default": True}),
        ("announcements", "📣・announcements", NEWS, "Stable releases and news. Follow it to get them in your own server.",
         {"access": "read_only", "default": True}),
        ("releases", "🚀・releases", TEXT, "Every build with its notes and downloads: stable releases and previews.",
         {"access": "read_only", "default": True}),
    ]),
    ("💬 COMMUNITY", [
        ("general", "💬・general", TEXT, "Talk about designing and printing parts. Try /recipe, /guide or /rank.",
         {"default": True}),
        ("introductions", "🙋・introductions", TEXT,
         "Say hi: what you print with, what you want to design, which agent you use.", {"default": True, "slowmode": 30}),
        ("showcase", "🧊・showcase", FORUM, (
            "Parts you designed with Form Studio. One post per part, or use /showcase.\n\n"
            "A good post has a photo of the print (or a render), what it is for, the printer, filament and slicer, and "
            "what you learned. Attach the .formstudio file if others may remix it, with its licence."),
         {"tags": ["🖨️ Printed", "🧊 3D model", "⚙️ Assembly", "🔁 Remix", "🌱 First print", "💥 Failure"],
          "emoji": "🔥", "layout": "gallery", "default": True}),
        ("wins-and-fails", "🍝・wins-and-fails", TEXT,
         "The print that came out perfect, and the spaghetti. Both teach something.", {"default": True}),
        ("off-topic", "🎲・off-topic", TEXT, "Everything that is not Form Studio.", {"default": True, "slowmode": 5}),
    ]),
    ("🔧 WORKSHOP", [
        ("printers", "🖨️・printers-and-slicers", TEXT,
         "Bambu Studio, OrcaSlicer, PrusaSlicer and friends: profiles, presets, filaments.", {"default": True}),
        ("agents", "🤖・agents-and-models", TEXT,
         "Claude Code, Codex, Gemini CLI, model APIs and local models: what designs well.", {"default": True}),
        ("design-tips", "📐・design-tips", TEXT,
         "Tolerances, fits, overhangs, wall thickness, threads: CAD know-how.", {"default": True}),
        ("calibration", "🧪・calibration", TEXT,
         "Fit coupons, measured results and printer bias: numbers that make fits land.", {}),
    ]),
    ("🏁 CHALLENGES & EVENTS", [
        ("challenges", "🏁・weekly-challenge", FORUM, (
            "A new design brief every week. Reply in its post with your design: a render or a photo, and how you "
            "made it. Star (⭐) the entries you like. On Sunday at 21:00 UTC the most starred entry wins the "
            "🏆 Challenge winner role and the next brief opens."),
         {"access": "replies", "tags": ["🟢 Open", "🏆 Closed"], "emoji": "⭐", "layout": "gallery", "default": True}),
        ("polls", "🗳️・polls", TEXT, "Polls about what comes next. Make one with /poll.", {"default": True}),
        ("events", "📅・events", TEXT, "Live build sessions, challenge results and other scheduled events.",
         {"access": "read_only", "default": True}),
        ("lounge", "🔊 Lounge", VOICE, "", {"default": True}),
        ("live", "🎙️ Live builds", STAGE, "", {"default": True}),
    ]),
    ("📚 LIBRARY", [
        ("guides", "📘・guides", FORUM, (
            "How to do things in Form Studio, one guide per post, with links to the full documentation. "
            "Reply in a guide to ask about it; /guide finds one from anywhere."),
         {"access": "replies", "tags": ["🚀 Start", "🤖 Agents", "🖨️ Printing", "🧭 App", "📖 Reference"],
          "emoji": "👍", "default": True}),
        ("recipes", "🧩・recipes", FORUM, (
            "Recipes are parametric building blocks written as code, with their own checks. Every built-in recipe has "
            "a post here; /recipe shows one anywhere.\n\nShare your own: the .formrecipe file, a render from a real "
            "build, what its parameters do and its licence. Tag it Review wanted."),
         {"tags": ["📦 Built-in", "🌍 Community", "👀 Review wanted", "✅ Accepted", "💡 Idea"], "emoji": "👍",
          "layout": "gallery", "default": True}),
    ]),
    ("🛟 HELP & FEEDBACK", [
        ("help", "🛟・help", FORUM, (
            "Stuck? One post per question, with a tag.\n\n"
            "Say your system and Form Studio version (Help › About), your printer and slicer, what you did, what you "
            "expected and what happened, and `form doctor` for setup problems.\n\n"
            "When it is solved, right-click the answer › Apps › Mark as solved."),
         {"tags": ["📥 Install", "🤖 Agents & models", "🖨️ Printers & slicers", "📏 Checks & fit", "📤 Export",
                   "🐞 Bug", "✅ Solved"], "emoji": "👍", "require_tag": True, "default": True}),
        ("ideas", "💡・ideas", FORUM, (
            "What Form Studio should do next. One idea per post: the problem first, then what you would want. "
            "Vote with the reaction. Maintainers tag what is Planned and what Shipped."),
         {"tags": ["✨ Feature", "🔧 Agent tool", "🖨️ Printer support", "🧩 Recipe", "🗺️ Planned", "🚢 Shipped"],
          "emoji": "👍", "default": True}),
    ]),
    ("⚙️ BUILD", [
        ("contributing", "🧑‍💻・contributing", TEXT,
         "Working on Form Studio's code, docs, recipes or the website. Start with the pinned post.", {}),
        ("github", "🐙・github", TEXT, "Issues, pull requests and discussions on GitHub, posted by the bot.",
         {"access": "read_only"}),
        ("ci", "🧯・ci", TEXT, "Failed runs on main and dev, posted by the bot.", {"access": "read_only"}),
    ]),
    ("🔒 STAFF", [
        ("mod-log", "🔒・mod-log", TEXT, "AutoMod alerts, Discord's community updates and the help desk queue.",
         {"access": "private"}),
    ]),
]
NAMES = {k: n for _, chans in LAYOUT for k, n, *_ in chans}


def N(key: str) -> str:
    """The name a channel is shown with, from its key."""
    return NAMES.get(key, key)


# Renamed: old name -> new name (the channel, its id and its history are kept). Every plain key is renamed too.
CHANNEL_RENAMES = {
    "👋  START HERE": "📌 START HERE", "START HERE": "📌 START HERE", "COMMUNITY": "💬 COMMUNITY",
    "💬  COMMUNITY": "💬 COMMUNITY", "LIBRARY": "📚 LIBRARY", "HELP & FEEDBACK": "🛟 HELP & FEEDBACK",
    "🛟  HELP": "🛟 HELP & FEEDBACK", "BUILD": "⚙️ BUILD", "🛠  BUILD FORM STUDIO": "⚙️ BUILD", "STAFF": "🔒 STAFF",
    "moderator-only": "🔒・mod-log", "Workshop": "🔊 Lounge",
    **{k: n for k, n in NAMES.items()},
}

# Deleted by setup, but only while empty (no messages, no channels inside). The before-snapshot records them.
RETIRE = [
    ("prints", TEXT), ("Print queue", VOICE), ("General", VOICE),
    ("🧊  FORM STUDIO", CATEGORY), ("🔊  WORKSHOP", CATEGORY), ("Text Channels", CATEGORY), ("Voice Channels", CATEGORY),
]

# ---- onboarding (Server Settings › Onboarding) ---------------------------------------------------------------------
# (question, [(option, description, emoji, roles, channels)])
ONBOARDING = [
    ("What brings you here?", [
        ("Designing parts", "Show what you made, find recipes, join the challenge", "🧊", [], ["showcase", "recipes", "challenges"]),
        ("Getting help", "Guides and the help forum", "🛟", [], ["help", "guides"]),
        ("Calibrating my printer", "Fit coupons and measured results", "🧪", [], ["calibration"]),
        ("Building Form Studio", "The code, CI and GitHub channels", "🧑‍💻", [], ["contributing", "github", "ci"]),
    ]),
    ("What do you print with?", [
        ("Bambu Lab", "", "🟢", ["🟢 Bambu Lab"], []), ("Prusa", "", "🟠", ["🟠 Prusa"], []),
        ("Creality", "", "🔵", ["🔵 Creality"], []),
        ("Another printer", "Elegoo, Anycubic, Voron, Snapmaker…", "🖨️", ["🖨️ Other printer"], []),
        ("No printer yet", "3D models, or printing elsewhere", "✏️", ["✏️ No printer yet"], []),
    ]),
    ("Which agent or model do you use?", [
        ("Claude Code", "", "🧡", ["🧡 Claude Code"], []), ("Codex", "", "⚪", ["⚪ Codex"], []),
        ("Gemini CLI", "", "🔷", ["🔷 Gemini CLI"], []),
        ("A model API", "Anthropic, OpenAI, OpenRouter…", "🔑", ["🔑 Model API"], []),
        ("Local models", "Ollama, LM Studio, llama.cpp", "🖥️", ["🖥️ Local models"], []),
    ]),
    ("What should we ping you for?", [
        ("Stable releases", "In #announcements, about once a month", "🔔", ["🔔 Release pings"], []),
        ("Weekly challenges", "Every Sunday night, when a new brief opens", "🏁", ["🏁 Challenge pings"], []),
        ("Live sessions", "When a live build is scheduled", "📅", ["📅 Event pings"], []),
    ]),
    ("Which system do you use?", [
        ("macOS", "", "🍎", ["🍎 macOS"], []), ("Windows", "", "🪟", ["🪟 Windows"], []),
        ("Linux", "", "🐧", ["🐧 Linux"], []),
    ]),
]

# Discord shows a few questions while joining; the rest are in Channels & Roles (<id:customize>).
ONBOARDING_SHOWN = 4

# ---- the Server Guide (Server Settings › Onboarding › Server Guide) ---------------------------------------------------
# Applied in the browser (the API has no endpoint a bot may use); kept here so it can be set again the same way.
SERVER_GUIDE = {
    "author": "the server owner",
    "welcome": ("Hi [@username], welcome to Form Studio: an open-source desktop app where an AI agent designs parts in a "
                "real CAD kernel, checks them on the solid and slices them with your own slicer. Start with the guides "
                "below, show what you make, and ask when you are stuck."),
    # (task, channel, done when: "visit" or "post"); Discord adds "Read the rules" itself
    "todos": [
        ("Learn the app, one guide at a time", "guides", "visit"),
        ("Show a part you designed", "showcase", "post"),
        ("Ask when you are stuck", "help", "visit"),
    ],
    # (title, channel, description); a resource channel leaves the channel list for the guide
    "resources": [
        ("About Form Studio", "welcome", "What Form Studio is, how a design goes, and where everything is."),
    ],
}

# ---- AutoMod -----------------------------------------------------------------------------------------------------
# name, trigger_type, trigger_metadata, block (or only alert). Alerts go to #mod-log; Maintainers are exempt.
AUTOMOD = [
    ("Block Mention Spam", 5, {"mention_total_limit": 8, "mention_raid_protection_enabled": True}, True),
    ("Block suspected spam", 3, {}, True),
    ("Block slurs and sexual content", 4, {"presets": [2, 3]}, True),
    ("Invite links to other servers", 1, {"regex_patterns": [r"(discord\.gg|discord(app)?\.com/invite)/[a-z0-9-]+"],
                                          "allow_list": []}, True),
]

# ---- posts -------------------------------------------------------------------------------------------------------
RULES = [
    ("Be kind", "Critique designs, not people. Everyone was a beginner once."),
    ("Real results only", "Say what was printed and what was simulated. A slice is a simulation; a fit yield is a model."),
    ("Ask in #help", "One post per question, with a tag, your system, version, printer and slicer."),
    ("Share what you may share", "Only models you made or are allowed to share, with their licence."),
    ("No spam or ads", "Your own work is welcome in #showcase. Selling, invite links and DMs to strangers are not."),
    ("Security issues stay private", "Report them at github.com/kaizensx/form-studio/security, never in a channel."),
]

# Guides: one forum post each in #guides. (title, tag, art, text, [(button, url)])
GUIDES = [
    ("Install and first start", "Start", "hero",
     "Download Form Studio for macOS, Windows or Linux. The first start installs what it needs by itself: the "
     "standard-parts libraries, a slicer if you print, an agent and its sign-in. It pauses only when you have to sign "
     "in or download something, and shows every command before it runs.\n\n"
     "Choose the Stable channel for releases or Preview for builds from `dev` in Settings › Updates. "
     "`form setup --auto` does the same setup headless, and `form doctor` shows what was found.",
     [("Download", REPO + "/releases/latest"), ("Setup and updates", FEATURES + "#setup-settings-and-updates"),
      ("Try it in your browser", SITE + "#try")]),
    ("Start a design from anything", "Start", "feature-start",
     "Home is one composer for whatever you have: words, a photo with a bank card or a coin for scale, a sketch in "
     "millimetres, a STEP, STL or 3MF part, a PDF drawing or a link. Sizes read off a photo are labelled "
     "\"estimated from the photo\" and stay assumed until you measure them.\n\n"
     "Choose **For my printer** or **Just a 3D model** under the composer. The workspace opens at once and the "
     "design grows feature by feature as it is built.",
     [("Start from anything", FEATURES + "#start-from-anything"), ("Concepts and measurements", FEATURES + "#concepts-and-measurements")]),
    ("Agents and models", "Agents", "feature-talk",
     "Each conversation picks its agent, model and reasoning effort: Claude Code, Codex, Gemini CLI and other agent "
     "apps, a model API (Anthropic, OpenAI, Gemini, OpenRouter and more, found from your keys), a local model from "
     "Ollama, LM Studio or llama.cpp, or any provider you add by its address.\n\n"
     "The agent's steps fold into the conversation, questions arrive as cards, and time, tokens and cost are shown "
     "per reply. Retry any reply with another model.",
     [("Conversations and agents", FEATURES + "#conversations-and-agents"), ("Any model, any provider", FEATURES + "#any-model-any-provider")]),
    ("How a part is proved: checks and fit", "Printing", "feature-proved",
     "Every revision is rebuilt and checked on the solid: one valid solid, interfaces as modelled, a closed export "
     "mesh, the build volume, the thinnest wall, overhangs and more. Each result says how it is known: computed, "
     "heuristic, simulated or measured.\n\n"
     "Fit is modelled from the object's dimension, your printer's bias and spread for the filament, and the "
     "tolerance you accept, and reports the chance the gap lands in the window and the cheapest way to raise it.",
     [("Checks and evidence", FEATURES + "#checks-and-evidence"), ("Fit", FEATURES + "#fit"),
      ("Verification", DOCS + "verification.html")]),
    ("Your slicer, your printers", "Printing", "feature-slicer",
     "Form Studio slices with the slicer you already use: Bambu Studio, OrcaSlicer, PrusaSlicer, SuperSlicer, "
     "QIDISlicer, ElegooSlicer or Snapmaker Orca, with your own printer, filament and process presets. Every printer "
     "set up in every installed slicer can be chosen per design.\n\n"
     "The G-code is read back and played in 3D with a per-layer time chart and the slicer's own estimate. "
     "Designs too big for one plate are laid out over several.",
     [("Printers, slicing and print simulation", FEATURES + "#printers-slicing-and-print-simulation")]),
    ("Revisions, compare and variants", "App", "feature-compare",
     "Every commit is a revision that records who made it, and nothing is overwritten. Scrub the timeline, branch from "
     "any earlier revision, and compare parameters, features, interfaces and fit between any two.\n\n"
     "Comparing with head also compares the solids in the kernel: material added in green, removed in red, with "
     "volumes. Variants keep named sets of values side by side until you promote one.",
     [("Revisions, branches and variants", FEATURES + "#revisions-branches-and-variants")]),
    ("Release a design", "App", "feature-release",
     "The release gate lists what is current, what is stale and what needs acknowledgement. One approval, by a person, "
     "freezes STEP, STL, OBJ, GLB, 3MF and G-code with SHA-256 hashes and a report of every check and its evidence. "
     "No agent can approve.\n\n"
     "Verify at any time that a release still matches its hashes. **Save files…** puts every file of a release in one .zip.",
     [("Release", FEATURES + "#release")]),
    ("Move and share designs", "App", "feature-move",
     "A design travels as one .formstudio file with its revisions, its conversations and the code it was built from. "
     "Import it on another computer and carry on; nothing is overwritten.\n\n"
     "Photoreal renders with Blender, share cards with the part's dimensions, checks and fit, and turntable videos "
     "all come from the real solid.",
     [("Moving and sharing designs", FEATURES + "#moving-and-sharing-designs"),
      ("Pictures", FEATURES + "#pictures-renders-share-cards-animations")]),
    ("Headless: the CLI and MCP", "Reference", "feature-headless",
     "The app's actions are also `form` commands, and every agent tool is an MCP tool you can call headless with "
     "`form tool NAME '{json}'`, with the same checks and refusals. Use Form Studio from any agent that speaks MCP, "
     "from scripts or from CI.",
     [("CLI", DOCS + "cli.html"), ("MCP tools", DOCS + "mcp.html"), ("Architecture", DOCS + "architecture.html")]),
    ("Recipes: use, write and share", "Reference", "recipes",
     "Recipes are parametric families written as code, with their own engineering checks: Gridfinity bins and "
     "baseplates, boxes with lids, pegboard accessories, stands, planters, enclosures and more. Agents start from them "
     "and change anything.\n\n"
     "Write your own, share it as one .formrecipe file, and submit it to the community gallery. Every built-in recipe "
     "has its own post in #recipes.",
     [("Recipe gallery", SITE + "recipes/"), ("Writing recipes", DOCS + "recipes.html")]),
]

# help forum tag -> the guides a new post in it is pointed to
HELP_GUIDES = {
    "Install": ["Install and first start"],
    "Agents & models": ["Agents and models"],
    "Printers & slicers": ["Your slicer, your printers"],
    "Checks & fit": ["How a part is proved: checks and fit"],
    "Export": ["Release a design", "Move and share designs"],
    "Bug": [],
}

# ---- levels and challenges (run by the worker, scripts/discord/worker) -------------------------------------------------
# XP: one message earns 15–25 XP, at most once a minute; a /thanks gives 25; an answer marked solved gives 40;
# a /showcase post gives 30. XP for the next level from level n: 5n² + 50n + 100 (the usual curve).
XP = {"message": [15, 25], "cooldown_s": 60, "thanks": 25, "thanks_per_day": 3, "solved": 40, "showcase": 30}

# One brief a week: it closes on Sunday 21:00 UTC, the most ⭐ entry wins, and the next brief opens at once.
# (title, the brief, what makes an entry count)
CHALLENGES = [
    ("Desk-edge cable clip", "A clip that holds three cables along the edge of a desk 18–25 mm thick.",
     "Prints without supports. Show the fit on your own desk."),
    ("A bin for your smallest tool", "A Gridfinity bin shaped around the smallest tool you own.",
     "Measure the tool and say how you measured it."),
    ("A hook that holds 2 kg", "A wall or pegboard hook that carries 2 kg without creeping.",
     "Show the checks, and a photo with the weight if you printed it."),
    ("Headphone stand under 60 g", "A stand for over-ear headphones that weighs less than 60 g of filament.",
     "Post the slicer's grams. Make it lighter is allowed."),
    ("A replacement knob", "A knob for something you own whose knob broke or went missing.",
     "Measure the shaft. Real fit beats pretty."),
    ("Phone stand, two angles", "A phone stand with a reading angle and a video-call angle.",
     "One print, no glue."),
    ("Spool holder adapter", "An adapter that lets a spool with an odd hub sit on your printer's holder.",
     "Say the hub diameter and the printer."),
    ("Self-watering planter", "A planter with a water reservoir for a herb on your windowsill.",
     "Show it with soil in it, or a render with the reservoir cut open."),
    ("Battery organiser", "A holder for AA and AAA cells with a place for the dead ones.",
     "Fits a drawer you own."),
    ("Drawer divider from one measurement", "Dividers for a drawer, made from its inside width alone.",
     "Say the one number you measured."),
    ("Print-in-place hinge", "A box or case with a hinge printed in place.",
     "Show it opening. Say the clearance you used."),
    ("SD and USB holder", "A holder for SD cards and USB sticks that lives on your desk.",
     "Every slot labelled."),
    ("Shelf bracket for a 20 mm board", "A bracket that holds a 20 mm shelf to a wall.",
     "Show where it would fail first and why it won't."),
    ("Desk grommet", "A cable grommet for a 60 mm hole with a lid that closes around the cables.",
     "Two parts, one plate."),
    ("Filament clip", "A clip that keeps a spool's loose end from unwinding, without tools.",
     "Works on two different spools."),
    ("Something you fixed", "Free brief: a part that fixed something broken in your home.",
     "Tell the story: what broke, what you measured, how it fits now."),
]
