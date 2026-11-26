import QtQuick
import QtQuick.Controls

// A menu of actions in a popover. model: [{ text, icon?, keys?, danger?, enabled?, checked?, run() } | { sep: true }]
// Up/Down move, Enter runs, Esc closes. openAt(item, x, y) opens it at a point of `item` (a right-click), open() where it was placed.
Pop {
    id: m
    property var model: []
    property int sel: -1
    signal ran(var entry)
    width: 232; padding: 5; focus: true
    function openAt(item, px, py) {
        var p = item.mapToItem(m.parent, px, py)
        m.x = Math.round(p.x); m.y = Math.round(p.y); m.open()
    }
    function _move(d) {
        var n = model.length, i = sel
        for (var k = 0; k < n; k++) { i = (i + d + n) % n; if (!model[i].sep && model[i].enabled !== false) { sel = i; return } }
    }
    function _run(i) { var e = model[i]; if (!e || e.sep || e.enabled === false) return; m.close(); if (e.run) e.run(); m.ran(e) }
    onOpened: { sel = -1; col.forceActiveFocus() }
    contentItem: Column {
        id: col; spacing: 1; focus: true
        Keys.onDownPressed: m._move(1)
        Keys.onUpPressed: m._move(-1)
        Keys.onReturnPressed: m._run(m.sel)
        Keys.onEnterPressed: m._run(m.sel)
        Repeater {
            model: m.model
            Item {
                id: row
                required property var modelData
                required property int index
                readonly property bool off: modelData.enabled === false
                width: col.width; height: modelData.sep ? 9 : 30
                Rectangle { visible: !!row.modelData.sep; y: 4; x: 10; width: parent.width - 20; height: 1; color: Theme.rule }
                Rectangle { visible: !row.modelData.sep; anchors.fill: parent; radius: 10
                    color: m.sel === row.index && !row.off ? (row.modelData.danger ? Theme.alpha(Theme.signal, 0.14) : Theme.glass2) : "transparent" }
                Icon { visible: !row.modelData.sep && !!row.modelData.icon; x: 10; size: 14; anchors.verticalCenter: parent.verticalCenter; name: row.modelData.icon || "dot"
                    opacity: row.off ? 0.4 : 1; color: row.modelData.danger ? Theme.signal : m.sel === row.index ? Theme.ink : Theme.ink2 }
                Txt { visible: !row.modelData.sep; x: row.modelData.icon ? 33 : 11; anchors.verticalCenter: parent.verticalCenter; text: row.modelData.text || ""
                    width: parent.width - x - 10 - (kb.visible ? kb.width + 8 : 0) - (ck.visible ? 22 : 0); elide: Text.ElideRight; wrapMode: Text.NoWrap
                    opacity: row.off ? 0.4 : 1; color: row.modelData.danger ? Theme.signal : Theme.ink }
                Kbd { id: kb; visible: !row.modelData.sep && !!row.modelData.keys; keys: row.modelData.keys || ""; quiet: true; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter }
                Icon { id: ck; visible: !!row.modelData.checked; name: "check"; size: 13; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter }
                MouseArea { anchors.fill: parent; hoverEnabled: true; enabled: !row.modelData.sep
                    onEntered: m.sel = row.index; onClicked: m._run(row.index) }
            }
        }
    }
}
