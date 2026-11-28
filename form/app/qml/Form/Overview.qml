import QtQuick
import QtQuick.Controls
import "F.js" as F

// The Overview of a design (direction I, decision 2): what Describe was, opened from the design capsule as a sheet over
// the stage. The conversation stays where it is. Left: the brief, what is known and measured, the references
// (Brief.qml, unchanged). Right: the revisions, who made each and what it changed. A sheet is for reading, so its
// glass is denser than a pane's (80 % plate). Esc, the capsule or the × close it.
Glass {
    id: ov
    objectName: "overview"
    property bool on: false
    readonly property var p: Store.project
    readonly property var revs: p && p.revisions ? p.revisions.slice().reverse() : []
    readonly property bool wide: width >= 760
    radius: Theme.rPane
    opacity: on ? 1 : 0; visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: ov.on ? Theme.base : Theme.exit; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    property real lift: on ? 0 : Theme.shift(Theme.rise)
    Behavior on lift { NumberAnimation { duration: Theme.move(Theme.benchOpen); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    transform: Translate { y: ov.lift }
    Rectangle { anchors.fill: parent; radius: ov.radius; color: Theme.alpha(Theme.plate1, ov.blurred ? 0.8 : 0.9) }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true;      // nothing under the sheet answers the pointer
        onWheel: function (w) { w.accepted = true } }
    focus: on
    Keys.onEscapePressed: Store.overview = false

    Item { id: head; x: 28; y: 22; width: parent.width - 56; height: 40
        Txt { id: nm; objectName: "overviewName"; kind: "h2"; text: ov.p ? ov.p.name : ""; anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width - 60 - (ov.wide ? meta.implicitWidth + 16 : 0)); elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Txt { id: meta; visible: ov.wide; anchors.left: nm.right; anchors.leftMargin: 16; anchors.baseline: nm.baseline; mono: true; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap
            text: !ov.p || !Store.data ? "" : [F.pad(ov.p.head), Store.data.approval.state === "approved" ? "released" : "unreleased",
                Store.purpose === "print" ? "for 3D printing" : Store.purpose === "game" ? "game asset" : "3D model"].join(" · ") }
        Btn { objectName: "overviewClose"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "quiet"; small: true; icon: "x"; tip: "Close the Overview"; keys: "Ctrl+I"
            onClicked: Store.overview = false } }

    Flickable { id: left; objectName: "overviewBrief"
        x: 28; y: 72; width: ov.wide ? Math.round((parent.width - 56 - 40) * 0.58) : parent.width - 56; height: parent.height - y - foot.height - 22 - 18
        contentHeight: brief.implicitHeight + 16; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Loader { id: brief; width: parent.width - 8; active: ov.visible && !!Store.data; source: "Brief.qml" } }

    Item { id: right; visible: ov.wide; x: left.x + left.width + 40; y: 72; width: parent.width - x - 28; height: left.height
        Item { id: rh; width: parent.width; height: 32
            Txt { id: rt; font.weight: Theme.wSemi; font.pixelSize: 14; text: "Revisions"; anchors.verticalCenter: parent.verticalCenter }
            Txt { anchors.left: rt.right; anchors.leftMargin: 10; anchors.baseline: rt.baseline; kind: "fine"; tone: 3; text: "who changed what" }
            Txt { anchors.right: parent.right; anchors.baseline: rt.baseline; mono: true; font.pixelSize: 11; tone: 3; text: String(ov.revs.length) } }
        ListView { objectName: "overviewRevisions"; anchors.top: rh.bottom; anchors.topMargin: 6; anchors.bottom: parent.bottom; width: parent.width; clip: true; boundsBehavior: Flickable.StopAtBounds
            model: ov.revs; spacing: 2
            ScrollBar.vertical: ScrollBar { width: 6 }
            delegate: Item { id: rv
                required property var modelData
                readonly property bool head: !!ov.p && modelData.n === ov.p.head
                width: ListView.view.width - 8; height: 46
                Rectangle { x: 6; y: 20; width: 6; height: 6; radius: 3; color: rv.head ? Theme.datum : Theme.ink3 }
                Txt { x: 24; y: 5; mono: true; font.pixelSize: 12; color: rv.head ? Theme.datum : Theme.ink; text: F.pad(rv.modelData.n) }
                Txt { x: 62; y: 5; width: parent.width - 62 - when.width - 10; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: rv.modelData.summary || rv.modelData.note || "revision" }
                Txt { x: 62; y: 25; kind: "fine"; tone: 3; width: parent.width - 62; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: "by " + Store.who(rv.modelData.origin) }
                Txt { id: when; anchors.right: parent.right; y: 6; kind: "fine"; tone: 3; text: F.ago(rv.modelData.ts) }
                // a revision other than the head opens the compare sheet against the head (CompareSheet.qml)
                Rectangle { z: -1; anchors.fill: parent; radius: 10; color: rvm.containsMouse && !rv.head ? Theme.washHover : "transparent" }
                MouseArea { id: rvm; objectName: "overviewRev-" + rv.modelData.n; anchors.fill: parent; hoverEnabled: true; enabled: !rv.head
                    cursorShape: Qt.PointingHandCursor; onClicked: { Store.overview = false; Store.openSheet("compare", { a: rv.modelData.n, b: ov.p.head }) } }
                Tip { show: rvm.containsMouse; text: "What changed from " + F.pad(rv.modelData.n) + " to the head" } } } }

    Row { id: foot; x: 28; anchors.bottom: parent.bottom; anchors.bottomMargin: 22; spacing: 8; height: 32
        Btn { text: "Revisions on the part"; icon: "history"; onClicked: { Store.overview = false; Store.timelineOpen = true } }
        Btn { text: "Export as one file"; icon: "archive"; onClicked: Store.exportProject(Store.pid) }
        Btn { visible: ov.wide; text: "Duplicate"; kind: "quiet"; onClicked: Store.duplicateProject(Store.pid) } }
}
