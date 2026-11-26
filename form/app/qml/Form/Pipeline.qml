import QtQuick
import "F.js" as F

// The artifact graph as a strip: parameters → solid → exports → checks → slice → release.
// Each node says whether it describes the current revision. Stale is never shown as current.
// In a workspace it is a glass capsule bottom right (`grid`): two columns of steps and the Auto switch, each step a
// state dot, its name and one mono line with its real value. `flat` drops its own card when a pane is drawn for it.
Rectangle {
    id: pl
    objectName: "pipeline"
    property bool flat: false
    property bool grid: false                           // two columns in a capsule instead of one row
    readonly property bool narrow: !grid && width < 620          // labels only; the detail moves into the tooltip
    readonly property bool tiny: !grid && width < 470            // dots only, and one sentence for whatever is not current
    readonly property bool roomy: !grid && width >= 900          // room for the long form of each node's line; otherwise the short one
    readonly property real cell: (width - 24 - 10) / 2
    // Each node is as wide as what it says, and the slack is shared out, so a short line never crowds a long one.
    property var needs: [0, 0, 0, 0, 0, 0]
    function setNeed(i, w) { if (needs[i] === w) return; var n = needs.slice(); n[i] = w; needs = n }
    readonly property real needSum: { var t = 0; for (var i = 0; i < needs.length; i++) t += needs[i]; return t }
    // When the lines do not all fit, the revision note gives way first (it is the only one of no fixed length);
    // only then do the others share the shortfall.
    function widthOf(i, need, least, room) {
        if (needSum <= 0) return room / nodes.length
        if (needSum <= room) return need + (room - needSum) / nodes.length
        var over = needSum - room, give = Math.min(over, Math.max(0, needs[0] - least0))
        if (i === 0) return need - give
        var rest = needSum - needs[0]
        return rest > 0 ? need - (over - give) * need / rest : need
    }
    property real least0: 0
    readonly property string summary: {
        var order = ["geometry", "exports", "checks", "slice"], names = ({ geometry: "Solid", exports: "Exports", checks: "Checks", slice: "Slice" })
        for (var i = 0; i < order.length; i++) { var s = stateOf(order[i]); if (s !== "current" && s !== "off") return names[order[i]] + ": " + (meta(order[i]) || s) }
        return rev + " · all current"
    }
    color: flat ? "transparent" : Theme.alpha(Theme.plate1, 0.9); radius: Theme.rLg; border.color: Theme.rule; border.width: flat ? 0 : 1
    implicitHeight: grid ? row.implicitHeight + 20 : narrow ? 34 : 48
    readonly property var d: Store.data
    readonly property var st: d ? d.status : ({})
    readonly property string rev: d ? F.pad(d.project.head) : ""
    readonly property bool dirty: F.vals(st).some(function (n) { return n.state !== "current" && n.state !== "off" })   // off: Design only
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
        if (s === "off") return pl.roomy ? "design only, not sliced" : "design only"
        if (s !== "current") return n.error ? n.error.message : (id === "slice" && n.unavailable) ? "slicer unavailable" : s === "stale" ? "made for " + F.pad(n.last_rev || 0) : s === "blocked" ? "waiting" : "not made"
        if (id === "geometry") return Store.view ? Store.view.faces + " faces" : ""
        if (id === "exports") return d.exports ? ["step", "stl", "obj", "glb"].filter(function (k) { return !!d.exports.files[k] }).map(function (k) { return "." + k }).join(" ") : ""
        if (id === "checks") { var r = d.checks ? d.checks.rollup : null; if (!r) return ""
            if (roomy) return r.PASS + " pass · " + r.WARN + " review · " + r.FAIL + " fail"
            return r.FAIL ? r.FAIL + " fail · " + r.WARN + " review" : r.WARN ? r.PASS + " pass · " + r.WARN + " review" : r.PASS + " pass" }
        if (id === "slice") return d.slice ? F.dur(d.slice.time_s) + (roomy ? " · " + F.fmt(d.slice.filament_g, 1) + " g" : "")
            + (d.slice.plates && d.slice.plates.length > 1 ? " · " + d.slice.plates.length + " plates" : "") : ""
        return ""
    }
    function tint(s) { return s === "current" ? Theme.pass : s === "running" ? Theme.datum : s === "failed" ? Theme.signal : s === "stale" ? Theme.amber : Theme.ink4 }
    // a 3D model (form/purpose.py) is never sliced: its strip has no Slice step at all
    readonly property var nodes: [
        { id: "params", label: "Parameters", stage: "shape" }, { id: "geometry", label: "Solid", stage: "shape" }, { id: "exports", label: "Exports", stage: "release" },
        { id: "checks", label: "Checks", stage: "prove" }, { id: "slice", label: "Slice", stage: "prove" }, { id: "release", label: "Release", stage: "release" }]
        .filter(function (n) { return n.id !== "slice" || Store.printUi })
    onNodesChanged: needs = nodes.map(function () { return 0 })
    Grid {
        id: row; x: pl.grid ? 12 : 4; y: pl.grid ? 10 : 0; width: parent.width - 2 * x; height: pl.grid ? implicitHeight : parent.height
        columns: pl.grid ? 2 : 99; columnSpacing: pl.grid ? 10 : 0; rowSpacing: pl.grid ? 4 : 0
        Repeater {
            model: pl.nodes
            Item {
                id: nd
                required property var modelData
                required property int index
                readonly property string nid: modelData.id
                readonly property var ap: pl.d ? pl.d.approval : ({})
                readonly property string s: nid === "params" ? "current" : nid === "release" ? (ap.state === "approved" ? "current" : ap.state === "superseded" ? "stale" : "missing") : pl.stateOf(nid)
                readonly property string what: Store.head ? (Store.head.summary || Store.head.note || "") : ""
                readonly property string say: nid === "params" ? pl.rev + (Store.hasDraft ? " · draft open" : pl.roomy && what ? " · " + what : "")
                    : nid === "release" ? (ap.state === "approved" ? ap.release : ap.state === "superseded" ? "earlier design" : pl.d && pl.d.gate.ready ? (pl.roomy ? "ready for approval" : "ready") : pl.dirty && !Store.job ? (pl.roomy ? "click to regenerate" : "regenerate") : "not ready")
                    : pl.meta(nid)
                // the long line of a roomy strip may still be cut (a revision note has no fixed length): it is capped, not measured
                readonly property real need: Math.ceil(Math.max(lbl.implicitWidth + 12, pl.narrow ? 0 : Math.min(sayTxt.implicitWidth, 400))) + 20
                readonly property real least: Math.ceil(lbl.implicitWidth) + 32
                onLeastChanged: if (index === 0) pl.least0 = least
                readonly property real room: row.width - auto.width
                onNeedChanged: pl.setNeed(index, need)
                Component.onCompleted: { pl.setNeed(index, need); if (index === 0) pl.least0 = least }
                width: pl.grid ? pl.cell : pl.tiny ? 16 : pl.widthOf(index, need, least, room)
                height: pl.grid ? 40 : row.height
                // a node that has just been made for this revision settles: the dot lands, nothing else moves
                onSChanged: if (s === "current" && was === "running") settle.restart()
                property string was: s
                Timer { interval: 0; running: nd.was !== nd.s; onTriggered: nd.was = nd.s }
                Rectangle { anchors.fill: parent; anchors.margins: pl.grid ? 0 : 3; radius: Theme.rMd; color: nm.pressed ? Theme.washPress : nm.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} } }
                // the link from the node before: drawn in the state of this node, so the eye follows what is current
                Rectangle { visible: nd.index > 0 && !pl.tiny && !pl.grid; x: -3; y: pl.narrow ? 16 : 15; width: 6; height: 1; color: nd.s === "current" ? Theme.alpha(Theme.pass, 0.5) : Theme.rule2 }
                Column { x: pl.grid ? 8 : pl.tiny ? 5 : 11; anchors.verticalCenter: parent.verticalCenter; width: parent.width - (pl.grid ? 8 : pl.tiny ? 5 : 20); spacing: pl.grid ? 4 : 2
                    Row { spacing: 7
                        Rectangle { id: dot; width: 6; height: 6; radius: 3; color: pl.tint(nd.s); anchors.verticalCenter: parent.verticalCenter
                            Behavior on color { ColorAnimation { duration: Motion.ui } }
                            SequentialAnimation on opacity { running: nd.s === "running"; loops: Animation.Infinite; alwaysRunToEnd: true
                                NumberAnimation { to: 0.25; duration: 450 } NumberAnimation { to: 1; duration: 450 } }
                            SequentialAnimation { id: settle
                                NumberAnimation { target: dot; property: "scale"; from: Theme.from(1.9); to: 1; duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
                        Txt { id: lbl; visible: !pl.tiny; text: nd.modelData.label; font.weight: Theme.wSemi; font.pixelSize: pl.grid ? 13 : 12; font.letterSpacing: -0.1; wrapMode: Text.NoWrap
                            width: Math.min(implicitWidth, nd.width - 30); elide: Text.ElideRight } }
                    Txt { id: sayTxt; visible: !pl.narrow; kind: "fine"; mono: pl.grid || nd.s === "current"; font.pixelSize: pl.grid ? 10 : 11; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        leftPadding: pl.grid ? 13 : 0; font.letterSpacing: pl.grid ? -0.4 : 0
                        color: nd.s === "failed" ? Theme.signal : nd.s === "stale" ? Theme.amber : pl.grid ? Theme.ink2 : Theme.ink3
                        text: nd.say } }
                Rectangle { // running sweep
                    visible: nd.s === "running" && !pl.tiny; anchors.bottom: parent.bottom; anchors.bottomMargin: 3; x: 12; width: parent.width - 24; height: 2; radius: 1; color: Theme.rule; clip: true
                    Rectangle { width: parent.width * 0.4; height: 2; radius: 1; color: Theme.datum
                        NumberAnimation on x { running: nd.s === "running"; from: -40; to: 160; duration: 900; loops: Animation.Infinite; easing.type: Easing.InOutQuad } } }
                MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true
                    onClicked: (nd.nid === "release" && pl.dirty && !Store.job) ? Store.run() : Store.setStage(nd.modelData.stage) }
                // a failed step: hand it to the agent (on hover; the strip stays quiet otherwise)
                FixBtn { objectName: "fixPipeline"; compact: true; z: 2
                    anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                    visible: nd.s === "failed" && !pl.tiny && Store.chatReady && !!Store.chat.available && (nm.containsMouse || hovered)
                    subject: "the " + nd.modelData.label.toLowerCase() + " step failed for " + pl.rev
                    details: pl.st[nd.nid] && pl.st[nd.nid].error ? "Pipeline step: " + nd.nid + "\nError: " + pl.st[nd.nid].error.message
                        + (pl.st[nd.nid].error.hint ? "\nHint: " + pl.st[nd.nid].error.hint : "") : "Pipeline step: " + nd.nid }
                Tip { show: nm.containsMouse
                    text: (pl.narrow && nd.say ? nd.modelData.label + ": " + nd.say + "\n" : "")
                        + (nd.nid === "params" && nd.what ? pl.rev + ": " + nd.what
                           : nd.nid === "slice" && pl.d && pl.d.slice && nd.s === "current" ? F.dur(pl.d.slice.time_s) + " · " + F.fmt(pl.d.slice.filament_g, 1) + " g, simulated\n" : "")
                        + (pl.st[nd.nid] && pl.st[nd.nid].error ? pl.st[nd.nid].error.message : pl.st[nd.nid] ? "Key " + pl.st[nd.nid].key : "") }
            }
        }
        Txt { visible: pl.tiny; width: row.width - auto.width - 16 * pl.nodes.length - 10; height: row.height; leftPadding: 10; verticalAlignment: Text.AlignVCenter
            font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight; text: pl.summary }
        Item { id: auto; objectName: "pipelineAuto"; width: pl.grid ? pl.cell : pl.narrow ? 44 : 78; height: pl.grid ? 40 : row.height
            readonly property bool on: !!pl.d && pl.d.project.auto_run !== false
            Rectangle { visible: !pl.grid; x: 0; y: 10; width: 1; height: parent.height - 20; color: Theme.rule }
            Txt { visible: !pl.narrow; kind: "cap"; text: "Auto"; anchors.verticalCenter: parent.verticalCenter; x: pl.grid ? 21 : Math.round((parent.width - width - 37) / 2) }
            // on is green: it is a state (everything follows each commit), not where you are
            Rectangle { id: sw; width: 30; height: 18; radius: 9; color: auto.on ? Theme.pass : Theme.alpha(Theme.lineBase, 0.2); anchors.verticalCenter: parent.verticalCenter
                x: pl.grid ? parent.width - width - 8 : pl.narrow ? Math.round((parent.width - width) / 2) : Math.round((parent.width + 37) / 2 - 3)
                Behavior on color { ColorAnimation { duration: Motion.ui } }
                Rectangle { y: 2; x: auto.on ? 14 : 2; width: 14; height: 14; radius: 7; color: "white"
                    Behavior on x { NumberAnimation { duration: Motion.move(Motion.ui); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } } }
            MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; onClicked: Store.settings({ auto_run: !auto.on }) }
            Tip { show: am.containsMouse; text: "Auto: when on, every commit regenerates the solid, exports, checks and slice. When off they stay stale until you run them." } }
    }
}
