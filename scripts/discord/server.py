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
GUILD_DESCRIPTION = ("Form Studio: describe anything, and an engineer-grade agent builds it as real, editable CAD. "
                     "Open source. 3D printing is optional.")
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
    ("🏗️ Architect", 0xFF6F51, True, False),           # level 40
    ("⚙️ Assembly", 0xC7B2FF, True, False),            # level 25
    ("🧊 Solid", 0x86A8FF, True, False),               # level 15
    ("🧱 Extrude", 0x86D9AD, True, False),             # level 8
    ("📐 Sketch", 0xD8D3C8, False, False),             # level 3
    # picked in onboarding or #roles
    ("🍎 macOS", 0, False, False), ("🪟 Windows", 0, False, False), ("🐧 Linux", 0, False, False),
    ("🟢 Bambu Lab", 0, False, False), ("🟠 Prusa", 0, False, False), ("🔵 Creality", 0, False, False),
    ("🖨️ Other printer", 0, False, False), ("🎨 I don't print", 0, False, False),
    ("🧡 Claude Code", 0, False, False), ("⚪ Codex", 0, False, False), ("🔷 Gemini CLI", 0, False, False),
    ("🔑 Model API", 0, False, False), ("🖥️ Local models", 0, False, False),
    ("🔔 Release pings", 0, False, True),               # mentioned for every stable release
    ("🏁 Challenge pings", 0, False, True),             # mentioned when a weekly challenge starts
    ("📅 Event pings", 0, False, True),                 # mentioned when a live session is scheduled
]
LEVELS = [(3, "📐 Sketch"), (8, "🧱 Extrude"), (15, "🧊 Solid"), (25, "⚙️ Assembly"), (40, "🏗️ Architect")]
# old name -> new name (same role, same members)
ROLE_RENAMES = {
    "Maintainer": "🛠️ Maintainer", "Contributor": "🧑‍💻 Contributor", "Recipe author": "🧩 Recipe author",
    "macOS": "🍎 macOS", "Windows": "🪟 Windows", "Linux": "🐧 Linux", "Bambu Lab": "🟢 Bambu Lab",
    "Prusa": "🟠 Prusa", "Creality": "🔵 Creality", "Other printer": "🖨️ Other printer",
    "No printer yet": "🎨 I don't print", "Claude Code": "🧡 Claude Code", "Codex": "⚪ Codex",
    "Gemini CLI": "🔷 Gemini CLI", "Model API": "🔑 Model API", "Local models": "🖥️ Local models",
    "Release pings": "🔔 Release pings",
    "Creality / Elegoo / other": "🖨️ Other printer", "Just designing": "🎨 I don't print",
    # creation first (2026-11-20): levels named after how a design grows, printing roles are one option among others
    "✏️ No printer yet": "🎨 I don't print", "🧱 First Layer": "📐 Sketch", "📏 Calibrated": "🧱 Extrude",
    "🏭 Print Farm": "🏗️ Architect",
}
R = {k: k for k, *_ in ROLES}
R.update({old: new for old, new in ROLE_RENAMES.items()})   # code may say R["Maintainer"]

