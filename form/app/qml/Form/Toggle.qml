import QtQuick

// On/off switch for a setting that takes effect at once (a Check is for a choice you confirm later).
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
        color: t.checked ? (ma.containsMouse ? Theme.datumHi : Theme.datum) : ma.containsMouse ? Theme.plate4 : Theme.plate3
        border.width: t.checked ? 0 : 1; border.color: Theme.rule2
        Behavior on color { Tint {} }
        Rectangle { y: 2; width: ma.pressed ? 17 : 14; height: 14; radius: 7
            x: t.checked ? parent.width - width - 2 : 2
            color: t.checked ? Theme.datumInk : Theme.ink2
            Behavior on x { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeSpring } }     // the knob lands with the faintest settle
            Behavior on width { Glide { duration: Theme.move(Theme.press) } }
            Behavior on color { Tint {} } } }
    FocusRing { on: t.activeFocus; radius: height / 2 + 3 }
    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; onClicked: t.toggled(!t.checked) }
}
