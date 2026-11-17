import QtQuick

// kind: default | primary | quiet | danger.   States: hover, pressed, keyboard focus, disabled, busy.
// `busy` keeps the width, swaps the icon for a spinner and ignores presses. `keys` shows a shortcut in the tooltip.
Item {
    id: b
    property string text: ""
    property string icon: ""
    property string kind: "default"
    property bool small: false
    property bool large: false
    property bool active: false
    property bool busy: false
    property string tip: ""
    property string keys: ""
    property alias hovered: ma.containsMouse
    property bool kdown: false
    readonly property bool down: (ma.pressed || kdown) && enabled && !busy
    signal clicked()
    implicitHeight: small ? Theme.hSm : large ? Theme.hLg : Theme.hMd
    implicitWidth: row.implicitWidth + (text ? (small ? 16 : large ? 28 : 22) : (small ? 8 : 12))
    opacity: enabled ? 1 : 0.4
    scale: down ? Theme.from(0.97) : 1
    activeFocusOnTab: enabled && visible
    Behavior on scale { Glide { duration: Theme.press } }
    Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; if (!e.isAutoRepeat) kdown = true } }
    Keys.onReleased: function (e) { if (kdown && (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter)) { e.accepted = true; kdown = false; if (enabled && !busy) clicked() } }
    onActiveFocusChanged: if (!activeFocus) kdown = false
    Rectangle {
        id: face
        anchors.fill: parent; radius: b.large ? Theme.rMd : Theme.rSm
        readonly property bool hot: ma.containsMouse && b.enabled && !b.busy
        color: b.kind === "primary" ? (b.down ? Qt.darker(Theme.datum, 1.08) : hot ? Theme.datumHi : Theme.datum)
             : b.kind === "quiet" ? (b.down ? Theme.washPress : b.active ? Theme.washOn : hot ? Theme.washHover : "transparent")
             : b.kind === "danger" ? (b.down ? Theme.alpha(Theme.signal, 0.24) : hot ? Theme.alpha(Theme.signal, 0.17) : Theme.alpha(Theme.signal, 0.1))
             : (b.down ? Theme.plate2 : hot || b.active ? Theme.plate4 : Theme.plate3)
        border.width: b.kind === "default" ? 1 : 0; border.color: hot ? Theme.rule3 : Theme.rule2
        Behavior on color { Tint {} }
        // a hairline of light on the top edge of raised buttons
        Rectangle { visible: b.kind === "default" || b.kind === "primary"; x: parent.radius; width: parent.width - 2 * parent.radius; y: 1; height: 1
            color: Qt.rgba(1, 1, 1, b.kind === "primary" ? 0.35 : 0.05) }
    }
    FocusRing { on: b.activeFocus; radius: face.radius + 3 }
    Row {
        id: row; anchors.centerIn: parent; spacing: b.small ? 5 : 6
        Item { visible: b.icon !== "" || b.busy; width: b.small ? 13 : 14; height: width; anchors.verticalCenter: parent.verticalCenter
            Icon { anchors.centerIn: parent; visible: !b.busy; name: b.icon; size: parent.width
                color: b.kind === "primary" ? Theme.datumInk : b.kind === "danger" ? Theme.signal : (b.active || ma.containsMouse) ? Theme.ink : Theme.ink2 }
            Spinner { anchors.centerIn: parent; visible: b.busy; size: parent.width; color: b.kind === "primary" ? Theme.datumInk : Theme.ink2 } }
        Text { visible: b.text !== ""; text: b.text; anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.sans; font.pixelSize: b.small ? 12 : 13; font.weight: b.kind === "primary" ? Theme.wSemi : Theme.wMedium; renderType: Text.NativeRendering
            color: b.kind === "primary" ? Theme.datumInk : b.kind === "danger" ? Theme.signal : (b.kind === "quiet" && !b.active && !ma.containsMouse) ? Theme.ink2 : Theme.ink }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: if (b.enabled && !b.busy) b.clicked() }
    Tip { text: b.tip; keys: b.keys; show: ma.containsMouse && b.tip !== "" && !ma.pressed }
}
