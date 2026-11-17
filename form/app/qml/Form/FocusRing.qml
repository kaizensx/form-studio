import QtQuick

// Keyboard focus ring. Put it inside a control: FocusRing { on: control.activeFocus; radius: Theme.rSm + 3 }
Rectangle {
    property bool on: false
    property int gap: 2
    anchors.fill: parent; anchors.margins: -gap - 1
    color: "transparent"; border.width: 2; border.color: Theme.focus
    visible: on; z: 5
}
