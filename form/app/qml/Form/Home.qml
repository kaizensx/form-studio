import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Home: where a design starts, and where the work you already did waits.
//   · the hero: the bench itself (a live build plate with your last design turning on it) and one composer that takes
//     words, a photo, a sketch, a part or a drawing, or a link. For my printer / Just a 3D model, or Start blank.
//   · concepts the agent proposed and you have not picked yet
//   · your designs as live parts on their plates, one card per design family (a design with its copies, variants and
//     picked concepts: they share lineage.root); a family opens under its row. Then your recent conversations.
// Nothing pre-made: no recipes, no briefs, no example projects. Every design starts from what the person describes.
Item {
    id: home
    objectName: "homeView"
    clip: true
    property string filter: "all"             // all | released | open
    property string order: "recent"           // recent | name
    property string renaming: ""
    property string renameDraft: ""      // what has been typed so far: kept here so a list refresh that rebuilds the card does not wipe it
    property string confirming: ""
    property var menuFor: null
    property bool dropping: false
    // concept drafts wait in their group until one is picked; they are not designs of their own yet
    readonly property var everything: Store.studio ? Store.studio.projects.filter(function (p) { return !p.error && !(p.concept && home.openGroup(p.concept.group)) }) : []
    readonly property var broken: Store.studio ? Store.studio.projects.filter(function (p) { return !!p.error }) : []
    readonly property bool fresh: everything.length === 0 && Store.concepts.length === 0
    // One card per family. A family is every design that shares an origin (Store.rootOf: lineage.root, or itself);
    // its face is the member changed last, which is the one you would go on with. Filter and sort act on the family:
    // it is shown when any member matches, and sorted by its face.
    property string openFamily: ""            // the root id of the family opened under its row
    readonly property var families: {
        var by = {}, order = []
        for (var i = 0; i < everything.length; i++) {
            var q = everything[i], r = Store.rootOf(q.id)
            if (!by[r]) { by[r] = { root: r, members: [] }; order.push(r) }
            by[r].members.push(q)
        }
        var out = order.map(function (r) {
            var m = by[r].members.slice().sort(function (a, b) { return b.updated - a.updated })
            return { root: r, face: m[0], members: m, count: m.length,
                     shown: m.some(function (q) { return home.filter === "all" || (home.filter === "released") === (q.approved_rev === q.head) }) }
        }).filter(function (f) { return f.shown })
        return out.sort(function (a, b) { return home.order === "name" ? String(a.face.name).localeCompare(String(b.face.name)) : b.face.updated - a.face.updated })
    }
    readonly property int grouped: everything.length - families.length          // designs tucked into a family
    function menuOpenFor(q) { return pm.opened && !!home.menuFor && home.menuFor.id === q.id }
    readonly property var latest: everything.length ? everything.slice().sort(function (a, b) { return b.updated - a.updated })[0] : null
    readonly property int released: everything.filter(function (p) { return p.approved_rev === p.head }).length
    // one card per conversation thread (its newest branch): a fork is not a second conversation
    readonly property var talks: { var seen = {}; return Store.convs.filter(function (c) {
        var t = c.thread || c.id; if (c.messages <= 0 || seen[t]) return false; seen[t] = true; return true }).slice(0, home.width > 1500 ? 4 : 3) }
    readonly property real cw: Math.min(width - (width < 1000 ? 48 : 96), 1200)          // content width
    readonly property real heroH: fresh ? height : chatting ? Math.max(500, Math.min(620, height * 0.7)) : Math.max(440, Math.min(540, height * 0.6))
    // a conversation is open in the column on the left: that is where you type, so the middle does not offer a second box
    readonly property bool chatting: Store.talkOpen && (Store.chatItems.length > 0 || Store.chatBusy)
    // the composer always sits in the middle; the bench behind it stays empty (the part you made last is in the list below)
    readonly property bool split: false
    readonly property real side: Math.round((width - cw) / 2)
    function openGroup(gid) { for (var i = 0; i < Store.concepts.length; i++) if (Store.concepts[i].id === gid) return true; return false }
    // newest Blender render of each project's current geometry (form/photo.py)
    property var photos: ({})
    function loadPhotos() { Store.get("/photos").then(function (r) { home.photos = r.latest }, function () {}) }
    Component.onCompleted: { loadPhotos(); Store.loadStart(); Store.loadConcepts(); Store.loadConvs() }
    // Everything rises in once, when Home appears. Sorting, filtering or a reload afterwards puts things in place at once.
    property bool entered: false
    Timer { interval: 40 + 9 * Theme.stagger + Theme.slow; running: true; onTriggered: home.entered = true }
    Connections { target: Store; function onStudioChanged() { home.loadPhotos() }
        function onSheetChanged() { if (!Store.sheet) Store.loadStart() }                 // a printer chosen in its sheet shows here
        function onModelPickWanted() { if (Store.screen === "home" && !Store.talkOpen) Qt.callLater(function () { if (!homeModelPop.opened) homeModelPop.open() }) } }
    function recipeTitle(id) {
        if (!Store.studio) return ""
        if (String(id).indexOf("src:") === 0 || String(id).indexOf("scad:") === 0) return "Designed as code"
        for (var i = 0; i < Store.studio.recipes.length; i++) if (Store.studio.recipes[i].id === id) return Store.studio.recipes[i].title
        var t = Store.studio.recipe_titles
        return t && t[id] ? t[id] : id
    }
    function greeting() {
        var h = new Date().getHours()
        return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
    }
    function exportProject(p) { saveDlg.pid = p.id; saveDlg.currentFile = Bridge.downloads() + "/" + p.id + ".formstudio"; Store.ask(saveDlg) }
    function menu(p) {
        return [
            { icon: "arrow_up_right", text: "Open", run: function () { Store.open(p.id) } },
            { sep: true },
            { icon: "pencil", text: "Rename", run: function () { home.confirming = ""; home.renameDraft = p.name; home.renaming = p.id } },
            { icon: "copy_plus", text: "Duplicate", run: function () { Store.duplicateProject(p.id) } },
            { icon: "archive", text: "Export…", run: function () { home.exportProject(p) } },
            { sep: true },
            { icon: "trash_2", text: "Move to trash…", danger: true, run: function () { home.renaming = ""; home.confirming = p.id } }
        ]
    }
    FileDialog { id: saveDlg; property string pid: ""; title: "Export the design"; fileMode: FileDialog.SaveFile; nameFilters: ["Form Studio projects (*.formstudio)"]
        onAccepted: { if (Bridge.save("/archive/" + pid + ".formstudio", selectedFile)) Store.toast("Exported", "The design, its history, its conversations and its code are in one file. Outputs are rebuilt where it is opened.")
                      else Store.toast("Could not write that file", "Choose another place.", true) } }
    PopMenu { id: pm; model: home.menuFor ? home.menu(home.menuFor) : [] }
    // a concept group: open it, or close it without a pick
    property var groupFor: null
    function groupMenu(g) {
        return [
            { icon: "arrow_up_right", text: "Open the concepts", run: function () { Store.openSheet("concepts", { group: g.id }) } },
            { sep: true },
            { icon: "copy_plus", text: "Keep all as designs", run: function () { Store.dismissConcepts(g.id, "all") } },
            { icon: "trash_2", text: "Discard all", danger: true, run: function () { Store.dismissConcepts(g.id, "none") } }
        ]
    }
    PopMenu { id: gpm; objectName: "conceptGroupMenu"; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside; model: home.groupFor ? home.groupMenu(home.groupFor) : [] }
    // the menu stays on Home itself: the group cards are re-made whenever the groups reload, and must not take it along
    function openGroupMenu(g, item, x, y) { groupFor = g; gpm.openAt(item, Math.max(0, Math.min(x, item.width - gpm.width)), y) }
    function openMenu(p, item, x, y) { menuFor = p; pm.parent = item; pm.openAt(item, x, y) }

    // ════ the bench: a live build plate behind the hero, your last design turning slowly on it ════
    Item {
        id: bench
        width: parent.width; height: home.heroH + 40
        y: -flick.contentY * 0.35                            // it scrolls away slower than the page: depth
        opacity: 0; Component.onCompleted: benchIn.start()
        NumberAnimation { id: benchIn; target: bench; property: "opacity"; to: 1; duration: 900; easing.type: Easing.OutCubic }
        Item {
            id: frame3d
            // split: its own frame right of the words, so the camera frames the part there without any offset
            // (the camera is drawn for frames wider than tall, so the frame reaches back under the words, which hide it)
            readonly property real edge: home.side + hero.colW - 40
            x: home.split ? Math.max(0, parent.width - Math.max(parent.width - edge, parent.height * 1.25)) : 0
            width: parent.width - x
            height: parent.height
        Viewport {
            id: stage; objectName: "homeStage"
            anchors.fill: parent
            insetLeft: home.split ? frame3d.edge - frame3d.x : 0
            lite: true; interactive: false; showDims: false; showCompanions: false
            // the part turns slowly to and fro around the bench's three-quarter view, like a piece being looked over
            SequentialAnimation on az { running: home.split && !!stage.model && !Theme.reduced && home.visible; loops: Animation.Infinite
                NumberAnimation { from: -34; to: -8; duration: 7000; easing.type: Easing.InOutSine }
                NumberAnimation { from: -8; to: -60; duration: 14000; easing.type: Easing.InOutSine }
                NumberAnimation { from: -60; to: -34; duration: 7000; easing.type: Easing.InOutSine } }
            plateSize: 260
            property string showing: ""
            function load() {
                var id = home.latest && home.split ? home.latest.id : ""      // narrow: the bench alone; a part would sit behind the words
                if (id === showing) return
                showing = id
                if (!id) { setModel(null); return }
                Store.get("/projects/" + id + "/view").then(function (v) {
                    if (stage.showing !== id) return
                    v.companions = []
                    stage.setModel(v); stage.setView("iso", false); stage.dist *= 1.1
                }, function () {})
            }
            Component.onCompleted: load()
            Connections { target: home; function onLatestChanged() { stage.load() } function onSplitChanged() { stage.load() } }
        }
        }
        // the light falls off towards the edges and under the composer, so the part reads as an object on the bench
        // behind the page rather than a picture in it
        Rectangle { anchors.fill: parent; visible: !home.split
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.alpha(Theme.plate, 0.92) }
                GradientStop { position: 0.28; color: Theme.alpha(Theme.plate, 0.35) }
                GradientStop { position: 0.72; color: Theme.alpha(Theme.plate, 0.35) }
                GradientStop { position: 1.0; color: Theme.alpha(Theme.plate, 0.92) } } }
        // split: the words sit on a quiet bench; the bench brightens towards the part
        Rectangle { visible: home.split; width: frame3d.edge; height: parent.height; color: Theme.plate }
        Rectangle { visible: home.split; x: frame3d.edge - 1; width: 300; height: parent.height
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.plate }
                GradientStop { position: 0.45; color: Theme.alpha(Theme.plate, 0.7) }
                GradientStop { position: 1.0; color: Theme.alpha(Theme.plate, 0.0) } } }
        Rectangle { visible: home.split; x: parent.width - 220; width: 220; height: parent.height
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.alpha(Theme.plate, 0.0) } GradientStop { position: 1.0; color: Theme.alpha(Theme.plate, 0.8) } } }
        Rectangle { anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Theme.alpha(Theme.plate, 0.85) }
                GradientStop { position: 0.32; color: Theme.alpha(Theme.plate, 0.25) }
                GradientStop { position: 0.62; color: Theme.alpha(Theme.plate, 0.55) }
                GradientStop { position: 1.0; color: Theme.plate } } }
        // a scan line crossing the plate now and then: the bench is on
        Rectangle { id: scanLine; width: parent.width; height: 120; opacity: 0.0
            gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0) } GradientStop { position: 0.5; color: Theme.alpha(Theme.datum, 0.035) } GradientStop { position: 1; color: Theme.alpha(Theme.datum, 0) } }
            SequentialAnimation { running: !Theme.reduced && home.visible; loops: Animation.Infinite
                PauseAnimation { duration: 2400 }
                ParallelAnimation {
                    NumberAnimation { target: scanLine; property: "y"; from: bench.height * 0.25; to: bench.height * 0.95; duration: 5200; easing.type: Easing.InOutSine }
                    SequentialAnimation { NumberAnimation { target: scanLine; property: "opacity"; to: 1; duration: 1200 } PauseAnimation { duration: 2800 } NumberAnimation { target: scanLine; property: "opacity"; to: 0; duration: 1200 } } }
                PauseAnimation { duration: 6000 } } }
    }

    Flickable {
        id: flick
        anchors.fill: parent; contentHeight: col.implicitHeight + 72; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col; x: Math.round((parent.width - width) / 2); width: home.cw; spacing: 0

            // ════ hero ════
            Item {
                id: hero; width: parent.width; height: home.heroH
                readonly property real colW: home.split ? Math.min(Math.round(parent.width * 0.6), 720) : Math.min(parent.width, 820)
                Column {
                    id: heroCol
                    width: hero.colW; x: home.split ? 0 : Math.round((parent.width - width) / 2)
                    y: home.fresh ? Math.max(40, Math.round((hero.height - height) * 0.42)) : Math.max(36, Math.round((hero.height - height) * 0.5) - 8)
                    spacing: 0
                    opacity: 0; Component.onCompleted: heroIn.start()
                    ParallelAnimation { id: heroIn
                        Glide { target: heroCol; property: "opacity"; to: 1; duration: 520 }
                        Glide { target: heroTr; property: "y"; from: Theme.shift(14); to: 0; duration: 620 } }
                    transform: Translate { id: heroTr }
                    Txt { kind: "cap"; color: Theme.datum; x: home.split ? 2 : (parent.width - width) / 2; font.letterSpacing: 1.6
                        text: home.fresh ? "Form Studio" : home.greeting() }
                    Item { width: 1; height: 14 }
                    Txt { objectName: "homeTitle"; width: parent.width; horizontalAlignment: home.split ? Text.AlignLeft : Text.AlignHCenter
                        font.pixelSize: home.cw > 900 ? Theme.tDisplay : 42; font.weight: Theme.wSemi; font.letterSpacing: home.cw > 900 ? -2.0 : -1.5; lineHeight: 1.0
                        text: "What do you want to make?" }
                    // the sentence under the question is for a first visit, or says where the conversation went; once there
                    // are designs the composer's own words are enough
                    Item { visible: lead.visible; width: 1; height: 14 }
                    Txt { id: lead; visible: home.fresh || home.chatting
                        width: Math.min(parent.width, 600); x: home.split ? 0 : (parent.width - width) / 2; horizontalAlignment: home.split ? Text.AlignLeft : Text.AlignHCenter
                        tone: 2; font.pixelSize: Theme.tLead; lineHeight: 1.4
                        text: home.chatting ? "You are talking with " + Store.chatAgentLabel + " in the column on the left. Open one of your designs to work on it together, or start a new design."
                            : Store.printOn && Store.newPurposeEffective === "print" ? "Describe it. Form Studio engineers it: real, editable CAD, checked and sliced for your printer. Drop a photo, a part or a sketch too."
                                                         : "Describe it. Form Studio engineers it: real, editable CAD you can check, render and export. Drop a photo, a part or a sketch too." }
                    Item { width: 1; height: 30 }
                    Row { objectName: "homeChatting"; visible: home.chatting; spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
                        Btn { objectName: "homeNewDesign"; kind: "primary"; icon: "plus"; text: "New design"; keys: "Ctrl+N"; onClicked: Store.startNew() }
                        Btn { kind: "quiet"; icon: "panel_left_close"; text: "Hide the conversation"; onClicked: Store.talkOpen = false } }
                    StartComposer { id: composer; visible: !home.chatting
                        Component.onDestruction: if (Store.screen === "designing" || Store.screen === "work") {
                            var p = composer.mapToItem(null, 0, 0); Store.morphFrom(Qt.rect(p.x, p.y, composer.width, composer.height)) }
                         width: parent.width; dragging: home.dropping; onSketchWanted: Store.openSheet("sketch") }
                    Item { visible: !home.chatting; width: 1; height: 16 }
                    // ── under the composer: what it is for, which printer, which agent and model, or a blank canvas ──
                    Row { id: opts; objectName: "startOptions"; visible: !home.chatting; anchors.horizontalCenter: parent.horizontalCenter; spacing: 6; height: 30
                        Seg { id: purposeSeg; objectName: "startPurpose"; visible: Store.printOn; anchors.verticalCenter: parent.verticalCenter; implicitHeight: 30
                            value: Store.newPurposeEffective; onPicked: function (v) { Store.setNewPurpose(v) }
                            model: [{ value: "print", text: "For my printer", tip: Store.printerName ? "Checked and sliced for " + Store.printerName : "Checked for printing; slicing starts once a printer is set up" },
                                    { value: "model", text: "Just a 3D model", tip: "No printer: no slicing and no print checks. STEP and STL are still exported." }] }
                        Btn { id: printerChip; anchors.verticalCenter: parent.verticalCenter; objectName: "startPrinter"; small: true; kind: "quiet"; icon: "printer"; visible: Store.printOn && Store.newPurposeEffective === "print"
                            text: Store.printerName ? Store.printerName : "Choose a printer"
                            tip: "The printer the next design is checked and sliced for. Click to change it."
                            onClicked: Store.openSheet("printer") }
                        Btn { id: modelChip; anchors.verticalCenter: parent.verticalCenter; objectName: "startModel"; small: true; kind: "quiet"; icon: "sparkles"; active: homeModelPop.opened
                            text: Store.chatReady ? Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) : "Connect an agent"
                            tip: Store.chatReady ? "The agent and model that design it. Click to change them." : "No agent is connected: add one in Settings › Agents"
                            onClicked: Store.chatReady ? (homeModelPop.opened ? homeModelPop.close() : homeModelPop.open()) : Store.openSettings("agents")
                            Pop {
                                id: homeModelPop; y: parent.height + 6; x: Math.round((parent.width - width) / 2); width: 380; padding: 6; origin: Popup.TopLeft
                                height: Math.min(hmp.implicitHeight + 12, home.height * 0.6)
                                onAboutToShow: hmp.reset()
                                onOpened: hmp.opened()
                                onClosed: Qt.callLater(function () {
                                    Store.retryAfterPick = false
                                    if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
                                Flickable { anchors.fill: parent; clip: true; contentHeight: hmp.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar { width: 6 }
                                    TalkModelPicker { id: hmp; width: parent.width; onDone: homeModelPop.close() } } } }
                        Item { width: 9; height: 30; anchors.verticalCenter: parent.verticalCenter; Rectangle { width: 1; height: 16; color: Theme.rule2; anchors.centerIn: parent } }
                        Btn { id: blank; anchors.verticalCenter: parent.verticalCenter; objectName: "startBlank"; small: true; kind: "quiet"; icon: "square_dashed"; text: "Start blank"
                            tip: "An empty build plate and the workspace. Describe, sketch or import what goes on it."
                            onClicked: Store.startBlank() }
                        Btn { anchors.verticalCenter: parent.verticalCenter; objectName: "startReplace"; small: true; kind: "quiet"; icon: "wrench"; text: "Replace a broken part"
                            tip: "From a photo: the agent estimates sizes, asks you for the ones that matter, then designs the new part."
                            onClicked: Store.openSheet("replace") } }
                    // the design you were on, one click away
                    Item { visible: !home.chatting && !home.fresh && !!home.latest; width: 1; height: 14 }
                    Txt { objectName: "homeContinue"; visible: !home.chatting && !home.fresh && !!home.latest; anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; tone: cm.containsMouse ? 1 : 3
                        text: home.latest ? "Continue “" + home.latest.name + "” · " + F.pad(home.latest.head) + " · " + F.ago(home.latest.updated) + "  →" : ""
                        MouseArea { id: cm; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.open(home.latest.id) } }
                    Item { visible: home.fresh && !home.chatting; width: 1; height: 40 }
                    Grid { id: ways; visible: home.fresh && !home.chatting; width: parent.width; columns: 4; spacing: 10
                        readonly property real tw: Math.floor((width - 3 * spacing) / 4)
                        Repeater {
                            model: [{ icon: "camera", t: "A photo", d: "With a card, coin or ruler in it, the agent can estimate sizes", run: function () { composer.pickFiles() } },
                                    { icon: "pen_tool", t: "A sketch", d: "Lines, arcs and the dimensions that matter", run: function () { Store.openSheet("sketch") } },
                                    { icon: "cuboid", t: "A part", d: "STEP, STL or 3MF to design around or change", run: function () { composer.pickFiles() } },
                                    { icon: "link", t: "A link", d: "A model page or a direct file link", run: function () { composer.openLink() } }]
                            Rectangle { id: way; required property var modelData; required property int index
                                width: ways.tw; height: 104; radius: Theme.rLg
                                color: wm.pressed ? Theme.plate1 : wm.containsMouse ? Theme.alpha(Theme.plate2, 0.9) : Theme.alpha(Theme.plate1, 0.55)
                                border.color: wm.containsMouse ? Theme.rule3 : Theme.rule
                                Behavior on color { Tint {} }
                                opacity: 0; Component.onCompleted: wIn.start()
                                SequentialAnimation { id: wIn; PauseAnimation { duration: 380 + way.index * 70 }
                                    ParallelAnimation { Glide { target: way; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: wtr; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } } }
                                transform: Translate { id: wtr }
                                Icon { x: 14; y: 14; name: way.modelData.icon; size: 16; color: wm.containsMouse ? Theme.datum : Theme.ink3; Behavior on color { Tint {} } }
                                Column { x: 14; y: 40; width: parent.width - 28; spacing: 2
                                    Txt { text: way.modelData.t; font.weight: Theme.wMedium }
                                    Txt { kind: "fine"; tone: 3; width: parent.width; text: way.modelData.d; maximumLineCount: 2; elide: Text.ElideRight } }
                                MouseArea { id: wm; anchors.fill: parent; hoverEnabled: true; onClicked: way.modelData.run() } } } }
                    Note { visible: !!Store.fatal; width: parent.width; kind: "red"; title: Store.fatal ? Store.fatal.message : ""; text: Store.fatal ? (Store.fatal.hint || "") : "" }
                }
                // the empty bench says where the work will appear, once
                Txt { visible: home.fresh; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 26
                    kind: "fine"; tone: 4
                    text: Store.printOn ? "Every design is built in a real CAD kernel and checked before you print it. Nothing prints or uploads on its own."
                                        : "Every design is built in a real CAD kernel and checked. Nothing uploads on its own." }
                Btn { visible: home.fresh; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.bottomMargin: 18; kind: "quiet"; small: true; icon: "import"; text: "Import…"
                    tip: "A .formstudio project or a conversation"; onClicked: Store.openSheet("import") }
            }

            Note { visible: home.broken.length > 0; width: parent.width; kind: "amber"; title: F.plural(home.broken.length, "folder") + " could not be read"
                text: home.broken.map(function (p) { return p.id }).join(", ") + ". Nothing was changed; open the projects folder to look." }

            // ════ concepts waiting for a pick ════
            Repeater {
                model: Store.concepts
                Item { id: cg; required property var modelData; required property int index; width: col.width; height: cgc.height + 18
                    Rectangle {
                        id: cgc; objectName: "conceptGroup"; width: parent.width; height: 132; radius: Theme.rLg + 2
                        color: cgm.containsMouse ? Theme.plate2 : Theme.plate1; border.color: cgm.containsMouse ? Theme.alpha(Theme.datum, 0.5) : Theme.alpha(Theme.datum, 0.28)
                        Behavior on color { Tint {} }
                        Behavior on border.color { Tint {} }
                        Column { x: 22; anchors.verticalCenter: parent.verticalCenter; width: parent.width - thumbs.width - 60; spacing: 6
                            Row { spacing: 8
                                Rectangle { width: 7; height: 7; radius: 3.5; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                                    SequentialAnimation on opacity { loops: Animation.Infinite; running: !Theme.reduced; NumberAnimation { to: 0.35; duration: 900 } NumberAnimation { to: 1; duration: 900 } } }
                                Txt { kind: "cap"; color: Theme.datum; text: F.plural(cg.modelData.members.length, "concept") + " · waiting for your pick" } }
                            Txt { kind: "h3"; text: cg.modelData.name; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Txt { kind: "fine"; tone: 2; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                text: cg.modelData.members.map(function (m) { return m.letter + "  " + m.title }).join("    ") } }
                        Row { id: thumbs; anchors.right: parent.right; anchors.rightMargin: 48; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            Repeater { model: cg.modelData.members.slice(0, home.cw > 900 ? 4 : 2)
                                Rectangle { required property var modelData; width: 120; height: 104; radius: Theme.rMd + 2; color: Theme.plate; border.color: Theme.rule; clip: true
                                    MiniView { anchors.fill: parent; anchors.margins: 1; projectId: parent.modelData.project; turning: cgm.containsMouse }
                                    Txt { x: 8; y: 6; text: parent.modelData.letter; font.weight: Theme.wBold; color: Theme.datum; font.pixelSize: 12 } } } }
                        MouseArea { id: cgm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function (e) {
                                if (e.button === Qt.RightButton) home.openGroupMenu(cg.modelData, cgc, e.x, e.y)
                                else Store.openSheet("concepts", { group: cg.modelData.id }) } }
                        // close it without a pick; the menu says what happens to the concepts
                        Btn { objectName: "conceptGroupClose"; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6; small: true; kind: "quiet"
                            icon: "x"; tip: "Close without picking"; opacity: cgm.containsMouse || hovered || gpm.opened ? 1 : 0.55
                            onClicked: home.openGroupMenu(cg.modelData, cgc, cgc.width - 6, 34) }
                    }
                }
            }

            // ════ the designs ════
            Item { visible: home.everything.length > 0; width: 1; height: 8 }
            Item { width: parent.width; height: 34; visible: home.everything.length > 0
                Row { spacing: 12; anchors.verticalCenter: parent.verticalCenter
                    Txt { kind: "h3"; text: "Designs" }
                    Txt { mono: true; tone: 3; font.pixelSize: 12; text: home.everything.length + (home.grouped > 0 ? "  ·  " + home.families.length + (home.families.length === 1 ? " family" : " families") : "") + (home.released ? "  ·  " + home.released + " released" : ""); anchors.baseline: parent.children[0].baseline } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Seg { visible: home.everything.length > 6; anchors.verticalCenter: parent.verticalCenter; value: home.filter; onPicked: function (v) { home.filter = v }
                        model: [{ value: "all", text: "All" }, { value: "open", text: "In progress" }, { value: "released", text: "Released" }] }
                    Btn { visible: home.everything.length > 6; kind: "quiet"; icon: "arrow_up_down"; text: home.order === "recent" ? "Last changed" : "Name"; tip: "Sort order"
                        onClicked: home.order = home.order === "recent" ? "name" : "recent" }
                    Btn { kind: "quiet"; icon: "import"; text: "Import…"; tip: "A .formstudio project, a .formproj, or a conversation"; onClicked: Store.openSheet("import") }
                    Btn { kind: "quiet"; icon: "folder_open"; tip: "Open the projects folder: " + Bridge.dataDirShort; onClicked: Bridge.openDataFolder() } } }
            Item { visible: home.everything.length > 0; width: 1; height: 14 }
            // rows of families; the family opened by its count sits under its own row, across the full width
            Column {
                id: grid; objectName: "designGrid"; width: parent.width; visible: home.everything.length > 0; spacing: 16
                readonly property int columns: Math.max(2, Math.floor((width + 16) / 280))
                readonly property real cw: Math.floor((width - (columns - 1) * 16) / columns)
                readonly property var rows: { var out = [], f = home.families; for (var i = 0; i < f.length; i += columns) out.push(f.slice(i, i + columns)); return out }
                Repeater {
                    model: grid.rows
                    Column {
                        id: band; required property var modelData; required property int index
                        width: grid.width; spacing: 16
                        readonly property var open: { for (var i = 0; i < modelData.length; i++) if (modelData[i].root === home.openFamily && modelData[i].count > 1) return modelData[i]; return null }
                        readonly property int openAt: { for (var i = 0; i < modelData.length; i++) if (modelData[i].root === home.openFamily) return i; return 0 }
                        Row { spacing: 16
                            Repeater { model: band.modelData
                                DesignCard { required property var modelData; required property int index
                                    width: grid.cw; host: home; p: modelData.face; count: modelData.count; photo: home.photos[modelData.face.id] || null
                                    index: band.index * grid.columns + index
                                    opened: home.openFamily === modelData.root && modelData.count > 1
                                    onToggled: home.openFamily = opened ? "" : modelData.root } } }
                        // the opened family: every design that shares the origin, the first one first
                        Rectangle {
                            id: fam; objectName: "familyPanel"; visible: !!band.open; width: parent.width
                            height: visible ? famCol.implicitHeight + 36 : 0; radius: Theme.rLg + 2
                            color: Theme.plate1; border.color: Theme.rule
                            readonly property var members: band.open ? band.open.members.slice().sort(function (a, b) {
                                var ar = !a.lineage || !a.lineage.parent, br = !b.lineage || !b.lineage.parent
                                return ar !== br ? (ar ? -1 : 1) : b.updated - a.updated }) : []
                            readonly property int per: Math.max(3, Math.floor((width - 36 + 12) / 232))
                            readonly property real mw: Math.floor((width - 36 - (per - 1) * 12) / per)
                            opacity: 0; onVisibleChanged: if (visible) { opacity = 0; famIn.restart() }
                            ParallelAnimation { id: famIn
                                Glide { target: fam; property: "opacity"; to: 1; duration: Theme.base }
                                Glide { target: famTr; property: "y"; from: Theme.shift(-6); to: 0; duration: Theme.base } }
                            transform: Translate { id: famTr }
                            // a notch points at the card it belongs to
                            Rectangle { width: 12; height: 12; rotation: 45; y: -6; x: Math.round(band.openAt * (grid.cw + 16) + 16); color: Theme.plate1; border.color: Theme.rule }
                            Rectangle { y: 1; x: Math.round(band.openAt * (grid.cw + 16) + 11); width: 22; height: 9; color: Theme.plate1 }
                            Column { id: famCol; x: 18; y: 16; width: parent.width - 36; spacing: 14
                                Item { width: parent.width; height: 22
                                    Row { spacing: 10; anchors.verticalCenter: parent.verticalCenter
                                        Txt { kind: "cap"; text: "Design family"; anchors.verticalCenter: parent.verticalCenter }
                                        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                                            text: F.plural(fam.members.length, "design") + " from one origin: the first design, then its copies, variants and picked concepts" } }
                                    Btn { objectName: "familyClose"; small: true; kind: "quiet"; icon: "x"; tip: "Close the family"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                        onClicked: home.openFamily = "" } }
                                Flow { width: parent.width; spacing: 12
                                    Repeater { model: fam.members
                                        DesignCard { required property var modelData; required property int index
                                            objectName: "familyMember"; width: fam.mw; host: home; p: modelData; member: true; photo: home.photos[modelData.id] || null } } } }
                        }
                    }
                }
            }
            Txt { visible: home.everything.length > 0 && home.families.length === 0; tone: 3; text: home.filter === "released" ? "Nothing is released yet. A design is released from Make, its last stage." : "Every design here is released." }

            // ════ recent conversations ════
            Item { visible: home.talks.length > 0; width: 1; height: home.everything.length > 0 ? Theme.s12 : 8 }
            Item { visible: home.talks.length > 0; width: parent.width; height: 30
                Txt { kind: "h3"; text: "Conversations"; anchors.verticalCenter: parent.verticalCenter }
                Btn { small: true; kind: "quiet"; icon: "history"; text: "All"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    onClicked: { Store.talkOpen = true; if (home.talks.length) Store.openConv(home.talks[0].id) } } }
            Item { visible: home.talks.length > 0; width: 1; height: 12 }
            Row {
                visible: home.talks.length > 0; width: parent.width; spacing: 12
                readonly property real tw: Math.floor((width - (home.talks.length - 1) * spacing) / Math.max(1, home.talks.length))
                Repeater { model: home.talks
                    Rectangle { id: tc; objectName: "homeConversation"; required property var modelData; required property int index
                        width: parent.tw; height: 84; radius: Theme.rLg
                        color: tcm.pressed ? Theme.plate1 : tcm.containsMouse ? Theme.plate2 : Theme.alpha(Theme.plate1, 0.7)
                        border.color: tcm.containsMouse ? Theme.rule3 : Theme.rule
                        Behavior on color { Tint {} }
                        opacity: 0; Component.onCompleted: { if (home.entered) opacity = 1; else tcIn.start() }
                        SequentialAnimation { id: tcIn; PauseAnimation { duration: 200 + tc.index * Theme.stagger } Glide { target: tc; property: "opacity"; to: 1; duration: Theme.slow } }
                        Column { x: 16; y: 14; width: parent.width - 32; spacing: 5
                            Row { spacing: 7; width: parent.width
                                Rectangle { width: 6; height: 6; radius: 3; anchors.verticalCenter: parent.verticalCenter
                                    color: tc.modelData.state === "running" ? Theme.datum : tc.modelData.state === "asking" ? Theme.amber : Theme.ink4 }
                                Txt { kind: "fine"; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: parent.width - 14
                                    text: (tc.modelData.state === "asking" ? "Waiting for you · " : tc.modelData.state === "running" ? "Working · " : "") + F.ago(tc.modelData.updated) } }
                            Txt { text: tc.modelData.title; font.weight: Theme.wMedium; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight; lineHeight: 1.3 } }
                        MouseArea { id: tcm; anchors.fill: parent; hoverEnabled: true; onClicked: { Store.talkOpen = true; Store.openConv(tc.modelData.id) } } } } }
        }
    }

    // ── drop anything, anywhere on Home: photos, parts, drawings; a dropped link is a link ──
    DropArea {
        id: drop; anchors.fill: parent; z: 5
        onEntered: function (d) { d.accepted = d.hasUrls || d.hasText; home.dropping = d.accepted }
        onExited: home.dropping = false
        onDropped: function (d) {
            home.dropping = false
            var files = [], links = []
            for (var i = 0; i < (d.urls || []).length; i++) { var u = String(d.urls[i]); if (/^file:/i.test(u)) files.push(d.urls[i]); else if (/^https?:/i.test(u)) links.push(u) }
            if (!files.length && !links.length && d.hasText && /^https?:\/\/\S+$/i.test(String(d.text).trim())) links.push(String(d.text).trim())
            if (files.length) Store.attachFiles(files)
            links.forEach(function (l) { Store.fetchLink(l) })
            d.accepted = files.length + links.length > 0
            composer.area.forceActiveFocus()
        }
        Rectangle { anchors.fill: parent; color: Theme.alpha(Theme.datum, 0.03); opacity: home.dropping ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } }
            border.width: 1; border.color: Theme.alpha(Theme.datum, 0.35)
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 22; width: dropTx.implicitWidth + 40; height: 36; radius: 18; color: Theme.plate3; border.color: Theme.alpha(Theme.datum, 0.5)
                Row { id: dropTx; anchors.centerIn: parent; spacing: 8
                    Icon { name: "import"; size: 14; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: "Drop to start from it · photos, STEP, STL, 3MF, PDF drawings, links"; font.weight: Theme.wMedium; anchors.verticalCenter: parent.verticalCenter } } } }
    }
}
