import QtQuick
import QtQuick.Controls
import "F.js" as F

// Saved conversations: search, open, rename, pin, delete (with a confirm). Used in the switcher popover of the
// agent column and, compact, under the prompt on the home screen.
Item {
    id: cl
    property bool compact: false           // home: no search box, no groups, a short list
    property int limit: compact ? 7 : 200
    property string query: ""
    property var found: null               // search results from the engine (it also looks inside the messages)
    property string renaming: ""
    property string confirming: ""
    signal chosen()
    implicitHeight: col.implicitHeight

    readonly property var all: (found !== null ? found : Store.convs).filter(function (c) { return c.messages > 0 || c.id === Store.convId })
    readonly property var here: compact || !Store.pid ? [] : all.filter(function (c) { return c.project === Store.pid })
    readonly property var rest: (compact || !Store.pid ? all : all.filter(function (c) { return c.project !== Store.pid })).slice(0, limit)
    function projectName(id) {
        if (!id) return "General"
        var ps = Store.studio ? Store.studio.projects : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i].name
        return id
    }
    function search(text) { query = text; debounce.restart() }
    Timer { id: debounce; interval: 160
        onTriggered: {
            var q = cl.query.trim()
            if (!q) { cl.found = null; return }
            Store.get("/conversations?q=" + encodeURIComponent(q)).then(function (r) { if (cl.query.trim() === q) cl.found = r.conversations }, function () {})
        } }
    Component.onCompleted: Store.loadConvs()
    function reset() { query = ""; found = null; renaming = ""; confirming = ""; if (box.visible) { box.text = ""; box.input.forceActiveFocus() } }

    Column {
        id: col; width: parent.width; spacing: 2
        Field { id: box; visible: !cl.compact; width: parent.width; placeholder: "Search conversations"
            onEdited: function (t) { cl.search(t) }
            onAccepted: function () { var l = cl.here.concat(cl.rest); if (l.length) { Store.openConv(l[0].id); cl.chosen() } } }
        Item { visible: !cl.compact; width: 1; height: 4 }
        // new conversation
        Rectangle { visible: !cl.compact; width: parent.width; height: 34; radius: Theme.rSm; color: nm.pressed ? Theme.washPress : nm.containsMouse ? Theme.washHover : "transparent"
            Icon { x: 8; name: "plus"; size: 14; anchors.verticalCenter: parent.verticalCenter; color: Theme.datum }
            Txt { x: 30; text: "New conversation"; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wMedium }
            Kbd { keys: "Ctrl+Shift+O"; quiet: true; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true; onClicked: { Store.newChat(); cl.chosen() } } }

        Item { visible: cl.here.length > 0; width: parent.width; height: 28; Txt { kind: "cap"; x: 8; y: 12; text: "This design" } }
        Repeater { model: cl.here; delegate: rowC }
        Item { visible: !cl.compact && cl.rest.length > 0; width: parent.width; height: 28; Txt { kind: "cap"; x: 8; y: 12; text: Store.pid && cl.here.length ? "All other" : "All" } }
        Repeater { model: cl.rest; delegate: rowC }
        Item { visible: cl.all.length === 0; width: 1; height: 8 }
        Txt { visible: cl.all.length === 0; x: 8; width: parent.width - 16; kind: "fine"
            text: cl.query.trim() ? "No conversation mentions “" + cl.query.trim() + "”." : "No saved conversations yet. They are kept in your projects folder." }
    }

    Component {
        id: rowC
        Rectangle {
            id: row
            objectName: "convRow"
            required property var modelData
            readonly property var c: modelData
            readonly property bool current: c.id === Store.convId
            readonly property bool asking: cl.confirming === c.id
            readonly property bool editing: cl.renaming === c.id
            width: col.width; height: 44; radius: Theme.rSm
            color: asking ? Theme.alpha(Theme.signal, 0.09) : current ? Theme.washOn : rm.pressed ? Theme.washPress : rm.containsMouse ? Theme.washHover : "transparent"
            Behavior on color { Tint {} }
            MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true
                onClicked: { if (!row.asking && !row.editing) { Store.openConv(row.c.id); cl.chosen() } } }
            // normal
            Column { visible: !row.asking && !row.editing; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                width: parent.width - 20 - (acts.visible ? acts.width + 4 : dot.visible ? 16 : 0)
                Row { spacing: 6; width: parent.width
                    Icon { visible: row.c.pinned; name: "pin"; size: 11; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: row.c.title; width: parent.width - (row.c.pinned ? 17 : 0); elide: Text.ElideRight; wrapMode: Text.NoWrap; font.weight: row.current ? 600 : 500 } }
                Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    color: row.c.state === "asking" ? Theme.amber : Theme.ink3
                    text: row.c.state === "asking" ? "Waiting for your answer · " + cl.projectName(row.c.project) : row.c.match ? row.c.match
                        : (!cl.compact && Store.pid && row.c.project === Store.pid ? "" : (row.c.project ? cl.projectName(row.c.project) : row.c.project_was ? row.c.project_was.name + " (in the trash)" : "General") + " · ") + F.ago(row.c.updated) + " · " + F.plural(row.c.messages, "message") } }
            Rectangle { id: dot; visible: (row.c.state === "running" || row.c.state === "asking") && !acts.visible; width: 7; height: 7; radius: 3.5
                color: row.c.state === "asking" ? Theme.amber : Theme.datum
                anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                SequentialAnimation on opacity { running: dot.visible; loops: Animation.Infinite
                    NumberAnimation { to: 0.3; duration: 600 } NumberAnimation { to: 1; duration: 600 } } }
            Row { id: acts; visible: rm.containsMouse && !row.asking && !row.editing || pb.hovered || eb.hovered || db.hovered
                anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter; spacing: 0
                Btn { id: pb; objectName: "convPin"; small: true; kind: "quiet"; icon: row.c.pinned ? "pin_off" : "pin"; tip: row.c.pinned ? "Unpin" : "Pin to the top"
                    onClicked: Store.pinConv(row.c.id, !row.c.pinned) }
                Btn { id: eb; objectName: "convRename"; small: true; kind: "quiet"; icon: "pencil"; tip: "Rename"
                    onClicked: { cl.confirming = ""; cl.renaming = row.c.id; rf.text = row.c.title; rf.input.forceActiveFocus(); rf.input.selectAll() } }
                Btn { id: db; objectName: "convDelete"; small: true; kind: "quiet"; icon: "trash_2"; tip: "Delete"; onClicked: { cl.renaming = ""; cl.confirming = row.c.id } } }
            // rename
            Field { id: rf; objectName: "convRenameField"; visible: row.editing; x: 6; width: parent.width - 12; anchors.verticalCenter: parent.verticalCenter
                onAccepted: function (t) { if (!row.editing) return; cl.renaming = ""; if (t.trim() && t.trim() !== row.c.title) Store.renameConv(row.c.id, t) }
                Keys.onEscapePressed: cl.renaming = ""
                Connections { target: rf.input; function onActiveFocusChanged() { if (!rf.input.activeFocus && row.editing) cl.renaming = "" } } }
            // delete?
            Row { visible: row.asking; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8; width: parent.width - 20
                Txt { text: "Delete this conversation and its attachments?"; width: parent.width - kb.width - xb.width - 16; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
                Btn { id: xb; objectName: "convDeleteYes"; small: true; kind: "danger"; text: "Delete"; onClicked: { cl.confirming = ""; Store.deleteConv(row.c.id) } }
                Btn { id: kb; small: true; kind: "quiet"; text: "Keep"; onClicked: cl.confirming = "" } }
        }
    }
}
