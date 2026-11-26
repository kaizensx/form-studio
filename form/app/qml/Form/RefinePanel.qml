import QtQuick
import QtQuick.Controls
import "F.js" as F

// Design refinement (form/refine): what runs after every build, and the refine changes the head carries. While a job
// runs it shows the stage it is at; afterwards one row per change (its label and why), each with its own undo, and
// undo all. It lives in the viewport's dock (top right); collapsed it is its header with the state in a word.
// Data: Store.refine (GET /api/projects/<id>/refine, form/refine/jobs.py status). Nothing here changes a design
// except the undo buttons and "Refine again", each a new revision.
Rectangle {
    id: rp
    objectName: "refinePanel"
    readonly property var rec: Store.refine || ({})
    readonly property var list: rec.changes || []
    readonly property bool running: rec.state === "running"
    property bool collapsed: false
    property real maxHeight: 420
    signal toggled()
    width: 252; radius: Theme.rMd
    height: collapsed ? 36 : Math.min(maxHeight, 36 + col.implicitHeight + 12)
    color: Theme.alpha(Theme.plate1, 0.95); border.color: running ? Theme.alpha(Theme.blueprint, 0.45) : Theme.rule
    Behavior on height { NumberAnimation { duration: Motion.move(160); easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: Motion.ui } }

    readonly property string headWord: running ? "Refining"
        : list.length ? F.plural(list.length, "change")
        : rec.state === "off" ? "Off" : rec.state === "failed" ? "Failed" : "Nothing added"

    Item { id: head; width: parent.width; height: 36
        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: Theme.rSm; color: hm.containsMouse ? Theme.washHover : "transparent" }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rp.toggled() }
        Spinner { x: 12; anchors.verticalCenter: parent.verticalCenter; size: 13; visible: rp.running; running: visible }
        Txt { kind: "cap"; x: rp.running ? 32 : 14; anchors.verticalCenter: parent.verticalCenter; text: "Refinement"; wrapMode: Text.NoWrap }
        Row { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Txt { objectName: "refineHeadWord"; kind: "fine"; tone: rp.running ? 1 : 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                color: rp.running ? Theme.strong(Theme.blueprint) : Theme.ink2; text: rp.headWord }
            Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter; rotation: rp.collapsed ? -90 : 0
                Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } } }
    }

    Flickable {
        visible: !rp.collapsed
        y: 36; width: parent.width; height: parent.height - 36 - 2
        contentHeight: col.implicitHeight + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 5 }
        Column {
            id: col; x: 14; width: parent.width - 28; spacing: 8
            // the stage a running job is at, or how the last one ended
            Txt { objectName: "refineStage"; kind: "fine"; tone: 2; width: parent.width; visible: text !== ""
                text: rp.running ? (rp.rec.stage || "Measuring the design")
                    : rp.rec.state === "off" ? (rp.rec.why || "Refinement is off for this design.")
                    : rp.rec.state === "failed" ? (rp.rec.error || "Refinement failed.")
                    : !rp.list.length && rp.rec.stage ? rp.rec.stage : "" }
            Column { width: parent.width; visible: rp.list.length > 0
                Repeater {
                    model: rp.list
                    Item { id: row
                        required property var modelData
                        required property int index
                        objectName: "refineChange_" + modelData.id
                        width: parent.width; height: rc.implicitHeight + 12
                        // pointing at a change shows what it changed: its feature lights up on the part
                        Rectangle { x: -8; width: parent.width + 16; height: parent.height; radius: Theme.rSm; color: rowHover.hovered ? Theme.washHover : "transparent"
                            Behavior on color { Tint {} } }
                        HoverHandler { id: rowHover
                            onHoveredChanged: if (row.modelData.kind === "feature") Store.hover(hovered ? row.modelData.id : "") }
                        Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Column { id: rc; y: 6; width: parent.width - 26; spacing: 2
                            Txt { font.pixelSize: 13; font.weight: Theme.wMedium; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                text: row.modelData.label }
                            Txt { kind: "fine"; tone: 2; width: parent.width; maximumLineCount: 3; elide: Text.ElideRight
                                text: row.modelData.reason || "" } }
                        Btn { objectName: "refineUndo_" + row.modelData.id; anchors.right: parent.right; anchors.rightMargin: -6; y: 4
                            small: true; kind: "quiet"; icon: "rotate_ccw"; tip: "Undo this change (a new revision)"
                            enabled: !Store.refineBusy; onClicked: Store.refineUndo(row.modelData.id) }
                    }
                }
            }
            // hold to see the design as it was before these changes; let go and the refined one is back
            Btn { id: peekBtn; objectName: "refinePeek"; small: true; icon: "eye"; width: parent.width
                visible: rp.list.length > 0 && !rp.running && Store.refineBase > 0 && !Store.hasDraft
                text: Store.peek && Store.peek.on ? "Before · " + F.pad(Store.peek.rev) : "Hold for Before / After"
                tip: "Hold to see " + F.pad(Store.refineBase) + ", before the refinement. Nothing changes."
                active: !!Store.peek && Store.peek.on
                onDownChanged: Store.peekBefore(down) }
            Row { spacing: 6; visible: !rp.running
                Btn { objectName: "refineUndoAll"; small: true; kind: "quiet"; text: "Undo all"; visible: rp.list.length > 1
                    enabled: !Store.refineBusy; onClicked: Store.refineUndo("") }
                Btn { objectName: "refineAgain"; small: true; kind: "quiet"; icon: "refresh_cw"; text: "Refine again"
                    enabled: !Store.refineBusy; onClicked: Store.refineAgain() } }
            Txt { kind: "fine"; tone: 3; width: parent.width
                text: "Each change is a named feature, kept only when the checks still pass. Measured with heuristics; Settings turns refinement off." }
        }
    }
}
