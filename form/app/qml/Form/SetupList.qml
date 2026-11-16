import QtQuick

// The setup checklist. Every item `form setup` reports, in its group, with a live status dot.
// Data-driven: items other parts of FORM add to setup.check() appear here without changes.
// A fix runs only when its box is ticked and Apply is pressed; its exact commands are shown first.
Column {
    id: sl
    width: parent ? parent.width : 0
    spacing: 16
    readonly property var st: Store.setup
    property bool attentionFirst: false     // the sheet lists groups that need something first
    readonly property var groups: {
        if (!st) return []
        if (!attentionFirst) return st.groups
        var need = function (g) { return g.items.some(function (id) { var it = Store.setupItem(id); return it && it.status !== "ok" && it.status !== "info" }) }
        return st.groups.filter(need).concat(st.groups.filter(function (g) { return !need(g) }))
    }
    readonly property bool busy: !!Store.setupJob && Store.setupJob.state === "running"
    function stepFor(id) {
        if (!Store.setupJob) return null
        var s = Store.setupJob.steps
        for (var i = 0; i < s.length; i++) if (s[i].id === id) return s[i]
        return null
    }
    function tint(status) { return status === "ok" ? Theme.pass : status === "warn" ? Theme.amber : status === "missing" ? Theme.signal : Theme.ink3 }
    function word(status) { return status === "ok" ? "ready" : status === "warn" ? "check" : status === "missing" ? "missing" : "note" }

    Row { visible: !sl.st; spacing: 8; height: 40
        Icon { name: "loader_circle"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter
            RotationAnimation on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: !sl.st } }
        Txt { tone: 2; text: "Checking what is installed… (the CAD kernel takes a few seconds to start)"; anchors.verticalCenter: parent.verticalCenter } }

    Column { visible: !!sl.st && sl.st.detected.length > 0; width: sl.width; spacing: 6
        Txt { kind: "cap"; text: "Found on this computer" }
        Flow { width: parent.width; spacing: 6
            Repeater { model: sl.st ? sl.st.detected : []
                Rectangle { required property var modelData
                    height: 24; width: dl.implicitWidth + 24; radius: Theme.rSm; color: Theme.plate1; border.color: Theme.rule
                    Rectangle { x: 9; width: 6; height: 6; radius: 3; color: Theme.pass; anchors.verticalCenter: parent.verticalCenter }
                    Txt { id: dl; x: 20; kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                        text: modelData.label + "  ·  " + modelData.detail.split(" · ")[0] } } } } }

    Repeater {
        model: sl.groups
        Column {
            id: grp
            required property var modelData
            width: sl.width; spacing: 6
            Txt { kind: "cap"; text: grp.modelData.title }
            Rectangle {
                width: parent.width; height: rows.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                Column {
                    id: rows; width: parent.width
                    Repeater {
                        model: grp.modelData.items
                        Item {
                            id: row
                            required property var modelData
                            required property int index
                            readonly property var it: Store.setupItem(modelData)
                            readonly property var step: sl.stepFor(modelData)
                            readonly property bool picked: !!Store.setupPick[modelData]
                            width: rows.width; height: it ? col.implicitHeight + 24 : 0; visible: !!it
                            Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                            Rectangle { x: 16; y: 18; width: 8; height: 8; radius: 4; color: row.it ? sl.tint(row.it.status) : Theme.ink4 }
                            Column {
                                id: col; x: 36; y: 12; width: parent.width - 36 - 16; spacing: 6
                                Item { width: parent.width; height: Math.max(lb.implicitHeight, 18)
                                    Row { spacing: 8
                                        Txt { id: lb; text: row.it ? row.it.label : ""; font.weight: 600; wrapMode: Text.NoWrap }
                                        Tag { visible: !!row.it && row.it.required; text: "required"; kind: ""; anchors.verticalCenter: parent.verticalCenter } }
                                    Txt { anchors.right: parent.right; kind: "fine"; text: row.it ? sl.word(row.it.status) : ""; color: row.it ? sl.tint(row.it.status) : Theme.ink3 } }
                                Txt { kind: "fine"; tone: 2; width: parent.width; text: row.it ? row.it.detail : ""; wrapMode: Text.WrapAnywhere; visible: text !== "" }
                                // the fix: a tick box, the exact commands, what it edits
                                Column { visible: !!row.it && !!row.it.fix && row.it.status !== "ok"; width: parent.width; spacing: 6; topPadding: 2
                                    Row { visible: !!row.it && row.it.runnable; spacing: 10
                                        Check { checked: row.picked; enabled: !sl.busy; anchors.verticalCenter: parent.verticalCenter
                                            onToggled: function (on) { Store.setPick(row.modelData, on) } }
                                        Txt { anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                                            text: "Set this up: " + (row.it && row.it.fix ? row.it.fix.summary : "")
                                            MouseArea { anchors.fill: parent; enabled: !sl.busy; onClicked: Store.setPick(row.modelData, !row.picked) } }
                                        Txt { visible: !!row.it && !!row.it.fix && !row.it.fix.recommended && !row.it.required; kind: "fine"; text: "optional"; anchors.verticalCenter: parent.verticalCenter } }
                                    Txt { visible: !!row.it && !row.it.runnable && !!row.it.fix; width: parent.width; tone: 2
                                        text: row.it && row.it.fix ? row.it.fix.summary + (row.it.fix.note ? "" : ".") : "" }
                                    Rectangle { visible: !!row.it && !!row.it.fix && row.it.fix.commands.length > 0
                                        width: parent.width; height: cmds.implicitHeight + 16; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                                        Txt { id: cmds; x: 10; y: 8; width: parent.width - 20; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.WrapAnywhere
                                            text: row.it && row.it.fix ? row.it.fix.commands.map(function (c) { return "$ " + c }).join("\n") : "" } }
                                    Txt { visible: !!row.it && row.it.edits_file; kind: "fine"; width: parent.width
                                        text: "Edits that file directly. A backup copy is saved next to it first." }
                                    Txt { visible: !!row.it && !!row.it.fix && !!row.it.fix.note; kind: "fine"; width: parent.width; wrapMode: Text.WrapAnywhere
                                        text: row.it && row.it.fix && row.it.fix.note ? row.it.fix.note : "" } }
                                // what happened when it ran
                                Column { visible: !!row.step; width: parent.width; spacing: 4
                                    Row { spacing: 6
                                        Icon { name: !row.step ? "dot" : row.step.state === "done" ? "circle_check" : row.step.state === "failed" ? "circle_alert" : "loader_circle"; size: 13
                                            color: !row.step ? Theme.ink3 : row.step.state === "done" ? Theme.pass : row.step.state === "failed" ? Theme.signal : Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                                        Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter
                                            text: !row.step ? "" : row.step.state === "waiting" ? "Waiting" : row.step.state === "running" ? "Running…"
                                                : (row.step.state === "done" ? "Done: " : "Failed: ") + row.step.message } }
                                    Rectangle { visible: !!row.step && row.step.output !== ""; width: parent.width; height: Math.min(out.implicitHeight, 160) + 16; radius: Theme.rSm; color: Theme.well; clip: true
                                        Txt { id: out; x: 10; y: 8; width: parent.width - 20; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.WrapAnywhere
                                            text: row.step ? row.step.output.split("\n").slice(-10).join("\n") : "" } } }
                            }
                        }
                    }
                }
            }
        }
    }
}
