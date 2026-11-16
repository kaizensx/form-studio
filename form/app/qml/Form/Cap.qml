import QtQuick

// Section caption: label on the left, optional quiet note or tag on the right.
Item {
    property string text: ""
    property string note: ""
    property string tag: ""
    implicitHeight: 18; width: parent ? parent.width : 0
    Txt { kind: "cap"; text: parent.text; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter }
    Txt { kind: "fine"; visible: parent.note !== ""; text: parent.note; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
    Tag { visible: parent.tag !== ""; text: parent.tag; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
}
