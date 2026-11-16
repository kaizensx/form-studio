import QtQuick

// A change: label, from → to.
Item {
    id: d
    property string label: ""
    property string from: ""
    property string to: ""
    property string unit: ""
    property color tint: Theme.ink
    width: parent ? parent.width : 0; implicitHeight: 20
    Txt { text: d.label; tone: 2; font.pixelSize: 12; anchors.left: parent.left; anchors.right: v.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap }
    Row {
        id: v; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
        Txt { text: d.from; mono: true; tone: 3; font.pixelSize: 12; visible: d.from !== "" }
        Txt { text: "→"; tone: 4; font.pixelSize: 12; visible: d.from !== "" }
        Txt { text: d.to + (d.unit ? " " + d.unit : ""); mono: true; font.pixelSize: 12; color: d.tint }
    }
}
