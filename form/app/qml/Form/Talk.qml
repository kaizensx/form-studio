import QtQuick
import QtQuick.Controls
import FormNative
import "F.js" as F

// Claude, in the app. Each message runs Claude Code headless on your own account with FORM's tools.
// The same column shows what any other agent (Claude Code, Codex, the CLI) is doing to your designs.
Rectangle {
    id: talk
    property bool hero: false                 // home screen: larger intro, wider column
    color: Theme.plate1
    readonly property var ideas: [
        "A case for a Raspberry Pi 5 with a snap-on lid",
        "A Gridfinity bin, 3 × 1, for screwdrivers",
        "The lightest wall hook that safely holds 5 kg",
        "A headphone hanger that clamps to my desk edge"
    ]
    function liveText() {
        var L = Store.chatLive
        if (!L) return "Thinking…"
        if (L.kind === "tool") return (L.name === "create_design" || L.name === "update_design") ? "Writing design code… " + (L.chars / 1000).toFixed(1) + " kB" : "Preparing " + L.name + "…"
        if (L.kind === "text") return L.text ? L.text.slice(-120).replace(/\s+/g, " ") : "Writing…"
        if (L.kind === "thinking") return "Thinking… " + (L.chars / 1000).toFixed(1) + " kB"
        return "Working…"
    }
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.rule }

    // header
    Item {
        id: head; width: parent.width; height: 40
        Row { x: 16; spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Rectangle { width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                color: Store.chatBusy ? Theme.datum : Store.chat.available ? Theme.pass : Theme.ink4
                SequentialAnimation on opacity { running: Store.chatBusy; loops: Animation.Infinite; alwaysRunToEnd: true
                    NumberAnimation { to: 0.3; duration: 600 } NumberAnimation { to: 1; duration: 600 } } }
            Txt { text: "Claude"; font.weight: 600; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter
                text: Store.chat.available ? Store.chat.model + " · your account" + (Store.chat.web ? " · web lookup" : "") : "not connected" } }
        Row { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 2
            Btn { kind: "quiet"; small: true; text: "Stop"; visible: Store.chatBusy; onClicked: Store.stopChat() }
            Btn { kind: "quiet"; small: true; icon: "plus"; tip: "New conversation"; visible: Store.chatItems.length > 0 && !Store.chatBusy; onClicked: Store.newChat() } }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    }

    // intro
    Column {
        visible: Store.chatItems.length === 0
        x: 16; width: parent.width - 32; spacing: 10
        anchors.top: head.bottom; anchors.topMargin: talk.hero ? 56 : 28
        Txt { kind: talk.hero ? "h1" : "h3"; width: parent.width; text: talk.hero ? "What do you need\nto print?" : "Describe a change,\nor a new part." }
        Txt { tone: 2; width: parent.width; lineHeight: 1.35
            text: "Claude designs it in a real CAD kernel. You watch it take shape here, with checks, a fit model and a real slice. Nothing prints or uploads." }
        Item { width: 1; height: 6 }
        Note { visible: !Store.chat.available && !!Store.studio; kind: "amber"; title: "Claude is not connected"
            text: (Store.chat.note || "") + " You can still start from a recipe and edit everything by hand." }
        Repeater {
            model: Store.chat.available ? talk.ideas : []
            Rectangle {
                id: idea
                required property string modelData
                required property int index
                width: parent.width; height: 38; radius: Theme.rMd
                color: im.containsMouse ? Theme.plate3 : Theme.plate2; border.color: Theme.rule
                Behavior on color { ColorAnimation { duration: Theme.fast } }
                opacity: 0
                Component.onCompleted: appear.start()
                SequentialAnimation { id: appear; PauseAnimation { duration: 80 + idea.index * 55 }
                    ParallelAnimation { NumberAnimation { target: idea; property: "opacity"; to: 1; duration: 300; easing.type: Easing.OutCubic }
                        NumberAnimation { target: tr; property: "y"; from: 6; to: 0; duration: 300; easing.type: Easing.OutCubic } } }
                transform: Translate { id: tr }
                Txt { x: 12; width: parent.width - 40; text: idea.modelData; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: im.containsMouse ? 1 : 2 }
                Icon { name: "arrow_right"; size: 13; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; color: im.containsMouse ? Theme.datum : Theme.ink4 }
                MouseArea { id: im; anchors.fill: parent; hoverEnabled: true; onClicked: Store.send(idea.modelData) }
            }
        }
    }

    // feed
    ListView {
        id: feed
        visible: Store.chatItems.length > 0
        anchors.top: head.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 0; topMargin: 14; bottomMargin: 10; clip: true; spacing: 8
        boundsBehavior: Flickable.StopAtBounds
        model: Store.chatItems
        onCountChanged: Qt.callLater(positionViewAtEnd)
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }
        delegate: Item {
            id: it
            required property var modelData
            readonly property var m: modelData
            width: feed.width; implicitHeight: body.item ? body.item.implicitHeight : 0; height: implicitHeight
            Loader { id: body; x: 16; width: parent.width - 32
                sourceComponent: it.m.t === "user" ? cUser : it.m.t === "text" ? cText : it.m.t === "tool" ? cTool : it.m.t === "act" ? cAct : it.m.t === "end" ? cEnd : cErr }
            Component { id: cUser; Item { implicitHeight: ub.height
                Rectangle { id: ub; anchors.right: parent.right; width: Math.min(parent.width - 28, ut.implicitWidth + 22); height: ut.implicitHeight + 16; radius: Theme.rLg; color: Theme.plate3
                    Txt { id: ut; x: 11; y: 8; width: Math.min(implicitWidth, body.width - 50); text: it.m.text; lineHeight: 1.3 } } } }
            Component { id: cText; Txt { text: it.m.text; textFormat: Text.MarkdownText; width: body.width; lineHeight: 1.35; color: Theme.ink
                linkColor: Theme.datum; onLinkActivated: function (l) { Bridge.openLink(l) } } }
            Component { id: cTool; Item { implicitHeight: 22
                readonly property var r: Store.chatTools[it.m.id]
                Rectangle { anchors.fill: parent; radius: Theme.rXs; color: Qt.rgba(1, 1, 1, 0.03) }
                Icon { x: 6; anchors.verticalCenter: parent.verticalCenter; size: 12
                    name: !parent.r ? "loader_circle" : parent.r.ok ? (parent.r.image ? "eye" : "check") : "x"
                    color: !parent.r ? Theme.datum : parent.r.ok ? Theme.pass : Theme.signal
                    RotationAnimation on rotation { running: !parent.parent.r; from: 0; to: 360; duration: 900; loops: Animation.Infinite } }
                Txt { x: 24; mono: true; font.pixelSize: 11; text: it.m.name; anchors.verticalCenter: parent.verticalCenter; tone: 2; id: tn }
                Txt { anchors.left: tn.right; anchors.leftMargin: 8; anchors.right: parent.right; anchors.rightMargin: 6; mono: true; font.pixelSize: 11; tone: 4
                    text: it.m.input || ""; elide: Text.ElideRight; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter } } }
            Component { id: cAct; Row { spacing: 6
                Icon { name: "zap"; size: 12; color: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; width: body.width - 20; text: it.m.by + "  " + it.m.text; color: Theme.ink2 } } }
            Component { id: cEnd; Txt { kind: "fine"; mono: true; tone: 4; text: (it.m.turns || 0) + " steps · $" + (it.m.cost_usd || 0).toFixed(2) } }
            Component { id: cErr; Note { kind: "red"; text: it.m.text; width: body.width } }
        }
        footer: Item { width: feed.width; height: Store.chatBusy ? 30 : 0; visible: Store.chatBusy
            Row { x: 16; y: 8; spacing: 8
                Row { spacing: 3; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: 3
                        Rectangle { required property int index; width: 4; height: 4; radius: 2; color: Theme.datum
                            SequentialAnimation on opacity { running: Store.chatBusy; loops: Animation.Infinite
                                PauseAnimation { duration: index * 160 } NumberAnimation { from: 0.25; to: 1; duration: 320 } NumberAnimation { to: 0.25; duration: 320 } PauseAnimation { duration: (2 - index) * 160 } } } } }
                Txt { kind: "fine"; text: talk.liveText(); width: feed.width - 70; elide: Text.ElideRight; wrapMode: Text.NoWrap } } }
    }

    // composer
    Item {
        id: foot; anchors.bottom: parent.bottom; width: parent.width; height: box.height + 44
        Area { id: box; x: 12; y: 8; width: parent.width - 24; minLines: talk.hero ? 3 : 2; submitOnEnter: true
            placeholder: !Store.chat.available ? "Claude is not connected" : Store.project ? "Ask about " + Store.project.name + ", or describe something new…" : "Describe what you want to print…"
            enabled: Store.chat.available
            onSubmit: function (t) { if (t.trim() && !Store.chatBusy) { Store.send(t); text = "" } } }
        // design tools: "Ask Claude about this feature…" puts its question here for the user to finish
        Connections { target: Store
            function onChatPrefill(t) { box.text = t; box.area.forceActiveFocus(); box.area.cursorPosition = box.area.length } }
        Txt { kind: "fine"; x: 14; anchors.top: box.bottom; anchors.topMargin: 8; width: parent.width - 110; elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: Store.chatBusy ? "Claude is working. Watch the model." : "Enter to send · Shift+Enter for a new line" }
        Btn { kind: "primary"; small: true; icon: "send"; text: "Send"; anchors.right: parent.right; anchors.rightMargin: 12; anchors.top: box.bottom; anchors.topMargin: 5
            enabled: Store.chat.available && !Store.chatBusy && box.text.trim() !== ""
            onClicked: { Store.send(box.text); box.text = "" } }
    }
}
