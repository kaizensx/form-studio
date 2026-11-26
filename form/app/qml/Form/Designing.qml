import QtQuick
import QtQuick.Controls
import "F.js" as F

// The workspace while a design is being made, before the agent has created it: the empty studio floor, what you
// gave it, and what the agent is doing right now. The design is attached the moment it exists (Store.follow opens
// it, and it builds up feature by feature); concepts open their own view. A conversation opened from the list that has
// made no design yet lands here too (Store.convNoDesign): it says so and offers to go on, never the Home question.
Item {
    id: dz
    objectName: "designingView"
    readonly property var me: Store.chatItems.filter(function (e) { return e.t === "user" })
    readonly property var first: me.length ? me[me.length - 1] : null
    readonly property var pics: first && first.attachments ? first.attachments : []
    readonly property var tools: Store.chatItems.filter(function (e) { return e.t === "tool" && e.name !== "suggest_replies" })
    readonly property bool done: !Store.chatBusy && (Store.convNoDesign || Store.chatItems.some(function (e) { return e.t === "end" || e.t === "error" }))
    // Start blank: nothing asked yet, nothing on the plate
    readonly property bool empty: Store.blankCanvas && dz.me.length === 0 && !Store.chatBusy
    readonly property var steps: {
        var map = { design_guide: "Reading the design contract", create_design: "Writing the design as code", update_design: "Changing the code",
                    propose_concepts: "Building concepts side by side", render: "Looking at the part", read_document: "Reading the drawing",
                    import_reference: "Importing the reference part", ask_user: "Asking you", ask_measurement: "Asking you to measure",
                    create_project: "Starting from a building block", describe_recipe: "Reading a building block", preview_change: "Trying a change",
                    commit_change: "Keeping a change", run_pipeline: "Building, checking and slicing", get_project: "Reading the design" }
        var out = []
        tools.forEach(function (t) { var n = String(t.name || "").replace(/^mcp__form__/, ""); var l = map[n] || ("Calling " + n)
            if (!out.length || out[out.length - 1] !== l) out.push(l) })
        return out
    }
    // the hero line while the agent writes code: the words, and the size of what it has written so far (it ticks)
    readonly property bool writing: Store.chatBusy && !Store.chatAsking && !!Store.chatLive && Store.chatLive.kind === "tool"
        && (Store.chatLive.name === "create_design" || Store.chatLive.name === "update_design" || Store.chatLive.name === "propose_concepts")
    function liveLine() {
        var L = Store.chatLive
        if (Store.chatAsking) return "Waiting for your answer"
        if (!Store.chatBusy) return dz.done ? ((Store.concepts && Store.concepts.length) ? "Concepts are ready: pick one in the conversation"
                                                 : Store.convNoDesign ? "This conversation has not made a design yet" : "The agent answered without creating a design") : "Starting the agent…"
        if (!L) return "Thinking about it…"
        if (L.kind === "tool") return (L.name === "create_design" || L.name === "update_design" || L.name === "propose_concepts")
                                      ? "Writing design code" : "Working…"
        if (L.kind === "thinking") return "Thinking it through…"
        if (L.kind === "text") return "Writing to you…"
        return "Working…"
    }

    // the stages of the design as they build (Store.showStage), before it is saved
    readonly property bool staged: !!Store.building && !Store.building.project
    // the room: what the panes of this screen blur
    Item { id: studio; anchors.fill: parent
    Viewport { id: dvp; objectName: "designingViewport"; anchors.fill: parent; lite: false; interactive: true; showDims: false; showCompanions: false
        showOrigin: dz.staged                    // the floor's cross belongs to a part; before there is one the words stand here
        floorGrid: Store.floorGrid; insetTop: 84; insetLeft: 40; insetRight: dz.staged ? 372 : 40
        insetBottom: Math.max(60, dz.height - (dz.staged ? stageCap.y - 10 : Store.barY) + 26)
        Component.onCompleted: { setModel(null); setView("iso", false); Store.stageViewer = dvp; Store.backdrop = studio }
        Component.onDestruction: if (Store.stageViewer === dvp) Store.stageViewer = null }
    Room { anchors.fill: parent; wall: false; poolK: 0 }
    }
    // the key light: it breathes while the agent thinks, and narrows and warms once stages arrive
    Room { anchors.fill: parent; wall: false; vignetteK: 0; poolX: 0.5; poolY: dz.staged ? 0.5 : 0.46
        poolW: dz.staged ? 640 : 900; poolH: dz.staged ? 300 : 380; poolK: Theme.dark ? (dz.staged ? 0.11 : 0.06) : (dz.staged ? 0.5 : 0.3); breathe: !dz.staged
        Behavior on poolW { NumberAnimation { duration: Theme.move(600); easing.type: Easing.InOutQuad } }
        Behavior on poolK { NumberAnimation { duration: 600; easing.type: Easing.InOutQuad } } }

    // The part that does not exist yet: the logo's construction. Two datum hairlines, X in from the left and Y down
    // from the top, meet at an origin and breathe; what the agent is doing is written from that origin like the
    // title block of a drawing: the line that matters large, its real steps as a ledger under it.
    Item {
        id: origin; objectName: "designingOrigin"
        readonly property real col: Math.min(parent.width - 2 * Theme.s10, 560)        // the text column
        x: Math.round((parent.width - col) / 2); y: Math.round(Math.min(parent.height * 0.3, Store.barY - 330))
        width: 1; height: 1
        visible: opacity > 0.01 && !dz.empty
        opacity: dz.staged ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.cross } }
        Item { id: lines; anchors.fill: parent
            property real breath: Theme.reduced ? 0.6 : 0.8
            opacity: dz.done ? 0.4 : breath; Behavior on opacity { enabled: dz.done; NumberAnimation { duration: Theme.cross } }
            SequentialAnimation on breath { running: !Theme.reduced && origin.visible && !dz.done; loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 1400; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.8; duration: 1400; easing.type: Easing.InOutSine } }
            Rectangle { y: 0; height: 1; width: Math.round(Math.min(origin.x - Theme.s6, 320)); x: -width
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0) } GradientStop { position: 1; color: Theme.datum } } }
            Rectangle { x: 0; width: 1; height: Math.round(Math.min(origin.y - Theme.s6, 240)); y: -height
                gradient: Gradient {
                    GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0) } GradientStop { position: 1; color: Theme.datum } } }
            // ticks every 24 px along both, the grid the mark is drawn on
            Repeater { model: 5
                Rectangle { required property int index; x: -(index + 1) * 24; y: -3; width: 1; height: 7; color: Theme.datum; opacity: 0.6 - index * 0.11 } }
            Repeater { model: 5
                Rectangle { required property int index; y: -(index + 1) * 24; x: -3; height: 1; width: 7; color: Theme.datum; opacity: 0.6 - index * 0.11 } }
        }
    }

    // what is happening, written from the origin
    Column {
        objectName: "designingState"; visible: !dz.empty && opacity > 0.01
        opacity: dz.staged ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.cross } }
        x: origin.x + Theme.s5; y: origin.y + Theme.s5; spacing: Theme.s2; width: origin.col - Theme.s5
        Txt { kind: "cap"; color: Theme.datum; objectName: "designingCaption"; text: dz.done ? "No design yet" : "Being designed" }
        Row { spacing: 0; width: parent.width
            Txt { objectName: "designingLine"; kind: "h2"; text: dz.liveLine(); width: Math.min(implicitWidth, parent.width - (kb.visible ? kb.width : 0)) }
            Tick { id: kb; objectName: "designingKb"; visible: dz.writing; font.pixelSize: Theme.tH2; font.weight: Theme.wMedium; font.letterSpacing: -0.4; tone: 2
                leftPadding: Theme.s3; unit: " kB"; decimals: 1; value: dz.writing ? Store.chatLive.chars / 1000 : 0 } }
        // a conversation whose designs were all moved to the trash says so, rather than pretending it made none
        Txt { visible: dz.done && Store.convNoDesign && Store.designsHere.length > 0; kind: "body"; tone: 2; width: parent.width; wrapMode: Text.WordWrap
            text: Store.designsHere.length === 1 ? "Its design, “" + Store.designsHere[0].name + "”, is in the trash (.trash in your projects folder)."
                : F.plural(Store.designsHere.length, "design") + " it made are in the trash (.trash in your projects folder)." }
        // the ledger: the agent's real steps, in order, the newest last and marked while it runs
        Item { width: 1; height: Theme.s1; visible: ledger.visible }
        Column { id: ledger; objectName: "designingLedger"; width: 320; spacing: Theme.s1; visible: dz.steps.length > 0
            property int seen: 0                     // steps already written: only new lines arrive
            readonly property int from: Math.max(0, dz.steps.length - 6)
            Repeater { model: dz.steps.slice(ledger.from)
                Item { id: stepRow; required property string modelData; required property int index
                    readonly property int n: ledger.from + index               // its place in the whole run
                    readonly property bool now: n === dz.steps.length - 1 && Store.chatBusy
                    width: ledger.width; height: 18
                    property real k: 1
                    opacity: k; transform: Translate { y: (1 - stepRow.k) * Theme.shift(6) }
                    Component.onCompleted: if (n >= ledger.seen) { k = 0; arrive.delay = Math.max(0, n - ledger.seen) * Theme.stagger; arrive.start()
                        Qt.callLater(function () { ledger.seen = Math.max(ledger.seen, dz.steps.length) }) }
                    SequentialAnimation { id: arrive; property int delay: 0
                        PauseAnimation { duration: arrive.delay }
                        NumberAnimation { target: stepRow; property: "k"; to: 1; duration: Theme.slow; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
                    Txt { mono: true; kind: "fine"; tone: 4; text: (stepRow.n + 1 < 10 ? "0" : "") + (stepRow.n + 1); anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                    Txt { x: 28; width: parent.width - 28 - 14; mono: true; kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: stepRow.now ? Theme.ink : Theme.ink3; text: stepRow.modelData }
                    Rectangle { visible: stepRow.now; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3; color: Theme.datum
                        SequentialAnimation on opacity { running: stepRow.now && !Theme.reduced; loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                } } }
        Item { width: 1; height: Theme.s2; visible: dz.done }
        Row { visible: dz.done; spacing: 8
            Btn { objectName: "designingContinue"; kind: "primary"; icon: "message_square"; text: "Continue the conversation"; visible: Store.chatReady && Store.convId !== ""
                tip: "Say what to make; it appears here as it is built"; onClicked: { Store.talkOpen = true; Store.chatFocus++ } }
            Btn { objectName: "designingHome"; icon: "arrow_left"; text: "Back to Home"; onClicked: Store.leaveDesigning() }
            Btn { kind: Store.convId !== "" && Store.chatReady ? "quiet" : "primary"; icon: "square_dashed"; text: "Start from a block"; tip: "A rounded block with its width, depth, height and corners as sliders, no agent needed"
                onClicked: run(function () { return Store.startBlock("") }) } }
    }

    // the cue while the stages arrive: the build's lower third above the bar, as in the workspace. A new design does
    // not say what comes next (the agent is still writing it), so only what was built before is named.
    Item {
        id: stageCap; objectName: "stageCaption"; z: 6
        readonly property string caption: Store.buildingText
        function before() {
            var b = Store.building
            for (var i = Store.stageLog.length - 1; b && i >= 0; i--) { var e = Store.stageLog[i]; if (e.draft === b.draft && e.at === b.at - 1) return e.label || "" }
            return "" }
        width: Math.max(360, Store.barW); x: Math.round(Store.barX + (Store.barW - width) / 2)
        height: stageLedger.height; y: Math.round(Store.barY - height - 26)
        opacity: dz.staged ? 1 : 0; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: dz.staged ? Theme.base : 420 } }
        Cue { id: stageLedger; width: parent.width; pulse: true
            label: Store.building ? Store.building.label : ""; at: Store.building ? Store.building.at : 0; of: Store.building ? Store.building.of : 0
            before: stageCap.before() }
    }
    // the program so far: the stages this build has drawn, as the listing the design will have
    Glass {
        id: dprog; objectName: "designingProgram"; source: studio; z: 6
        readonly property var rows: { var b = Store.building, out = []
            for (var i = 0; b && i < Store.stageLog.length; i++) { var e = Store.stageLog[i]; if (e.draft === b.draft && !out.some(function (o) { return o.at === e.at })) out.push(e) }
            return out }
        width: 332; radius: Theme.rPane; x: dz.width - Theme.edge - width; y: 80
        height: Math.min(dz.height - 80 - Theme.edge, 52 + rows.length * 32)
        opacity: dz.staged && rows.length > 0 ? 1 : 0; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.base } }
        Behavior on height { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        Txt { id: dpt; x: 18; y: 13; text: "Program"; font.weight: Theme.wSemi; font.pixelSize: 14 }
        Txt { anchors.right: parent.right; anchors.rightMargin: 18; anchors.baseline: dpt.baseline; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.5; font.capitalization: Font.AllUppercase; color: Theme.datum
            text: Store.building && Store.building.of > 1 ? Store.building.at + " of " + Store.building.of : "building" }
        Rectangle { x: 51; y: 50; width: 1; height: Math.max(0, parent.height - 60); color: Theme.rule }
        Rectangle { x: 50; y: 46; width: 2; radius: 1; height: Math.max(0, dprog.rows.length * 32 - 12); color: Theme.datum; opacity: 0.8
            Behavior on height { NumberAnimation { duration: Theme.reduced ? 0 : 140 } } }
        Column { x: 6; y: 46; width: parent.width - 12; clip: true; height: parent.height - 52
            Repeater { model: dprog.rows
                Item { id: dl; required property var modelData; required property int index
                    readonly property bool now: !!Store.building && modelData.at === Store.building.at
                    width: parent.width; height: 32
                    Rectangle { anchors.fill: parent; radius: 10; color: dl.now ? Theme.glass2 : "transparent" }
                    Txt { width: 30; y: 9; horizontalAlignment: Text.AlignRight; mono: true; font.pixelSize: 11; color: dl.now ? Theme.datum : Theme.ink3; text: (dl.modelData.at < 10 ? "0" : "") + dl.modelData.at }
                    Icon { visible: !dl.now; x: 41; y: 10; name: "check"; size: 13; color: Theme.pass }
                    Txt { x: 66; y: 8; width: parent.width - 150; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13; font.weight: dl.now ? Theme.wSemi : Theme.wMedium; tone: dl.now ? 1 : 2; text: dl.modelData.label || dl.modelData.feature }
                    Txt { visible: dl.now; anchors.right: parent.right; anchors.rightMargin: 12; y: 10; mono: true; font.pixelSize: 10; font.weight: Theme.wMedium; font.letterSpacing: 1.0; color: Theme.datum; text: "BUILDING" } } } }
    }

    // the blank canvas: the empty studio floor and the ways to put something on it
    Column {
        objectName: "blankCanvas"; visible: dz.empty
        anchors.centerIn: parent; anchors.verticalCenterOffset: -70; spacing: 12; width: Math.min(parent.width - 80, 620)
        Txt { kind: "cap"; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter; text: "Blank canvas" }
        Txt { kind: "h2"; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width
            text: "Nothing here yet" }
        Txt { kind: "body"; tone: 2; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; wrapMode: Text.WordWrap
            text: Store.chatReady ? "Say what goes here in the bar below, draw it, or bring a part you have."
                                  : "Draw it, bring a part you have, or start from a block you shape with sliders. Connect an agent in Settings › Agents & models to describe it in words." }
        Item { width: 1; height: 4 }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Btn { objectName: "blankSketch"; icon: "pen_tool"; text: "Sketch it"; onClicked: Store.openSheet("sketch") }
            Btn { objectName: "blankImport"; icon: "import"; text: "Import a part or project"; onClicked: Store.openSheet("import") }
            Btn { objectName: "blankBlock"; icon: "cuboid"; text: "Start from a block"; tip: "A rounded block with its width, depth, height and corners as sliders, no agent needed"
                onClicked: run(function () { return Store.startBlock("") }) }
            Btn { kind: "quiet"; icon: "arrow_left"; text: "Home"; onClicked: Store.home() } }
    }

    // what you gave it, kept in view: the photo, the sketch, the part
    Row {
        visible: dz.pics.length > 0; anchors.left: parent.left; anchors.top: parent.top; anchors.leftMargin: Theme.edge; anchors.topMargin: 84; spacing: 8
        Txt { kind: "cap"; text: "Working from"; anchors.verticalCenter: parent.verticalCenter; rightPadding: 4 }
        Repeater { model: dz.pics.slice(0, 5)
            Rectangle { required property var modelData; readonly property bool pic: modelData.kind === "image"
                width: pic ? 64 : wl.implicitWidth + 40; height: pic ? 64 : 32; radius: Theme.rMd; color: Theme.plate2; border.color: Theme.rule2; clip: true; anchors.verticalCenter: parent.verticalCenter
                Image { visible: parent.pic; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                    source: parent.pic && Store.convId ? Store.attachmentUrl(parent.modelData.file) : "" }
                Icon { visible: !parent.pic; x: 10; size: 13; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter
                    name: parent.modelData.kind === "sketch" ? "pen_tool" : parent.modelData.kind === "cad" ? "cuboid" : "file_text" }
                Txt { id: wl; visible: !parent.pic; x: 30; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                    text: parent.modelData.kind === "sketch" ? "Sketch" : parent.modelData.name } } }
    }
}
