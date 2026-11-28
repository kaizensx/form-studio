import QtQuick
import FormNative
import "F.js" as F

// Command palette: every action, design and conversation, from the keyboard. No animation: it is used all day.
// A pane of glass over the room with the command line's prompt (the accent "›") before the search field.
// Results are grouped (Recent, Go to, Tools, In the open design, Designs, Conversations, Settings); typing matches
// loosely — the letters in order, not necessarily together — and the matched letters are lit. The commands you ran
// last come first.
// A row previews what it leads to: after its name one quiet line (what it is), and at the right edge its figure in
// mono when it has one (a feature's value, a study's headline, a design's revision and checks) or its key.
// Tab searches everywhere: the words are then also looked for inside the conversations (GET /conversations?q=, which
// reads every message and answers with the line around the match) and in every setting's name; those rows stand
// under "Everywhere". Tab again goes back.
Item {
    id: pal
    anchors.fill: parent; visible: Store.paletteOpen; z: 50
    onVisibleChanged: if (visible) { q.text = ""; sel = 0; rest = null; everywhere = false; found = []; Store.loadConvs(); q.input.forceActiveFocus() }
    // ── Tab: search everywhere ──
    property bool everywhere: false
    property var found: []                     // conversations whose messages hold the words: { id, title, updated, match }
    property string foundFor: ""               // the words `found` answers
    function toggleEverywhere() { everywhere = !everywhere; if (everywhere && !Store.config) Store.loadConfig(); seek.restart() }
    function look() {
        var t = q.text.trim()
        if (!everywhere || t.length < 2) { found = []; foundFor = ""; return }
        Store.get("/conversations?q=" + encodeURIComponent(t)).then(function (r) {
            if (q.text.trim() !== t || !pal.everywhere) return           // the words moved on while the engine read
            pal.found = (r.conversations || []).filter(function (c) { return c.messages > 0 && !!c.match }).slice(0, 6); pal.foundFor = t
            Qt.callLater(pal.pickBest) }, function () {})
    }
    Timer { id: seek; interval: 160; onTriggered: pal.look() }
    // the line around the match as the engine found it (lower case, "…" at a cut end), with the words lit
    function quote(m, t) {
        var w = t.split(" ")[0], s = String(m || ""), i = s.toLowerCase().indexOf(w), at = []
        if (s.length > 64) { var a = Math.max(0, Math.min(i - 18, s.length - 64)); s = (a > 0 ? "…" : "") + s.slice(a, a + 64).replace(/^…/, "") + "…"; i = s.toLowerCase().indexOf(w) }
        for (var k = 0; i >= 0 && k < w.length; k++) at.push(i + 1 + k)
        return { text: "“" + s + "”", at: at }
    }
    property int sel: 0
    // the pointer picks a row only once it moves: a pointer resting where the list appears (or where rows slide in
    // as you type) never takes the highlight from the keyboard
    property var rest: null
    function pointed(item, mouse) {
        var g = item.mapToItem(pal, mouse.x, mouse.y)
        if (rest === null) { rest = g; return false }
        if (rest !== true && Math.abs(g.x - rest.x) + Math.abs(g.y - rest.y) < 3) return false
        rest = true
        return true
    }
    objectName: "palette"
    readonly property string selText: rows[picks[sel]] ? rows[picks[sel]].text : ""     // the highlighted command
    property alias query: q.text
    readonly property var groups: ["Recent", "Saved prompts", "Go to", "Tools", "In design", "Bench", "Designs", "Conversations", "Settings", "Everywhere"]
    function groupName(g) { return g === "In design" ? "In " + (Store.project ? Store.project.name : "this design") : g }
    function updates() { Store.checkUpdates(true).then(function (u) {
        if (u && u.available) { Store.updateHidden = false; Store.openSheet("update") }
        else if (u && !u.enabled) Store.toast("Update checks are off", "[updates] check = false or FORM_NO_UPDATE_CHECK=1")
        else if (u && u.latest) Store.toast("Form Studio " + u.current + " is up to date")
        else Store.toast("Could not reach GitHub", "Nothing changed. Try again later.") }) }
    readonly property var all: {
        var c = [], w = Store.screen === "work"
        function add(g, id, icon, text, hint, run, keys) { c.push({ g: g, id: id, icon: icon, text: text, hint: hint || "", run: run, keys: keys || "" }) }
        function val(v) { c[c.length - 1].value = v || "" }          // the figure at the row's right edge
        if (w) {
            // a mode also answers to what it was called and to what it holds (`also`: words that find it, never shown)
            var also = { shape: "shape tree program features model", prove: "review prove studies checks", release: "release routes export print", document: "documents drawings report" }
            Store.stages.forEach(function (s, i) { add("Go to", "stage." + s.id, "arrow_right", s.title, s.hint, function () { Store.setStage(s.id) }, Theme.modeMod + "+" + Store.stageKey[s.id]); c[c.length - 1].also = also[s.id] || "" })
            add("Go to", "bench.sheet", "list_checks", "Bench", "Every study, route and document on one sheet", function () { Store.toggleBench() }, "Ctrl+B")
            add("Go to", "stage.brief", "file_text", "Overview", "Describe: the brief, what is known about the object, the revisions", function () { Store.setStage("brief") }, "Ctrl+I")
            if (Store.printUi) add("Go to", "stage.fit", "arrow_right", "Fit study", "Check: clearance under uncertainty, a model", function () { Store.setStage("fit") })
        }
        add("Go to", "home", "home", "All designs", "Home", function () { Store.home() }, "Ctrl+Shift+H")
        if (w) {
            ;[["iso", "1"], ["front", "2"], ["side", "3"], ["top", "4"], ["under", "5"]].forEach(function (v) { add("Tools", "view." + v[0], "rotate_3d", "View: " + v[0], "Camera", function () { Store.setView(v[0]) }, v[1]) })
            ;["x", "y", "z"].forEach(function (a) { add("Tools", "cut." + a, "scissors", "Cut along " + a.toUpperCase(), "Section view", function () { Store.setSection(a, 0.5) }) })
            add("Tools", "cut.off", "scissors", "Remove the section cut", "Section view", function () { Store.setSection("", 0.5) })
            add("Tools", "frame", "focus", "Frame the selection", "Or the whole part", function () { Store.frameSelection() }, "F")
            add("Tools", "resetview", "rotate_ccw", "Reset the view", "Camera", function () { Store.resetView() }, ".")
            add("Tools", "dims", "ruler", (Store.dims ? "Hide" : "Show") + " overall dimensions", "Viewport", function () { Store.toggleDims() })
            add("Tools", "measure", "ruler", Store.measuring ? "Stop measuring" : "Measure", "Distance, angle, radius on the solid", function () { Store.setMeasuring(!Store.measuring) }, "M")
            add("Tools", "annotate", "map_pin", Store.selecting ? "Stop annotating" : "Annotate", "Pick or paint on the part, keep a note, ask the agent", function () { Store.setSelecting(!Store.selecting) }, "N")
            // modelling by hand (form/modelling.py): the same as the tool dock's group; each becomes a feature in the code
            if (!Store.hasDraft) add("Tools", "hand.sketch", "pen_tool", "Sketch on a plane", "Extrude, cut or revolve a profile you draw", function () { Store.openSheet("handsketch", { mode: "add", plane: { datum: "XY", offset: 0 } }) })
            add("Tools", "hand.round", "radius", "Fillet or chamfer edges", "Pick the edges to round or bevel", function () { if (!Store.selecting) Store.setSelecting(true); Store.selMode = "edge" })
            add("Tools", "hand.face", "circle_dot", "Hole, shell or sketch on a face", "Pick a flat face", function () { if (!Store.selecting) Store.setSelecting(true); Store.selMode = "face" })
            add("Tools", "hand.tree", "list_filter", "Feature tree", "Roll back, suppress, rename or reorder features", function () { Store.setStage("shape") })
            Store.analysisMaps.forEach(function (m) { if (m.value) add("Tools", "map." + m.value, "layers", "Analysis map: " + m.text, Store.analysisMap === m.value ? "Showing now" : "Colour the part by " + m.text.toLowerCase(), function () { Store.setAnalysis(m.value) }) })
            if (Store.analysisMap) add("Tools", "map.off", "layers", "Hide the analysis map", Store.analysisLabel(Store.analysisMap), function () { Store.setAnalysis("") })
            add("Tools", "orient", "move_3d", "Find a print orientation", "Ranks the ways it can sit on the plate", function () { Store.setStage("prove"); Store.findOrientation() })
            if (Store.printUi) add("Tools", "slicerOpen", "external_link", "Open in " + Store.slicerName, "Sliced with settings chosen for this part", function () { Store.setStage("prove"); Store.openInSlicer() })
            add("Tools", "simulate", "film", "Simulate the print", "Layer by layer, from the real slice", function () { Store.simulate() })
            add("Tools", "layers", "layers", Store.layers ? "Close the layer view" : "Show the sliced layers", "The toolpath of the current slice", function () { Store.showLayers(!Store.layers) })
            add("Tools", "run", "play", "Regenerate everything", "Solid, exports, checks, slice", function () { Store.run() })
            add("Tools", "alternatives", "boxes", "Compare alternatives", "Build a grid of candidates", function () { Store.openSheet("alternatives") })
            add("Tools", "lighter", "weight", "Make it lighter", "Thinner walls, pockets, less infill: every passing check kept", function () { Store.openSheet("lighter") })
            add("Tools", "parts", "wrench", "Standard parts", "Screws, inserts, bearings, motors… placed with their hole cut and fit checked", function () { Store.openStudy({ app: "parts" }) })
            add("Tools", "variants", "layout_grid", "Variants board", "Named variants side by side", function () { Store.openSheet("variants") })
            add("Tools", "share", "share_2", "Share card", "A 1600 × 900 image of this design", function () { Store.openSheet("share") })
            add("Tools", "turntable", "film", "Turntable video", "The part turning, as MP4, PNG frames, WebP or GIF", function () { Store.openSheet("turntable") })
            add("Tools", "render", "camera", "Render in Blender", "An illustration of the current revision", function () { Store.openSheet("render") })
            add("Tools", "game", "gamepad_2", "Game asset", "LODs, UVs, baked maps and collision for Godot, Unity or Unreal", function () { Store.openSheet("game") })
            add("Tools", "timeline", "history", (Store.timelineOpen ? "Hide" : "Show") + " the revision timeline", "Scrub through revisions", function () { Store.timelineOpen = !Store.timelineOpen; if (!Store.timelineOpen) Store.endScrub() })
            add("Tools", "morph", "play", "Play the revision history", "Morph through every revision", function () { Store.timelineOpen = true; Store.playMorph() })
            if (Store.hidden.length) add("Tools", "showall", "eye", "Show all features", F.plural(Store.hidden.length, "feature") + " hidden", function () { Store.showAll() }, "Alt+H")
            if (Store.hasDraft) { add("Tools", "commit", "git_commit_horizontal", "Commit the draft", "Saves a revision", function () { Store.commit() }, "Ctrl+Return")
                add("Tools", "discard", "undo_2", "Discard the draft", "", function () { Store.discard() }) }
            add("Tools", "importpart", "box", "Import a reference part…", "STEP, IGES, a mesh, a scan or a zip, shown in blueprint", function () { Store.askImportPart() })
            add("Tools", "freecad", "external_link", "Open the STEP in FreeCAD", "Release · working files", function () { Store.openIn("step", "freecad") })
            if (Store.canAskReview) add("Tools", "review", "eye", "Ask for a design review", "Silhouette, relationships, details", function () { Store.askReview() })
        }
        // the open design's features, in build order: each with the values it is made of
        if (w && Store.recipe && Store.recipe.features) Store.recipe.features.forEach(function (ft, i) {
            var ps = (Store.recipe.params || []).filter(function (p) { return p.feature === ft.id }), vs = Store.head ? Store.head.values : null, out = [], unit = ""
            for (var k = 0; vs && k < ps.length && out.length < 3; k++) { var v = vs[ps[k].key]; if (typeof v === "number") { out.push(String(Number(v.toFixed(2)))); unit = ps[k].unit || "" } }
            add("In design", "feature." + ft.id, "box", (i < 9 ? "0" : "") + (i + 1) + " " + (ft.label || ft.id), "feature", function () { Store.setStage("shape"); Store.select(ft.id) })
            val(out.length === 1 ? out[0] + (unit ? " " + unit : "") : out.join(" × ")) })
        // the Bench: every study, route and document of this design with its state (form/studies.py); a current one
        // opens what it made, any other runs
        if (w && Store.bench && Store.bench.project === Store.pid) Store.bench.entries.forEach(function (e) {
            if (e.state === "n/a") return
            var st = e.state === "current" ? "Current" : e.state === "stale" ? "Stale: describes " + F.pad(e.rev)
                   : e.state === "never" ? "Never run" : e.state === "unavailable" ? (e.why || "Cannot run here") : e.state === "failed" ? "Failed" : "Running"
            add("Bench", "bench." + e.id, e.group === "study" ? "list_checks" : e.group === "route" ? "external_link" : "file_text",
                (e.state === "current" || e.state === "running" ? "" : e.by === "agent" ? "Ask for: " : e.by === "person" ? "" : "Run: ") + e.label, st,
                function () { if (e.state === "current" && e.by === "engine") Store.openStudy(e); else if (e.state !== "running") Store.runStudy(e.id) })
            if (e.state === "current") val(e.headline)
        })
        // messages you saved as commands (the bookmark on a message of yours): one key sends it again, with the selection
        Store.savedPrompts.forEach(function (p, i) { add("Saved prompts", "prompt." + i + "." + p.name, "bookmark", p.name, p.text.length > p.name.length ? "your saved prompt" : "send it again",
            function () { Store.talkOpen = true; Store.send(Store.scoped(p.text)) }) })
        add("Tools", "new", "plus", "New design", "Describe it, or drop a photo, a sketch, a part or a link", function () { Store.startNew() }, "Ctrl+N")
        add("Tools", "sketch", "pen_tool", "Sketch a new design", "Lines, circles, arcs and dimensions in mm", function () { if (Store.screen !== "home") Store.home(); Store.openSheet("sketch") })
        add("Tools", "replace", "wrench", "Replace a broken part", "From a photo: estimated, measured, designed", function () { if (Store.screen !== "home") Store.home(); Store.openSheet("replace") })
        add("Tools", "blank", "square_dashed", "Start blank", "An empty design: describe, sketch or import what goes in it", function () { Store.startBlank() })
        add("Tools", "block", "cuboid", "Start from a block", "A rounded block shaped with sliders, no agent", function () { Store.startBlock("") })
        if (Store.concepts.length) add("Tools", "concepts", "boxes", "Concepts waiting for a pick", Store.concepts[0].name, function () { Store.openConcepts(Store.concepts[0].id) })
        if (Store.studio) Store.studio.projects.forEach(function (p) { if (!p.error && p.id !== Store.pid) { add("Designs", "p." + p.id, "cuboid", p.name, F.ago(p.updated), function () { Store.open(p.id) })
            val(F.pad(p.head) + (p.checks ? (p.checks.fail ? " · " + p.checks.fail + " fail" : p.checks.warn ? " · " + p.checks.warn + " to review" : " · " + p.checks.pass + " pass") : "")) } })
        add("Conversations", "chat.new", "message_square_plus", "New conversation", "", function () { Store.newChat(); Store.talkOpen = true }, "Ctrl+Shift+O")
        if (w) add("Conversations", "chat.toggle", "panel_left", (Store.talkOpen ? "Hide" : "Show") + " the conversation", "", function () { Store.toggleTalk() }, "Ctrl+J")
        if (w) add("View", "view.focus", "maximize_2", Store.focusView ? "Leave Focus: bring the side columns back" : "Focus: the part alone, both side columns away", "", function () { Store.focusView = !Store.focusView }, "Ctrl+.")
        Store.convs.forEach(function (cv) { if (cv.messages > 0 && cv.id !== Store.convId) { add("Conversations", "c." + cv.id, "message_square", cv.title, "conversation", function () { Store.openConv(cv.id); Store.talkOpen = true }); val(F.ago(cv.updated)) } })
        // the model that answers: every model of the current agent, and each other agent that is installed
        var ai = Store.chatAgentInfo
        if (ai) (ai.models || []).forEach(function (m) { add("Conversations", "model." + ai.id + "." + m.id, "bot", "Model: " + m.label, Store.chatModel === m.id || (m.id === "default" && !Store.chatModel) ? "In use · " + ai.label : ai.label, function () { Store.setChatChoice(undefined, m.id) }) })
        ;(Store.chatAgents || []).forEach(function (a) { if (a.available && a.id !== Store.chatAgent) add("Conversations", "agent." + a.id, "bot", "Agent: " + a.label, "Switch the agent that answers", function () { Store.setChatChoice(a.id) }) })
        add("Settings", "settings", "settings", "Settings", "", function () { Store.openSettings("general") }, "Ctrl+,")
        if (Store.printOn) add("Settings", "settings.printer", "printer", "Settings: printing", "Default printer, slicer, bed", function () { Store.openSettings("printer") })
        add("Settings", "settings.use", "printer", Store.printOn ? "Turn 3D printing off" : "Turn 3D printing on",
            "Set up for: printing is optional; off hides it and uninstalls nothing", function () { Store.setCap("print", !Store.printOn) })
        if (Store.project && Store.printOn) add("Settings", "purpose", Store.modelDesign ? "printer" : "box", Store.modelDesign ? "Make this design for 3D printing" : "Make this design just a 3D model",
            "What this design is for", function () { Store.setPurpose(Store.modelDesign ? "print" : "model") })
        add("Settings", "settings.chat", "message_square", "Settings: agents", "Agent apps, API keys, local models", function () { Store.openSettings("chat") })
        if (Store.printOn) add("Settings", "printer", "printer", "Choose printer", "Printer, filament and process for this design", function () { Store.openSheet("printer") })
        if (Store.printOn) add("Settings", "slicer", "printer", "Choose slicer", Store.slicer.label || "", function () { Store.openSheet("slicer") })
        add("Settings", "software", "wrench", "Software: install or check", "Slicer, agents, CAD apps", function () { Store.openSettings("software") })
        add("Settings", "setup", "list_checks", "Setup checklist", "What Form Studio found on this computer", function () { Store.openSetup() })
        add("Settings", "onboard", "sparkles", "Run the first-time setup again", "Three short steps", function () { Store.setOnboardStep(0); Store.checkSoftware(); Store.welcome = true })
        add("Settings", "updates", "refresh_cw", "Check for updates", "Form Studio " + Bridge.version, function () { pal.updates() })
        add("Settings", "shortcuts", "keyboard", "Keyboard shortcuts", "", function () { Store.openSheet("shortcuts") }, "?")
        add("Settings", "folder", "folder_open", "Open the projects folder", Bridge.dataDirShort, function () { Bridge.openDataFolder() })
        add("Settings", "about", "info", "About Form Studio", "Version and licences", function () { Store.openSheet("about") })
        // home workstream: what's new, import and export
        add("Settings", "whatsnew", "sparkle", "What’s new", "Form Studio " + Bridge.version, function () { Store.showWhatsNew() })
        add("Settings", "import", "import", "Import a project or conversation", ".formstudio, .formproj or .json", function () { Store.openSheet("import") })
        if (Store.project) add("Settings", "export.project", "archive", "Export this design", "One .formstudio file with its conversations", function () { Store.exportProject(Store.pid) })
        if (Store.convId) add("Conversations", "export.conv.md", "file_text", "Export this conversation as Markdown", "", function () { Store.exportConversation(Store.convId, "md") })
        if (Store.convId) add("Conversations", "export.conv.json", "file_code", "Export this conversation as JSON", "Import brings it back", function () { Store.exportConversation(Store.convId, "json") })
        return c
    }
    // loose match: every letter of the query, in order. Returns { score, at: [indices] } or null.
    // How close a command is to what was typed, in tiers, so a nearer kind of match always beats a farther one:
    //   3000  the name is exactly the words typed          2000  the name starts with them
    //   1600  a word it also answers to starts with them  1500  a word of the name starts with them
    //   1000  they are inside the name                      700  a word of its hint starts with them
    //   < 600 the letters appear in order in the name (fuzzy)
    // Inside a tier: the earlier the match and the shorter the name, the higher. A verb in front of a Bench entry's
    // name ("Run: ", "Ask for: ") is not part of the name. `at` is where to light the letters in the text shown.
    function wordStart(low, t) {
        for (var i = low.indexOf(t); i >= 0; i = low.indexOf(t, i + 1)) if (i === 0 || /[^a-z0-9]/.test(low[i - 1])) return i
        return -1
    }
    function match(text, t) {
        var pre = /^(Run|Ask for): /.exec(text), off = pre ? pre[0].length : 0
        var low = text.slice(off).toLowerCase(), at = [], i = low.indexOf(t), k
        if (i >= 0) {
            for (k = 0; k < t.length; k++) at.push(off + i + k)
            var w = pal.wordStart(low, t)
            if (w >= 0 && w !== i) { at = []; for (k = 0; k < t.length; k++) at.push(off + w + k); i = w }
            var tier = low === t ? 3000 : i === 0 ? 2000 : w >= 0 ? 1500 : 1000
            return { score: tier - (off + i) * 2 - Math.min(40, low.length - t.length) * 0.5, at: at }     // how far into the text shown
        }
        var p = 0, score = 0, last = -2
        for (var j = 0; j < t.length; j++) {
            if (t[j] === " ") continue
            var f = low.indexOf(t[j], p)
            if (f < 0) return null
            score += (f === last + 1 ? 14 : 0) + (f === 0 || low[f - 1] === " " ? 10 : 0) - (f - p)
            at.push(off + f); last = f; p = f + 1
        }
        return { score: Math.min(590, score), at: at }
    }
    function rank(c, t) {
        var best = pal.match(c.text, t)
        if (c.also && pal.wordStart(c.also, t) >= 0 && (!best || best.score < 1600)) best = { score: 1600, at: [] }
        var h = t.length >= 3 ? pal.wordStart((String(c.hint) + " " + String(c.value || "")).toLowerCase(), t) : -1
        if (h >= 0 && (!best || best.score < 700 - Math.min(80, h))) best = { score: 700 - Math.min(80, h), at: [] }
        if (!best) return null
        // the modes are the map of the app: at an equal match they come first; what was used lately, next
        return { at: best.at, score: best.score + (c.g === "Go to" ? 30 : 0) + (Store.paletteRecent.indexOf(c.id) >= 0 ? 25 : 0) }
    }
    // the rows shown: headers and commands, in group order
    readonly property var rows: {
        var t = q.text.trim().toLowerCase(), out = [], items = all, i
        if (!t) {
            var rec = []
            Store.paletteRecent.forEach(function (id) { for (var k = 0; k < items.length; k++) if (items[k].id === id) { rec.push(Object.assign({}, items[k], { g: "Recent" })); break } })
            rec = rec.slice(0, 4)
            var per = { "Saved prompts": 4, "Go to": 6, "Tools": 5, "Designs": 4, "Conversations": 3, "Settings": 2 }, seen = {}
            rec.forEach(function (r) { seen[r.id] = true })
            items = rec.concat(items.filter(function (c) { if (seen[c.id]) return false; per[c.g] = (per[c.g] || 0) - 1; return per[c.g] >= 0 }))
        } else {
            var hit = []
            for (i = 0; i < items.length; i++) {
                var m = pal.rank(items[i], t)
                if (m) hit.push(Object.assign({}, items[i], { at: m.at, score: m.score, n: i }))
            }
            hit.sort(function (a, b) { return b.score - a.score || a.n - b.n })
            items = hit.slice(0, pal.everywhere ? 5 : 14)          // everywhere: room for what was said
            if (pal.everywhere) {
                // inside the conversations: the line around the words, as the engine read it
                if (pal.foundFor === q.text.trim()) pal.found.forEach(function (cv, k) {
                    if (!cv.match) return                                   // only its title matched: it is listed under Conversations
                    var qt = pal.quote(cv.match, t)
                    items.push({ g: "Everywhere", id: "found." + cv.id, icon: "message_square", text: qt.text, at: qt.at, score: 400 - k, n: 9000 + k,
                                 hint: "in " + cv.title, value: F.ago(cv.updated), keys: "",
                                 run: function () { Store.openConv(cv.id); Store.talkOpen = true } }) })
                // every setting by name: it opens its page
                var names = { general: "General", printer: "Printing", chat: "Agents & models", apps: "Other apps", costs: "Costs", appearance: "Appearance", backups: "Backups", updates: "Updates", advanced: "Advanced" }
                var sets = []
                ;(Store.config ? Store.config.settings : []).forEach(function (r, k) {
                    if (r.hidden || (r.tab === "printer" && !Store.printOn) || !names[r.tab]) return
                    var path = "Settings › " + names[r.tab] + " › ", m = pal.match(r.label, t)
                    if (m && m.score >= 1000) sets.push({ g: "Everywhere", id: "set." + r.key, icon: "sliders_horizontal", text: path + r.label, score: m.score - 800, n: 9500 + k,
                        at: m.at.map(function (x) { return x + path.length }), hint: "", keys: "", value: "", run: function () { Store.openSettings(r.tab) } }) })
                sets.sort(function (a, b) { return b.score - a.score || a.n - b.n })
                items = items.concat(sets.slice(0, 4))
            }
        }
        pal.groups.forEach(function (g) {
            var l = items.filter(function (c) { return c.g === g })
            if (!l.length) return
            out.push({ head: pal.groupName(g) })
            l.forEach(function (c) { out.push(c) })
        })
        return out
    }
    // the rows without their headers, as plain facts (what a journey reads)
    readonly property var listed: rows.filter(function (r) { return !r.head }).map(function (r) { return { id: r.id, g: r.g, text: r.text, hint: r.hint || "", value: r.value || "" } })
    readonly property var picks: { var p = []; for (var i = 0; i < rows.length; i++) if (!rows[i].head) p.push(i); return p }
    // what typing highlights: the closest match, wherever its group is listed (the rows stay in group order)
    readonly property int best: { var b = 0, s = -1e9; for (var i = 0; i < picks.length; i++) { var r = rows[picks[i]]; if (r.score !== undefined && r.score > s) { s = r.score; b = i } } return b }
    function pickBest() { sel = best; if (picks.length) list.positionViewAtIndex(picks[sel], ListView.Contain) }
    function lit(text, at) {
        if (!at || !at.length) return text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
        var s = "", set = {}
        at.forEach(function (i) { set[i] = true })
        for (var i = 0; i < text.length; i++) {
            var ch = text[i] === "&" ? "&amp;" : text[i] === "<" ? "&lt;" : text[i]
            s += set[i] ? "<font color=\"" + Theme.datum + "\">" + ch + "</font>" : ch
        }
        return s
    }
    function go(n) { var h = rows[picks[n]]; Store.paletteOpen = false; if (h) { Store.notePaletteRun(h.id); h.run() } }
    function move(d) { sel = Math.max(0, Math.min(picks.length - 1, sel + d)); list.positionViewAtIndex(picks[sel], ListView.Contain) }

    Rectangle { anchors.fill: parent; color: Theme.scrim; MouseArea { anchors.fill: parent; onClicked: Store.paletteOpen = false; onWheel: function (w) { w.accepted = true } } }
    Glass {
        id: box
        source: Store.backdrop; radius: Theme.rPane
        width: Math.min(640, parent.width - 80); anchors.horizontalCenter: parent.horizontalCenter; y: Math.max(64, Math.round(parent.height * 0.14))
        height: 58 + Math.min(list.contentHeight, Math.min(pal.everywhere ? 600 : 460, parent.height - y - 120)) + 12 + 36
        onHeightChanged: place()
        Rectangle { anchors.fill: parent; radius: box.radius; color: Theme.alpha(Theme.plate1, box.blurred ? 0.66 : 0.9) }
        MouseArea { anchors.fill: parent }
        // the prompt: the well the command is typed into, as in the bar under the part
        Rectangle { id: well; x: 8; y: 8; width: parent.width - 16; height: 44; radius: Theme.rPane - 8; color: Theme.glassWell; border.width: 1; border.color: Theme.alpha(Theme.datum, 0.55)
            Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.alpha(Theme.datum, 0.13) } }
        // where the search looks first: the open design
        Rectangle { id: ctx; objectName: "paletteScope"; visible: pal.everywhere || (!!Store.project && Store.screen === "work"); anchors.right: well.right; anchors.rightMargin: 10; anchors.verticalCenter: well.verticalCenter
            width: ctxT.width + 16; height: 22; radius: 6; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.10 : 0.07)
            Txt { id: ctxT; anchors.centerIn: parent; kind: "cap"; tone: 2; color: Theme.ink2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                width: Math.min(implicitWidth, 180); text: pal.everywhere ? "Everywhere" : Store.project ? Store.project.name : "" } }
        Text { x: 22; y: 7; height: 44; verticalAlignment: Text.AlignVCenter; text: "›"; color: Theme.datum
            font.family: Theme.mono; font.pixelSize: 20; font.weight: Theme.wMedium; renderType: Theme.textRender }
        Field { id: q; x: 40; y: 14; width: parent.width - 62 - (ctx.visible ? ctx.width + 8 : 0); height: 32; bare: true; placeholder: "Search commands, designs and conversations"
            onEdited: { pal.sel = 0; list.positionViewAtBeginning(); Qt.callLater(pal.pickBest); if (pal.everywhere) seek.restart() }     // once the rows follow the text
            input.font.pixelSize: 15
            input.Keys.onPressed: function (e) {
                if (e.key === Qt.Key_Down || (e.key === Qt.Key_N && (e.modifiers & Qt.ControlModifier))) { pal.move(1); e.accepted = true }
                else if (e.key === Qt.Key_Up || (e.key === Qt.Key_P && (e.modifiers & Qt.ControlModifier))) { pal.move(-1); e.accepted = true }
                else if (e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) { pal.toggleEverywhere(); e.accepted = true }
                else if (e.key === Qt.Key_Escape) { Store.paletteOpen = false; e.accepted = true }
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { pal.go(pal.sel); e.accepted = true }
            } }
        ListView {
            id: list
            x: 8; y: 60; width: parent.width - 16; height: parent.height - 60 - 36 - 4; clip: true; boundsBehavior: Flickable.StopAtBounds
            model: pal.rows
            delegate: Item {
                id: row
                required property var modelData
                required property int index
                readonly property bool isHead: !!modelData.head
                readonly property bool on: !isHead && pal.picks[pal.sel] === index
                width: list.width; height: isHead ? 34 : 40
                Txt { visible: row.isHead; kind: "cap"; x: 14; y: 16; color: Theme.ink3; text: row.modelData.head || "" }
                // the row the keys are on: a lit plate with a hairline, the brightest thing in the list
                Rectangle { visible: row.on; anchors.fill: parent; radius: 12; border.width: 1; border.color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.10 : 0.08)
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.16 : 0.09) }
                        GradientStop { position: 1; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.09 : 0.05) } } }
                Icon { visible: !row.isHead; x: 14; name: row.modelData.icon || "dot"; size: 15; anchors.verticalCenter: parent.verticalCenter; color: row.on ? Theme.ink : Theme.ink2 }
                Txt { visible: !row.isHead; x: 42; anchors.verticalCenter: parent.verticalCenter; textFormat: Text.StyledText; font.weight: Theme.wMedium; text: row.isHead ? "" : pal.lit(row.modelData.text, row.modelData.at)
                    width: Math.min(implicitWidth, parent.width - 40 - 12 - (kb.visible ? kb.width + 10 : 0) - (pv.visible ? pv.width + 12 : 0) - 60); elide: Text.ElideRight; wrapMode: Text.NoWrap; id: lab }
                Txt { visible: !row.isHead; kind: "fine"; anchors.left: lab.right; anchors.leftMargin: 10; anchors.right: pv.visible ? pv.left : kb.visible ? kb.left : parent.right; anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: 3; text: row.modelData.hint || "" }
                // the preview: the row's own figure, in mono, where a key would stand
                Txt { id: pv; objectName: "paletteValue"; visible: !row.isHead && !!row.modelData.value && !kb.visible; mono: true; font.pixelSize: 11; tone: 2; lineHeight: 1.0
                    anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, 190); elide: Text.ElideRight; wrapMode: Text.NoWrap; text: row.modelData.value || "" }
                Kbd { id: kb; visible: !row.isHead && !!row.modelData.keys; keys: row.modelData.keys || ""; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
                MouseArea { anchors.fill: parent; enabled: !row.isHead; hoverEnabled: true
                    onPositionChanged: function (mouse) { if (!pal.pointed(this, mouse)) return
                        var n = pal.picks.indexOf(row.index); if (n >= 0 && n !== pal.sel) pal.sel = n }
                    onClicked: pal.go(pal.picks.indexOf(row.index)) }
            }
        }
        Txt { visible: pal.picks.length === 0; x: 22; y: 72; tone: 3; text: "Nothing matches “" + q.text.trim() + "”." }
        // what the keys do
        Row { anchors.bottom: parent.bottom; anchors.bottomMargin: 11; x: 22; spacing: 14
            Row { spacing: 5; Kbd { keys: "Up" } Kbd { keys: "Down" } Txt { kind: "fine"; text: "move"; anchors.verticalCenter: parent.verticalCenter } }
            Row { spacing: 5; Kbd { keys: "Return" } Txt { kind: "fine"; text: "run"; anchors.verticalCenter: parent.verticalCenter } }
            Row { objectName: "paletteTab"; spacing: 5; Kbd { keys: "Tab" } Txt { kind: "fine"; text: pal.everywhere ? (Store.project && Store.screen === "work" ? "back to " + Store.project.name : "commands only") : "search everywhere"; anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, 190); elide: Text.ElideRight; wrapMode: Text.NoWrap } } }
        Txt { anchors.bottom: parent.bottom; anchors.bottomMargin: 12; anchors.right: parent.right; anchors.rightMargin: 22; kind: "fine"; mono: true; tone: 3
            text: pal.everywhere && q.text.trim().length >= 2 && pal.foundFor === q.text.trim() ? (pal.found.length ? "said in " + F.plural(pal.found.length, "conversation") : "nothing more inside conversations") : pal.all.length + " commands" }
    }
}
