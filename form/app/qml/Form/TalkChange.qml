import QtQuick
import "F.js" as F

// What one reply changed in a design: "r04 → r06". Compare shows the revision before as a ghost; Go back makes it
// the head again (the newer revisions stay in the history, nothing is deleted).
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
    implicitHeight: 40 + (asking ? 34 : 0)
    radius: Theme.rMd
    color: Theme.plate1
    border.color: asking ? Theme.alpha(Theme.signal, 0.45) : Theme.rule
    Behavior on implicitHeight { NumberAnimation { duration: Theme.base; easing.type: Easing.OutQuad } }
    clip: true

    Row { x: 12; y: 0; height: 40; spacing: 8
        Icon { name: ch.isNew ? "cuboid" : "git_commit_horizontal"; size: 13; color: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: revs; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
            text: !ch.change ? "" : ch.isNew ? F.pad(ch.change.to) : F.pad(ch.change.from) + " → " + F.pad(ch.change.to) }
        Txt { anchors.verticalCenter: parent.verticalCenter; kind: "fine"; wrapMode: Text.NoWrap; elide: Text.ElideRight
            visible: width > 40
            width: Math.max(0, Math.min(implicitWidth, ch.width - 12 - 21 - revs.implicitWidth - 8 - acts.width - 14))
            text: ch.isNew ? "New design · " + ch.name : ch.other ? ch.name : ch.headMoved ? "head is now " + F.pad(Store.project.head) : "this reply's change" }
    }
    Row { id: acts; anchors.right: parent.right; anchors.rightMargin: 6; y: 8; spacing: 2
        Btn { objectName: "changeOpen"; visible: ch.other; small: true; kind: "quiet"; icon: "arrow_up_right"; text: "Open"
            onClicked: Store.open(ch.change.project) }
        Btn { objectName: "changeCompare"; visible: !ch.isNew; small: true; kind: "quiet"; icon: "git_compare"; text: "Compare"
            active: !!ch.change && !ch.other && !!Store.compare && Store.compare.rev === ch.change.from
            tip: "Show " + (ch.change ? F.pad(ch.change.from) : "") + " as a ghost over the current head"
            onClicked: Store.compareChange(ch.change) }
        Btn { objectName: "changeUndo"; visible: !ch.isNew; small: true; kind: "quiet"; icon: "undo_2"; text: "Go back"
            enabled: !Store.hasDraft && !Store.chatBusy
            tip: "Make " + (ch.change ? F.pad(ch.change.from) : "") + " the head again"
            onClicked: ch.asking = true }
    }
    // go back: said plainly, confirmed once
    Item { visible: ch.asking; x: 12; y: 40; width: parent.width - 18; height: 28
        Txt { anchors.verticalCenter: parent.verticalCenter; width: parent.width - gb.width - kb.width - 16; kind: "fine"; tone: 2; elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: "Head goes back to " + (ch.change ? F.pad(ch.change.from) : "") + ". Newer revisions stay in the history." }
        Btn { id: kb; small: true; kind: "quiet"; text: "Cancel"; anchors.right: gb.left; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
            onClicked: ch.asking = false }
        Btn { id: gb; objectName: "changeUndoYes"; small: true; kind: "danger"; text: "Go back"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            onClicked: { ch.asking = false; Store.undoChange(ch.change) } }
    }
}
