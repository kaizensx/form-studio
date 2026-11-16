import QtQuick
import QtQuick.Controls

// Dropdown. model: [{ value, text }] ; value is the current selection.
Rectangle {
    id: p
    property var model: []
    property var value: null
    signal picked(var value)
    function label() { for (var i = 0; i < model.length; i++) if (model[i].value === value) return model[i].text; return "" }
    implicitHeight: 28; implicitWidth: 140; radius: Theme.rSm
    color: Theme.well; border.width: 1; border.color: pop.opened ? Theme.datum : Theme.rule2
    Txt { text: p.label(); anchors.left: parent.left; anchors.right: chev.left; anchors.leftMargin: 9; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13 }
    Icon { id: chev; name: "chevron_down"; size: 13; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink3 }
    MouseArea { anchors.fill: parent; onClicked: pop.opened ? pop.close() : pop.open() }
    Popup {
        id: pop; y: parent.height + 4; width: Math.max(parent.width, 180); padding: 4
        height: Math.min(list.contentHeight + 8, 280)
        background: Rectangle { color: Theme.plate3; radius: Theme.rMd; border.color: Theme.rule2 }
        enter: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 140; easing.type: Easing.OutCubic } } }
        ListView {
            id: list; anchors.fill: parent; clip: true; model: p.model; boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                required property var modelData
                width: list.width; height: 26; radius: Theme.rXs
                color: hm.containsMouse ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
                Txt { text: modelData.text; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13
                    color: modelData.value === p.value ? Theme.datum : Theme.ink }
                MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: { pop.close(); p.picked(modelData.value) } }
            }
        }
    }
}
