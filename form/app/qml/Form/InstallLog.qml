import QtQuick
import QtQuick.Controls

// The live log of an install, in a drawer that stays closed until asked for (or until something fails).
// Every line the commands print is here; nothing is summarised away.
Column {
    id: lg
    width: parent ? parent.width : 0
    readonly property bool open: Store.installLogOpen
    readonly property var job: Store.installJob
    readonly property var lines: Store.installLog
    visible: !!job
    spacing: 6
    Connections { target: Store; function onInstallJobChanged() { if (Store.installJob && Store.installJob.state === "failed") Store.installLogOpen = true } }
    Item { width: parent.width; height: 24
        Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
            Icon { name: lg.open ? "chevron_down" : "chevron_right"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: (lg.open ? "Hide the log" : "Show the log") + "  ·  " + lg.lines.length + (lg.lines.length === 1 ? " line" : " lines") }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; visible: !!lg.job
                text: !lg.job ? "" : lg.job.state === "running" ? "·  running " + Math.round(lg.job.seconds) + " s" : "·  " + lg.job.state + " after " + Math.round(lg.job.seconds) + " s" }
            Tag { visible: !!lg.job && lg.job.fake; text: "simulated"; kind: "simulated"; anchors.verticalCenter: parent.verticalCenter } }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Store.installLogOpen = !Store.installLogOpen }
        // the newest line, while the drawer is closed
        Txt { visible: !lg.open && lg.lines.length > 0; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - 330); horizontalAlignment: Text.AlignRight; mono: true; font.pixelSize: 11; tone: 3
            elide: Text.ElideRight; wrapMode: Text.NoWrap; text: lg.lines.length ? lg.lines[lg.lines.length - 1].text : "" } }
    Rectangle { visible: lg.open; width: parent.width; height: 168; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule; clip: true
        ListView {
            id: list; anchors.fill: parent; anchors.margins: 8; model: lg.lines; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            onCountChanged: Qt.callLater(positionViewAtEnd)
            onVisibleChanged: if (visible) Qt.callLater(positionViewAtEnd)
            delegate: Txt { required property var modelData
                width: list.width - 8; mono: true; font.pixelSize: 11; wrapMode: Text.WrapAnywhere
                text: (modelData.kind === "cmd" ? "$ " : "") + modelData.text
                color: modelData.kind === "cmd" ? Theme.ink : modelData.kind === "err" ? Theme.signal : modelData.kind === "note" ? Theme.amber : Theme.ink3 } } }
}
