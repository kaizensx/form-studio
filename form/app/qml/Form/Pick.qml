import QtQuick
import QtQuick.Controls

// Dropdown. model: [{ value, text }] ; value is the current selection. Space/Enter/Down open it from the keyboard.
Rectangle {
    id: p
    property var model: []
    property var value: null
    signal picked(var value)
    function label() { for (var i = 0; i < model.length; i++) if (model[i].value === value) return model[i].text; return "" }
    function _index() { for (var i = 0; i < model.length; i++) if (model[i].value === value) return i; return -1 }
    implicitHeight: Theme.hMd; implicitWidth: 140; radius: Theme.rSm
    opacity: enabled ? 1 : 0.5
    color: pm.pressed ? Theme.plate : Theme.well; border.width: 1; border.color: pop.opened ? Theme.datum : pm.containsMouse ? Theme.rule3 : Theme.rule2
    Behavior on border.color { Tint {} }
    activeFocusOnTab: true
    Keys.onSpacePressed: { pop.instant = true; pop.open() }
    Keys.onReturnPressed: { pop.instant = true; pop.open() }
    Keys.onDownPressed: { pop.instant = true; pop.open() }
    FocusRing { on: p.activeFocus && !pop.opened; radius: p.radius + 3 }
    Txt { text: p.label(); anchors.left: parent.left; anchors.right: chev.left; anchors.leftMargin: 9; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13 }
    Icon { id: chev; name: "chevrons_up_down"; size: 12; anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter; color: pm.containsMouse || pop.opened ? Theme.ink2 : Theme.ink3 }
    MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; onClicked: { pop.instant = false; pop.opened ? pop.close() : pop.open() } }
    Pop {
        id: pop; y: parent.height + 4; width: Math.max(parent.width, 180); padding: 4; focus: true
        height: Math.min(list.contentHeight + 8, 280)
        onOpened: { list.currentIndex = p._index(); list.forceActiveFocus() }
        onClosed: if (instant) p.forceActiveFocus()
        ListView {
            id: list; anchors.fill: parent; clip: true; model: p.model; boundsBehavior: Flickable.StopAtBounds; keyNavigationEnabled: true; highlightMoveDuration: 0
            Keys.onReturnPressed: if (currentIndex >= 0) { var v = p.model[currentIndex].value; pop.close(); p.picked(v) }
            Keys.onEnterPressed: if (currentIndex >= 0) { var v2 = p.model[currentIndex].value; pop.close(); p.picked(v2) }
            ScrollBar.vertical: ScrollBar { width: 6 }
            delegate: Rectangle {
                id: opt
                required property var modelData
                required property int index
                width: list.width; height: 26; radius: Theme.rXs
                color: list.currentIndex === index ? Theme.washOn : "transparent"
                Txt { text: opt.modelData.text; x: 8; width: parent.width - 34; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13 }
                Icon { visible: opt.modelData.value === p.value; name: "check"; size: 13; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
                MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: list.currentIndex = opt.index; onClicked: { pop.close(); p.picked(opt.modelData.value) } }
            }
        }
    }
}
