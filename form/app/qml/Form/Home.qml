import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Shapes
import FormNative
import "F.js" as F

// Home: where a design starts, and where the work you already did waits. Lightdesk: Home stands in the window's room
// (Main.qml draws it), so nothing here paints a ground of its own.
//   · the question, and one pane of glass that takes words, a photo, a sketch, a part or a drawing, or a link, with
//     the numbered ways to start under it. Make it for: Anything / My printer (only when 3D printing is on) / Game asset.
//   · concepts the agent proposed and you have not picked yet
//   · the shelf: your designs as live parts, each standing in its own pool of light, one per design family (a design
//     with its copies, variants and picked concepts: they share lineage.root); a family opens under its row. The first
//     row shows what fits and "All N designs" shows the rest. Then your recent conversations.
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
    readonly property real heroH: hero.height
    property bool showAll: false              // the shelf shows every row (off: the first row, and "All N designs")
    // a conversation is open in the column on the left: that is where you type, so the middle does not offer a second box
    readonly property bool chatting: Store.talkOpen && (Store.chatItems.length > 0 || Store.chatBusy)
    // the composer always sits in the middle; the bench behind it stays empty (the part you made last is in the list below)
    // … except on the first day, when there is nothing below yet: then the words sit on the left and a real build turns
    // beside them (Bridge.showpiece: kernel geometry kept as a file, not a project), so Home shows what gets made here.
    readonly property bool split: fresh && !chatting && width >= 1180 && !!showpiece
    property var showpiece: null
    function loadShowpiece() { if (showpiece) return; try { var t = Bridge.showpiece(); if (t) showpiece = JSON.parse(t) } catch (e) { showpiece = null } }
    onFreshChanged: if (fresh) loadShowpiece()
    readonly property real side: Math.round((width - cw) / 2)
    function openGroup(gid) { for (var i = 0; i < Store.concepts.length; i++) if (Store.concepts[i].id === gid) return true; return false }
    // newest Blender render of each project's current geometry (form/photo.py)
    property var photos: ({})
    function loadPhotos() { Store.get("/photos").then(function (r) { home.photos = r.latest }, function () {}) }
    Component.onCompleted: { if (fresh) loadShowpiece(); loadPhotos(); Store.loadStart(); Store.loadConcepts(); Store.loadConvs() }
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

    // ════ the first day: a real build turns beside the words. Its own floor fades into the room all round, so the
    // part reads as an object standing in the room and not as a picture in it. Nothing is drawn here otherwise. ════
    readonly property bool pieceShown: !!benchLd.item && benchLd.item.shown
    Loader {
        id: benchLd; active: home.split
        width: parent.width; height: home.heroH + 40
        y: -flick.contentY * 0.35                            // it scrolls away slower than the page: depth
        sourceComponent: Item {
            id: bench
            readonly property bool shown: !!stage.model
            opacity: 0; Component.onCompleted: benchIn.start()
            NumberAnimation { id: benchIn; target: bench; property: "opacity"; to: 1; duration: 900; easing.type: Easing.OutCubic }
            Item {
                id: frame3d
                // its own frame right of the words, so the camera frames the part there without any offset
                // (the camera is drawn for frames wider than tall, so the frame reaches back under the words)
                readonly property real edge: home.side + hero.colW - 40
                x: Math.max(0, parent.width - Math.max(parent.width - edge, parent.height * 1.25))
                width: parent.width - x
                height: parent.height
                layer.enabled: true
                layer.effect: MultiEffect { maskEnabled: true; maskSource: benchFade; maskThresholdMin: 0.5; maskSpreadAtMin: 1 }
                Viewport {
                    id: stage; objectName: "homeStage"
                    anchors.fill: parent
                    insetLeft: frame3d.edge - frame3d.x
                    lite: true; floorGrid: false; interactive: false; showDims: false; showCompanions: false
                    showOrigin: !!stage.model                // an empty floor under the opening words has no cross through them
                    // the part turns slowly to and fro around the bench's three-quarter view, like a piece being looked over
                    SequentialAnimation on az { running: !!stage.model && !Theme.reduced && home.visible; loops: Animation.Infinite
                        NumberAnimation { from: -34; to: -8; duration: 7000; easing.type: Easing.InOutSine }
                        NumberAnimation { from: -8; to: -60; duration: 14000; easing.type: Easing.InOutSine }
                        NumberAnimation { from: -60; to: -34; duration: 7000; easing.type: Easing.InOutSine } }
                    Component.onCompleted: if (home.showpiece) { stage.setModel(home.showpiece); stage.setView("iso", false); stage.dist *= 1.1 }
                }
            }
            // where the 3D view shows: full around the part, falling away to nothing before the words and the edges
            Item { id: benchFade; x: frame3d.x; width: frame3d.width; height: frame3d.height; visible: false; layer.enabled: true
                Shape { id: bf; anchors.fill: parent
                    readonly property real free: frame3d.edge - frame3d.x
                    ShapePath {
                        strokeWidth: -1
                        fillGradient: RadialGradient {
                            centerX: bf.free + (bf.width - bf.free) / 2; centerY: bf.height * 0.52; focalX: centerX; focalY: centerY
                            centerRadius: Math.max(260, Math.min(bf.width - bf.free, bf.height) * 0.62)
                            GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 1) }
                            GradientStop { position: 0.5; color: Qt.rgba(0, 0, 0, 1) }
                            GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0) } }
                        startX: 0; startY: 0
                        PathLine { x: bf.width; y: 0 } PathLine { x: bf.width; y: bf.height } PathLine { x: 0; y: bf.height } PathLine { x: 0; y: 0 }
                    } } }
        }
    }

    // one block of Home arriving: a fade and a short rise, `beat` steps after the screen. Reduce Motion: the fade.
    component Arrive: SequentialAnimation {
        id: arr
        property Item item: null
        property Translate lift: null
        property int beat: 0
        running: true
        PauseAnimation { duration: 40 + arr.beat * 2 * Theme.stagger }
        ParallelAnimation {
            NumberAnimation { target: arr.item; property: "opacity"; to: 1; duration: Theme.slow; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
            NumberAnimation { target: arr.lift; property: "y"; from: Theme.shift(Theme.rise); to: 0; duration: Theme.move(Theme.slow + 80); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    }

    Flickable {
        id: flick
        anchors.fill: parent; contentHeight: col.implicitHeight + 72; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col; x: Math.round((parent.width - width) / 2); width: home.cw; spacing: 0

            // ════ the question and the bar ════
            Item {
                id: hero; width: parent.width
                height: home.fresh ? home.height : heroCol.y + heroCol.height + Math.round(Math.max(52, Math.min(95, home.height * 0.107)))
                readonly property real colW: home.split ? Math.min(Math.round(parent.width * 0.6), 720) : Math.min(parent.width, 760)
                readonly property bool big: home.width >= 900
                Column {
                    id: heroCol
                    width: hero.colW; x: home.split ? 0 : Math.round((parent.width - width) / 2)
                    y: home.fresh ? Math.max(40, Math.round((hero.height - height) * 0.42)) : Math.round(Math.max(28, Math.min(48, home.height * 0.055)))
                    spacing: 0
                    Column { id: ask; width: parent.width; spacing: 0
                        opacity: 0; transform: Translate { id: askLift }
                        Arrive { item: ask; lift: askLift; beat: 0 }
                        Txt { mono: true; color: Theme.datum; x: home.split ? 2 : Math.round((parent.width - width) / 2); wrapMode: Text.NoWrap
                            font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 2.2; font.capitalization: Font.AllUppercase; lineHeight: 1.0
                            text: home.fresh ? "Form Studio" : home.greeting() }
                        Item { width: 1; height: hero.big ? 8 : 12 }
                        // one line when the window allows it (it may run wider than the bar under it), else it wraps
                        Item { width: parent.width; height: title.height
                            Txt { id: title; objectName: "homeTitle"
                                readonly property bool oneLine: hero.big && !home.split
                                width: oneLine ? implicitWidth : parent.width; x: oneLine ? Math.round((parent.width - width) / 2) : 0
                                wrapMode: oneLine ? Text.NoWrap : Text.WordWrap; horizontalAlignment: home.split ? Text.AlignLeft : Text.AlignHCenter
                                font.pixelSize: hero.big ? Theme.tDisplay : 42; font.weight: Theme.wSemi; font.letterSpacing: hero.big ? -3 : -1.6; lineHeight: 1.0
                                text: "What do you want to make?" } }
                        // the sentence under the question is for a first visit, or says where the conversation went; once there
                        // are designs the composer's own words are enough
                        Item { visible: lead.visible; width: 1; height: 10 }
                        Txt { id: lead; visible: home.fresh || home.chatting
                            width: Math.min(parent.width, 600); x: home.split ? 0 : (parent.width - width) / 2; horizontalAlignment: home.split ? Text.AlignLeft : Text.AlignHCenter
                            tone: 2; font.pixelSize: Theme.tLead; lineHeight: 1.4
                            text: home.chatting ? "You are talking with " + Store.chatAgentLabel + " in the column on the left. Open one of your designs to work on it together, or start a new design."
                                : Store.newPurpose === "game" ? "Describe it. Form Studio models it as real CAD, then makes it a game asset: levels of detail, UVs, baked textures and collision for your engine."
                                : Store.printOn && Store.newPurposeEffective === "print" ? "Describe it. Form Studio engineers it: real, editable CAD, checked and sliced for your printer. Drop a photo, a part or a sketch too."
                                                             : "Describe it. Form Studio engineers it: real, editable CAD you can check, render and export. Drop a photo, a part or a sketch too." }
                        Item { width: 1; height: hero.big ? 24 : 26 }
                    }
                    Row { objectName: "homeChatting"; visible: home.chatting; spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
                        Btn { objectName: "homeNewDesign"; kind: "primary"; icon: "plus"; text: "New design"; keys: "Ctrl+N"; onClicked: Store.startNew() }
                        Btn { kind: "quiet"; icon: "panel_left_close"; text: "Hide the conversation"; onClicked: Store.talkOpen = false } }
                    StartComposer { id: composer; visible: !home.chatting
                        Component.onDestruction: if (Store.screen === "designing") {
                            var p = composer.mapToItem(null, 0, 0); Store.morphFrom(Qt.rect(p.x, p.y, composer.width, composer.height)) }
                        width: parent.width; dragging: home.dropping; onSketchWanted: Store.openSheet("sketch")
                        latest: home.fresh ? null : home.latest          // the design you were on, one key away
                        opacity: 0; transform: Translate { id: barLift }
                        Arrive { item: composer; lift: barLift; beat: 1 } }
                    Item { visible: !home.chatting; width: 1; height: Theme.s4 }
                    // ── under the bar: what it is for and which printer on the left, the agent on the right, both
                    // lined up with the bar's edges. Every item is one height on one centre line, and the
                    // left group is measured with the printer chip whenever printing is on, so picking My printer only
                    // shows the chip in its reserved place: nothing moves, nothing wraps. The row wraps (the agent to a
                    // second line) only when the bar itself is too narrow for both groups.
                    Item { id: opts; objectName: "startOptions"; visible: !home.chatting; width: parent.width
                        readonly property int h: 34
                        readonly property int inset: 10
                        readonly property real leftMax: forLbl.implicitWidth + forRow.spacing + purposeSeg.implicitWidth
                                                        + (Store.printOn ? forRow.spacing + printerChip.implicitWidth : 0)
                        readonly property bool wrap: leftMax + Theme.s4 + modelChip.implicitWidth > width - 2 * inset
                        height: wrap ? 2 * h + Theme.s2 : h
                        opacity: 0; transform: Translate { id: optsLift }
                        Arrive { item: opts; lift: optsLift; beat: 2 }
                        Row { id: forRow; x: opts.inset; height: opts.h; spacing: Theme.s3
                            // what the next design is made for. Anything is the default; saying "for my A1 mini" in the
                            // request does the same as picking My printer.
                            Txt { id: forLbl; tone: 2; text: "Make it for"; height: opts.h; lineHeight: 1.0; verticalAlignment: Text.AlignVCenter; wrapMode: Text.NoWrap }
                            Seg { id: purposeSeg; objectName: "startPurpose"; anchors.verticalCenter: parent.verticalCenter; implicitHeight: opts.h
                                value: Store.newPurpose === "print" || Store.newPurpose === "game" ? Store.newPurpose : "any"; onPicked: function (v) { Store.setNewPurpose(v) }
                                model: [{ value: "any", text: "Anything", tip: "A 3D model: STEP, STL, 3MF and more, for any way of making it." + (Store.printOn ? " Say “for my printer” in the request, or pick My printer, to check and slice it." : "") }]
                                       .concat(Store.printOn ? [{ value: "print", text: "My printer", tip: Store.printerName ? "Checked and sliced for " + Store.printerName : "Checked for printing; slicing starts once a printer is set up" }] : [])
                                       .concat([{ value: "game", text: "Game asset", badge: "Beta", tip: "For a game engine: LODs at triangle budgets, UVs, baked textures and collision, for Godot, Unity or Unreal. In Beta: visual quality is still improving." }]) }
                            Btn { id: printerChip; anchors.verticalCenter: parent.verticalCenter; objectName: "startPrinter"; small: true; height: Theme.hMd; kind: "quiet"; icon: "printer"
                                visible: Store.printOn && Store.newPurposeEffective === "print"
                                text: Store.printerName ? Store.printerName : "Choose a printer"
                                tip: "The printer the next design is checked and sliced for. Click to change it."
                                onClicked: Store.openSheet("printer") } }
                        Btn { id: modelChip; objectName: "startModel"; height: Theme.hMd; kind: "quiet"; icon: "sparkles"; active: homeModelPop.opened
                            x: opts.wrap ? opts.inset - 13 : opts.width - opts.inset - width + 13; y: (opts.wrap ? opts.h + Theme.s2 : 0) + Math.round((opts.h - height) / 2)
                            text: Store.chatReady ? Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) : "Connect an agent"
                            tip: Store.chatReady ? "The agent and model that design it. Click to change them." : "No agent is connected: add one in Settings › Agents & models"
                            onClicked: Store.chatReady ? (homeModelPop.opened ? homeModelPop.close() : homeModelPop.open()) : Store.openSettings("agents")
                            Pop {
                                id: homeModelPop; y: parent.height + 6; x: opts.wrap ? 0 : Math.round(parent.width - width); width: 380; padding: 6
                                origin: opts.wrap ? Popup.TopLeft : Popup.TopRight
                                height: Math.min(hmp.implicitHeight + 12, home.height * 0.6)
                                onAboutToShow: hmp.reset()
                                onOpened: hmp.opened()
                                onClosed: Qt.callLater(function () {
                                    Store.retryAfterPick = false
                                    if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
                                Flickable { anchors.fill: parent; clip: true; contentHeight: hmp.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar { width: 6 }
                                    TalkModelPicker { id: hmp; width: parent.width; onDone: homeModelPop.close() } } } } }
                    Note { visible: !!Store.fatal; width: parent.width; kind: "red"; title: Store.fatal ? Store.fatal.message : ""; text: Store.fatal ? (Store.fatal.hint || "") : "" }
                }
                // first day: what is turning on the bench, said honestly (kernel geometry, an example, not one of yours)
                Row { id: pieceCap; objectName: "showpieceCaption"; visible: home.split; spacing: Theme.s2
                    x: Math.round(hero.colW + (hero.width - hero.colW) / 2 - width / 2 + 28); y: Math.round(hero.height * 0.8)
                    opacity: home.pieceShown ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.slow } }
                    Rectangle { width: 5; height: 5; radius: 2.5; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "cap"; tone: 3; font.letterSpacing: 0.8; anchors.verticalCenter: parent.verticalCenter
                        text: home.showpiece ? "An example build · " + home.showpiece.name + " · " + home.showpiece.features + " features · real CAD from the kernel" : "" } }
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
                        id: cgc; objectName: "conceptGroup"; width: parent.width; height: 132; radius: Theme.rPane
                        color: cgm.containsMouse ? Theme.glass2 : Theme.glass; border.color: cgm.containsMouse ? Theme.alpha(Theme.datum, 0.5) : Theme.alpha(Theme.datum, 0.28)
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

            // ════ the shelf: the designs ════
            Item { id: shelfHead; width: parent.width; height: 34; visible: home.everything.length > 0
                opacity: 0; transform: Translate { id: shelfLift }
                Arrive { item: shelfHead; lift: shelfLift; beat: 3 }
                Row { spacing: 14; anchors.verticalCenter: parent.verticalCenter
                    Txt { text: "Designs"; font.pixelSize: 20; font.weight: Theme.wSemi; font.letterSpacing: -0.4; lineHeight: 1.0 }
                    Txt { mono: true; tone: 3; font.pixelSize: 12; text: home.everything.length + (home.grouped > 0 ? " · " + home.families.length + (home.families.length === 1 ? " family" : " families") : "") + (home.released ? " · " + home.released + " released" : ""); anchors.baseline: parent.children[0].baseline } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                    Seg { visible: home.everything.length > 6; anchors.verticalCenter: parent.verticalCenter; implicitHeight: 34; value: home.filter; onPicked: function (v) { home.filter = v }
                        model: [{ value: "all", text: "All" }, { value: "open", text: "In progress" }, { value: "released", text: "Released" }] }
                    Item { visible: home.everything.length > 6; width: 10; height: 1 }
                    Btn { visible: home.everything.length > 6; kind: "quiet"; icon: "arrow_up_down"; text: home.order === "recent" ? "Last changed" : "Name"; tip: "Sort order"; anchors.verticalCenter: parent.verticalCenter
                        onClicked: home.order = home.order === "recent" ? "name" : "recent" }
                    Btn { kind: "quiet"; icon: "import"; text: "Import…"; tip: "A .formstudio project, a .formproj, or a conversation"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.openSheet("import") }
                    Btn { kind: "quiet"; icon: "folder_open"; tip: "Open the projects folder: " + Bridge.dataDirShort; anchors.verticalCenter: parent.verticalCenter; onClicked: Bridge.openDataFolder() } } }
            Item { visible: home.everything.length > 0; width: 1; height: 8 }
            // rows of families; the family opened by its count sits under its own row, across the full width. Until
            // "All N designs" is picked only the first row shows, and its last place says how many more there are.
            Column {
                id: grid; objectName: "designGrid"; width: parent.width; visible: home.everything.length > 0; spacing: 12
                readonly property int gap: 20
                readonly property int columns: Math.max(2, Math.floor((width + gap) / 285))
                readonly property real cw: Math.floor((width - (columns - 1) * gap) / columns)
                readonly property bool folded: !home.showAll && home.families.length > columns
                readonly property var shown: folded ? home.families.slice(0, columns - 1) : home.families
                readonly property var hidden: folded ? home.families.slice(columns - 1) : []
                readonly property var rows: { var out = [], f = shown; for (var i = 0; i < f.length; i += columns) out.push(f.slice(i, i + columns)); return out }
                Repeater {
                    model: grid.rows
                    Column {
                        id: band; required property var modelData; required property int index
                        width: grid.width; spacing: 12
                        readonly property var open: { for (var i = 0; i < modelData.length; i++) if (modelData[i].root === home.openFamily && modelData[i].count > 1) return modelData[i]; return null }
                        Row { spacing: grid.gap
                            Repeater { model: band.modelData
                                DesignCard { required property var modelData; required property int index
                                    width: grid.cw; host: home; p: modelData.face; count: modelData.count; photo: home.photos[modelData.face.id] || null
                                    order: band.index * grid.columns + index
                                    opened: home.openFamily === modelData.root && modelData.count > 1
                                    onToggled: home.openFamily = opened ? "" : modelData.root } }
                            // the rest of the shelf: a round pane of glass with the count, and what is behind it
                            Item { id: moreCell; objectName: "designsMore"; visible: grid.folded && band.index === 0; width: grid.cw; height: 264
                                readonly property bool hot: mm.containsMouse || activeFocus
                                activeFocusOnTab: true
                                Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; home.showAll = true } }
                                opacity: 0; Component.onCompleted: { if (home.entered) opacity = 1; else moreIn.start() }
                                SequentialAnimation { id: moreIn; PauseAnimation { duration: 220 + grid.columns * Theme.stagger } Glide { target: moreCell; property: "opacity"; to: 1; duration: Theme.slow } }
                                Item { id: disc; width: 132; height: 132; y: 34; anchors.horizontalCenter: parent.horizontalCenter
                                    scale: mm.pressed ? Theme.from(0.97) : 1; Behavior on scale { Glide { duration: Theme.press } }
                                    transform: Translate { y: moreCell.hot && !mm.pressed ? -Theme.shift(4) : 0; Behavior on y { Glide { duration: Theme.base } } }
                                    Shadow { radius: 66; spread: 30; drop: 14; strength: Theme.dark ? 0.8 : 0.4 }
                                    Glass { anchors.fill: parent; flat: true; radius: 66 }
                                    Rectangle { anchors.fill: parent; radius: 66; color: Theme.washHover; opacity: moreCell.hot ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
                                    Txt { anchors.centerIn: parent; mono: true; tone: 2; font.pixelSize: 22; font.weight: Theme.wMedium; text: "+" + grid.hidden.length }
                                    FocusRing { on: moreCell.activeFocus; radius: 69 } }
                                Column { y: 206; width: parent.width; spacing: 5
                                    Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 9; height: 20
                                        Txt { text: "All " + F.plural(home.everything.length, "design"); font.pixelSize: 15; font.weight: Theme.wSemi; font.letterSpacing: -0.15; lineHeight: 1.0; anchors.verticalCenter: parent.verticalCenter }
                                        Icon { name: "arrow_right"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter } }
                                    Txt { width: parent.width - 12; x: 6; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 12; tone: 3; lineHeight: 1.0
                                        text: grid.hidden.length ? grid.hidden[0].face.name + (grid.hidden.length > 1 ? " and " + (grid.hidden.length - 1) + " more" : "") : "" } }
                                MouseArea { id: mm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: home.showAll = true }
                            }
                        }
                        // the opened family: every design that shares the origin, the first one first
                        Rectangle {
                            id: fam; objectName: "familyPanel"; visible: !!band.open; width: parent.width
                            height: visible ? famCol.implicitHeight + 36 : 0; radius: Theme.rPane
                            color: Theme.glass; border.width: 1; border.color: Theme.dark ? Theme.glassEdge : Theme.rule
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
                            Column { id: famCol; x: 18; y: 16; width: parent.width - 36; spacing: 8
                                Item { width: parent.width; height: 22
                                    Row { spacing: 10; anchors.verticalCenter: parent.verticalCenter
                                        Txt { kind: "cap"; color: Theme.datum; text: "Design family"; anchors.verticalCenter: parent.verticalCenter }
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
            Btn { objectName: "designsFewer"; visible: home.showAll && home.families.length > grid.columns; anchors.horizontalCenter: parent.horizontalCenter
                kind: "quiet"; small: true; icon: "chevron_up"; text: "Show fewer"; onClicked: { home.showAll = false; flick.contentY = 0 } }
            Txt { visible: home.everything.length > 0 && home.families.length === 0; tone: 3; text: home.filter === "released" ? "Nothing is released yet. A design is released from Make, its last stage." : "Every design here is released." }

            // ════ recent conversations ════
            Item { visible: home.talks.length > 0; width: 1; height: home.everything.length > 0 ? Theme.s12 : 8 }
            Item { visible: home.talks.length > 0; width: parent.width; height: 30
                Txt { text: "Conversations"; font.pixelSize: 20; font.weight: Theme.wSemi; font.letterSpacing: -0.4; lineHeight: 1.0; anchors.verticalCenter: parent.verticalCenter }
                Btn { small: true; kind: "quiet"; icon: "history"; text: "All"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    onClicked: { Store.talkOpen = true; if (home.talks.length) Store.openConv(home.talks[0].id) } } }
            Item { visible: home.talks.length > 0; width: 1; height: 12 }
            Row {
                visible: home.talks.length > 0; width: parent.width; spacing: 12
                readonly property real tw: Math.floor((width - (home.talks.length - 1) * spacing) / Math.max(1, home.talks.length))
                Repeater { model: home.talks
                    Rectangle { id: tc; objectName: "homeConversation"; required property var modelData; required property int index
                        readonly property string convId: modelData.id
                        width: parent.tw; height: 84; radius: Theme.rLg
                        color: tcm.pressed ? Theme.glass : tcm.containsMouse ? Theme.glass2 : Theme.glass
                        border.color: tcm.containsMouse ? Theme.rule3 : Theme.dark ? Theme.glassEdge : Theme.rule
                        Behavior on color { Tint {} }
                        opacity: 0; Component.onCompleted: { if (home.entered) opacity = 1; else tcIn.start() }
                        SequentialAnimation { id: tcIn; PauseAnimation { duration: 200 + tc.index * Theme.stagger } Glide { target: tc; property: "opacity"; to: 1; duration: Theme.slow } }
                        // the designs it made, small, on the right (a trashed one is left out; a conversation with none shows none)
                        readonly property var made: Store.convDesigns(tc.modelData).filter(function (d) { return d.live }).slice(-3)
                        Row { id: tthumbs; objectName: "conversationDesigns"; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                            visible: tc.made.length > 0 && tc.width > 260
                            Repeater { model: tc.made.slice(-2)
                                Rectangle { required property var modelData; required property int index
                                    width: 52; height: 52; radius: Theme.rMd; color: Theme.plate; border.color: Theme.rule2; clip: true; z: 10 - index
                                    MiniView { anchors.fill: parent; anchors.margins: 1; projectId: parent.modelData.project } } } }
                        Column { x: 16; y: 14; width: parent.width - 32 - (tthumbs.visible ? tthumbs.width + 12 : 0); spacing: 5
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
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 22; width: dropTx.implicitWidth + 40; height: 36; radius: 18; color: Theme.glassSolid; border.color: Theme.alpha(Theme.datum, 0.5)
                Row { id: dropTx; anchors.centerIn: parent; spacing: 8
                    Icon { name: "import"; size: 14; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: "Drop to start from it · photos, STEP, STL, 3MF, PDF drawings, links"; font.weight: Theme.wMedium; anchors.verticalCenter: parent.verticalCenter } } } }
    }
}
