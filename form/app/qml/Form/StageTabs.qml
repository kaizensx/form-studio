import QtQuick
import "F.js" as F

// The four modes of a design as one glass capsule in the middle of the top bar: Design, Check, Make, Document, each
// with one line that says where it stands (how many features, what the checks say, whether it can be released, how
// many documents there are). The lit segment glides to the mode you pick (180 ms); its line is in the accent, because
// that is where you are. Green and amber on the other lines are states, never decoration.
// Describe is the Overview (the design capsule opens it) and Fit is a study in Check: neither is a mode.
Glass {
    id: tabs
    objectName: "stageTabs"
    property real room: 600                   // the width it may take
    readonly property var d: Store.data
    readonly property int at: { for (var i = 0; i < Store.stages.length; i++) if (Store.stages[i].id === Store.mode) return i; return 0 }
    function stageNote(id) {
        if (!d || !Store.head || !d.recipe) return ["", ""]
        var roll = d.checks ? d.checks.rollup : null
        if (id === "shape") return [Store.hasDraft ? "Draft open" : F.plural(d.recipe.features.length, "feature"), Store.hasDraft ? "draft" : ""]
        if (id === "prove") return !roll ? ["Not current", "warn"] : roll.FAIL ? [roll.FAIL + " failed", "fail"] : roll.WARN ? [roll.WARN + " to review", "warn"] : ["All pass", "ok"]
        if (id === "release") return d.approval.state === "approved" ? ["Released", "ok"] : d.gate.ready ? ["Ready", ""] : ["Not ready", ""]
        if (id === "document") { var n = Store.documentCount; return [n ? F.plural(n, "document") : "None yet", ""] }
        return ["", ""]
    }
    function noteColor(c) { return c === "ok" ? Theme.pass : c === "warn" ? Theme.amber : c === "fail" ? Theme.signal : c === "draft" ? Theme.datum : Theme.ink3 }

    // each segment is 118 wide when there is room for that (the mockup's), wider when its words need it
    property var needs: [0, 0, 0, 0]
    function setNeed(i, w) { if (needs[i] === w) return; var n = needs.slice(); n[i] = w; needs = n }
    readonly property int count: Store.stages.length
    readonly property real least: Math.max(64, Math.min(118, (room - 8 - 2 * (count - 1)) / Math.max(1, count)))
    function segW(i) { return Math.max(least, Math.min(needs[i] + 32, Math.max(least, (room - 8) / Math.max(1, count)))) }
    // as wide as it is when every segment has its words in full (the top bar centres it when there is room for that)
    readonly property real natural: { var t = 8; for (var i = 0; i < count; i++) t += Math.max(64, needs[i] + 32) + (i ? 2 : 0); return t }
    readonly property real total: { var t = 8; for (var i = 0; i < count; i++) t += segW(i) + (i ? 2 : 0); return t }
    width: Math.min(room, total); height: 52; radius: 26

    Rectangle { id: lit; y: 4; height: tabs.height - 8; radius: height / 2; color: Theme.dark ? Theme.glass2 : Theme.plate3
        readonly property Item seg: stageRep.count > tabs.at ? stageRep.itemAt(tabs.at) : null
        property bool settled: false
        x: seg ? row.x + seg.x : 0; width: seg ? seg.width : 0
        Component.onCompleted: Qt.callLater(function () { lit.settled = true })
        Behavior on x { enabled: lit.settled; NumberAnimation { duration: Theme.move(Theme.mode); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        Behavior on width { enabled: lit.settled; NumberAnimation { duration: Theme.move(Theme.mode); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        border.width: Theme.dark ? 0 : 1; border.color: Theme.rule
        Rectangle { x: parent.radius; width: parent.width - 2 * parent.radius; y: 0; height: 1; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.12 : 0) } }
    Row { id: row; x: 4; y: 4; height: tabs.height - 8; spacing: 2
        Repeater {
            id: stageRep
            model: Store.stages
            Item {
                id: tab
                objectName: "stage-" + modelData.id
                required property var modelData
                required property int index
                readonly property bool on: Store.mode === modelData.id
                readonly property var note: tabs.stageNote(modelData.id)
                readonly property real need: Math.ceil(Math.max(tl.implicitWidth, tn.implicitWidth))
                onNeedChanged: tabs.setNeed(index, need)
                Component.onCompleted: tabs.setNeed(index, need)
                width: tabs.segW(index); height: row.height
                Rectangle { anchors.fill: parent; radius: height / 2; color: tab.on ? "transparent" : tm.pressed ? Theme.washPress : tm.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} } }
                Column { anchors.centerIn: parent; spacing: 2
                    Txt { id: tl; anchors.horizontalCenter: parent.horizontalCenter; text: tab.modelData.title; font.weight: Theme.wSemi; font.pixelSize: 13; font.letterSpacing: -0.1
                        color: tab.on || tm.containsMouse ? Theme.ink : Theme.ink2; Behavior on color { Tint {} } wrapMode: Text.NoWrap }
                    Txt { id: tn; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: Theme.tFine; text: tab.note[0]; wrapMode: Text.NoWrap; visible: text !== ""
                        width: Math.min(implicitWidth, tab.width - 12); elide: Text.ElideRight
                        // where you are is in the accent; elsewhere a line is only coloured when it is a state
                        color: tab.note[1] === "fail" ? Theme.signal : tab.on ? (tab.note[1] === "warn" ? Theme.amber : Theme.datum) : tabs.noteColor(tab.note[1])
                        Behavior on color { Tint {} } } }
                MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.setStage(tab.modelData.id) }
                Tip { show: tm.containsMouse; below: true; text: tab.modelData.hint; keys: Theme.modeMod + "+" + Store.stageKey[tab.modelData.id] }
            }
        }
    }
}
