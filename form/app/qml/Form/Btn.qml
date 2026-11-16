import QtQuick

// kind: default | primary | quiet | danger
Item {
    id: b
    property string text: ""
    property string icon: ""
    property string kind: "default"
    property bool small: false
    property bool active: false
    property string tip: ""
    property alias hovered: ma.containsMouse
    signal clicked()
    implicitHeight: small ? 24 : 28
    implicitWidth: row.implicitWidth + (text ? (small ? 16 : 22) : (small ? 8 : 12))
    opacity: enabled ? 1 : 0.4
    scale: ma.pressed && enabled ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
    Rectangle {
        anchors.fill: parent; radius: Theme.rSm
        color: b.kind === "primary" ? (ma.containsMouse ? "#cdf2e4" : Theme.datum)
             : b.kind === "quiet" ? (b.active ? Qt.rgba(1, 1, 1, 0.1) : ma.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent")
             : (ma.containsMouse ? Theme.plate4 : Theme.plate3)
        border.width: b.kind === "default" ? 1 : 0; border.color: Theme.rule2
        Behavior on color { ColorAnimation { duration: Theme.fast } }
    }
    Row {
        id: row; anchors.centerIn: parent; spacing: 6
        Icon { visible: b.icon !== ""; name: b.icon; size: b.small ? 13 : 14; anchors.verticalCenter: parent.verticalCenter
            color: b.kind === "primary" ? Theme.datumInk : (b.active || ma.containsMouse) ? Theme.ink : Theme.ink2 }
        Text { visible: b.text !== ""; text: b.text; anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.sans; font.pixelSize: b.small ? 12 : 13; font.weight: b.kind === "primary" ? 650 : 550; renderType: Text.NativeRendering
            color: b.kind === "primary" ? Theme.datumInk : b.kind === "danger" ? Theme.signal : (b.kind === "quiet" && !b.active && !ma.containsMouse) ? Theme.ink2 : Theme.ink }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: if (b.enabled) b.clicked() }
    Tip { text: b.tip; show: ma.containsMouse && b.tip !== "" }
}
