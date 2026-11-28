import QtQuick
import QtQuick.Window
import "F.js" as F

// Quick actions on the model: the viewport's context menu (right-click or long-press a feature) and its keys.
// Hiding is visual only: the solid, the checks and the exports are untouched. No animation: it is used all day.
Item {
    id: cm
    readonly property var m: Store.ctxMenu
    readonly property var feat: m && m.feature ? Store.featureById(m.feature) : null
    readonly property bool isHidden: !!feat && Store.hidden.indexOf(m.feature) >= 0
    readonly property var items: {
        if (!m) return []
        var f = m.feature, out = []
        if (feat) {
            out.push({ icon: "sliders_horizontal", text: "Edit parameters", key: "", run: function () { Store.pick(f) } })
            out.push({ icon: "message_square", text: "Ask the agent about this feature…", key: "", off: !Store.chat.available, run: function () { Store.askAbout(f) } })
            out.push({ icon: "focus", text: "Frame this feature", key: "F", run: function () { Store.select(f) } })
            out.push({ icon: "eye_off", text: "Hide feature", key: "H", run: function () { Store.toggleHidden(f) } })
            out.push({ icon: "copy", text: "Copy dimensions", key: "", run: function () { Store.copyDims(f) } })
        } else {
            out.push({ icon: "focus", text: "Frame the whole part", key: "F", run: function () { Store.select(""); Store.frameSelection() } })
            out.push({ icon: "rotate_ccw", text: "Reset the view", key: ".", run: function () { Store.resetView() } })
            out.push({ icon: "scissors", text: Store.sectionNow() ? "Remove the section cut" : "Cut a section", key: "X", run: function () { Store.toggleSection() } })
            out.push({ icon: "copy", text: "Copy overall dimensions", key: "", run: function () { Store.copyDims("") } })
        }
        if (Store.hidden.length) out.push({ icon: "eye", text: "Show all features", key: "⇧H", run: function () { Store.showAll() } })
        out.push({ icon: "keyboard", text: "Keyboard shortcuts", key: "?", run: function () { Store.openSheet("shortcuts") } })
        return out
    }
    function go(it) { Store.ctxMenu = null; if (it && !it.off) it.run() }

    MouseArea { anchors.fill: parent; enabled: !!cm.m; acceptedButtons: Qt.AllButtons; onPressed: Store.ctxMenu = null; onWheel: function (w) { Store.ctxMenu = null; w.accepted = false } }
    Glass {
        id: box
        visible: !!cm.m
        source: Store.backdrop; radius: Theme.rMd + 3
        onXChanged: place()
        onYChanged: place()
        width: 268; height: head.height + col.implicitHeight + 12
        x: cm.m ? Math.max(8, Math.min(cm.width - width - 8, cm.m.x + 2)) : 0
        y: cm.m ? Math.max(8, Math.min(cm.height - height - 8, cm.m.y + 2)) : 0
        Rectangle { anchors.fill: parent; radius: box.radius; color: Theme.alpha(Theme.plate3, box.blurred ? 0.46 : 0.85) }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
        Item { id: head; width: parent.width; height: cm.feat ? 36 : 6
            Row { visible: !!cm.feat; x: 15; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Txt { text: cm.feat ? cm.feat.label : ""; font.weight: 600; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Tag { text: cm.feat ? cm.feat.role : ""; anchors.verticalCenter: parent.verticalCenter } }
 }
        Column { id: col; x: 5; y: head.height; width: parent.width - 10
            Repeater { model: cm.items
                Rectangle { id: row; required property var modelData
                    width: parent.width; height: 30; radius: 10; opacity: modelData.off ? 0.4 : 1
                    color: rm.containsMouse && !modelData.off ? Theme.glass2 : "transparent"
                    Icon { x: 10; name: row.modelData.icon; size: 14; anchors.verticalCenter: parent.verticalCenter; color: rm.containsMouse ? Theme.datum : Theme.ink3 }
                    Txt { x: 33; text: row.modelData.text; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                    Txt { visible: row.modelData.key !== ""; text: row.modelData.key; mono: true; font.pixelSize: 11; tone: 3
                        anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: cm.go(row.modelData) } } } }
    }

    // ── viewport keys. Off while a sheet, the palette or a text box has the keyboard. ──
    readonly property var focusItem: Window.activeFocusItem
    readonly property bool keys: Store.screen === "work" && !Store.sheet && !Store.paletteOpen && !Store.layers && !(Store.sketchHost && Store.sketchHost.on)
        && !(focusItem && focusItem.cursorPosition !== undefined)
    Shortcut { sequence: "F"; enabled: cm.keys; onActivated: Store.frameSelection() }
    Shortcut { sequence: "1"; enabled: cm.keys; onActivated: Store.setView("iso") }
    Shortcut { sequence: "2"; enabled: cm.keys; onActivated: Store.setView("front") }
    Shortcut { sequence: "3"; enabled: cm.keys; onActivated: Store.setView("side") }
    Shortcut { sequence: "4"; enabled: cm.keys; onActivated: Store.setView("top") }
    Shortcut { sequence: "5"; enabled: cm.keys; onActivated: Store.setView("under") }
    Shortcut { sequence: "H"; enabled: cm.keys; onActivated: {
        if (Store.feature) Store.toggleHidden(Store.feature)
        else if (Store.hidden.length) Store.showAll()
        else Store.toast("Select a feature to hide", "Click it on the model, then press H. Hiding is visual only.") } }
    Shortcut { sequence: "Shift+H"; enabled: cm.keys; onActivated: Store.showAll() }
    Shortcut { sequence: "X"; enabled: cm.keys; onActivated: Store.toggleSection() }
    Shortcut { sequence: "."; enabled: cm.keys; onActivated: Store.resetView() }
    Shortcut { sequences: ["?", "Shift+/"]; enabled: Store.screen === "work" && !Store.paletteOpen && !(cm.focusItem && cm.focusItem.cursorPosition !== undefined)
        onActivated: Store.openSheet(Store.sheet && Store.sheet.kind === "shortcuts" ? null : "shortcuts") }
}
