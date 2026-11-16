import QtQuick
import "F.js" as F

// The artifact graph as a strip: parameters → solid → exports → checks → slice → release.
// Each node says whether it describes the current revision. Stale is never shown as current.
Rectangle {
    id: pl
    color: Theme.alpha(Theme.plate1, 0.9); radius: Theme.rLg; border.color: Theme.rule
    implicitHeight: 58
    readonly property var d: Store.data
    readonly property var st: d ? d.status : ({})
    readonly property string rev: d ? F.pad(d.project.head) : ""
    readonly property bool dirty: F.vals(st).some(function (n) { return n.state !== "current" })
    function stateOf(id) {
        var n = st[id]; if (!n) return "missing"
        var run = Store.running[id]
        if (run === "running" || run === "queued") return "running"
        if (n.blocked && n.state !== "current" && n.state !== "failed") return n.state === "stale" ? "stale" : "blocked"
        return n.state
    }
    function meta(id) {
        var n = st[id], s = stateOf(id); if (!n) return ""
        if (s === "running") return Store.running[id] === "queued" ? "queued" : "working…"
        if (s !== "current") return n.error ? n.error.message : (id === "slice" && n.unavailable) ? "slicer unavailable" : s === "stale" ? "made for " + F.pad(n.last_rev || 0) : s === "blocked" ? "waiting" : "not made"
        if (id === "geometry") return Store.view ? Store.view.faces + " faces" : ""
        if (id === "exports") return d.exports ? (d.exports.files.step ? ".step  .stl  .3mf" : ".stl only (mesh)") : ""
        if (id === "checks") { var r = d.checks ? d.checks.rollup : null; return r ? r.PASS + " pass · " + r.WARN + " review · " + r.FAIL + " fail" : "" }
        if (id === "slice") return d.slice ? F.dur(d.slice.time_s) + " · " + F.fmt(d.slice.filament_g, 1) + " g" : ""
        return ""
    }
    function tint(s) { return s === "current" ? Theme.pass : s === "running" ? Theme.datum : s === "failed" ? Theme.signal : s === "stale" ? Theme.amber : Theme.ink4 }
    readonly property var nodes: [
        { id: "params", label: "Parameters", stage: "shape" }, { id: "geometry", label: "Solid", stage: "shape" }, { id: "exports", label: "Exports", stage: "release" },
        { id: "checks", label: "Checks", stage: "prove" }, { id: "slice", label: "Slice", stage: "prove" }, { id: "release", label: "Release", stage: "release" }]
    Row {
        id: row; anchors.fill: parent; anchors.leftMargin: 6; anchors.rightMargin: 6
        Repeater {
            model: pl.nodes
            Item {
                id: nd
                required property var modelData
                required property int index
                readonly property string nid: modelData.id
                readonly property var ap: pl.d ? pl.d.approval : ({})
                readonly property string s: nid === "params" ? "current" : nid === "release" ? (ap.state === "approved" ? "current" : ap.state === "superseded" ? "stale" : "missing") : pl.stateOf(nid)
                width: (row.width - auto.width) / pl.nodes.length; height: row.height
                Rectangle { anchors.fill: parent; anchors.margins: 4; radius: Theme.rMd; color: nm.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent" }
                Rectangle { visible: nd.index > 0; x: -5; y: 20; width: 10; height: 1; color: Theme.rule2 }
                Column { x: 14; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 22; spacing: 3
                    Row { spacing: 6
                        Rectangle { width: 6; height: 6; radius: 3; color: pl.tint(nd.s); anchors.verticalCenter: parent.verticalCenter
                            SequentialAnimation on opacity { running: nd.s === "running"; loops: Animation.Infinite; alwaysRunToEnd: true
                                NumberAnimation { to: 0.25; duration: 450 } NumberAnimation { to: 1; duration: 450 } } }
                        Txt { text: nd.modelData.label; font.weight: 600; font.pixelSize: 12 } }
                    Txt { kind: "fine"; mono: nd.s === "current"; font.pixelSize: 11; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        color: nd.s === "failed" ? Theme.signal : nd.s === "stale" ? Theme.amber : Theme.ink3
                        text: nd.nid === "params" ? pl.rev + " · " + (Store.head ? (Store.head.summary || Store.head.note || "") : "")
                            : nd.nid === "release" ? (nd.ap.state === "approved" ? nd.ap.release : nd.ap.state === "superseded" ? "earlier design" : pl.d && pl.d.gate.ready ? "ready for approval" : pl.dirty && !Store.job ? "click to regenerate" : "not ready")
                            : pl.meta(nd.nid) } }
                Rectangle { // running sweep
                    visible: nd.s === "running"; anchors.bottom: parent.bottom; anchors.bottomMargin: 6; x: 14; width: parent.width - 28; height: 2; radius: 1; color: Theme.rule; clip: true
                    Rectangle { width: parent.width * 0.4; height: 2; radius: 1; color: Theme.datum
                        NumberAnimation on x { running: nd.s === "running"; from: -40; to: 160; duration: 900; loops: Animation.Infinite; easing.type: Easing.InOutQuad } } }
                MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true
                    onClicked: (nd.nid === "release" && pl.dirty && !Store.job) ? Store.run() : Store.setStage(nd.modelData.stage) }
                Tip { show: nm.containsMouse; text: pl.st[nd.nid] && pl.st[nd.nid].error ? pl.st[nd.nid].error.message : pl.st[nd.nid] ? "Key " + pl.st[nd.nid].key : "" }
            }
        }
        Item { id: auto; width: 74; height: row.height
            readonly property bool on: !!pl.d && pl.d.project.auto_run !== false
            Rectangle { x: 0; y: 14; width: 1; height: parent.height - 28; color: Theme.rule }
            Column { anchors.centerIn: parent; spacing: 4
                Txt { kind: "cap"; text: "Auto"; anchors.horizontalCenter: parent.horizontalCenter }
                Rectangle { width: 30; height: 16; radius: 8; color: auto.on ? Theme.alpha(Theme.datum, 0.9) : Theme.plate4; anchors.horizontalCenter: parent.horizontalCenter
                    Rectangle { y: 2; x: auto.on ? 16 : 2; width: 12; height: 12; radius: 6; color: auto.on ? Theme.datumInk : Theme.ink3
                        Behavior on x { NumberAnimation { duration: Theme.base; easing.type: Easing.OutCubic } } } } }
            MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: Store.settings({ auto_run: !auto.on }) }
            Tip { show: am.containsMouse; text: "When on, every commit regenerates the solid, exports, checks and slice. When off they stay stale until you run them." } }
    }
}
