import QtQuick

// The visibility eye of a feature in the tree: hides it in the 3D view only (Store.hidden). The solid, the checks and
// the exports are unchanged; that is suppress, in the line's menu. Shown on the hovered line, and on any line hidden.
Item {
    id: eye
    property string fid: ""
    property bool hot: false
    readonly property bool off: Store.hidden.indexOf(fid) >= 0
    readonly property bool hovered: em.containsMouse
    objectName: "featureEye-" + fid
    width: 24; height: 24
    Rectangle { anchors.fill: parent; radius: 7; color: em.containsMouse ? Theme.plate4 : "transparent" }
    Icon { anchors.centerIn: parent; name: eye.off ? "eye_off" : "eye"; size: 13; color: eye.off ? Theme.amber : Theme.ink2 }
    MouseArea { id: em; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.toggleHidden(eye.fid) }
    Tip { show: em.containsMouse; text: eye.off ? "Show it again (it was only hidden in the view)" : "Hide it in the view only: the solid, the checks and the files keep it" }
}
