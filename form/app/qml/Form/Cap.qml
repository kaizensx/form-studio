import QtQuick

// Section caption: the title on the left (13 px, semibold), an optional quiet note in mono or a tag on the right.
Item {
    id: cap
    property string text: ""
    property string note: ""
    property string tag: ""
    implicitHeight: 20; width: parent ? parent.width : 0
    Txt { id: ttl; text: cap.text; font.pixelSize: 13; font.weight: Theme.wSemi; font.letterSpacing: -0.1; wrapMode: Text.NoWrap
        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width); elide: Text.ElideRight }
    Txt { kind: "fine"; mono: true; tone: 3; visible: cap.note !== ""; text: cap.note; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, Math.max(0, parent.width - ttl.width - 12)); elide: Text.ElideRight; wrapMode: Text.NoWrap; horizontalAlignment: Text.AlignRight }
    Tag { visible: cap.tag !== ""; text: cap.tag; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
}
