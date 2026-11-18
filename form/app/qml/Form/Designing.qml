import QtQuick
import QtQuick.Controls
import "F.js" as F

// The workspace while a design is being made, before the agent has created it: the empty build plate, what you
// gave it, and what the agent is doing right now. The design is attached the moment it exists (Store.follow opens
// it, and it builds up feature by feature); concepts open their own view.
Item {
    id: dz
    objectName: "designingView"
    readonly property var me: Store.chatItems.filter(function (e) { return e.t === "user" })
    readonly property var first: me.length ? me[me.length - 1] : null
    readonly property var pics: first && first.attachments ? first.attachments : []
    readonly property var tools: Store.chatItems.filter(function (e) { return e.t === "tool" && e.name !== "suggest_replies" })
    readonly property bool done: !Store.chatBusy && Store.chatItems.some(function (e) { return e.t === "end" || e.t === "error" })
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
        if (!Store.chatBusy) return dz.done ? "The agent answered without creating a design" : "Starting the agent…"
        if (!L) return "Thinking about it…"
        if (L.kind === "tool") return (L.name === "create_design" || L.name === "update_design" || L.name === "propose_concepts")
                                      ? "Writing design code · " + (L.chars / 1000).toFixed(1) + " kB" : "Working…"
        if (L.kind === "thinking") return "Thinking it through…"
        if (L.kind === "text") return "Writing to you…"
        return "Working…"
    }

    Viewport { anchors.fill: parent; lite: false; interactive: true; showDims: false; showCompanions: false; plateSize: 200
        Component.onCompleted: { setModel(null); setView("iso", false) } }
    Rectangle { anchors.fill: parent
        gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.15) } GradientStop { position: 0.7; color: Theme.alpha(Theme.plate, 0.05) } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.55) } } }

    // the part that does not exist yet: a wireframe block assembling and dissolving, quietly, until the real one arrives
    Item {
        id: ghost; width: 220; height: 220; anchors.centerIn: parent; anchors.verticalCenterOffset: -30
        visible: !dz.done
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
        anchors.horizontalCenter: parent.horizontalCenter; anchors.top: ghost.bottom; anchors.topMargin: 8; spacing: 10; width: Math.min(parent.width - 80, 560)
        Txt { kind: "cap"; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter; text: dz.done ? "No design yet" : "Being designed" }
        Txt { objectName: "designingLine"; kind: "h2"; anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter; width: parent.width; text: dz.liveLine() }
        Column { anchors.horizontalCenter: parent.horizontalCenter; spacing: 4; visible: dz.steps.length > 0
            Repeater { model: dz.steps
                Row { id: stepRow; required property string modelData; required property int index; spacing: 8; anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined
                    readonly property bool now: index === dz.steps.length - 1 && Store.chatBusy
                    Icon { name: stepRow.now ? "loader_circle" : "check"; size: 12; color: stepRow.now ? Theme.datum : Theme.ink4; anchors.verticalCenter: parent.verticalCenter
                        RotationAnimation on rotation { running: stepRow.now && !Theme.reduced; loops: Animation.Infinite; from: 0; to: 360; duration: 1100 } }
                    Txt { kind: "fine"; tone: stepRow.now ? 2 : 3; text: stepRow.modelData } } } }
        Row { visible: dz.done; spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
            Btn { objectName: "designingHome"; icon: "arrow_left"; text: "Back to Home"; onClicked: Store.leaveDesigning() }
            Btn { kind: "primary"; icon: "square_dashed"; text: "Start blank instead"; onClicked: run(function () { return Store.startBlank("") }) } }
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
