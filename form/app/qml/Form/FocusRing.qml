import QtQuick

// Keyboard focus ring. Put it inside a control: FocusRing { on: control.activeFocus; radius: Theme.rSm + 3 }
Rectangle {
    property bool on: false
    property int gap: 2
    anchors.fill: parent; anchors.margins: -gap - 1
    color: "transparent"; border.width: 2; border.color: Theme.focus
    z: 5
    // the ring closes in on the control as focus lands, and fades when it leaves
    opacity: on ? 1 : 0; visible: opacity > 0
    scale: on ? 1 : Theme.from(1.06)
    Behavior on opacity { NumberAnimation { duration: on ? Theme.pop : Theme.exit } }
    Behavior on scale { Glide { duration: Theme.pop } }
}
