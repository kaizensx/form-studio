import QtQuick
import FormNative
import "F.js" as F

// Command palette: every action, design and conversation, from the keyboard. No animation: it is used all day.
// Results are grouped (Recent, Go to, Tools, Designs, Conversations, Settings); typing matches loosely — the letters in
// order, not necessarily together — and the matched letters are lit. The commands you ran last come first.
Item {
    id: pal
    anchors.fill: parent; visible: Store.paletteOpen; z: 50
    onVisibleChanged: if (visible) { q.text = ""; sel = 0; rest = null; Store.loadConvs(); q.input.forceActiveFocus() }
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
    readonly property var groups: ["Recent", "Go to", "Tools", "Designs", "Conversations", "Settings"]
    function updates() { Store.checkUpdates(true).then(function (u) {
        if (u && u.available) { Store.updateHidden = false; Store.openSheet("update") }
        else if (u && !u.enabled) Store.toast("Update checks are off", "[updates] check = false or FORM_NO_UPDATE_CHECK=1")
        else if (u && u.latest) Store.toast("Form Studio " + u.current + " is up to date")
        else Store.toast("Could not reach GitHub", "Nothing changed. Try again later.") }) }
    readonly property var all: {
        var c = [], w = Store.screen === "work"
        function add(g, id, icon, text, hint, run, keys) { c.push({ g: g, id: id, icon: icon, text: text, hint: hint || "", run: run, keys: keys || "" }) }
        if (w) {
            Store.stages.forEach(function (s, i) { add("Go to", "stage." + s.id, "arrow_right", s.title, s.hint, function () { Store.setStage(s.id) }, "Ctrl+" + Store.stageKey[s.id]) })
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
            Store.analysisMaps.forEach(function (m) { if (m.value) add("Tools", "map." + m.value, "layers", "Analysis map: " + m.text, Store.analysisMap === m.value ? "Showing now" : "Colour the part by " + m.text.toLowerCase(), function () { Store.setAnalysis(m.value) }) })
            if (Store.analysisMap) add("Tools", "map.off", "layers", "Hide the analysis map", Store.analysisLabel(Store.analysisMap), function () { Store.setAnalysis("") })
            add("Tools", "orient", "move_3d", "Find a print orientation", "Ranks the ways it can sit on the plate", function () { Store.setStage("prove"); Store.findOrientation() })
            if (Store.printUi) add("Tools", "slicerOpen", "external_link", "Open in " + Store.slicerName, "Sliced with settings chosen for this part", function () { Store.setStage("prove"); Store.openInSlicer() })
            add("Tools", "simulate", "film", "Simulate the print", "Layer by layer, from the real slice", function () { Store.simulate() })
            add("Tools", "layers", "layers", Store.layers ? "Close the layer view" : "Show the sliced layers", "The toolpath of the current slice", function () { Store.showLayers(!Store.layers) })
            add("Tools", "run", "play", "Regenerate everything", "Solid, exports, checks, slice", function () { Store.run() })
            add("Tools", "alternatives", "boxes", "Compare alternatives", "Build a grid of candidates", function () { Store.openSheet("alternatives") })
            add("Tools", "lighter", "weight", "Make it lighter", "Thinner walls, pockets, less infill: every passing check kept", function () { Store.openSheet("lighter") })
            add("Tools", "variants", "layout_grid", "Variants board", "Named variants side by side", function () { Store.openSheet("variants") })
            add("Tools", "share", "share_2", "Share card", "A 1600 × 900 image of this design", function () { Store.openSheet("share") })
            add("Tools", "turntable", "film", "Turntable video", "The part turning, as MP4, PNG frames, WebP or GIF", function () { Store.openSheet("turntable") })
            add("Tools", "render", "camera", "Render in Blender", "An illustration of the current revision", function () { Store.openSheet("render") })
            add("Tools", "game", "gamepad_2", "Game asset", "LODs, UVs, baked maps and collision for Godot, Unity or Unreal", function () { Store.openSheet("game") })
            add("Tools", "timeline", "history", (Store.timelineOpen ? "Hide" : "Show") + " the revision timeline", "Scrub through revisions", function () { Store.timelineOpen = !Store.timelineOpen; if (!Store.timelineOpen) Store.endScrub() })
            add("Tools", "morph", "play", "Play the revision history", "Morph through every revision", function () { Store.timelineOpen = true; Store.playMorph() })
            if (Store.hidden.length) add("Tools", "showall", "eye", "Show all features", F.plural(Store.hidden.length, "feature") + " hidden", function () { Store.showAll() }, "Shift+H")
            if (Store.hasDraft) { add("Tools", "commit", "git_commit_horizontal", "Commit the draft", "Saves a revision", function () { Store.commit() }, "Ctrl+Return")
                add("Tools", "discard", "undo_2", "Discard the draft", "", function () { Store.discard() }) }
            add("Tools", "importpart", "box", "Import a reference part…", "STEP or STL, shown in blueprint", function () { Store.askImportPart() })
            add("Tools", "freecad", "external_link", "Open the STEP in FreeCAD", "Release · working files", function () { Store.openIn("step", "freecad") })
            if (Store.canAskReview) add("Tools", "review", "eye", "Ask for a design review", "Silhouette, relationships, details", function () { Store.askReview() })
        }
        add("Tools", "new", "plus", "New design", "Describe it, or drop a photo, a sketch, a part or a link", function () { Store.startNew() }, "Ctrl+N")
        add("Tools", "sketch", "pen_tool", "Sketch a new design", "Lines, circles, arcs and dimensions in mm", function () { if (Store.screen !== "home") Store.home(); Store.openSheet("sketch") })
        add("Tools", "replace", "wrench", "Replace a broken part", "From a photo: estimated, measured, designed", function () { if (Store.screen !== "home") Store.home(); Store.openSheet("replace") })
        add("Tools", "blank", "square_dashed", "Start blank", "An empty design: describe, sketch or import what goes in it", function () { Store.startBlank() })
        add("Tools", "block", "cuboid", "Start from a block", "A rounded block shaped with sliders, no agent", function () { Store.startBlock("") })
        if (Store.concepts.length) add("Tools", "concepts", "boxes", "Concepts waiting for a pick", Store.concepts[0].name, function () { Store.openConcepts(Store.concepts[0].id) })
        if (Store.studio) Store.studio.projects.forEach(function (p) { if (!p.error && p.id !== Store.pid) add("Designs", "p." + p.id, "cuboid", p.name, F.pad(p.head) + " · " + F.ago(p.updated), function () { Store.open(p.id) }) })
        add("Conversations", "chat.new", "message_square_plus", "New conversation", "", function () { Store.newChat(); Store.talkOpen = true }, "Ctrl+Shift+O")
        if (w) add("Conversations", "chat.toggle", "panel_left", (Store.talkOpen ? "Hide" : "Show") + " the conversation", "", function () { Store.talkOpen = !Store.talkOpen }, "Ctrl+J")
        Store.convs.forEach(function (cv) { if (cv.messages > 0 && cv.id !== Store.convId) add("Conversations", "c." + cv.id, "message_square", cv.title, F.ago(cv.updated), function () { Store.openConv(cv.id); Store.talkOpen = true }) })
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
    function match(text, t) {
        var low = text.toLowerCase(), at = [], i = low.indexOf(t)
        if (i >= 0) { for (var k = 0; k < t.length; k++) at.push(i + k); return { score: 1000 - i * 2 + (i === 0 || low[i - 1] === " " ? 60 : 0), at: at } }
        var p = 0, score = 0, last = -2
        for (var j = 0; j < t.length; j++) {
            if (t[j] === " ") continue
            var f = low.indexOf(t[j], p)
            if (f < 0) return null
            score += (f === last + 1 ? 14 : 0) + (f === 0 || low[f - 1] === " " ? 10 : 0) - (f - p)
            at.push(f); last = f; p = f + 1
        }
        return { score: score, at: at }
    }
    // the rows shown: headers and commands, in group order
    readonly property var rows: {
        var t = q.text.trim().toLowerCase(), out = [], items = all, i
        if (!t) {
            var rec = []
            Store.paletteRecent.forEach(function (id) { for (var k = 0; k < items.length; k++) if (items[k].id === id) { rec.push(Object.assign({}, items[k], { g: "Recent" })); break } })
            rec = rec.slice(0, 4)
            var per = { "Go to": 6, "Tools": 5, "Designs": 4, "Conversations": 3, "Settings": 2 }, seen = {}
            rec.forEach(function (r) { seen[r.id] = true })
            items = rec.concat(items.filter(function (c) { if (seen[c.id]) return false; per[c.g] = (per[c.g] || 0) - 1; return per[c.g] >= 0 }))
        } else {
            var hit = []
            for (i = 0; i < items.length; i++) {
                var m = pal.match(items[i].text, t), h = m ? null : pal.match(items[i].hint, t)
                if (m) hit.push(Object.assign({}, items[i], { at: m.at, score: m.score + (Store.paletteRecent.indexOf(items[i].id) >= 0 ? 25 : 0) }))
                else if (h && h.score > 900) hit.push(Object.assign({}, items[i], { at: [], score: h.score - 600 }))
            }
            hit.sort(function (a, b) { return b.score - a.score })
            items = hit.slice(0, 14)
        }
        pal.groups.forEach(function (g) {
            var l = items.filter(function (c) { return c.g === g })
            if (!l.length) return
            out.push({ head: g })
            l.forEach(function (c) { out.push(c) })
        })
        return out
    }
    readonly property var picks: { var p = []; for (var i = 0; i < rows.length; i++) if (!rows[i].head) p.push(i); return p }
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
    Rectangle {
        id: box
        width: Math.min(620, parent.width - 80); anchors.horizontalCenter: parent.horizontalCenter; y: Math.max(64, Math.round(parent.height * 0.14))
        height: 54 + Math.min(list.contentHeight, Math.min(440, parent.height - y - 120)) + 12 + 34
        radius: Theme.rLg + 2; color: Theme.plate2; border.color: Theme.rule2
        Shadow { radius: parent.radius; spread: 44; drop: 18; strength: 1.25 }
        MouseArea { anchors.fill: parent }
        Icon { x: 18; y: 19; name: "search"; size: 16; color: Theme.ink3 }
        Field { id: q; x: 42; y: 11; width: parent.width - 60; height: 32; bare: true; placeholder: "Search commands, designs and conversations"
            onEdited: { pal.sel = 0; list.positionViewAtBeginning() }
            input.font.pixelSize: 15
            input.Keys.onPressed: function (e) {
                if (e.key === Qt.Key_Down || (e.key === Qt.Key_N && (e.modifiers & Qt.ControlModifier))) { pal.move(1); e.accepted = true }
                else if (e.key === Qt.Key_Up || (e.key === Qt.Key_P && (e.modifiers & Qt.ControlModifier))) { pal.move(-1); e.accepted = true }
                else if (e.key === Qt.Key_Escape) { Store.paletteOpen = false; e.accepted = true }
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { pal.go(pal.sel); e.accepted = true }
            } }
        Rectangle { y: 53; width: parent.width; height: 1; color: Theme.rule }
        ListView {
            id: list
            x: 6; y: 58; width: parent.width - 12; height: parent.height - 58 - 34 - 4; clip: true; boundsBehavior: Flickable.StopAtBounds
            model: pal.rows
            delegate: Item {
                id: row
                required property var modelData
                required property int index
                readonly property bool isHead: !!modelData.head
                readonly property bool on: !isHead && pal.picks[pal.sel] === index
                width: list.width; height: isHead ? 28 : 34
                Txt { visible: row.isHead; kind: "cap"; x: 12; y: 11; text: row.modelData.head || "" }
                Rectangle { visible: !row.isHead; anchors.fill: parent; radius: Theme.rSm; color: row.on ? Theme.washOn : "transparent" }
                Icon { visible: !row.isHead; x: 12; name: row.modelData.icon || "dot"; size: 14; anchors.verticalCenter: parent.verticalCenter; color: row.on ? Theme.datum : Theme.ink3 }
                Txt { visible: !row.isHead; x: 38; anchors.verticalCenter: parent.verticalCenter; textFormat: Text.StyledText; text: row.isHead ? "" : pal.lit(row.modelData.text, row.modelData.at)
                    width: Math.min(implicitWidth, parent.width - 38 - 12 - (kb.visible ? kb.width + 10 : 0) - 60); elide: Text.ElideRight; wrapMode: Text.NoWrap; id: lab }
                Txt { visible: !row.isHead; kind: "fine"; anchors.left: lab.right; anchors.leftMargin: 10; anchors.right: kb.visible ? kb.left : parent.right; anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; tone: 3; text: row.modelData.hint || "" }
                Kbd { id: kb; visible: !row.isHead && !!row.modelData.keys; keys: row.modelData.keys || ""; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
                MouseArea { anchors.fill: parent; enabled: !row.isHead; hoverEnabled: true
                    onPositionChanged: function (mouse) { if (!pal.pointed(this, mouse)) return
                        var n = pal.picks.indexOf(row.index); if (n >= 0 && n !== pal.sel) pal.sel = n }
                    onClicked: pal.go(pal.picks.indexOf(row.index)) }
            }
        }
        Txt { visible: pal.picks.length === 0; x: 18; y: 66; tone: 3; text: "Nothing matches “" + q.text.trim() + "”." }
        // what the keys do
        Rectangle { anchors.bottom: parent.bottom; anchors.bottomMargin: 33; width: parent.width; height: 1; color: Theme.rule }
        Row { anchors.bottom: parent.bottom; anchors.bottomMargin: 8; x: 16; spacing: 14
            Row { spacing: 5; Kbd { keys: "Up" } Kbd { keys: "Down" } Txt { kind: "fine"; text: "move"; anchors.verticalCenter: parent.verticalCenter } }
            Row { spacing: 5; Kbd { keys: "Return" } Txt { kind: "fine"; text: "run"; anchors.verticalCenter: parent.verticalCenter } }
            Row { spacing: 5; Kbd { keys: "Esc" } Txt { kind: "fine"; text: "close"; anchors.verticalCenter: parent.verticalCenter } } }
        Txt { anchors.bottom: parent.bottom; anchors.bottomMargin: 10; anchors.right: parent.right; anchors.rightMargin: 16; kind: "fine"; tone: 4
            text: pal.all.length + " commands" }
    }
}
