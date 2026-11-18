"""The Form Studio Discord server, as data: roles, categories, channels, forum tags, onboarding.

setup_server.py makes the server match this, by name, as often as it is run (nothing is deleted).
"""

SITE = "https://kaizensx.github.io/form-studio/"
REPO = "https://github.com/kaizensx/form-studio"

# colours from form/app/qml/Form/Theme.qml
ROLES = [
    # name, colour, hoist, mentionable, what it is
    ("Maintainer", 0xB9E8D7, True, False, "keeps Form Studio"),
    ("Contributor", 0x86A8FF, True, False, "has a merged pull request"),
    ("Recipe author", 0xC7B2FF, True, False, "has a recipe in the community gallery"),
    ("Form Studio", 0xD8D3C8, False, False, "the bot"),
    # picked by members in onboarding: what they print with and design with
    ("Bambu Lab", 0x86D9AD, False, True, ""),
    ("Prusa", 0xFF6F51, False, True, ""),
    ("Creality / Elegoo / other", 0xE9B860, False, True, ""),
    ("Just designing", 0xA8B2AF, False, True, ""),
    ("Claude Code", 0xE9B860, False, True, ""),
    ("Codex", 0xA8B2AF, False, True, ""),
    ("Gemini CLI", 0x86A8FF, False, True, ""),
    ("Local models", 0x86D9AD, False, True, ""),
    ("Release pings", 0xB9E8D7, False, True, "a mention for every release"),
]

TEXT, VOICE, CATEGORY, NEWS, STAGE, FORUM = 0, 2, 4, 5, 13, 15

# category -> [(name, type, topic, options)]
# options: read_only (members can't post), tags (forum), emoji (forum default reaction), slowmode (s)
LAYOUT = [
    ("👋  START HERE", [
        ("welcome", TEXT, "What Form Studio is, and where everything is.", {"read_only": True}),
        ("rules", TEXT, "Be kind, share real results, label what is simulated.", {"read_only": True}),
        ("announcements", NEWS, "Releases and news. Follow it from your own server.", {"read_only": True}),
    ]),
    ("🧊  FORM STUDIO", [
        ("releases", TEXT, "Every release, with what changed and the downloads. Posted by the bot.", {"read_only": True}),
        ("github", TEXT, "Issues, pull requests, discussions and CI from github.com/kaizensx/form-studio.", {"read_only": True}),
        ("showcase", FORUM, "Parts you designed and printed with Form Studio: photos, the .formstudio file, what you learned.",
         {"tags": ["Printed", "3D model", "Assembly", "Remix", "First print"], "emoji": "🧊"}),
        ("recipes", FORUM, "Building blocks for the community gallery: share, review, improve.",
         {"tags": ["New recipe", "Review wanted", "Accepted", "Idea"], "emoji": "🧩"}),
    ]),
    ("🛟  HELP", [
        ("help", FORUM, "Stuck? One post per question. Say your OS, Form Studio version, printer and slicer.",
         {"tags": ["Install", "Agents & models", "Printers & slicers", "Checks", "Export", "Solved"], "emoji": "✅",
          "slowmode": 0}),
        ("printers-and-slicers", TEXT, "Bambu Studio, OrcaSlicer, PrusaSlicer and the rest: profiles and presets.", {}),
        ("agents-and-models", TEXT, "Claude Code, Codex, Gemini CLI, model APIs, local models and custom providers.", {}),
    ]),
    ("💬  COMMUNITY", [
        ("general", TEXT, "Anything about designing parts.", {}),
        ("ideas", FORUM, "What Form Studio should do next. Upvote with 👍.",
         {"tags": ["Feature", "Agent tool", "Printer support", "Design", "Planned"], "emoji": "👍"}),
        ("prints", TEXT, "Photos of prints, failures included: they teach the most.", {}),
        ("off-topic", TEXT, "Everything else.", {"slowmode": 5}),
    ]),
    ("🛠  BUILD FORM STUDIO", [
        ("contributing", TEXT, "Working on the code: start with CONTRIBUTING.md and AGENTS.md.", {}),
        ("ci", TEXT, "Failed runs on main and dev, posted by the bot.", {"read_only": True}),
    ]),
    ("🔊  WORKSHOP", [
        ("Workshop", VOICE, "", {}),
        ("Print queue", VOICE, "", {}),
    ]),
]

RULES = [
    ("Be kind", "Critique designs, not people. Everyone was a beginner once."),
    ("Real results only", "Say what was printed and what was simulated. A slice is a simulation; a fit yield is a model."),
    ("One question, one post", "Ask in #help with your OS, Form Studio version, printer and slicer."),
    ("Share files you may share", "Only post models you made or are allowed to share, with their licence."),
    ("No spam or ads", "Links to your own work are welcome in #showcase; selling and DMs to strangers are not."),
    ("Security issues", "Report them privately: github.com/kaizensx/form-studio/security, not in public channels."),
]

ONBOARDING = [
    ("What do you print with?", ["Bambu Lab", "Prusa", "Creality / Elegoo / other", "Just designing"],
     ["🟢", "🟠", "🟡", "✏️"]),
    ("Which agent do you use?", ["Claude Code", "Codex", "Gemini CLI", "Local models"],
     ["🧡", "⚪", "🔵", "🖥️"]),
    ("Get a ping for every release?", ["Release pings"], ["🔔"]),
]
