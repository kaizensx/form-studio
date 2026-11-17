import QtQuick
import FormNative

// Rows of the installer registry (form/installer.py): what each thing is for, whether it was found, the exact command
// an install would run, and what happened when it ran. Data-driven: a new registry entry appears without changes here.
// `ids` picks which rows to show (or `all: true`). The Claude sign-in has its own card (ClaudeSignIn.qml). Nothing runs from a tick: ticks only choose what the button installs.
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
                readonly property bool open: r.status !== "ok" && r.status !== "info"
                width: col.width; height: body.implicitHeight + 26
                Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                // status: a tick box when it can be installed, else a dot or a check
                Item { x: 16; y: 14; width: 16; height: 16
                    Check { objectName: "softwareCheck"; readonly property string sid: row.r.id; visible: sl.selectable && row.r.installable; checked: row.picked; enabled: !Store.installing
                        onToggled: function (on) { Store.setInstallPick(row.r.id, on) } }
                    Icon { visible: row.r.status === "ok"; name: "circle_check"; size: 15; color: Theme.pass; anchors.centerIn: parent }
                    Rectangle { visible: row.r.status !== "ok" && !(sl.selectable && row.r.installable); width: 8; height: 8; radius: 4
                        anchors.centerIn: parent; color: sl.tint(row.r.status) } }
                Column {
                    id: body; x: 44; y: 13; width: parent.width - 44 - 16; spacing: 5
                    Item { width: parent.width; height: 18
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Txt { text: row.r.label; font.weight: 600; wrapMode: Text.NoWrap
                                MouseArea { anchors.fill: parent; enabled: sl.selectable && row.r.installable && !Store.installing
                                    onClicked: Store.setInstallPick(row.r.id, !row.picked) } }
                            Tag { visible: row.r.level !== "optional" && row.r.status !== "ok"; text: row.r.level; kind: row.r.level === "required" ? "WARN" : "specified"
                                anchors.verticalCenter: parent.verticalCenter }
                            Txt { visible: row.open && row.r.size !== ""; kind: "fine"; text: row.r.size; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } }
                        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; wrapMode: Text.NoWrap
                            text: sl.word(row.r); color: sl.tint(row.r.status) } }
                    Txt { kind: "fine"; tone: 2; width: parent.width; text: row.r.status === "ok" ? row.r.detail : row.r.why
                        wrapMode: row.r.status === "ok" ? Text.NoWrap : Text.WordWrap; elide: row.r.status === "ok" ? Text.ElideMiddle : Text.ElideNone }
                    Txt { visible: row.open && row.r.detail !== "" && row.r.detail.indexOf("Not installed.") !== 0 && row.r.detail.indexOf("Installed; Form Studio is not") !== 0
                        kind: "fine"; width: parent.width; text: row.r.detail; wrapMode: Text.Wrap }
                    Txt { visible: row.open && !!row.r.blocked_by; kind: "fine"; width: parent.width; color: Theme.amber
                        text: row.r.blocked_by ? "Install " + row.r.blocked_by.map(function (b) { var it = Store.softwareItem(b); return it ? it.label : b }).join(", ") + " first." : "" }
                    // the exact command, before anything runs
                    Rectangle { visible: row.open && !!row.r.plan && row.r.plan.commands.length > 0 && row.r.plan.kind !== "login"
                        width: parent.width; height: cmds.implicitHeight + 14; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                        Txt { id: cmds; x: 10; y: 7; width: parent.width - 20; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.WrapAnywhere
                            text: row.r.plan ? row.r.plan.commands.map(function (c) { return "$ " + c }).join("\n") : "" } }
                    Txt { visible: row.open && !!row.r.plan && row.r.plan.note !== "" && row.r.plan.kind !== "login"; kind: "fine"; width: parent.width
                        text: row.r.plan ? row.r.plan.note : "" }
                    // why FORM cannot do it itself here
                    Txt { visible: row.open && !row.r.plan && row.r.methods.length > 0; kind: "fine"; width: parent.width
                        text: {
                            var why = row.r.methods.filter(function (m) { return !m.available && m.reason }).map(function (m) { return m.label + ": " + m.reason })
                            var note = row.r.methods.filter(function (m) { return m.kind === "bundled" && m.note }).map(function (m) { return m.note })
                            return note.concat(why.length ? ["Form Studio cannot install this by itself here (" + why.join("; ") + ")."] : []).join(" ")
                        } }
                    Row { visible: row.open && !row.step && (row.r.installable || row.r.manual !== ""); spacing: 8; topPadding: 1
                        Btn { small: true; visible: row.r.installable && !sl.selectable; icon: "download"; text: "Install"; enabled: !Store.installing
                            onClicked: Store.installSoftware([row.r.id]) }
                        Btn { small: true; kind: "quiet"; icon: "external_link"
                            text: row.r.installable ? "Download page instead" : "Open the download page"; visible: row.r.manual !== ""; onClicked: Bridge.openLink(row.r.manual) } }
                    // what happened when it ran
                    Row { visible: !!row.step; spacing: 6; topPadding: 1
                        Icon { size: 13; anchors.verticalCenter: parent.verticalCenter
                            name: !row.step ? "dot" : row.step.state === "done" ? "circle_check" : row.step.state === "failed" ? "circle_alert" : row.step.state === "running" ? "loader_circle" : "dot"
                            color: !row.step ? Theme.ink3 : row.step.state === "done" ? Theme.pass : row.step.state === "failed" ? Theme.signal : Theme.ink2
                            RotationAnimation on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: row.busy }
                            onNameChanged: if (name !== "loader_circle") rotation = 0 }
                        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: body.width - 24
                            text: !row.step ? "" : row.step.state === "waiting" ? "Waiting for its turn" : row.step.state === "running" ? "Working… the log shows each line"
                                : row.step.state === "done" && Store.installJob.fake ? "Simulated: nothing was installed"
                                : row.step.state === "done" ? (row.r.id.indexOf("agent.") === 0 ? "Added: " : "Installed and found: ") + row.step.message : row.step.state === "cancelled" ? "Cancelled"
                                : "Did not install: " + row.step.message } }
                }
            }
        }
    }
}
