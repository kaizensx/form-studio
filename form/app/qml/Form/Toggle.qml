import QtQuick

// On/off switch for a setting that takes effect at once (a Check is for a choice you confirm later).
// Lightdesk: a 30 x 18 capsule, green (pass) when on, with a white knob that glides across.
Item {
    id: t
    property bool checked: false
    signal toggled(bool checked)
    implicitWidth: 30; implicitHeight: 18
    opacity: enabled ? 1 : 0.4
    activeFocusOnTab: true          // Qt skips hidden and disabled items by itself
    Keys.onSpacePressed: toggled(!checked)
    Keys.onReturnPressed: toggled(!checked)
    Rectangle { anchors.fill: parent; radius: height / 2
        color: t.checked ? (ma.containsMouse ? Qt.lighter(Theme.pass, 1.08) : Theme.pass)
             : Theme.alpha(Theme.lineBase, ma.containsMouse ? (Theme.dark ? 0.26 : 0.24) : (Theme.dark ? 0.18 : 0.17))
        Behavior on color { Tint {} }
        Rectangle { y: 2; width: ma.pressed ? 17 : 14; height: 14; radius: 7
            x: t.checked ? parent.width - width - 2 : 2
            color: Qt.rgba(1, 1, 1, t.checked || !Theme.dark ? 1 : 0.82)
            Behavior on x { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeSpring } }     // the knob lands with the faintest settle
            Behavior on width { Glide { duration: Theme.move(Theme.press) } }
            Behavior on color { Tint {} } } }
    FocusRing { on: t.activeFocus; radius: height / 2 + 3 }
    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; onClicked: t.toggled(!t.checked) }
}