# self-assigned in #roles (the bot's role picker) as well as in onboarding: (group, placeholder, [roles])
ROLE_PICKER = [
    ("agent", "Your agent or model", ["🧡 Claude Code", "⚪ Codex", "🔷 Gemini CLI", "🔑 Model API", "🖥️ Local models"]),
    ("system", "Your system", ["🍎 macOS", "🪟 Windows", "🐧 Linux"]),
    ("pings", "Notifications", ["🔔 Release pings", "🏁 Challenge pings", "📅 Event pings"]),
    ("printer", "3D printing (optional): your printer", ["🟢 Bambu Lab", "🟠 Prusa", "🔵 Creality", "🖨️ Other printer",
                                                         "🎨 I don't print"]),
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
        ("roles", "🎭・roles", TEXT, "Pick your agent, system, pings and (if you print) your printer. Change them any time.",
         {"access": "read_only", "default": True}),
        ("announcements", "📣・announcements", NEWS, "Stable releases and news. Follow it to get them in your own server.",
         {"access": "read_only", "default": True}),
        ("releases", "🚀・releases", TEXT, "Every build with its notes and downloads: stable releases and previews.",
         {"access": "read_only", "default": True}),
    ]),
    ("✨ CREATE", [
        ("showcase", "🧊・showcase", FORUM, (
            "What you made with Form Studio: a part, a product, a mechanism, a textured shell. One post per design, "
            "or use /showcase.\n\n"
            "A good post has a render or a photo, what you asked for, how the agent built it (brief, plan, critique) "
            "and what you changed. Attach the .formstudio file or the STEP if others may remix it, with its licence."),
         {"tags": ["🧊 3D model", "⚙️ Mechanism", "🎨 Organic & textured", "🧩 Assembly", "🧬 From a mesh", "🔁 Remix",
                   "🖨️ Printed", "💡 Lessons learned"],
          "emoji": "🔥", "layout": "gallery", "default": True}),
        ("design-tips", "🧠・design-and-engineering", TEXT,
         "Briefs, plans and critiques; mechanisms, fits, surfacing and texture: how to get excellent designs.",
         {"default": True}),
        ("mesh-to-cad", "🧬・mesh-to-cad", TEXT,
         "Turning STL, OBJ and 3MF meshes into editable CAD: results, reports, deviation maps and edge cases.",
         {"default": True}),
        ("agents", "🤖・agents-and-models", TEXT,
         "Claude Code, Codex, Gemini CLI, model APIs and local models: which design best, and how to connect them.",
         {"default": True}),
    ]),
    ("💬 COMMUNITY", [
        ("general", "💬・general", TEXT, "Talk about designing anything. Try /recipe, /guide or /rank.", {"default": True}),
        ("introductions", "🙋・introductions", TEXT,
         "Say hi: what you want to design, which agent you use, and whether you print.", {"default": True, "slowmode": 30}),
        ("wins-and-fails", "🍝・wins-and-fails", TEXT,
         "The design that came out perfect and the one that didn't: both teach something.", {"default": True}),
        ("off-topic", "🎲・off-topic", TEXT, "Everything that is not Form Studio.", {"default": True, "slowmode": 5}),
    ]),
    ("📚 LIBRARY", [
        ("guides", "📘・guides", FORUM, (
            "How to do things in Form Studio, one guide per post, with links to the full documentation. "
            "Reply in a guide to ask about it; /guide finds one from anywhere."),
         {"access": "replies", "tags": ["🚀 Start", "🧠 Design", "🤖 Agents", "🧭 App", "📖 Reference", "🖨️ 3D printing"],
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
            "Say your system and Form Studio version (Help › About), your agent and model, what you asked for, what "
            "you expected and what happened, and `form doctor` for setup problems.\n\n"
            "When it is solved, right-click the answer › Apps › Mark as solved."),
         {"tags": ["📥 Setup", "🤖 Agents & models", "🧠 Designing", "🧬 Mesh to CAD", "📤 Export & CAD exchange",
                   "🖨️ 3D printing", "🐞 Bug", "✅ Solved"], "emoji": "👍", "require_tag": True, "default": True}),
        ("ideas", "💡・ideas", FORUM, (
            "What Form Studio should do next. One idea per post: the problem first, then what you would want. "
            "Vote with the reaction. Maintainers tag what is Planned and what Shipped."),
         {"tags": ["✨ Feature", "🧠 Design intelligence", "🔧 Agent tool", "🧬 Mesh to CAD", "🧩 Recipe",
                   "🖨️ 3D printing", "🗺️ Planned", "🚢 Shipped"],
          "emoji": "👍", "default": True}),
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
    ("⚙️ BUILD", [
        ("contributing", "🧑‍💻・contributing", TEXT,
         "Working on Form Studio's code, docs, recipes or the website. Start with the pinned post.", {}),
        ("github", "🐙・github", TEXT, "Issues, pull requests and discussions on GitHub, posted by the bot.",
         {"access": "read_only"}),
        ("ci", "🧯・ci", TEXT, "Failed runs on main and dev, posted by the bot.", {"access": "read_only"}),
    ]),
    ("🖨️ 3D PRINTING (OPTIONAL)", [
        ("printers", "🖨️・printers-and-slicers", TEXT,
         "For people who print: Bambu Studio, OrcaSlicer, PrusaSlicer and friends, profiles, presets and filaments. "
         "Printing is optional in Form Studio; turn it on in Settings › General › Set up for.", {}),
        ("calibration", "🧪・calibration", TEXT,
         "Fit coupons, measured results and printer bias: the numbers that make printed fits land.", {}),
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
    "moderator-only": "🔒・mod-log", "Workshop": "🔊 Lounge", "📐・design-tips": "🧠・design-and-engineering",
    **{k: n for k, n in NAMES.items()},
}

# Forum tags renamed in place (the tag keeps its id, so posts keep it): forum key -> {old name: new name}
TAG_RENAMES = {
    "showcase": {"Printed": "Printed", "3D model": "3D model", "First print": "Mechanism", "Failure": "Lessons learned"},
    "guides": {"Printing": "3D printing"},
    "help": {"Install": "Setup", "Printers & slicers": "3D printing", "Checks & fit": "Designing",
             "Export": "Export & CAD exchange"},
    "ideas": {"Printer support": "3D printing"},
}

# Deleted by setup, but only while empty (no messages, no channels inside). The before-snapshot records them.
RETIRE = [
    ("prints", TEXT), ("Print queue", VOICE), ("General", VOICE),
    ("🧊  FORM STUDIO", CATEGORY), ("🔊  WORKSHOP", CATEGORY), ("Text Channels", CATEGORY), ("Voice Channels", CATEGORY),
    ("🔧 WORKSHOP", CATEGORY),          # creation first: its channels moved to ✨ CREATE and 🖨️ 3D PRINTING (OPTIONAL)
]

# ---- onboarding (Server Settings › Onboarding) ---------------------------------------------------------------------
# (question, [(option, description, emoji, roles, channels)])
ONBOARDING = [
    ("What brings you here?", [
        ("Designing anything", "Show what you made, design talk, recipes, the weekly challenge", "🧊", [],
         ["showcase", "design-tips", "recipes", "challenges"]),
        ("Mesh to editable CAD", "Rebuild STL, OBJ and 3MF files as CAD", "🧬", [], ["mesh-to-cad"]),
        ("Getting help", "Guides and the help forum", "🛟", [], ["help", "guides"]),
        ("3D printing", "Printers, slicers and calibration (optional)", "🖨️", [], ["printers", "calibration"]),
        ("Building Form Studio", "The code, CI and GitHub channels", "🧑‍💻", [], ["contributing", "github", "ci"]),
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
    ("Do you 3D print? (optional)", [
        ("I don't print", "Renders, STEP and CAD exchange, CNC…", "🎨", ["🎨 I don't print"], []),
        ("Bambu Lab", "", "🟢", ["🟢 Bambu Lab"], ["printers"]), ("Prusa", "", "🟠", ["🟠 Prusa"], ["printers"]),
        ("Creality", "", "🔵", ["🔵 Creality"], ["printers"]),
        ("Another printer", "Elegoo, Anycubic, Voron, Snapmaker…", "🖨️", ["🖨️ Other printer"], ["printers"]),
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
    "welcome": ("Hi [@username], welcome to Form Studio: describe anything, and an engineer-grade agent builds it as "
                "real, editable CAD. Start with the guides below, show what you make, and ask when you are stuck."),
    # (task, channel, done when: "visit" or "post"); Discord adds "Read the rules" itself
    "todos": [
        ("Learn the app, one guide at a time", "guides", "visit"),
        ("Show something you designed", "showcase", "post"),
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
    ("Say how you know", "Measured, computed, simulated or assumed: say which. A render is not a part; a fit yield is a model."),
    ("Ask in #help", "One post per question, with a tag, your system, version, agent and model."),
    ("Share what you may share", "Only designs you made or are allowed to share, with their licence."),
    ("No spam or ads", "Your own work is welcome in #showcase. Selling, invite links and DMs to strangers are not."),
    ("Security issues stay private", "Report them at github.com/kaizensx/form-studio/security, never in a channel."),
]

# Guides: one forum post each in #guides. (title, tag, art, text, [(button, url)])
# Features that dev has and the last release does not say so; their links go to the docs on dev.
DEV_FEATURES = REPO + "/blob/dev/docs/FEATURES.md"
NEXT = "\n\n*New in Form Studio 1.1: in the Preview channel first, then the next stable release.*"
GUIDES = [
    ("Install and choose what you make", "Start", "hero",
     "Download Form Studio for macOS, Windows or Linux. The first start is a launcher: it asks **What do you want to "
     "make?** with a card for each capability (parametric CAD, mechanical parts, mesh to CAD, photoreal renders, CAD "
     "exchange and, last, 3D printing) and a live download total, then your agent, and installs only what you chose, "
     "with every command in the log.\n\n"
     "Change it any time in **Settings › General › Set up for**: turning a card on installs only what it needs, "
     "turning one off hides it and never uninstalls anything. `form capabilities [on|off <id>]` does the same "
     "headless, and `form doctor` shows what was found." + NEXT,
     [("Download", REPO + "/releases/latest"), ("Setup and settings", DEV_FEATURES + "#setup-settings-and-updates"),
      ("Try it in your browser", SITE + "#try")]),
    ("Start a design from anything", "Start", "start",
     "Home asks **What do you want to make?** and takes whatever you have: words, a photo with a bank card or a coin for "
     "scale, a sketch in millimetres, a STEP, STL, OBJ or 3MF part, a PDF drawing or a link. Sizes read off a photo "
     "are labelled \"estimated from the photo\" and stay assumed until you measure them.\n\n"
     "Describe it, and Form Studio engineers it: the workspace opens at once and the design grows feature by feature "
     "as it is built, as real CAD you can edit.",
     [("Start from anything", DEV_FEATURES + "#start-from-anything"),
      ("Concepts and measurements", DEV_FEATURES + "#concepts-and-measurements")]),
    ("Design intelligence: brief, plan, critique", "Design", "shape",
     "For a mechanism, an organic or styled form, a texture or several parts, the agent first writes a **brief** "
     "(requirements, key dimensions with their source, and the unknowns it could not settle) and a **feature plan** "
     "(every feature, how it is built, clearances, risks). Form Studio refuses to build a complex design without a plan.\n\n"
     "Every new or changed design comes back with a six-view sheet and a section, so walls, voids and clearances are "
     "seen, not assumed. **Critique** renders a close-up of every feature and computes metrics from the solid "
     "(smallest fillet, sharp edges, symmetry, proportions, surface mix, missing planned features), all labelled "
     "heuristic; a briefed design is released only after a critique of that revision. MCP `design_brief`, "
     "`plan_design`, `critique`." + NEXT,
     [("Design intelligence", DEV_FEATURES + "#design-intelligence")]),
    ("Mechanisms, shapes and texture", "Design", "gears",
     "`form.craft` gives designs the building blocks of real design work: lofts, sweeps, revolves, shells and fillets "
     "that fall back safely; hinges, snap fits, bayonets, dovetails, detents, ratchets, cams, four-bar linkages, gear "
     "trains and planetary sets with their numbers; ISO 286 fits; ribs, gussets, bosses and lattices; helmet, grip "
     "and handle bodies from sections.\n\n"
     "Texture comes in two honest tiers: knurls, spiral ribs and embossed cells as real CAD geometry, and fine mesh "
     "textures (leather grain, twill, cells, noise, hexagons, a heightmap) that the STL, OBJ, GLB and renders carry "
     "while the STEP keeps the smooth body, labelled as such." + NEXT,
     [("Design intelligence", DEV_FEATURES + "#design-intelligence")]),
    ("Mesh to editable CAD", "Design", "proved",
     "Bring an STL, OBJ or 3MF and Form Studio rebuilds it as a new design, then measures how close it is to the mesh: "
     "**Make editable** next to an imported mesh, `form reconstruct FILE`, or MCP `reconstruct`.\n\n"
     "**Layer 0** always builds the mesh as an exact solid (Hausdorff distance at float precision). **Layer 1** (beta) "
     "fits planes, cylinders, cones, spheres and tori within a tolerance (0.02 mm by default). **Layer 2** (beta) "
     "writes a parametric recipe for a part that is one extrusion or one revolution, with holes snapped to standard "
     "sizes. Every run reports the two-sided Hausdorff distance, the volume difference, the parametric share and a "
     "deviation map. Scans and sculpted shapes stay faceted: exact to the mesh, not parametric." + NEXT,
     [("Mesh to editable CAD", DEV_FEATURES + "#mesh-to-editable-cad")]),
    ("Agents and models", "Agents", "talk",
     "Each conversation picks its agent, model and reasoning effort: Claude Code, Codex, Gemini CLI and other agent "
     "apps, a model API (Anthropic, OpenAI, Gemini, OpenRouter and more, found from your keys), a local model from "
     "Ollama, LM Studio or llama.cpp, or any provider you add by its address.\n\n"
     "The agent's steps fold into the conversation, questions arrive as cards, and time, tokens and cost are shown "
     "per reply. Retry any reply with another model.",
     [("Conversations and agents", DEV_FEATURES + "#conversations-and-agents"),
      ("Any model, any provider", DEV_FEATURES + "#any-model-any-provider")]),
    ("Linked conversations and forks", "Agents", "talk",
     "A conversation follows its design: picking a concept, a design the agent makes in the conversation, or copying "
     "a design keeps the talk linked instead of starting a blank one.\n\n"
     "**Fork from here** on any message starts a branch with the conversation up to that point; the column's header "
     "shows the branch and switches between them, and the conversation list shows branches under the conversation "
     "they came from. Designs record where they came from. `form conversations fork <id> [--at N]`." + NEXT,
     [("Conversations and agents", DEV_FEATURES + "#conversations-and-agents")]),
    ("Checks and evidence", "App", "proved",
     "Every revision is rebuilt and checked on the solid: one valid solid, interfaces as modelled, a closed export "
     "mesh, the STL against the CAD, and more. Each result says how it is known: computed, heuristic, simulated or "
     "measured. Numbers you can measure are asked for with a measurement card and recorded with how they were measured.",
     [("Checks and evidence", DEV_FEATURES + "#checks-and-evidence"), ("Verification", DOCS + "verification.html")]),
    ("Revisions, compare and variants", "App", "move",
     "Every commit is a revision that records who made it, and nothing is overwritten. Scrub the timeline, branch from "
     "any earlier revision, and compare parameters, features and interfaces between any two.\n\n"
     "Comparing with head also compares the solids in the kernel: material added in green, removed in red, with "
     "volumes. Variants keep named sets of values side by side until you promote one.",
     [("Revisions, branches and variants", DEV_FEATURES + "#revisions-branches-and-variants")]),
    ("Release a design", "App", "release",
     "The release gate lists what is current, what is stale and what needs acknowledgement. One approval, by a person, "
     "freezes STEP, STL, OBJ, GLB and 3MF (and G-code when you print) with SHA-256 hashes and a report of every check "
     "and its evidence. No agent can approve.\n\n"
     "Verify at any time that a release still matches its hashes. **Save files…** puts every file of a release in one .zip.",
     [("Release", DEV_FEATURES + "#release")]),
    ("Move and share designs", "App", "release",
     "A design travels as one .formstudio file with its revisions, its conversations and the code it was built from. "
     "Import it on another computer and carry on; nothing is overwritten.\n\n"
     "Photoreal renders with Blender, share cards with the design's dimensions and checks, and turntable videos "
     "all come from the real solid.",
     [("Moving and sharing designs", DEV_FEATURES + "#moving-and-sharing-designs"),
      ("Pictures", DEV_FEATURES + "#pictures-renders-share-cards-animations")]),
    ("Headless: the CLI and MCP", "Reference", "headless",
     "The app's actions are also `form` commands, and every agent tool is an MCP tool you can call headless with "
     "`form tool NAME '{json}'`, with the same checks and refusals. Use Form Studio from any agent that speaks MCP, "
     "from scripts or from CI. `form tool` lists every tool with a one-line summary.",
     [("CLI", REPO + "/blob/dev/docs/CLI.md"), ("MCP tools", REPO + "/blob/dev/docs/MCP.md"),
      ("Architecture", DOCS + "architecture.html")]),
    ("Recipes: use, write and share", "Reference", "recipes",
     "Recipes are parametric families written as code, with their own engineering checks: Gridfinity bins and "
     "baseplates, boxes with lids, pegboard accessories, stands, planters, enclosures and more. Agents start from them "
     "and change anything.\n\n"
     "Write your own, share it as one .formrecipe file, and submit it to the community gallery. Every built-in recipe "
     "has its own post in #recipes.",
     [("Recipe gallery", SITE + "recipes/"), ("Writing recipes", DOCS + "recipes.html")]),
    ("3D printing (optional): slicers, printers and fit", "3D printing", "slicer",
     "Printing is one optional output, next to STEP and CAD exchange, renders and CNC. Turn it on in **Settings › "
     "General › Set up for**; until then there is no printer, slicer or print row anywhere, and new designs are 3D "
     "models.\n\n"
     "With printing on, Form Studio slices with the slicer you already use (Bambu Studio, OrcaSlicer, PrusaSlicer and "
     "others) and your own presets, plays the G-code back in 3D, and models fits from your printer's bias and spread "
     "with the chance the gap lands in the window.",
     [("3D printing", DEV_FEATURES + "#3d-printing-optional"),
      ("Printers and slicing", DEV_FEATURES + "#printers-slicing-and-print-simulation")]),
]
# a guide that was renamed keeps its forum post (and its replies): old title -> new title
GUIDE_RENAMES = {
    "Install and first start": "Install and choose what you make",
    "How a part is proved: checks and fit": "Checks and evidence",
    "Your slicer, your printers": "3D printing (optional): slicers, printers and fit",
}

# help forum tag -> the guides a new post in it is pointed to
HELP_GUIDES = {
    "Setup": ["Install and choose what you make"],
    "Agents & models": ["Agents and models", "Linked conversations and forks"],
    "Designing": ["Design intelligence: brief, plan, critique", "Mechanisms, shapes and texture"],
    "Mesh to CAD": ["Mesh to editable CAD"],
    "Export & CAD exchange": ["Release a design", "Move and share designs"],
    "3D printing": ["3D printing (optional): slicers, printers and fit"],
    "Bug": [],
}

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
