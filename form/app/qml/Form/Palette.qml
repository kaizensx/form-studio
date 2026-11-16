import QtQuick
import FormNative
import "F.js" as F

// Command palette: every action and every project, from the keyboard. No animation — it is used all day.
Item {
    id: pal
    anchors.fill: parent; visible: Store.paletteOpen; z: 50
    onVisibleChanged: if (visible) { q.text = ""; sel = 0; q.input.forceActiveFocus() }
    property int sel: 0
    readonly property var all: {
        var c = [], w = Store.screen === "work"
        if (w) {
            Store.stages.forEach(function (s) { c.push({ icon: "arrow_right", text: "Go to " + s.title, hint: s.hint, run: function () { Store.setStage(s.id) } }) })
            ;["iso", "front", "side", "top", "under"].forEach(function (v) { c.push({ icon: "rotate_3d", text: "View: " + v, hint: "Camera", run: function () { Store.setView(v) } }) })
            ;["x", "y", "z"].forEach(function (a) { c.push({ icon: "scissors", text: "Cut along " + a.toUpperCase(), hint: "Section view", run: function () { Store.setSection(a, 0.5) } }) })
            c.push({ icon: "scissors", text: "Remove the section cut", hint: "Section view", run: function () { Store.setSection("", 0.5) } })
            c.push({ icon: "ruler", text: (Store.dims ? "Hide" : "Show") + " overall dimensions", hint: "Viewport", run: function () { Store.toggleDims() } })
            c.push({ icon: "play", text: "Regenerate everything", hint: "Solid, exports, checks, slice", run: function () { Store.run() } })
            c.push({ icon: "boxes", text: "Compare alternatives", hint: "Build a grid of candidates", run: function () { Store.openSheet("alternatives") } })
            c.push({ icon: "camera", text: "Render in Blender", hint: "An illustration of the current revision", run: function () { Store.openSheet("render") } })
            if (Store.hasDraft) { c.push({ icon: "git_commit_horizontal", text: "Commit the draft", hint: "Saves a revision", run: function () { Store.commit() } })
                c.push({ icon: "undo_2", text: "Discard the draft", hint: "", run: function () { Store.discard() } }) }
            c.push({ icon: "home", text: "All designs", hint: "Home", run: function () { Store.home() } })
        }
        c.push({ icon: "plus", text: "New design from a recipe", hint: "", run: function () { Store.openSheet("new") } })
        c.push({ icon: "message_square", text: "New conversation with Claude", hint: "", run: function () { Store.newChat(); Store.talkOpen = true } })
        c.push({ icon: "folder_open", text: "Open the projects folder", hint: Bridge.dataDir, run: function () { Bridge.openDataFolder() } })
        if (Store.studio) Store.studio.projects.forEach(function (p) { if (!p.error && p.id !== Store.pid) c.push({ icon: "cuboid", text: p.name, hint: "Open design · " + F.pad(p.head), run: function () { Store.open(p.id) } }) })
        return c
    }
    readonly property var hits: { var t = q.text.trim().toLowerCase(); return all.filter(function (c) { return !t || (c.text + " " + c.hint).toLowerCase().indexOf(t) >= 0 }).slice(0, 9) }
    function go(i) { var h = hits[i]; Store.paletteOpen = false; if (h) h.run() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.45); MouseArea { anchors.fill: parent; onClicked: Store.paletteOpen = false } }
    Rectangle {
        width: 560; height: 52 + Math.max(1, pal.hits.length) * 38 + 10; anchors.horizontalCenter: parent.horizontalCenter; y: 110
        radius: Theme.rLg; color: Theme.plate2; border.color: Theme.rule2
        Icon { x: 16; y: 18; name: "search"; size: 16; color: Theme.ink3 }
        Field { id: q; x: 40; y: 10; width: parent.width - 56; height: 32; color: "transparent"; border.width: 0; placeholder: "Type a command or a design name"
            onEdited: pal.sel = 0
            input.Keys.onPressed: function (e) {
                if (e.key === Qt.Key_Down) { pal.sel = Math.min(pal.hits.length - 1, pal.sel + 1); e.accepted = true }
                else if (e.key === Qt.Key_Up) { pal.sel = Math.max(0, pal.sel - 1); e.accepted = true }
                else if (e.key === Qt.Key_Escape) { Store.paletteOpen = false; e.accepted = true }
                else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { pal.go(pal.sel); e.accepted = true }
            } }
        Rectangle { y: 51; width: parent.width; height: 1; color: Theme.rule }
        Column { y: 56; x: 6; width: parent.width - 12
            Repeater { model: pal.hits
                Rectangle { required property var modelData; required property int index
                    width: parent.width; height: 38; radius: Theme.rSm; color: index === pal.sel ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
                    Icon { x: 10; name: modelData.icon; size: 14; anchors.verticalCenter: parent.verticalCenter; color: index === pal.sel ? Theme.datum : Theme.ink3 }
                    Txt { x: 36; text: modelData.text; anchors.verticalCenter: parent.verticalCenter }
                    Txt { anchors.right: parent.right; anchors.rightMargin: 12; kind: "fine"; text: modelData.hint; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 240); elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                    MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: pal.sel = index; onClicked: pal.go(index) } } }
            Txt { visible: pal.hits.length === 0; x: 10; height: 38; verticalAlignment: Text.AlignVCenter; tone: 3; text: "Nothing matches." } }
    }
}
