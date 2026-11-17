import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Every way to start a design, in one sheet:
//   Describe it      words (and a reference STEP/STL) go to the agent, which writes the design as code
//   From a recipe    the library: built-in recipes, recipes you installed, community recipes from the website
//   From a brief     guided questions, then the agent designs it; your own saved templates first
//   Import           a .formstudio / .formproj archive, a conversation, or a shipped example
// Open on a tab with Store.openSheet("new", { tab: "brief", preset: "remote-holder", answers: {...} }),
// or { tab: "recipe", section: "mine", pick: "my-recipe" }.
Column {
    id: ns
    objectName: "newSheet"
    property string title: "New design"
    property int sheetWidth: Theme.sheetXl
    property int sheetHeight: 604
    readonly property var tabs: [{ value: "blank", text: "Describe it" }, { value: "recipe", text: "From a recipe" },
                                 { value: "brief", text: "From a brief" }, { value: "import", text: "Import" }]
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    property string tab: props.tab || "recipe"
    property Item firstFocus: tab === "blank" ? describe.area : null
    function accept() {
        if (tab === "recipe") make()
        else if (tab === "brief") { if (preset && missing.length === 0 && !sending && Store.chatReady && !Store.chatBusy) ask() }
        else if (tab === "blank") describeSend()
    }
    spacing: 14
    Component.onCompleted: {
        Store.get("/presets").then(function (r) { ns.presets = r.presets }, Store.fail)
        if (!Store.starters) Store.loadStarters()
        loadLib(false)
        if (showExamples) loadExamples()
    }

    // ── footers, per tab ──
    property Component footerLeft: tab === "recipe" ? leftRecipe : tab === "brief" && preset ? leftBrief : tab === "blank" ? leftBlank : null
    property Component footer: tab === "recipe" ? rightRecipe : tab === "brief" && preset ? rightBrief : tab === "blank" ? rightBlank : null
    Component { id: leftRecipe; Row { spacing: 4
        Btn { objectName: "installRecipeFile"; kind: "quiet"; icon: "file_code"; text: "Install from a file…"; tip: "A .py (build123d) or .scad (OpenSCAD) recipe. You see its code before anything is installed."
            onClicked: Store.ask(recipeDlg) }
        Btn { kind: "quiet"; icon: "refresh_cw"; text: "Refresh"; visible: ns.section === "community"; onClicked: ns.loadLib(true) } } }
    Component { id: rightRecipe; Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { visible: !!ns.chosen && ns.chosen.section === "mine"; kind: "quiet"; icon: "code"; text: "View code"; onClicked: ns.viewSource(ns.chosen.id) }
        Btn { objectName: "recipePrimary"; kind: "primary"; keys: "Return"; busy: ns.creating
            icon: ns.needsInstall ? "download" : "plus"
            text: ns.needsInstall ? "Review and install…" : "Create design"
            enabled: !!ns.chosen && !(ns.chosen.section === "community" && ns.chosen.installed && !ns.mineFor(ns.chosen))
            onClicked: ns.make() } } }
    Component { id: leftBrief; Txt { kind: "fine"; elide: Text.ElideRight; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        color: ns.missing.length > 0 ? Theme.amber : Theme.ink3
        text: ns.missing.length > 0 ? "Still needed: " + ns.missing.map(function (q) { return q.label }).join(", ") + "." : "Your answers are saved with the project. Nothing is printed or uploaded." } }
    Component { id: rightBrief; Row { spacing: 8
        Btn { kind: "quiet"; icon: "bookmark_plus"; text: "Save as my template"; tip: "Keep these answers as a starting point on Home"
            enabled: !!ns.preset && F.keys(ns.answers).some(function (k) { return String(ns.answers[k]).trim() !== "" })
            onClicked: Store.saveBriefTemplate(ns.presetId, ns.answers, "", ns.measured) }
        Btn { kind: "quiet"; icon: "copy"; text: "Copy the prompt"; enabled: !!ns.preset && ns.missing.length === 0 && !ns.sending; onClicked: ns.copy() }
        Btn { kind: "primary"; icon: "message_square"; text: "Ask " + Store.chatAgentLabel + " to design it"; busy: ns.sending
            enabled: !!ns.preset && ns.missing.length === 0 && Store.chatReady && !Store.chatBusy
            tip: Store.chatBusy ? Store.chatAgentLabel + " is still answering the previous message" : ""
            onClicked: ns.ask() } } }
    Component { id: leftBlank; Txt { kind: "fine"; verticalAlignment: Text.AlignVCenter; text: "Nothing is printed or uploaded." } }
    Component { id: rightBlank; Row { spacing: 8
        Btn { kind: "quiet"; text: "Edit in the composer"; enabled: ns.describeText.trim() !== ""; onClicked: ns.describeToComposer() }
        Btn { objectName: "describeSend"; kind: "primary"; icon: "message_square"; text: "Ask " + Store.chatAgentLabel + " to design it"; busy: ns.sending
            enabled: ns.describeText.trim() !== "" && Store.chatReady && !Store.chatBusy; onClicked: ns.describeSend() } } }

    // ════ Describe it ════════════════════════════════════════════════════════════════════
    property string describeText: ""
    property var refs: []                      // file urls of reference parts to attach
    function describeToComposer() {
        var t = describeText.trim(), r = refs
        Store.openSheet(null); Store.newChat(); Store.recallChat(t)
        if (r.length) Store.attachFiles(r)
    }
    function describeSend() {
        var t = describeText.trim()
        if (!t || !Store.chatReady || Store.chatBusy || sending) return
        if (!refs.length) { Store.openSheet(null); Store.newChat(); Store.send(t); return }
        // attach the parts first; send once every upload is in the conversation
        sending = true
        Store.newChat(); Store.attachFiles(refs)
        waitAttach.want = refs.length; waitAttach.text = t; waitAttach.tries = 0; waitAttach.start()
    }
    Timer { id: waitAttach; interval: 150; repeat: true; property int want: 0; property string text: ""; property int tries: 0
        onTriggered: {
            if (Store.chatAttach.length >= want || ++tries > 120) { stop(); ns.sending = false; Store.openSheet(null); Store.send(text) }
        } }
    Column { width: parent.width; spacing: 14; visible: ns.tab === "blank"
        Row { width: parent.width; spacing: 20
            Column { width: parent.width - side.width - 20; spacing: 10
                Txt { kind: "lead"; font.weight: Theme.wSemi; text: "Describe the part" }
                Txt { tone: 2; width: parent.width; text: "What it holds, where it goes, what it must survive, and the sizes you measured. " + Store.chatAgentLabel + " writes the design as code in a real CAD kernel and shows its work." }
                Area { id: describe; objectName: "describeArea"; width: parent.width; minLines: 9
                    placeholder: "e.g. A wall bracket for a 120 mm fan, two M4 screws 105 mm apart, PETG, behind a desk."
                    onTextChanged: ns.describeText = text } }
            Column { id: side; width: 300; spacing: 10
                Txt { kind: "cap"; text: "A part it must fit" }
                Txt { kind: "fine"; width: parent.width; text: "A STEP or STL from the maker, such as a circuit board. It is attached to the message; the agent imports it as a reference and designs around it." }
                Repeater { model: ns.refs
                    Rectangle { required property var modelData; required property int index
                        width: side.width; height: 32; radius: Theme.rSm; color: Theme.plate2; border.color: Theme.rule2
                        Icon { x: 10; name: "box"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                        Txt { x: 30; width: parent.width - 64; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                            text: decodeURIComponent(String(modelData).replace(/^.*[\/\\]/, "")) }
                        Btn { small: true; kind: "quiet"; icon: "x"; tip: "Remove"; anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
                            onClicked: { var r = ns.refs.slice(); r.splice(index, 1); ns.refs = r } } } }
                Btn { icon: "file_input"; text: "Attach a STEP or STL…"; onClicked: Store.ask(refDlg) }
                Note { visible: !Store.chatReady && !!Store.studio; kind: "amber"; title: "No agent is connected"
                    text: (Store.chat.note || "") + " A recipe or an imported project works without one." } } }
        Txt { kind: "fine"; width: parent.width; text: "Form Studio works from a written brief, dimensions you measure, reference parts and photos with a marked scale. It does not reconstruct geometry from photos or scans." }
        Rectangle { width: parent.width; height: 1; color: Theme.rule; visible: starterList.count > 0 }
        Txt { kind: "cap"; text: "Start from one of your starters"; visible: starterList.count > 0 }
        Grid { width: parent.width; columns: 2; columnSpacing: 10; rowSpacing: 8; visible: starterList.count > 0
            Repeater { id: starterList; model: Store.starters ? Store.starters.prompts.slice(0, 6) : []
                Rectangle { id: sr; required property var modelData; required property int index
                    width: (ns.width - 10) / 2; height: 40; radius: Theme.rMd
                    color: srm.pressed ? Theme.plate1 : srm.containsMouse ? Theme.plate3 : Theme.plate2; border.color: srm.containsMouse ? Theme.rule3 : Theme.rule
                    Behavior on color { Tint {} }
                    Icon { x: 12; name: sr.modelData.pinned ? "pin" : sr.modelData.source === "mine" ? "pencil" : sr.modelData.source === "learned" ? "sparkle" : "lightbulb"
                        size: 13; color: sr.modelData.source === "learned" ? Theme.blueprint : sr.modelData.source === "suggested" && !sr.modelData.pinned ? Theme.ink3 : Theme.datum
                        anchors.verticalCenter: parent.verticalCenter }
                    Txt { x: 34; width: parent.width - 66; text: sr.modelData.text; elide: Text.ElideRight; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter; tone: srm.containsMouse ? 1 : 2 }
                    Icon { name: "corner_down_left"; size: 13; color: srm.containsMouse ? Theme.datum : Theme.ink4; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { id: srm; anchors.fill: parent; hoverEnabled: true
                        onClicked: { Store.post("/starters/used", { id: sr.modelData.id }).then(function () {}, function () {})
                                     describe.text = sr.modelData.text; describe.area.forceActiveFocus(); describe.area.cursorPosition = describe.text.length } }
                    Tip { show: srm.containsMouse; text: "Use these words, then add your sizes" } } } }
    }

    // ════ From a recipe: the library ═════════════════════════════════════════════════════════
    property var lib: ({ items: [], tags: [], counts: {}, community_error: null })
    property bool libLoaded: false
    property string section: props.section || "all"
    property string query: ""
    property string tag: ""
    property string sort: "name"
    property string pickId: props.pick || ""
    property bool creating: false
    readonly property var chosen: { var l = lib.items; for (var i = 0; i < l.length; i++) if (l[i].id + "|" + l[i].section === pickKey) return l[i]; return null }
    property string pickKey: ""
    readonly property bool needsInstall: !!chosen && chosen.section === "community" && !chosen.installed
    onSectionChanged: loadLib(false)
    onTagChanged: loadLib(false)
    onSortChanged: loadLib(false)
    onQueryChanged: searchLater.restart()
    Timer { id: searchLater; interval: 140; onTriggered: ns.loadLib(false) }
    property int _libSeq: 0
    function loadLib(refresh) {
        var seq = ++_libSeq
        var qs = "?q=" + encodeURIComponent(query) + "&section=" + (section === "all" ? "" : section) + "&tag=" + encodeURIComponent(tag)
                 + "&sort=" + sort + (refresh ? "&refresh=1" : "")
        Store.get("/recipes/library" + qs).then(function (r) {
            if (seq !== ns._libSeq) return
            ns.lib = r; ns.libLoaded = true
            if (!ns.chosen) {
                var want = r.items.filter(function (i) { return ns.pickId ? i.id === ns.pickId : i.section !== "community" })[0] || r.items[0]
                ns.pickKey = want ? want.id + "|" + want.section : ""
            }
        }, Store.fail)
    }
    function mineFor(item) {                   // the installed copy of a community recipe
        var l = lib.items
        for (var i = 0; i < l.length; i++) if (l[i].section === "mine" && l[i].community_id === item.id) return l[i]
        return null
    }
    function make() {
        var c = chosen
        if (!c || creating) return
        if (c.section === "community") {
            if (c.builtin) { pickBuiltin(c.id); return }
            var m = mineFor(c)
            if (m) { c = m } else {
                creating = true
                Store.post("/recipes/community/preview", { id: c.id }).then(function (r) {
                    ns.creating = false; Store.openSheet("recipe", { mode: "community", info: r })
                }, function (e) { ns.creating = false; Store.fail(e) })
                return
            }
        }
        var nm = name.text.trim() || c.title, br = brief.text.trim()
        if (c.section === "builtin") { Store.create(nm, c.id, br); return }
        creating = true
        Store.post("/recipes/create", { id: c.id, name: nm, brief: br }).then(function (r) {
            ns.creating = false; Store.openSheet(null); Store.stage = "shape"
            Store.reloadStudio().then(function () { Store.open(r.id).then(function () { Store.track(r.job) }) })
        }, function (e) { ns.creating = false; Store.fail(e) })
    }
    function pickBuiltin(id) { section = "builtin"; pickId = id; pickKey = id + "|builtin" }
    function viewSource(id) { Store.get("/recipes/mine/" + id + "/source").then(function (r) { Store.openSheet("recipe", { mode: "installed", info: r }) }, Store.fail) }
    readonly property var sectionModel: [
        { value: "all", text: "All" },
        { value: "builtin", text: "Built-in" + (lib.counts && lib.counts.builtin ? "  " + lib.counts.builtin : "") },
        { value: "mine", text: "Mine" + (lib.counts && lib.counts.mine ? "  " + lib.counts.mine : "") },
        { value: "community", text: "Community" + (lib.counts && lib.counts.community ? "  " + lib.counts.community : "") }]

    Column { id: recipeTab; width: parent.width; spacing: 12; visible: ns.tab === "recipe"
        // search, sections, sort
        Item { width: parent.width; height: 30
            Field { id: search; objectName: "recipeSearch"; width: 250; placeholder: "Search recipes"; anchors.verticalCenter: parent.verticalCenter
                onEdited: function (t) { ns.query = t } }
            Icon { visible: search.text === ""; name: "search"; size: 13; color: Theme.ink4; x: search.width - 22; anchors.verticalCenter: parent.verticalCenter }
            Seg { x: search.width + 12; anchors.verticalCenter: parent.verticalCenter; value: ns.section; model: ns.sectionModel
                onPicked: function (v) { ns.section = v } }
            Pick { anchors.right: parent.right; width: 168; anchors.verticalCenter: parent.verticalCenter; value: ns.sort
                model: [{ value: "name", text: "Sort: by name" }, { value: "recent", text: "Sort: newest installed" }]
                onPicked: function (v) { ns.sort = v } } }
        // tags and categories
        Flow { width: parent.width; height: 24; spacing: 6; clip: true
            Repeater { model: (ns.lib.tags || []).slice(0, 12)
                Rectangle { id: chip; required property var modelData
                    readonly property bool on: ns.tag === modelData.tag
                    width: ct.implicitWidth + 18; height: 24; radius: 12
                    color: on ? Theme.alpha(Theme.datum, 0.14) : cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.washHover : "transparent"
                    border.color: on ? Theme.alpha(Theme.datum, 0.5) : Theme.rule2
                    Behavior on color { Tint {} }
                    Txt { id: ct; anchors.centerIn: parent; font.pixelSize: 12; text: chip.modelData.tag; color: chip.on ? Theme.datum : cm.containsMouse ? Theme.ink : Theme.ink2 }
                    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; onClicked: ns.tag = chip.on ? "" : chip.modelData.tag } } } }
        // the grid: virtualized, so a library of hundreds stays quick
        Item { width: parent.width; height: ns.sheetHeight - 30 - 24 - 66 - 3 * 12 - 22
            GridView {
                id: grid
                objectName: "recipeGrid"
                anchors.fill: parent; clip: true; boundsBehavior: Flickable.StopAtBounds
                readonly property int cols: Math.max(2, Math.floor(width / 240))
                cellWidth: Math.floor(width / cols); cellHeight: 214
                cacheBuffer: 214
                model: ns.lib.items
                ScrollBar.vertical: ScrollBar { width: 6 }
                delegate: Item {
                    id: cell
                    required property var modelData
                    required property int index
                    readonly property var it: modelData
                    readonly property bool on: ns.pickKey === it.id + "|" + it.section
                    width: grid.cellWidth; height: grid.cellHeight
                    Rectangle {
                        id: card
                        x: 5; y: 5; width: parent.width - 10; height: parent.height - 10; radius: Theme.rLg
                        color: Theme.plate1
                        border.color: cell.on ? Theme.alpha(Theme.datum, 0.7) : rm.containsMouse ? Theme.rule3 : Theme.rule
                        Behavior on border.color { Tint {} }
                        scale: rm.pressed ? Theme.from(0.985) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        // preview: built-in recipes are built and drawn live; others show their published image or their kind
                        Item { id: pv; x: 1; y: 1; width: parent.width - 2; height: 112; clip: true
                            Rectangle { anchors.fill: parent; radius: Theme.rLg - 1; color: Theme.plate2 }
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Theme.rLg; color: Theme.plate2 }
                            RecipeView { anchors.fill: parent; visible: cell.it.section === "builtin"; recipeId: cell.it.section === "builtin" ? cell.it.id : ""
                                turning: rm.containsMouse || cell.on }
                            Image { id: img; anchors.fill: parent; visible: cell.it.section !== "builtin" && !!cell.it.preview && status === Image.Ready
                                fillMode: Image.PreserveAspectCrop; asynchronous: true; source: cell.it.section !== "builtin" && cell.it.preview ? cell.it.preview : "" }
                            Column { visible: cell.it.section !== "builtin" && img.status !== Image.Ready; anchors.centerIn: parent; spacing: 6
                                Icon { anchors.horizontalCenter: parent.horizontalCenter; name: cell.it.section === "community" ? "globe" : "file_code"; size: 26; color: Theme.ink4 }
                                Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; tone: 4; text: cell.it.kind === "scad" ? "OpenSCAD" : "build123d" } } }
                        Rectangle { y: pv.height + 1; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
                        Column { x: 14; y: pv.height + 10; width: parent.width - 28; spacing: 3
                            Txt { text: cell.it.title; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Txt { kind: "fine"; text: cell.it.summary || ""; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight; height: 30 }
                            Row { spacing: 6
                                Tag { text: cell.it.section === "builtin" ? "built-in" : cell.it.section === "mine" ? "mine" : cell.it.builtin ? "included" : cell.it.installed ? "installed" : "community"
                                      kind: "x"; tint: cell.it.section === "builtin" ? Theme.ink3 : cell.it.section === "mine" ? Theme.datum : Theme.blueprint }
                                Txt { kind: "fine"; tone: 3; text: cell.it.author && cell.it.section !== "builtin" ? "by " + cell.it.author : cell.it.category || ""
                                      anchors.verticalCenter: parent.verticalCenter } } }
                        Icon { visible: cell.on; name: "circle_check"; size: 16; color: Theme.datum; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10 }
                        MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true
                            onClicked: ns.pickKey = cell.it.id + "|" + cell.it.section
                            onDoubleClicked: { ns.pickKey = cell.it.id + "|" + cell.it.section; ns.make() } }
                    }
                }
            }
            // empty and offline states
            Column { anchors.centerIn: parent; width: Math.min(420, parent.width - 40); spacing: 8; visible: ns.libLoaded && ns.lib.items.length === 0
                Icon { anchors.horizontalCenter: parent.horizontalCenter; name: ns.section === "community" ? "globe" : ns.section === "mine" ? "file_code" : "search"; size: 26; color: Theme.ink4 }
                Txt { anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; font.weight: Theme.wSemi
                    text: ns.query || ns.tag ? "Nothing matches" : ns.section === "mine" ? "No recipes of your own yet" : ns.section === "community" ? (ns.lib.community_error ? "The community library is out of reach" : "No community recipes are published yet") : "No recipes" }
                Txt { anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; tone: 3
                    text: ns.query || ns.tag ? "Try fewer words, or another section." : ns.section === "mine" ? "Install a .py or .scad recipe from a file, or one from Community." : ns.section === "community" ? (ns.lib.community_error ? ns.lib.community_error + " Built-in recipes and your own work offline." : "Recipes shared on the website appear here.") : "" } }
        }
        // what the design is called and what it is for
        Row { width: parent.width; spacing: 12
            Column { width: 320; spacing: 4
                Txt { kind: "cap"; text: "Name" }
                Field { id: name; objectName: "newName"; width: parent.width; placeholder: ns.chosen ? ns.chosen.title : "e.g. Hallway phone dock" } }
            Column { width: parent.width - 332; spacing: 4
                Txt { kind: "cap"; text: "What it is for" }
                Field { id: brief; width: parent.width; placeholder: ns.chosen && ns.chosen.section !== "builtin" && !ns.needsInstall ? "Optional. Creating it runs this recipe’s code on this computer." : "Optional. You can write this later." } } }
    }

    // ════ From a brief ═══════════════════════════════════════════════════════════════════
    property var presets: []
    property string presetId: props.preset || ""
    property var answers: props.answers || ({})
    property bool measured: !!props.measured
    property bool sending: false
    readonly property var preset: { for (var i = 0; i < presets.length; i++) if (presets[i].id === presetId) return presets[i]; return null }
    readonly property var missing: preset ? preset.questions.filter(function (q) { return q.required && !String(answers[q.key] || "").trim() }) : []
    // learned order: your templates, then the templates you use most (form/starters.py)
    readonly property var briefCards: {
        var out = [], seen = ({}), byId = ({})
        presets.forEach(function (p) { byId[p.id] = p })
        var ranked = Store.starters ? Store.starters.briefs : []
        ranked.forEach(function (b) {
            var p = byId[b.preset]; if (!p) return
            out.push({ id: b.id, kind: b.kind, preset: p, title: b.title, summary: b.summary, answers: b.answers || null, source: b.source, measured: !!b.measured })
            if (b.kind === "preset") seen[p.id] = true
        })
        presets.forEach(function (p) { if (!seen[p.id]) out.push({ id: "p-" + p.id, kind: "preset", preset: p, title: p.title, summary: p.summary, answers: null, source: "suggested" }) })
        return out
    }
    function startBrief(then) {
        sending = true
        Store.post("/briefs", { preset: presetId, answers: answers, measured: measured }).then(function (r) {
            sending = false; then(r)
        }, function (e) { sending = false; Store.fail(e) })
    }
    function ask() { startBrief(function (r) { Store.openSheet(null); Store.send(r.prompt) }) }
    function copy() { startBrief(function (r) { Bridge.copy(r.prompt); Store.toast("Prompt copied", "Paste it into any agent that has Form Studio's MCP tools.") }) }
    function setAnswer(k, v) { var o = Object.assign({}, answers); o[k] = v; answers = o }
    function envLine(e) { return e.setting + " · humidity " + e.humidity + " · UV " + e.uv }

    Column { width: parent.width; spacing: 12; visible: ns.tab === "brief" && !ns.preset
        Txt { tone: 2; width: parent.width; text: "Answer the few questions that decide fit, material and mounting. " + Store.chatAgentLabel + " designs it from your answers and asks only for what is still missing." }
        Grid { width: parent.width; columns: 3; spacing: 10
            Repeater { model: ns.briefCards
                Rectangle { id: pc; required property var modelData; required property int index
                    readonly property bool mine: modelData.kind === "template"
                    width: (ns.width - 20) / 3; height: 104; radius: Theme.rLg
                    color: pm.pressed ? Theme.plate1 : pm.containsMouse ? Theme.plate3 : Theme.plate2
                    border.color: pc.mine ? Theme.alpha(Theme.datum, pm.containsMouse ? 0.6 : 0.35) : pm.containsMouse ? Theme.rule3 : Theme.rule
                    Behavior on color { Tint {} }
                    opacity: 0; Component.onCompleted: bin.start()
                    SequentialAnimation { id: bin; PauseAnimation { duration: Math.min(pc.index, 8) * Theme.stagger }
                        ParallelAnimation { Glide { target: pc; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: btr; property: "y"; from: Theme.shift(6); to: 0; duration: Theme.slow } } }
                    transform: Translate { id: btr }
                    Column { x: 14; y: 13; width: parent.width - 28; spacing: 3
                        Row { spacing: 8; width: parent.width
                            Txt { text: pc.modelData.title; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; width: Math.min(implicitWidth, parent.width - 70) }
                            Tag { visible: pc.mine || pc.modelData.source === "learned" || pc.modelData.source === "related"
                                text: pc.mine ? "yours" : pc.modelData.source === "learned" ? "you use this" : "like your designs"; kind: "x"
                                tint: pc.modelData.source === "related" ? Theme.blueprint : Theme.datum } }
                        Txt { kind: "fine"; text: pc.modelData.summary; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight }
                        Txt { kind: "fine"; tone: 3; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: pc.mine ? "from the " + pc.modelData.preset.title.toLowerCase() + " template" : pc.modelData.preset.questions.length + " questions · starts from " + pc.modelData.preset.material.suggested } }
                    MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true
                        onClicked: { if (pc.mine) Store.post("/starters/used", { id: pc.modelData.id }).then(function () {}, function () {})
                                     ns.answers = pc.modelData.answers || ({}); ns.measured = !!pc.modelData.measured; ns.presetId = pc.modelData.preset.id } } } } }
        Txt { kind: "fine"; width: parent.width; visible: ns.presets.length === 0; text: "Loading templates…" }
    }

    Column { width: parent.width; spacing: 12; visible: ns.tab === "brief" && !!ns.preset
        Row { spacing: 8; x: -8
            Btn { kind: "quiet"; small: true; icon: "arrow_left"; text: "All templates"; onClicked: { ns.presetId = ""; ns.answers = ({}) } } }
        Column { width: parent.width; spacing: 2
            Txt { kind: "lead"; text: ns.preset ? ns.preset.title : ""; font.weight: 600 }
            Txt { tone: 2; width: parent.width; text: ns.preset ? ns.preset.summary : "" } }
        Sec { title: "Your answers"; note: "* needed"
            Column { width: parent.width
                Repeater { model: ns.preset ? ns.preset.questions : []
                    Item { id: qr; required property var modelData; required property int index
                        readonly property bool wide: modelData.kind === "text"
                        width: parent.width; implicitHeight: (wide ? ql.implicitHeight + 6 + qf.height : Math.max(ql.implicitHeight, 28)) + 14
                        Rectangle { visible: qr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Column { id: ql; y: 8; width: qr.wide ? parent.width : parent.width - 252; spacing: 1
                            Txt { text: qr.modelData.label + (qr.modelData.required ? " *" : ""); font.weight: 600; width: parent.width }
                            Txt { kind: "fine"; text: qr.modelData.why; width: parent.width } }
                        Field { id: qf; visible: qr.modelData.kind !== "choice"
                            x: qr.wide ? 0 : parent.width - 240; y: qr.wide ? ql.y + ql.implicitHeight + 6 : 8; width: qr.wide ? parent.width : 240
                            numeric: qr.modelData.kind === "number"; unit: qr.modelData.unit || ""
                            placeholder: qr.modelData.placeholder || (qr.modelData.kind === "number" ? "not known yet" : "")
                            Component.onCompleted: text = ns.answers[qr.modelData.key] !== undefined ? String(ns.answers[qr.modelData.key]) : ""
                            onEdited: function (t) { ns.setAnswer(qr.modelData.key, t) } }
                        Pick { visible: qr.modelData.kind === "choice"; x: parent.width - 240; y: 8; width: 240
                            model: [{ value: "", text: "Choose…" }].concat((qr.modelData.choices || []).map(function (c) { return { value: c, text: c } }))
                            value: ns.answers[qr.modelData.key] || ""
                            onPicked: function (v) { ns.setAnswer(qr.modelData.key, v) } } } } }
            Item { width: parent.width; implicitHeight: Math.max(mt.implicitHeight, 16) + 6
                Check { y: 3; checked: ns.measured; onToggled: function (c) { ns.measured = c } }
                Column { id: mt; x: 26; y: 2; width: parent.width - 26; spacing: 1
                    Txt { text: "I measured these numbers"; font.weight: 600 }
                    Txt { kind: "fine"; width: parent.width; text: "With calipers or a ruler on the real object. Otherwise they are carried as assumed until you confirm." } }
                MouseArea { x: 20; width: parent.width - 20; height: parent.height; onClicked: ns.measured = !ns.measured } } }
        Note { visible: !Store.chatReady; kind: "amber"; title: "No agent is connected"
            text: (Store.chat.note || "") + " You can copy the prompt and paste it into any agent that has Form Studio's tools." }
        Sec { title: "Template defaults"; tag: "assumed"
            Txt { kind: "fine"; width: parent.width; text: "The agent starts from these and corrects them from your answers. Tell it where they are wrong." }
            Column { width: parent.width; visible: !!ns.preset
                KV { first: true; k: "Environment"; sub: ns.preset ? ns.envLine(ns.preset.environment) : ""
                    value: ns.preset ? ns.preset.environment.temperature_c[0] + " to " + ns.preset.environment.temperature_c[1] + " °C" : "" }
                KV { k: "Load"; sub: ns.preset ? ns.preset.environment.load.note : ""
                    value: ns.preset ? ns.preset.environment.load.kind + " · about " + ns.preset.environment.load.mass_g + " g" : "" }
                KV { k: "Material to start from"; sub: ns.preset ? ns.preset.material.why : ""; value: ns.preset ? ns.preset.material.suggested : "" } } }
        Sec { title: "Checks to plan for"; note: ns.preset ? ns.preset.checks.length + " · not run yet" : ""
            Column { width: parent.width; spacing: 4
                Repeater { model: ns.preset ? ns.preset.checks : []
                    Txt { required property var modelData; kind: "fine"; width: parent.width
                        text: "<b>" + modelData.name + "</b> — " + modelData.why; textFormat: Text.StyledText } } } }
    }

    // ════ Import ═══════════════════════════════════════════════════════════════════════
    property bool showExamples: !!props.examples
    property var examples: []
    onShowExamplesChanged: if (showExamples) loadExamples()
    onTabChanged: if (tab === "import" && !examples.length) loadExamples()
    function loadExamples() { Store.get("/examples").then(function (r) { ns.examples = r.examples }, Store.fail) }
    Component.onDestruction: waitAttach.stop()
    Column { width: parent.width; spacing: 16; visible: ns.tab === "import"
        Row { width: parent.width; spacing: 12
            ImportTile { objectName: "importProject"; icon: "archive"; title: "A project"; onPicked: Store.ask(projDlg)
                text: "A .formstudio file: the design, its history, its conversations and the code it was built from. Older .formproj files work too." }
            ImportTile { objectName: "importConversation"; icon: "message_square"; title: "A conversation"; onPicked: Store.ask(convDlg)
                text: "A conversation exported as JSON from Form Studio. It is added to your conversations; its design link is kept when that design is here." } }
        Txt { kind: "fine"; width: parent.width; text: "Files are checked before anything is written: a damaged or unsafe archive is refused whole. A design or conversation whose id already exists here gets a new one; nothing is overwritten." }
        Column { width: parent.width; spacing: 6
            Txt { kind: "cap"; text: "Examples that ship with Form Studio" }
            Txt { kind: "fine"; width: parent.width; text: "Opening one copies its design history into your projects; its outputs are rebuilt on your computer." }
            Repeater { model: ns.examples
                Rectangle { id: ex; required property var modelData
                    width: ns.width; height: 40; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Icon { x: 12; name: "box"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { x: 34; text: ex.modelData.name; font.weight: 600; anchors.verticalCenter: parent.verticalCenter }
                    Btn { objectName: "exampleAdd"; small: true; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                        text: ex.modelData.present ? "Open" : "Add and open"
                        onClicked: { if (ex.modelData.present) { Store.openSheet(null); Store.open(ex.modelData.id) } else Store.addExample(ex.modelData.id) } } } } }
    }

    component ImportTile: Rectangle {
        id: ic
        property string icon: ""; property string title: ""; property string text: ""
        signal picked()
        width: (ns.width - 12) / 2; height: 150; radius: Theme.rLg
        color: im.pressed ? Theme.plate1 : im.containsMouse ? Theme.plate3 : Theme.plate2; border.color: im.containsMouse ? Theme.rule3 : Theme.rule
        Behavior on color { Tint {} }
        Rectangle { x: 18; y: 18; width: 40; height: 40; radius: Theme.rMd; color: Theme.alpha(Theme.datum, 0.1)
            Icon { anchors.centerIn: parent; name: ic.icon; size: 18; color: Theme.datum } }
        Column { x: 74; y: 18; width: parent.width - 92; spacing: 4
            Txt { kind: "lead"; font.weight: Theme.wSemi; text: ic.title }
            Txt { tone: 2; width: parent.width; text: ic.text } }
        Txt { x: 74; anchors.bottom: parent.bottom; anchors.bottomMargin: 16; kind: "fine"; color: im.containsMouse ? Theme.datum : Theme.ink3; text: "Choose a file…" }
        MouseArea { id: im; anchors.fill: parent; hoverEnabled: true; onClicked: ic.picked() } }
    FileDialog { id: projDlg; title: "Import a Form Studio project"; nameFilters: ["Form Studio projects (*.formstudio *.formproj *.zip)"]; onAccepted: Store.importFile(selectedFile) }
    FileDialog { id: convDlg; title: "Import a conversation"; nameFilters: ["Form Studio conversations (*.json)"]; onAccepted: Store.importFile(selectedFile) }
    FileDialog { id: refDlg; title: "Attach a reference part"; nameFilters: ["STEP or STL (*.step *.stp *.stl)"]; fileMode: FileDialog.OpenFiles
        onAccepted: { var r = ns.refs.slice(), f = selectedFiles && selectedFiles.length ? selectedFiles : [selectedFile]
                      for (var i = 0; i < f.length; i++) if (String(f[i])) r.push(f[i]); ns.refs = r } }
    FileDialog { id: recipeDlg; title: "Install a recipe from a file"; nameFilters: ["Recipes (*.py *.scad)"]
        onAccepted: {
            var nm = decodeURIComponent(String(selectedFile).replace(/^.*[\/\\]/, ""))
            Store.upload("/recipes/inspect?name=" + encodeURIComponent(nm), selectedFile).then(function (r) { Store.openSheet("recipe", { mode: "file", info: r }) }, Store.fail)
        } }
}
