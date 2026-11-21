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
        return out.slice(-5)
    }
    function liveLine() {
        var L = Store.chatLive
        if (Store.chatAsking) return "Waiting for your answer"
        if (!Store.chatBusy) return dz.done ? (Store.convNoDesign ? "This conversation has not made a design yet" : "The agent answered without creating a design") : "Starting the agent…"
        if (!L) return "Thinking about it…"
        if (L.kind === "tool") return (L.name === "create_design" || L.name === "update_design" || L.name === "propose_concepts")
                                      ? "Writing design code · " + (L.chars / 1000).toFixed(1) + " kB" : "Working…"
        if (L.kind === "thinking") return "Thinking it through…"
        if (L.kind === "text") return "Writing to you…"
        return "Working…"
    }

    // the stages of the design as they build (Store.showStage), before it is saved
    readonly property bool staged: !!Store.building && !Store.building.project
    Viewport { id: dvp; objectName: "designingViewport"; anchors.fill: parent; lite: false; interactive: true; showDims: false; showCompanions: false
        Component.onCompleted: { setModel(null); setView("iso", false); Store.stageViewer = dvp }
        Component.onDestruction: if (Store.stageViewer === dvp) Store.stageViewer = null }
    Rectangle { anchors.fill: parent
        gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.15) } GradientStop { position: 0.7; color: Theme.alpha(Theme.plate, 0.05) } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.55) } } }

    // the part that does not exist yet: a wireframe block assembling and dissolving, quietly, until the real one arrives
    Item {
        id: ghost; width: 220; height: 220; anchors.centerIn: parent; anchors.verticalCenterOffset: -30
        visible: opacity > 0.01 && !dz.done && !dz.empty
        opacity: dz.staged ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.move(260) } }
        Repeater { model: 12
            Rectangle { required property int index
                readonly property var e: [[0,0,1,0],[1,0,1,1],[1,1,0,1],[0,1,0,0],[0,0,0.5,-0.35],[1,0,1.5,-0.35],[1,1,1.5,0.65],[0,1,0.5,0.65],[0.5,-0.35,1.5,-0.35],[1.5,-0.35,1.5,0.65],[1.5,0.65,0.5,0.65],[0.5,0.65,0.5,-0.35]][index]
                readonly property real ax: 40 + e[0] * 100; readonly property real ay: 80 + e[1] * 100
                readonly property real bx: 40 + e[2] * 100; readonly property real by: 80 + e[3] * 100
                x: ax; y: ay; width: Math.hypot(bx - ax, by - ay); height: 1.5; color: Theme.datum; antialiasing: true
                transformOrigin: Item.Left; rotation: Math.atan2(by - ay, bx - ax) * 180 / Math.PI
                opacity: 0
                SequentialAnimation on opacity { loops: Animation.Infinite; running: !Theme.reduced && ghost.visible
                    PauseAnimation { duration: index * 140 } NumberAnimation { to: 0.55; duration: 500; easing.type: Easing.OutCubic }
                    PauseAnimation { duration: 2600 - index * 140 } NumberAnimation { to: 0.08; duration: 900; easing.type: Easing.InOutSine } PauseAnimation { duration: 400 } } } }
    }

    // what is happening, under the part
    Column {
        objectName: "designingState"; visible: !dz.empty && opacity > 0.01
        opacity: dz.staged ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.move(260) } }
        anchors.horizontalCenter: parent.horizontalCenter; anchors.top: ghost.bottom; anchors.topMargin: dz.done ? -120 : 8; spacing: 10; width: Math.min(parent.width - 80, 560)
        Txt { kind: "cap"; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter; objectName: "designingCaption"; text: dz.done ? "No design yet" : "Being designed" }
        Txt { objectName: "designingLine"; kind: "h2"; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; text: dz.liveLine() }
        // a conversation whose designs were all moved to the trash says so, rather than pretending it made none
        Txt { visible: dz.done && Store.convNoDesign && Store.designsHere.length > 0; kind: "body"; tone: 2; width: parent.width
            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
            text: Store.designsHere.length === 1 ? "Its design, “" + Store.designsHere[0].name + "”, is in the trash (.trash in your projects folder)."
                : F.plural(Store.designsHere.length, "design") + " it made are in the trash (.trash in your projects folder)." }
        Column { anchors.horizontalCenter: parent.horizontalCenter; spacing: 4; visible: dz.steps.length > 0
            Repeater { model: dz.steps
                Row { id: stepRow; required property string modelData; required property int index; spacing: 8; anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined
                    readonly property bool now: index === dz.steps.length - 1 && Store.chatBusy
                    Icon { name: stepRow.now ? "loader_circle" : "check"; size: 12; color: stepRow.now ? Theme.datum : Theme.ink4; anchors.verticalCenter: parent.verticalCenter
                        RotationAnimation on rotation { running: stepRow.now && !Theme.reduced; loops: Animation.Infinite; from: 0; to: 360; duration: 1100 } }
                    Txt { kind: "fine"; tone: stepRow.now ? 2 : 3; text: stepRow.modelData } } } }
        Row { visible: dz.done; spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
            Btn { objectName: "designingContinue"; kind: "primary"; icon: "message_square"; text: "Continue the conversation"; visible: Store.chatReady && Store.convId !== ""
                tip: "Say what to make; it appears here as it is built"; onClicked: { Store.talkOpen = true; Store.chatFocus++ } }
            Btn { objectName: "designingHome"; icon: "arrow_left"; text: "Back to Home"; onClicked: Store.leaveDesigning() }
            Btn { kind: Store.convId !== "" && Store.chatReady ? "quiet" : "primary"; icon: "square_dashed"; text: "Start from a block"; tip: "A rounded block with its width, depth, height and corners as sliders, no agent needed"
                onClicked: run(function () { return Store.startBlock("") }) } }
    }

    // a quiet caption while the stages arrive: "Building Rim (3 of 5)"
    Rectangle {
        id: stageCap; objectName: "stageCaption"; z: 6
        readonly property string caption: Store.buildingText
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 32
        width: scr.implicitWidth + 28; height: 32; radius: 16; color: Theme.alpha(Theme.plate3, 0.94); border.color: Theme.alpha(Theme.datum, 0.45)
        opacity: dz.staged ? 1 : 0; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: dz.staged ? Theme.fast : 420 } }
        Row { id: scr; anchors.centerIn: parent; spacing: 9
            Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                SequentialAnimation on opacity { running: stageCap.visible && !Theme.reduced; loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
            Txt { kind: "cap"; color: Theme.datum; text: "Building"; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: Store.building ? Store.building.label : ""; font.weight: Theme.wMedium; anchors.verticalCenter: parent.verticalCenter }
            Txt { visible: !!Store.building && Store.building.of > 1; kind: "fine"; mono: true; tone: 3; anchors.verticalCenter: parent.verticalCenter
                text: Store.building ? Store.building.at + " of " + Store.building.of : "" } }
    }

    // the blank canvas: the empty studio floor and the ways to put something on it
    Column {
        objectName: "blankCanvas"; visible: dz.empty
        anchors.centerIn: parent; anchors.verticalCenterOffset: -20; spacing: 12; width: Math.min(parent.width - 80, 620)
        Txt { kind: "cap"; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter; text: "Blank canvas" }
        Txt { kind: "h2"; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width
            text: "Nothing here yet" }
        Txt { kind: "body"; tone: 2; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; wrapMode: Text.WordWrap
            text: Store.chatReady ? "Say what goes here in the conversation on the left, draw it, or bring a part you have."
                                  : "Draw it, bring a part you have, or start from a block you shape with sliders. Connect an agent in Settings › Agents to describe it in words." }
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
        visible: dz.pics.length > 0; anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 20; spacing: 8
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
