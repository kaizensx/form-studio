import QtQuick
import "F.js" as F

// The project rail of a workspace: Home, the Bench, the designs you worked on last with how many conversations each
// has, Trash and Settings. Folded it is a column of 44 px icons that takes no width from the stage: beside the
// conversation's column it stands at the window's edge and the column gives it the room; with the conversation
// folded to the bar it stands under the tool dock, in the dock's own column. Opened (remembered) it is 220 px with
// the names, and the conversation and the stage move right of it.
Glass {
    id: pr
    objectName: "projectRail"
    property bool col: false                  // the conversation is a column (Main.qml): the rail is full height beside it
    property real fullH: 600                  // the window's height under the top row
    readonly property bool open: Frame.railOpen
    readonly property bool tall: open || col
    radius: open ? Theme.rPane : 22
    width: open ? 220 : 44

    // the designs, newest first, the open one among them; how many conversations each one has
    readonly property var designs: {
        var ps = Store.studio && Store.studio.projects ? Store.studio.projects.filter(function (p) { return !p.error }) : []
        return ps.slice().sort(function (a, b) { return (b.updated || 0) - (a.updated || 0) })
    }
    readonly property var convCount: {
        var n = ({}), cs = Store.convs || []
        for (var i = 0; i < cs.length; i++) { var p = cs[i].project; if (p) n[p] = (n[p] || 0) + 1 }
        return n
    }
    readonly property int trashed: Store.studio && Store.studio.trash ? Store.studio.trash : 0
    // how many designs fit: the rows that are always there (5 × 34 px folded, 38 opened) and two rules; in a low window
    // under the dock (`tight`) the rail keeps Projects, Home, the Bench and Settings, and Trash is a click away when opened
    readonly property real avail: tall ? fullH : Math.max(0, Frame.footTop - 12 - (Frame.dockFoot + 12))
    readonly property int rowH: open ? 38 : 34
    readonly property bool tight: !tall && avail < 12 + 5 * rowH + 18
    readonly property int fit: tight ? 0 : Math.max(0, Math.min(open ? 8 : 6, designs.length, Math.floor((avail - 12 - 5 * rowH - 18) / rowH)))
    readonly property var recent: designs.slice(0, fit)
    height: tall ? fullH : col1.implicitHeight + 12
    visible: Store.screen === "work" && (tall || avail >= 12 + 4 * rowH)
    Component.onCompleted: Store.loadConvs()
    Connections { target: Store; function onPidChanged() { Store.loadConvs() } }

    component RailRow: Item {
        id: rr
        property string icon: ""
        property string letter: ""            // a design: its first letter in a disc, where an icon would be
        property string label: ""
        property string side: ""              // right of the label: a count or a key
        property string keys: ""
        property string tip: ""
        property bool lit: false              // where you are
        signal clicked()
        width: pr.open ? 204 : 32; height: pr.open ? 36 : 32
        Rectangle { anchors.fill: parent; radius: pr.open ? 12 : 16
            color: rm.pressed ? Theme.washPress : rr.lit ? Theme.washOn : rm.containsMouse ? Theme.washHover : "transparent"
            Behavior on color { Tint {} } }
        Item { id: glyph; width: pr.open ? 36 : 32; height: parent.height
            Icon { visible: rr.icon !== ""; anchors.centerIn: parent; name: rr.icon; size: 16; color: rm.containsMouse || rr.lit ? Theme.ink : Theme.ink2 }
            Rectangle { visible: rr.letter !== ""; anchors.centerIn: parent; width: 22; height: 22; radius: 11
                color: rr.lit ? Theme.alpha(Theme.datum, 0.16) : Theme.glass2; border.width: 1; border.color: rr.lit ? Theme.alpha(Theme.datum, 0.7) : Theme.rule2
                Txt { anchors.centerIn: parent; text: rr.letter; mono: true; font.pixelSize: 11; font.weight: Theme.wSemi; topPadding: 0; bottomPadding: 0; lineHeight: 1
                    color: rr.lit ? Theme.datum : Theme.ink2; wrapMode: Text.NoWrap } } }
        Txt { visible: pr.open; x: 36; width: parent.width - 36 - sideT.width - 12; anchors.verticalCenter: parent.verticalCenter
            text: rr.label; font.pixelSize: 13; font.weight: rr.lit ? Theme.wSemi : Theme.wMedium; wrapMode: Text.NoWrap; elide: Text.ElideRight
            color: rr.lit || rm.containsMouse ? Theme.ink : Theme.ink2 }
        Txt { id: sideT; visible: pr.open && text !== ""; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
            text: rr.keys ? Theme.keyText(rr.keys) : rr.side; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap }
        MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: rr.clicked() }
        Tip { show: rm.containsMouse && (!pr.open || rr.tip !== ""); text: pr.open ? rr.tip : (rr.tip || rr.label); keys: pr.open ? "" : rr.keys }
    }
    component Rule: Item { width: pr.open ? 204 : 36; height: 9
        Rectangle { x: pr.open ? 10 : 8; y: 4; width: parent.width - 2 * x; height: 1; color: Theme.rule } }

    Column {
        id: col1; x: pr.open ? 8 : 6; y: 6; spacing: 2
        RailRow { objectName: "railToggle"; icon: pr.open ? "panel_left_close" : "panel_left_open"; label: "Projects"
            tip: pr.open ? "Fold the rail to its icons" : "Open the rail: the designs by name"; onClicked: Frame.railOpen = !Frame.railOpen }
        RailRow { objectName: "railHome"; icon: "home"; label: "Home"; keys: "Ctrl+Shift+H"; tip: pr.open ? "" : "All designs"; onClicked: Store.home() }
        RailRow { objectName: "railBench"; icon: "list_checks"; label: "Bench"; keys: "Ctrl+B"; lit: Store.benchOpen
            tip: pr.open ? "" : "The Bench: every study, route and document"; onClicked: Store.toggleBench() }
        Rule { visible: pr.recent.length > 0 }
        Txt { visible: pr.open && pr.recent.length > 0; kind: "cap"; text: "Recent"; leftPadding: 10; height: 22; verticalAlignment: Text.AlignVCenter; wrapMode: Text.NoWrap }
        Repeater {
            model: pr.recent
            RailRow {
                required property var modelData
                readonly property int n: pr.convCount[modelData.id] || 0
                objectName: "railDesign-" + modelData.id
                letter: (modelData.name || "?").replace(/^[^A-Za-z0-9]+/, "").charAt(0).toUpperCase() || "?"
                label: modelData.name; side: n ? String(n) : ""
                lit: modelData.id === Store.pid
                tip: modelData.name + " · " + (n ? F.plural(n, "conversation") : "no conversations") + " · " + F.ago(modelData.updated)
                onClicked: if (modelData.id !== Store.pid) Store.open(modelData.id)
            }
        }
        Rule { visible: !pr.tight }
        RailRow { objectName: "railTrash"; visible: !pr.tight; icon: "trash_2"; label: "Trash"; side: pr.trashed ? String(pr.trashed) : ""
            tip: pr.trashed ? "Recently deleted: " + F.plural(pr.trashed, "design") + " you can put back" : "Recently deleted: nothing"
            onClicked: Store.openSettings("backups") }
        RailRow { objectName: "railSettings"; icon: "sliders_horizontal"; label: "Settings"; keys: "Ctrl+,"; tip: pr.open ? "" : "Settings"
            lit: !!Store.sheet && Store.sheet.kind === "settings"; onClicked: Store.openSettings("general") }
    }
}
