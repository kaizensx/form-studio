import QtQuick
import "F.js" as F

// A revision this reply made, as a card in the conversation: "r01 → r02", what changed (the features it touched as
// tags, the parameters as from → to), and what you can do about it. Compare shows the revision before as a ghost;
// Go back makes it the head again (the newer revisions stay in the history, nothing is deleted).
Rectangle {
    id: ch
    objectName: "changeCard"
    property var change: null              // { project, from, to }
    property bool asking: false
    readonly property bool other: !!change && change.project !== Store.pid
    readonly property string name: {
        if (!change) return ""
        var ps = Store.studio ? Store.studio.projects : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === change.project) return ps[i].name
        return change.project
    }
    readonly property bool isNew: !!change && (change.from === null || change.from === undefined)
    readonly property bool headMoved: !ch.other && !!Store.project && !!change && Store.project.head !== change.to
    readonly property bool comparing: !!ch.change && !ch.other && !!Store.compare && Store.compare.rev === ch.change.from
    // what it changed, asked once the card is on screen (a revision that is gone simply shows no detail)
    property var diff: null
    readonly property var feats: diff && diff.impact ? diff.impact.features.filter(function (f) { return f.change !== "trimmed" }).slice(0, 6) : []
    readonly property var params: diff && diff.impact ? diff.impact.params.slice(0, 3) : []
    readonly property int moreParams: diff && diff.impact ? Math.max(0, diff.impact.params.length - 3) : 0
    function look() {
        if (!change || isNew || diff) return
        var c = change
        Store.revDiff(c.project, c.from, c.to).then(function (r) { if (ch.change === c) ch.diff = r }, function () {})
    }
    onChangeChanged: { diff = null; look() }
    Component.onCompleted: look()

    readonly property bool detailed: feats.length > 0 || params.length > 0
    implicitHeight: 44 + (detailed ? detail.implicitHeight + 10 : 0) + (asking ? 36 : 0)
    // the same quiet well as the Sources and the plan (TalkCard.qml)
    radius: 14
    color: Theme.dark ? Qt.rgba(0, 0, 0, 0.20) : Qt.rgba(1, 1, 1, 0.55)
    border.color: asking ? Theme.alpha(Theme.signal, 0.45) : comparing ? Theme.alpha(Theme.blueprint, 0.5) : Theme.rule
    Behavior on border.color { Tint {} }
    clip: true

    // ── the revision: rNN, in the draft/compare colour, and what it is ──
    Row { x: 10; y: 0; height: 44; spacing: 8
        Rectangle { width: revs.implicitWidth + 14; height: 22; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
            color: Theme.alpha(Theme.blueprint, 0.12)
            Txt { id: revs; anchors.centerIn: parent; mono: true; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap; color: Theme.strong(Theme.blueprint)
                text: !ch.change ? "" : ch.isNew ? F.pad(ch.change.to) : F.pad(ch.change.from) + " → " + F.pad(ch.change.to) } }
        Txt { anchors.verticalCenter: parent.verticalCenter; kind: "fine"; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
            visible: width > 40
            width: Math.max(0, Math.min(implicitWidth, ch.width - 10 - revs.implicitWidth - 14 - 8 - acts.width - 14))
            text: ch.isNew ? "New design · " + ch.name : ch.other ? ch.name : ch.headMoved ? "head is now " + F.pad(Store.project.head) : "New revision" }
    }
    Row { id: acts; anchors.right: parent.right; anchors.rightMargin: 6; y: 10; spacing: 2
        Btn { objectName: "changeOpen"; visible: ch.other; small: true; kind: "quiet"; icon: "arrow_up_right"; text: "Open"
            onClicked: Store.open(ch.change.project) }
        Btn { objectName: "changeCompare"; visible: !ch.isNew; small: true; kind: "quiet"; icon: "git_compare"; text: ch.comparing ? "Comparing" : "Compare"
            active: ch.comparing
            tip: ch.comparing ? "Stop comparing" : "Show " + (ch.change ? F.pad(ch.change.from) : "") + " as a ghost over the current head"
            onClicked: Store.compareChange(ch.change) }
        Btn { objectName: "changeUndo"; visible: !ch.isNew; small: true; kind: "quiet"; icon: "undo_2"
            enabled: !Store.hasDraft && !Store.chatBusy
            tip: "Go back: make " + (ch.change ? F.pad(ch.change.from) : "") + " the head again"
            onClicked: ch.asking = true }
    }
    // ── what changed: features as tags (what happened to each), parameters as from → to ──
    Column { id: detail; objectName: "changeDetail"; visible: ch.detailed; x: 10; y: 42; width: parent.width - 20; spacing: 6
        opacity: ch.detailed ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } }
        Flow { width: parent.width; spacing: 4; visible: ch.feats.length > 0
            Repeater { model: ch.feats
                Tag { required property var modelData; objectName: "changeFeature"; text: modelData.label; kind: modelData.change } } }
        Repeater { model: ch.params
            Row { required property var modelData; width: detail.width; spacing: 6
                Txt { kind: "fine"; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, parent.width - vals.implicitWidth - 6); text: modelData.label }
                Txt { id: vals; kind: "fine"; mono: true; tone: 2; wrapMode: Text.NoWrap
                    text: F.trim(modelData.from) + " → " + F.trim(modelData.to) + (modelData.unit ? " " + modelData.unit : "") } } }
        Txt { visible: ch.moreParams > 0; kind: "fine"; tone: 4; text: "and " + F.plural(ch.moreParams, "more value") }
    }
    // go back: said plainly, confirmed once
    Item { visible: ch.asking; x: 10; y: ch.implicitHeight - 36; width: parent.width - 16; height: 30
        opacity: ch.asking ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } }
        Txt { anchors.verticalCenter: parent.verticalCenter; width: parent.width - gb.width - kb.width - 16; kind: "fine"; tone: 2; elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: "Head goes back to " + (ch.change ? F.pad(ch.change.from) : "") + ". Newer revisions stay in the history." }
        Btn { id: kb; small: true; kind: "quiet"; text: "Cancel"; anchors.right: gb.left; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
            onClicked: ch.asking = false }
        Btn { id: gb; objectName: "changeUndoYes"; small: true; kind: "danger"; text: "Go back"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            onClicked: { ch.asking = false; Store.undoChange(ch.change) } }
    }
}
