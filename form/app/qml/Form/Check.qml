import QtQuick

Item {
    id: c
    property bool checked: false
    signal toggled(bool checked)
    implicitWidth: 16; implicitHeight: 16
    Rectangle { anchors.fill: parent; radius: 4; color: c.checked ? Theme.datum : Theme.well; border.width: c.checked ? 0 : 1; border.color: Theme.rule2
        Icon { anchors.centerIn: parent; name: "check"; size: 12; color: Theme.datumInk; visible: c.checked } }
    MouseArea { anchors.fill: parent; anchors.margins: -8; onClicked: c.toggled(!c.checked) }
}
