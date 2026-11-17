import QtQuick

// A section of an inspector that folds. Closed, it is one line: its name and the one fact worth knowing (`note`,
// or a `tag`). Open, its children stack below like a Sec. `key` remembers the state while the app runs.
Column {
    id: f
    property string title: ""
    property string note: ""
    property string tag: ""
    property color noteColor: Theme.ink3
    property string key: ""
    property bool openByDefault: false
    property bool open: key !== "" ? Ws.isOpen(key, openByDefault) : openByDefault
    default property alias content: body.data
    function toggle() { if (key !== "") Ws.setOpen(key, !open); else open = !open }
    width: parent ? parent.width : 0
    Item {
        width: parent.width; height: 40
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Rectangle { x: -8; y: 4; width: parent.width + 16; height: parent.height - 7; radius: Theme.rSm; color: hm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent" }
        Icon { id: chev; y: 14; name: "chevron_right"; size: 12; color: hm.containsMouse ? Theme.ink2 : Theme.ink4
            rotation: f.open ? 90 : 0
            Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } }
        Txt { id: cap; kind: "cap"; x: 20; y: 14; text: f.title; color: f.open || hm.containsMouse ? Theme.ink2 : Theme.ink3
            width: Math.min(implicitWidth, parent.width - 20 - 70); elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Txt { kind: "fine"; visible: f.note !== "" && f.tag === ""; text: f.note; color: f.noteColor; anchors.right: parent.right; y: 13
            width: Math.min(implicitWidth, parent.width - 20 - cap.width - 14); elide: Text.ElideRight; wrapMode: Text.NoWrap; horizontalAlignment: Text.AlignRight }
        Tag { visible: f.tag !== ""; text: f.tag; anchors.right: parent.right; y: 12 }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: f.toggle() }
    }
    Column {
        id: body
        width: parent.width; spacing: 8; bottomPadding: 14
        visible: f.open
        opacity: f.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
    }
}
