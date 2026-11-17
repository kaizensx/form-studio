import QtQuick

// Checkbox. Space toggles it when it has keyboard focus.
Item {
    id: c
    property bool checked: false
    signal toggled(bool checked)
    implicitWidth: 16; implicitHeight: 16
    opacity: enabled ? 1 : 0.4
    activeFocusOnTab: true          // Qt skips hidden and disabled items by itself
    Keys.onSpacePressed: toggled(!checked)
    Rectangle { anchors.fill: parent; radius: Theme.rXs
        color: c.checked ? (ma.containsMouse ? Theme.datumHi : Theme.datum) : ma.pressed ? Theme.plate2 : Theme.well
        border.width: c.checked ? 0 : 1; border.color: ma.containsMouse ? Theme.rule3 : Theme.rule2
        scale: ma.pressed ? Theme.from(0.92) : 1
        Behavior on scale { Glide { duration: Theme.press } }
        Behavior on color { Tint {} }
        Icon { anchors.centerIn: parent; name: "check"; size: 12; color: Theme.datumInk; opacity: c.checked ? 1 : 0; scale: c.checked ? 1 : Theme.from(0.6)
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            Behavior on scale { Glide { duration: Theme.fast } } } }
    FocusRing { on: c.activeFocus; radius: Theme.rXs + 3 }
    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -8; hoverEnabled: true; onClicked: c.toggled(!c.checked) }
}
