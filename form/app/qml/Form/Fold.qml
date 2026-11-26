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
        Rectangle { x: -8; y: 4; width: parent.width + 16; height: parent.height - 7; radius: 10; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent"
            Behavior on color { Tint {} } }
        Icon { id: chev; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 0.5; name: "chevron_right"; size: 12; color: hm.containsMouse ? Theme.ink2 : Theme.ink4
            rotation: f.open ? 90 : 0
            Behavior on rotation { Glide { duration: Theme.move(Theme.ui) } } }
        Txt { id: cap; kind: "cap"; x: 20; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 0.5; text: f.title; color: f.open || hm.containsMouse ? Theme.ink2 : Theme.ink3
            width: Math.min(implicitWidth, parent.width - 20 - 70); elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Txt { kind: "fine"; visible: f.note !== "" && f.tag === ""; text: f.note; color: f.noteColor; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 0.5
            width: Math.min(implicitWidth, parent.width - 20 - cap.width - 14); elide: Text.ElideRight; wrapMode: Text.NoWrap; horizontalAlignment: Text.AlignRight }
        Tag { visible: f.tag !== ""; text: f.tag; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 0.5 }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: f.toggle() }
    }
    // Opening: the content fades in and settles 6 px down into place, behind a clip, while the chevron turns.
    // Closing: it fades out, then the section takes its room back. Height is never animated (the UI contract: only
    // opacity, scale, x/y and colour move), so nothing below is re-laid-out frame by frame. With reduced motion the
    // slide and the turn are gone and only the fade is left.
    Item {
        id: slot
        width: parent.width; clip: true
        visible: f.open || body.opacity > 0.01
        height: visible ? body.implicitHeight : 0
        Column {
            id: body
            objectName: "foldBody"
            width: parent.width; spacing: 8; bottomPadding: 14
            enabled: f.open
            opacity: f.open ? 1 : 0
            y: f.open ? 0 : -Theme.shift(6)
            Behavior on opacity { Glide { duration: f.open ? Theme.ui : Theme.exit } }
            Behavior on y { Glide { duration: Theme.move(f.open ? Theme.ui : Theme.exit) } }
        }
    }
}
