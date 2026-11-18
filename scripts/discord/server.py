"""The Form Studio Discord server, as data: roles, channels, forums, onboarding, guides, AutoMod and the posts.

setup_server.py makes the server match this, by name, as often as it is run. It deletes only what RETIRE lists,
and only while it is empty. snapshot.py records the server before and after every setup (Actions artifacts), so
any run can be compared or rolled back.

The design system, in one place:
- Names. Categories are plain words in capitals; channels are lowercase single words. No emoji in names or titles.
- Colour is evidence, as in the app (form/app/qml/Form/Theme.qml): datum = settled and official, blueprint = in
  progress or discussion, violet = previews and recipes, amber = needs attention, signal = failed, pass = done.
  Only roles that say something about a person (Maintainer, Contributor, Recipe author) have a colour.
- Embeds. One colour from the palette, a sentence-case title, short paragraphs, and the footer "Form Studio · Section"
  with the Form Studio mark. Buttons are links with plain labels.
- Copy. Plain sentences that say what a place is for and what to post there.
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
INVITE = "https://discord.gg/"   # completed with the code below
INVITE_CODE = ""

# ---- roles -------------------------------------------------------------------------------------------------------
# name, colour, hoist, mentionable. Listed top to bottom; setup orders them so (under the bot's own role).
ROLES = [
    ("Maintainer", 0xB9E8D7, True, False),       # datum: keeps Form Studio
    ("Contributor", 0x86A8FF, True, False),      # blueprint: has a merged pull request
    ("Recipe author", 0xC7B2FF, True, False),    # violet: has a recipe in the community gallery
    # picked in onboarding; no colour, so a coloured name always means something
    ("macOS", 0, False, False),
    ("Windows", 0, False, False),
    ("Linux", 0, False, False),
    ("Bambu Lab", 0, False, False),
    ("Prusa", 0, False, False),
    ("Creality", 0, False, False),
    ("Other printer", 0, False, False),
    ("No printer yet", 0, False, False),
    ("Claude Code", 0, False, False),
    ("Codex", 0, False, False),
    ("Gemini CLI", 0, False, False),
    ("Model API", 0, False, False),
    ("Local models", 0, False, False),
    ("Release pings", 0, False, False),          # the bot mentions it for every stable release
]
ROLE_RENAMES = {"Creality / Elegoo / other": "Other printer", "Just designing": "No printer yet"}

# Recognition. Discord user ids (Developer Mode › right-click a name › Copy User ID).
# The server owner is always a Maintainer. To get the Contributor role, add your GitHub login and Discord id here in
# a pull request; it is given when the pull request merges (and on every setup).
MAINTAINERS: list[str] = []
CONTRIBUTORS: dict[str, str] = {}     # GitHub login -> Discord user id
RECIPE_AUTHORS: dict[str, str] = {}   # GitHub login -> Discord user id

# ---- channels ----------------------------------------------------------------------------------------------------
TEXT, VOICE, CATEGORY, NEWS, STAGE, FORUM = 0, 2, 4, 5, 13, 15

# options:
#   access    "read_only" (members react and read), "replies" (forum: members reply, only staff post),
#             "private" (Maintainer and the bot only); default: open
#   default   in every member's channel list from the start (onboarding)
#   tags, emoji, layout ("list"/"gallery"), require_tag, slowmode
LAYOUT = [
    ("START HERE", [
        ("welcome", TEXT, "What Form Studio is and where everything is. Start here.",
         {"access": "read_only", "default": True}),
        ("rules", TEXT, "Six short rules. Read them once.", {"access": "read_only", "default": True}),
        ("announcements", NEWS, "Stable releases and news, nothing else. Follow it to get them in your own server.",
         {"access": "read_only", "default": True}),
        ("releases", TEXT, "Every build with its notes and downloads: stable releases and previews from dev.",
         {"access": "read_only", "default": True}),
    ]),
    ("COMMUNITY", [
        ("general", TEXT, "Talk about designing and printing parts. Questions that need an answer go to #help.",
         {"default": True}),
        ("showcase", FORUM, (
            "Parts you designed with Form Studio. One post per part.\n\n"
            "A good post has:\n"
            "- a photo of the print, or a render if it is a 3D model\n"
            "- what it is for and what you asked for\n"
            "- the printer, filament and slicer\n"
            "- what you learned, failures included: they teach the most\n\n"
            "Attach the .formstudio file if you want others to remix it, with its licence."),
         {"tags": ["Printed", "3D model", "Assembly", "Remix", "First print", "Failure"], "emoji": "👍",
          "layout": "gallery", "default": True}),
        ("Workshop", VOICE, "", {"default": True}),
    ]),
    ("LIBRARY", [
        ("guides", FORUM, (
            "How to do things in Form Studio, one guide per post, with links to the full documentation. "
            "Reply in a guide to ask about it; questions of your own go to #help."),
         {"access": "replies", "tags": ["Start", "Agents", "Printing", "App", "Reference"], "emoji": "👍",
          "default": True}),
        ("recipes", FORUM, (
            "Recipes are parametric building blocks written as code, with their own checks. "
            "Every built-in recipe has a post here; the gallery is on the website.\n\n"
            "Share your own: a post with the .formrecipe file, a render from a real build, what its parameters do and "
            "its licence. Tag it Review wanted. Accepted recipes go into the community gallery."),
         {"tags": ["Built-in", "Community", "Review wanted", "Accepted", "Idea"], "emoji": "👍",
          "layout": "gallery", "default": True}),
    ]),
    ("HELP & FEEDBACK", [
        ("help", FORUM, (
            "Stuck? One post per question, with a tag.\n\n"
            "Say:\n"
            "- your system and Form Studio version (Help › About)\n"
            "- your printer and slicer, or that it is a 3D model\n"
            "- what you did, what you expected and what happened\n"
            "- the output of `form doctor` when it is about setup\n\n"
            "When it is solved, add the Solved tag. Bugs you can reproduce: open an issue on GitHub."),
         {"tags": ["Install", "Agents & models", "Printers & slicers", "Checks & fit", "Export", "Bug", "Solved"],
          "emoji": "👍", "require_tag": True, "default": True}),
        ("ideas", FORUM, (
            "What Form Studio should do next. One idea per post: the problem first, then what you would want. "
            "Vote with the reaction. Maintainers tag what is Planned and what Shipped."),
         {"tags": ["Feature", "Agent tool", "Printer support", "Recipe", "Planned", "Shipped"], "emoji": "👍",
          "default": True}),
    ]),
    ("BUILD", [
        ("contributing", TEXT, "Working on Form Studio's code, docs, recipes or the website. Start with the pinned post.", {}),
        ("github", TEXT, "Issues, pull requests and discussions on github.com/kaizensx/form-studio, posted by the bot.",
         {"access": "read_only"}),
        ("ci", TEXT, "Failed runs on main and dev, posted by the bot.", {"access": "read_only"}),
    ]),
    ("STAFF", [
        ("mod-log", TEXT, "AutoMod alerts, Discord's community updates and the help desk queue.", {"access": "private"}),
    ]),
]

# Renamed in this layout: old name -> new name (the channel, its id and its history are kept)
CHANNEL_RENAMES = {
    "👋  START HERE": "START HERE",
    "💬  COMMUNITY": "COMMUNITY",
    "🛟  HELP": "HELP & FEEDBACK",
    "🛠  BUILD FORM STUDIO": "BUILD",
    "moderator-only": "mod-log",
}

# Deleted by setup, but only while empty (no messages, no channels inside). The before-snapshot records them.
RETIRE = [
    ("prints", TEXT), ("off-topic", TEXT), ("printers-and-slicers", TEXT), ("agents-and-models", TEXT),
    ("Print queue", VOICE), ("General", VOICE),
    ("🧊  FORM STUDIO", CATEGORY), ("🔊  WORKSHOP", CATEGORY), ("Text Channels", CATEGORY), ("Voice Channels", CATEGORY),
]

# ---- onboarding (Server Settings › Onboarding) ---------------------------------------------------------------------
# (question, [(option, description, roles, channels)])
ONBOARDING = [
    ("What brings you here?", [
        ("Designing parts", "Show what you made, find recipes", [], ["showcase", "recipes"]),
        ("Getting help", "Guides and the help forum", [], ["help", "guides"]),
        ("Building Form Studio", "The code, CI and GitHub channels", [], ["contributing", "github", "ci"]),
    ]),
    ("What do you print with?", [
        ("Bambu Lab", "", ["Bambu Lab"], []), ("Prusa", "", ["Prusa"], []), ("Creality", "", ["Creality"], []),
        ("Another printer", "Elegoo, Anycubic, Voron, Snapmaker…", ["Other printer"], []),
        ("No printer yet", "3D models, or printing elsewhere", ["No printer yet"], []),
    ]),
    ("Which agent or model do you use?", [
        ("Claude Code", "", ["Claude Code"], []), ("Codex", "", ["Codex"], []), ("Gemini CLI", "", ["Gemini CLI"], []),
        ("A model API", "Anthropic, OpenAI, OpenRouter…", ["Model API"], []),
        ("Local models", "Ollama, LM Studio, llama.cpp", ["Local models"], []),
    ]),
    ("Get a mention for every stable release?", [
        ("Yes, mention me", "In #announcements, a few times a month at most", ["Release pings"], []),
    ]),
    ("Which system do you use?", [
        ("macOS", "", ["macOS"], []), ("Windows", "", ["Windows"], []), ("Linux", "", ["Linux"], []),
    ]),
]

# Discord shows a few questions while joining; the rest are in Channels & Roles (<id:customize>).
ONBOARDING_SHOWN = 4

# ---- the Server Guide (Server Settings › Onboarding › Server Guide) ---------------------------------------------------
# Applied in the browser (the API has no endpoint a bot may use); kept here so it can be set again the same way.
SERVER_GUIDE = {
    "welcome": ("Form Studio is an open-source desktop app where an AI agent designs parts in a real CAD kernel, "
                "checks them on the solid and slices them with your own slicer. This is where people who use it "
                "and build it meet."),
    "todos": [
        ("Read the six rules", "rules"),
        ("Learn the app, one guide at a time", "guides"),
        ("Show a part you designed", "showcase"),
        ("Ask when you are stuck", "help"),
    ],
    "resources": [
        ("Install and first start", "guides"), ("Recipes", "recipes"), ("Releases", "releases"), ("Rules", "rules"),
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
