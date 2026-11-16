import QtQuick

// Key / value row. `sub` is a quiet second line; children sit on the right instead of `value`.
Item {
    id: r
    property string k: ""
    property string sub: ""
    property string value: ""
    property string tag: ""
    property bool first: false
    default property alias content: right.data
    width: parent ? parent.width : 0
    implicitHeight: Math.max(left.implicitHeight, right.implicitHeight, 18) + 14
    Rectangle { visible: !r.first; width: parent.width; height: 1; color: Theme.rule }
    Column {
        id: left; anchors.left: parent.left; anchors.right: right.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 1
        Txt { text: r.k; tone: 2; width: parent.width }
        Txt { kind: "fine"; visible: r.sub !== ""; text: r.sub; width: parent.width }
    }
    Row {
        id: right; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
        Txt { visible: r.value !== ""; text: r.value; mono: true; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
        Tag { visible: r.tag !== ""; text: r.tag; anchors.verticalCenter: parent.verticalCenter }
    }
}
