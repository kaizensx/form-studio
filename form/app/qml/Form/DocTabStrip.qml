import QtQuick

// The design's open things as tabs, in the top row right of the design capsule (Frame.qml says what they are).
// The same glass capsule as its neighbours; the tab in front is lit as a mode is. Each tab but the model closes,
// and drags along the row to a new place; Ctrl+1..9 (⌘ on macOS) switches. When the row has no room for every
// tab, the one in front stays and the others are behind a count that opens them as a menu.
Glass {
    id: ts
    objectName: "docTabs"
    property real room: 400                   // the width it may take
    readonly property var model: Frame.all
    readonly property bool on: model.length > 1
    height: 44; radius: 22
    FontMetrics { id: fm; font.family: Theme.sans; font.pixelSize: 12; font.weight: Theme.wMedium }
    function natural(t) { return t ? Math.ceil(fm.advanceWidth(t.title)) + 14 + 6 + 20 + (t.key === "design" ? 0 : 18) : 0 }
    readonly property real need: { var w = 8; for (var i = 0; i < model.length; i++) w += Math.min(168, natural(model[i])) + (i ? 2 : 0); return w }
    // too many for the room: the tab in front, and a count for the rest
    readonly property bool folded: need > room
    readonly property var shown: folded ? [model[Math.min(Frame.index, model.length - 1)]].filter(function (t) { return !!t }) : model
    readonly property int hidden: model.length - shown.length
    width: Math.round(Math.min(room, folded ? 8 + Math.min(Math.max(80, room - 8 - 64), natural(shown[0])) + 2 + 56 : need))
    visible: on && room >= 120

    property int dragFrom: -1
    property real dragDx: 0
    Row {
        id: row; x: 4; y: 4; height: parent.height - 8; spacing: 2
        Repeater {
            model: ts.shown
            Item {
                id: tab
                required property var modelData
                required property int index
                readonly property bool front: modelData.key === Frame.active
                readonly property int at: ts.folded ? Frame.index : index       // its place in Frame.all
                objectName: "docTab-" + modelData.key
                width: Math.min(168, ts.natural(modelData), ts.folded ? Math.max(80, ts.room - 8 - 64) : 1e9); height: row.height
                z: ts.dragFrom === at ? 2 : 0
                transform: Translate { x: ts.dragFrom === tab.at ? ts.dragDx : 0 }
                Rectangle { anchors.fill: parent; radius: height / 2
                    color: tab.front ? (Theme.dark ? Theme.glass2 : Theme.plate3) : tm.pressed ? Theme.washPress : tm.containsMouse ? Theme.washHover : "transparent"
                    border.width: tab.front && !Theme.dark ? 1 : 0; border.color: Theme.rule
                    Behavior on color { Tint {} } }
                Row { x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                    Icon { name: tab.modelData.icon || "file"; size: 14; anchors.verticalCenter: parent.verticalCenter
                        color: tab.front ? Theme.datum : tm.containsMouse ? Theme.ink : Theme.ink3 }
                    Txt { text: tab.modelData.title; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        width: Math.min(implicitWidth, tab.width - 10 - 14 - 6 - (tab.modelData.key === "design" ? 10 : 28))
                        anchors.verticalCenter: parent.verticalCenter; color: tab.front || tm.containsMouse ? Theme.ink : Theme.ink2 } }
                MouseArea {
                    id: tm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    preventStealing: true          // the top row moves the window when dragged; a tab keeps its own drag
                    property real x0: 0; property bool moved: false
                    function rowX(e) { return mapToItem(row, e.x, 0).x }      // the tab moves under the pointer: measure in the row
                    onPressed: function (e) { x0 = rowX(e); moved = false }
                    onPositionChanged: function (e) {
                        if (!pressed || tab.modelData.key === "design" || ts.folded) return
                        if (!moved && Math.abs(rowX(e) - x0) > 6) { moved = true; ts.dragFrom = tab.at }
                        if (moved) ts.dragDx = rowX(e) - x0
                    }
                    onReleased: function (e) {
                        if (moved) {                         // dropped: the place whose middle it passed
                            var mid = tab.x + tab.width / 2 + ts.dragDx, to = tab.at
                            for (var i = 1; i < row.children.length; i++) { var c = row.children[i]; if (c.at !== undefined && c !== tab && c.at > 0) {
                                if (c.at > tab.at && mid > c.x + c.width / 2) to = Math.max(to, c.at)
                                if (c.at < tab.at && mid < c.x + c.width / 2) to = Math.min(to, c.at) } }
                            ts.dragFrom = -1; ts.dragDx = 0
                            if (to !== tab.at) Frame.move(tab.at, to)
                            return
                        }
                        if (e.button === Qt.MiddleButton) Frame.close(tab.modelData.key); else Frame.activate(tab.modelData.key)
                    }
                    onCanceled: { ts.dragFrom = -1; ts.dragDx = 0 }
                }
                // close: on every tab but the model
                Item { id: closeBox; objectName: "docTabClose-" + tab.modelData.key; visible: tab.modelData.key !== "design"
                    width: 20; height: 20; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                    opacity: tab.front || tm.containsMouse || cm.containsMouse ? 1 : 0.0
                    Rectangle { anchors.fill: parent; radius: 10; color: cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.washHover : "transparent" }
                    Icon { anchors.centerIn: parent; name: "x"; size: 12; color: cm.containsMouse ? Theme.ink : Theme.ink3 }
                    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; onClicked: Frame.close(tab.modelData.key) } }
                Tip { show: tm.containsMouse && !tm.pressed; below: true; text: tab.modelData.full || tab.modelData.title
                    keys: tab.at < 9 ? Theme.tabMod + "+" + (tab.at + 1) : "" }
            }
        }
        // the rest, folded: a count that opens them
        Item {
            id: rest; objectName: "docTabsMore"; visible: ts.hidden > 0; width: 56; height: row.height
            Rectangle { anchors.fill: parent; radius: height / 2; color: rm.pressed ? Theme.washPress : rm.containsMouse || restMenu.opened ? Theme.washHover : "transparent" }
            Row { anchors.centerIn: parent; spacing: 4
                Txt { mono: true; font.pixelSize: 12; text: "+" + ts.hidden; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter } }
            MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: restMenu.opened ? restMenu.close() : restMenu.open() }
            Tip { show: rm.containsMouse; below: true; text: ts.model.length + " open: " + ts.model.map(function (t) { return t.full || t.title }).join(", ") }
            PopMenu { id: restMenu; y: parent.height + 12; width: 240
                model: ts.model.map(function (t, i) { return { name: "docTabMenu-" + t.key, icon: t.icon, text: t.title, checked: t.key === Frame.active,
                                                               keys: i < 9 ? Theme.tabMod + "+" + (i + 1) : "", run: function () { Frame.activate(t.key) } } }) }
        }
    }
}
