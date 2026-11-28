import QtQuick

// One option in the tool capsule: a word, lit while it is the one in use. 28 px high, as the capsule's row.
Rectangle {
    id: c
    property string text: ""
    property string icon: ""
    property bool on: false
    property string tip: ""
    property bool mono: false
    property color tint: Theme.ink
    signal clicked()
    height: 28; radius: 14; width: Math.ceil(row.implicitWidth) + 20
    opacity: enabled ? 1 : 0.4
    color: c.on ? Theme.glass2 : ma.pressed ? Theme.washPress : ma.containsMouse ? Theme.washHover : "transparent"
    Behavior on color { Tint {} }
    Row { id: row; anchors.centerIn: parent; spacing: 6
        Icon { visible: c.icon !== ""; name: c.icon; size: 14; color: lbl.color; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: lbl; visible: c.text !== ""; text: c.text; mono: c.mono; font.pixelSize: c.mono ? 12 : 13; wrapMode: Text.NoWrap
            font.weight: c.on ? Theme.wMedium : 400; color: c.on ? c.tint : ma.containsMouse ? Theme.ink : Theme.ink2
            anchors.verticalCenter: parent.verticalCenter } }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: c.clicked() }
    Tip { show: ma.containsMouse && c.tip !== ""; text: c.tip; below: true }
}
