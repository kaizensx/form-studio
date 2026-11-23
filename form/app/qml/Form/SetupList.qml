import QtQuick
import FormNative

// Rows of the installer registry (form/installer.py): what each thing is for, whether it was found, the exact command
// an install would run, and what happened when it ran. Data-driven: a new registry entry appears without changes here.
// `ids` picks which rows to show (or `all: true`). The Claude sign-in has its own card (ClaudeSignIn.qml). Nothing runs from a tick: ticks only choose what the button installs.
// Every row that is not there yet has its own Install button (or the official download page when Form Studio cannot
// install it here); its size and licence are always on the card. A non-commercial licence is shown as one line in a
// confirmation first, and pressing Install there accepts it. While it installs, the row shows the latest line and
// how far a download got; a failure is shown on the row, and the row can be installed again.
Rectangle {
    id: sl
    property var ids: []
    property bool all: false                // show every row (ids is ignored)
    property bool selectable: true          // tick boxes (a button elsewhere installs the ticked rows)
    property bool showAbsent: false         // agents that are not on this computer
    readonly property var sw: Store.software
    readonly property var rows: {
        if (!sw) return []
        var all = sw.software, want = sl.ids
        return all.filter(function (r) { return r.id !== "claude.signin" && (sl.all || want.indexOf(r.id) >= 0) && (sl.showAbsent || !r.absent) })
    }
    width: parent ? parent.width : 0
    height: col.implicitHeight; visible: rows.length > 0 || !sw
    radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
    function tint(st) { return st === "ok" ? Theme.pass : st === "warn" ? Theme.amber : st === "missing" ? Theme.ink3 : Theme.ink4 }
    function word(r) {
        var agent = r.id.indexOf("agent.") === 0
        return r.status === "ok" ? (agent ? "added" : "ready") : r.status === "warn" ? "check" : r.status === "missing" ? (agent ? "not added yet" : "not installed") : "not needed"
    }

    Column {
        id: col; width: parent.width
        Row { visible: !sl.sw; x: 16; spacing: 8; height: 48
            Icon { name: "loader_circle"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter
                RotationAnimation on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: !sl.sw } }
            Txt { tone: 2; text: "Looking at what is installed…"; anchors.verticalCenter: parent.verticalCenter } }
        Repeater {
            model: sl.rows
            Item {
                id: row
                required property var modelData
                required property int index
                readonly property var r: modelData
                readonly property var step: Store.installStep(r.id)
                readonly property bool picked: !!Store.installPick[r.id]
                readonly property bool busy: !!step && step.state === "running"
                readonly property bool queued: !!step && (step.state === "running" || step.state === "waiting")
                readonly property bool open: r.status !== "ok" && r.status !== "info"
                property bool confirming: false     // the licence line is showing, waiting for Install or Cancel
                readonly property bool hasPage: r.methods.some(function (m) { return m.kind === "open" })
                // the latest line this row's install wrote, and how far a download got ("… (40%)")
                readonly property string lastLine: {
                    if (!busy) return ""
                    var L = Store.installLog
                    for (var i = L.length - 1; i >= 0; i--) if (L[i].step === r.id && L[i].kind !== "cmd" && L[i].text) return L[i].text
                    return ""
                }
                readonly property real pct: { var m = /\((\d+)%\)/.exec(lastLine); return m ? Number(m[1]) / 100 : -1 }
                width: col.width; height: body.implicitHeight + 26
                Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                // status: a tick box when it can be installed, else a dot or a check
                Item { x: 16; y: 14; width: 16; height: 16
                    Check { objectName: "softwareCheck"; readonly property string sid: row.r.id; visible: sl.selectable && row.r.installable && !row.r.noncommercial; checked: row.picked; enabled: !Store.installing
                        onToggled: function (on) { Store.setInstallPick(row.r.id, on) } }
                    Icon { visible: row.r.status === "ok"; name: "circle_check"; size: 15; color: Theme.pass; anchors.centerIn: parent }
                    Rectangle { visible: row.r.status !== "ok" && !(sl.selectable && row.r.installable && !row.r.noncommercial); width: 8; height: 8; radius: 4
                        anchors.centerIn: parent; color: sl.tint(row.r.status) } }
                Column {
                    id: body; x: 44; y: 13; width: parent.width - 44 - 16; spacing: 5
                    Item { width: parent.width; height: 18
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Txt { text: row.r.label; font.weight: 600; wrapMode: Text.NoWrap
                                MouseArea { anchors.fill: parent; enabled: sl.selectable && row.r.installable && !row.r.noncommercial && !Store.installing
                                    onClicked: Store.setInstallPick(row.r.id, !row.picked) } }
                            Tag { visible: row.r.level !== "optional" && row.r.status !== "ok"; text: row.r.level; kind: row.r.level === "required" ? "WARN" : "specified"
                                anchors.verticalCenter: parent.verticalCenter } }
                        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; wrapMode: Text.NoWrap
                            text: sl.word(row.r); color: sl.tint(row.r.status) } }
                    Txt { kind: "fine"; tone: 2; width: parent.width; text: row.r.status === "ok" ? row.r.detail : row.r.why
                        wrapMode: row.r.status === "ok" ? Text.NoWrap : Text.WordWrap; elide: row.r.status === "ok" ? Text.ElideMiddle : Text.ElideNone }
                    // size and licence, always on the card
                    Txt { objectName: "softwareMeta"; readonly property string sid: row.r.id; kind: "fine"; tone: 3; width: parent.width; wrapMode: Text.WordWrap
                        visible: text !== ""
                        text: [row.r.size ? "Size: " + row.r.size : "", row.r.licence ? "Licence: " + row.r.licence : ""].filter(function (x) { return x }).join("   ·   ") }
                    Txt { visible: row.open && row.r.detail !== "" && row.r.detail.indexOf("Not installed.") !== 0 && row.r.detail.indexOf("Installed; Form Studio is not") !== 0
                        kind: "fine"; width: parent.width; text: row.r.detail; wrapMode: Text.Wrap }
                    Txt { visible: row.open && !!row.r.blocked_by; kind: "fine"; width: parent.width; color: Theme.amber
                        text: row.r.blocked_by ? "Install " + row.r.blocked_by.map(function (b) { var it = Store.softwareItem(b); return it ? it.label : b }).join(", ") + " first." : "" }
                    // the exact command, before anything runs
                    Rectangle { visible: row.open && !!row.r.plan && row.r.plan.commands.length > 0 && row.r.plan.kind !== "login"
                        width: parent.width; height: cmds.implicitHeight + 14; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                        Txt { id: cmds; x: 10; y: 7; width: parent.width - 20; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.WrapAnywhere
                            text: row.r.plan ? row.r.plan.commands.map(function (c) { return (row.r.plan.kind === "action" ? "" : "$ ") + c }).join("\n") : "" } }
                    Txt { visible: row.open && !!row.r.plan && row.r.plan.note !== "" && row.r.plan.kind !== "login"; kind: "fine"; width: parent.width
                        text: row.r.plan ? row.r.plan.note : "" }
                    // why FORM cannot do it itself here
                    Txt { visible: row.open && !row.r.plan && row.r.methods.length > 0; kind: "fine"; width: parent.width
                        text: {
                            var why = row.r.methods.filter(function (m) { return !m.available && m.reason }).map(function (m) { return m.label + ": " + m.reason })
                            var note = row.r.methods.filter(function (m) { return m.kind === "bundled" && m.note }).map(function (m) { return m.note })
                            return note.concat(why.length ? ["Form Studio cannot install this by itself here (" + why.join("; ") + ")."] : []).join(" ")
                        } }
                    Row { visible: row.open && !row.queued && !row.confirming && (row.r.installable || row.r.manual !== ""); spacing: 8; topPadding: 1
                        Btn { objectName: "softwareInstall"; readonly property string sid: row.r.id; small: true; kind: "primary"
                            visible: row.r.installable; icon: "download"; text: "Install"; enabled: !Store.installing
                            onClicked: { if (row.r.noncommercial) row.confirming = true; else Store.installSoftware([row.r.id]) } }
                        Btn { objectName: "softwarePage"; readonly property string sid: row.r.id; small: true; kind: row.r.installable ? "quiet" : "default"; icon: "external_link"
                            text: !row.r.installable ? (row.hasPage ? "Open download page" : "Open its page") : row.hasPage ? "Download page instead" : "Project page"
                            visible: row.r.manual !== ""; onClicked: Bridge.openLink(row.r.manual) } }
                    // a non-commercial licence: one line, then Install accepts it
                    Rectangle { objectName: "licenceConfirm"; readonly property string sid: row.r.id; visible: row.confirming && row.open && !row.queued
                        width: parent.width; height: cf.implicitHeight + 20; radius: Theme.rSm; color: Theme.well; border.color: Theme.amber
                        Column { id: cf; x: 10; y: 10; width: parent.width - 20; spacing: 8
                            Txt { kind: "fine"; width: parent.width; wrapMode: Text.WordWrap; text: row.r.licence_notice || ("Licence: " + row.r.licence) }
                            Row { spacing: 8
                                Btn { objectName: "licenceAccept"; small: true; kind: "primary"; icon: "download"; text: "Install"; enabled: !Store.installing
                                    onClicked: { row.confirming = false; Store.installSoftware([row.r.id]) } }
                                Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: row.confirming = false }
                                Btn { small: true; kind: "quiet"; icon: "external_link"; text: "Read the licence"; visible: !!row.r.licence_url
                                    onClicked: Bridge.openLink(row.r.licence_url) } } } }
                    // what happened when it ran
                    Row { visible: !!row.step; spacing: 6; topPadding: 1
                        Icon { size: 13; anchors.verticalCenter: parent.verticalCenter
                            name: !row.step ? "dot" : row.step.state === "done" ? "circle_check" : row.step.state === "failed" ? "circle_alert" : row.step.state === "running" ? "loader_circle" : "dot"
                            color: !row.step ? Theme.ink3 : row.step.state === "done" ? Theme.pass : row.step.state === "failed" ? Theme.signal : Theme.ink2
                            RotationAnimation on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: row.busy }
                            onNameChanged: if (name !== "loader_circle") rotation = 0 }
                        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: body.width - 24
                            color: !!row.step && row.step.state === "failed" ? Theme.signal : Theme.ink2
                            text: !row.step ? "" : row.step.state === "waiting" ? "Waiting for its turn" : row.step.state === "running" ? (row.lastLine || "Working… the log shows each line")
                                : row.step.state === "done" && Store.installJob.fake ? "Simulated: nothing was installed"
                                : row.step.state === "done" ? (row.r.id.indexOf("agent.") === 0 ? "Added: " : "Installed and found: ") + row.step.message : row.step.state === "cancelled" ? "Cancelled"
                                : "Did not install: " + row.step.message + ". Nothing was changed; press Install to try again." } }
                    // how far a download got
                    Rectangle { objectName: "softwareProgress"; visible: row.busy && row.pct >= 0; width: parent.width; height: 3; radius: 1.5; color: Theme.rule
                        Rectangle { width: parent.width * Math.max(0, Math.min(1, row.pct)); height: parent.height; radius: 1.5; color: Theme.ink2
                            Behavior on width { NumberAnimation { duration: 200 } } } }
                }
            }
        }
    }
}
