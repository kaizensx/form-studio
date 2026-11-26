import QtQuick
import QtQuick.Controls

// Progress of an install you can trust: one segment per item (so it is determinate: "2 of 3"), the newest line the
// command printed while it runs, and the whole log in a drawer that opens by itself when something fails.
// Every line the commands print is here; nothing is summarised away.
Column {
    id: lg
    width: parent ? parent.width : 0
    readonly property bool open: Store.installLogOpen
    readonly property var job: Store.installJob
    readonly property var lines: Store.installLog
    readonly property var steps: job && job.steps ? job.steps : []
    readonly property int done: steps.filter(function (s) { return s.state === "done" }).length
    readonly property int failed: steps.filter(function (s) { return s.state === "failed" }).length
    readonly property var now: { for (var i = 0; i < steps.length; i++) if (steps[i].state === "running" || steps[i].state === "needs_user") return steps[i]; return null }
    readonly property var you: job && job.waiting_for_you ? job.waiting_for_you : null     // hands-free setup paused for the person
    readonly property bool auto: !!job && job.kind === "auto"
    readonly property bool running: !!job && job.state === "running"
    function items(n) { return n === 1 ? "1 item" : n + " items" }
    function label(s) { var it = Store.softwareItem(s.id); return it ? it.label : s.id }
    visible: !!job
    spacing: 8
    Connections { target: Store; function onInstallJobChanged() { if (Store.installJob && Store.installJob.state === "failed") Store.installLogOpen = true } }
    // what is happening, in words
    Item { width: parent.width; height: 22
        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Spinner { visible: lg.running; size: 13; anchors.verticalCenter: parent.verticalCenter }
            Icon { visible: !lg.running; size: 14; anchors.verticalCenter: parent.verticalCenter
                name: lg.failed ? "circle_alert" : lg.job && lg.job.state === "cancelled" ? "circle_x" : "circle_check"
                color: lg.failed ? Theme.signal : lg.job && lg.job.state === "cancelled" ? Theme.ink3 : Theme.pass }
            Txt { font.weight: Theme.wMedium; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: !lg.job ? "" : lg.you ? "Waiting for you · " + lg.label(lg.you) : lg.running && lg.auto ? "Setting up " + Math.min(lg.steps.length, lg.done + lg.failed + 1) + " of " + lg.steps.length + (lg.now ? " · " + lg.label(lg.now) : "")
                    : lg.running ? "Installing " + Math.min(lg.steps.length, lg.done + lg.failed + 1) + " of " + lg.steps.length + (lg.now ? " · " + lg.label(lg.now) : "")
                    : lg.failed ? lg.items(lg.failed) + " did not install" : lg.job.state === "cancelled" ? "Cancelled. " + lg.done + " of " + lg.steps.length + " installed"
                    : "Installed " + lg.done + " of " + lg.steps.length }
            Txt { kind: "fine"; mono: true; anchors.verticalCenter: parent.verticalCenter; visible: !!lg.job; text: lg.job ? Math.round(lg.job.seconds) + " s" : "" }
            Tag { visible: !!lg.job && lg.job.fake; text: "simulated"; kind: "simulated"; anchors.verticalCenter: parent.verticalCenter } }
        Btn { small: true; kind: "quiet"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            icon: lg.open ? "chevron_up" : "chevron_down"; text: (lg.open ? "Hide the log" : "Show the log") + " · " + lg.lines.length
            onClicked: Store.installLogOpen = !Store.installLogOpen } }
    // one segment per item
    Row { width: parent.width; spacing: 4
        Repeater { model: lg.steps
            Rectangle { id: seg; required property var modelData
                width: (lg.width - (lg.steps.length - 1) * 4) / Math.max(1, lg.steps.length); height: 4; radius: 2
                color: modelData.state === "done" ? Theme.pass : modelData.state === "failed" ? Theme.signal : modelData.state === "needs_user" ? Theme.amber
                    : modelData.state === "skipped" ? Theme.ink4 : modelData.state === "running" ? Theme.alpha(Theme.datum, 0.3) : Theme.rule2
                Behavior on color { Tint { duration: Theme.base } }
                // the item being installed: a light that travels, because how long a download takes is not known
                Rectangle { visible: seg.modelData.state === "running"; height: parent.height; width: Math.max(24, parent.width * 0.3); radius: 2; color: Theme.datum
                    SequentialAnimation on x { running: seg.modelData.state === "running" && lg.visible; loops: Animation.Infinite
                        NumberAnimation { from: 0; to: seg.width - Math.max(24, seg.width * 0.3); duration: 900; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0; duration: 900; easing.type: Easing.InOutSine } } }
                HoverHandler { id: sh }
                Tip { show: sh.hovered; text: lg.label(seg.modelData) + " · " + seg.modelData.state + (seg.modelData.message ? " · " + seg.modelData.message : "") } } } }
    // the one thing only the person can do; the engine checks every few seconds and continues by itself
    Rectangle { objectName: "installYourTurn"; visible: !!lg.you; width: parent.width; height: yt.implicitHeight + 24; radius: 14
        color: Theme.alpha(Theme.amber, 0.09)
        Column { id: yt; x: 14; y: 12; width: parent.width - 28; spacing: 8
            Row { spacing: 8
                Icon { name: lg.you && lg.you.action && lg.you.action.kind === "signin" ? "shield_check" : "download"; size: 14; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
                Txt { font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
                    text: lg.you ? (lg.you.action && lg.you.action.kind === "signin" ? "Sign in to continue" : "Install " + lg.label(lg.you) + " to continue") : "" } }
            Txt { kind: "fine"; tone: 2; width: parent.width; text: lg.you && lg.you.action ? lg.you.action.text : "" }
            Row { spacing: 8
                Btn { small: true; kind: "primary"; icon: "external_link"; visible: !!lg.you && !!lg.you.action && !!lg.you.action.url
                    text: lg.you && lg.you.action && lg.you.action.kind === "signin" ? "Open the sign-in page" : "Open the download page"
                    onClicked: Bridge.openLink(lg.you.action.url) }
                Btn { small: true; kind: "quiet"; text: "Skip this"; onClicked: Store.skipInstall(lg.you.id) }
                Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
                    Spinner { size: 11; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; text: "Checking every few seconds"; anchors.verticalCenter: parent.verticalCenter } } } } }
    // the newest line, while the drawer is closed
    Txt { visible: !lg.open && lg.lines.length > 0; width: parent.width; mono: true; font.pixelSize: 11; tone: 3
        elide: Text.ElideRight; wrapMode: Text.NoWrap
        text: lg.lines.length ? (lg.lines[lg.lines.length - 1].kind === "cmd" ? "$ " : "") + lg.lines[lg.lines.length - 1].text : "" }
    Rectangle { visible: lg.open; width: parent.width; height: 168; radius: Theme.rMd; color: Theme.glassWell; border.color: Theme.rule; clip: true
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
