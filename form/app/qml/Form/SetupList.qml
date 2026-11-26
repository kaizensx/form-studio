import QtQuick
import FormNative

// Rows of the installer registry (form/installer.py). Data-driven: a new registry entry appears without changes here.
// `ids` picks which rows to show (or `all: true`). The Claude sign-in has its own card (ClaudeSignIn.qml).
//
// One row, always the same shape:
//   what it is        its mark, its name, one line on what it does, its size and licence
//   where it stands   installed / not installed / installing, at the right
//   what you can do   Install (or the official download page), and once it is installed "Use in Form Studio": the
//                     switch that says whether Form Studio calls it (form/use.py), with one line on what that changes
//                     and the licence beside it. Installed and used are two separate things.
// The chevron opens the rest: what it gives you, where it is, the exact commands an install would run, Remove.
// Nothing runs from a tick: ticks only choose what "Install selected" installs. A non-commercial licence is shown as
// one line in a confirmation first, and pressing Install there accepts it. While it installs, the row shows the latest
// line and how far a download got; a failure is shown on the row, and the row can be installed again.
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
    radius: Theme.rLg; color: Theme.plate1; border.color: Theme.rule
    function tint(st) { return st === "ok" ? Theme.pass : st === "warn" ? Theme.amber : st === "missing" ? Theme.ink3 : Theme.ink4 }
    function word(r) {
        var agent = r.id.indexOf("agent.") === 0
        return r.status === "ok" ? (agent ? "Added" : r.id === "data" ? "Ready" : r.id.indexOf(".signin") > 0 ? "Signed in" : "Installed") : r.status === "warn" ? "Check" : r.status === "missing" ? (agent ? "Not added" : "Not installed") : "Not needed"
    }
    // the mark on the row's tile: what kind of thing it is
    function glyph(r) {
        var id = r.id
        if (id === "kernel") return "cuboid"
        if (id === "data") return "folder"
        if (id === "parts") return "cog"
        if (id.indexOf("slicer.") === 0) return "layers"
        if (id === "recon.learned") return "sparkles"
        if (id === "recon.cadfit") return "scan_line"
        if (id === "game.coacd") return "gamepad_2"
        if (id === "exemplars.cadevolve") return "library"
        if (id === "blender") return "image"
        if (id === "freecad") return "box"
        if (id === "openscad") return "code"
        if (id.indexOf("agent.") === 0) return "link"
        if (id.indexOf(".signin") > 0) return "user"
        return r.group === "ai" || r.group === "agents" ? "bot" : "package"
    }

    Column {
        id: col; width: parent.width
        Row { visible: !sl.sw; x: 16; spacing: 8; height: 56
            Icon { name: "loader_circle"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
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
                readonly property bool ok: r.status === "ok"
                readonly property bool open: r.status !== "ok" && r.status !== "info"       // something could be installed
                readonly property bool hasUse: ok && !!r.use
                readonly property bool used: Store.useOn(r)
                readonly property bool locked: !!r.use && r.use.locked_by !== ""
                property bool more: false           // the details are unfolded
                property bool confirming: false     // the licence line is showing, waiting for Install or Cancel
                property bool removing: false       // the Remove question is showing
                readonly property bool hasPage: r.methods.some(function (m) { return m.kind === "open" })
                readonly property bool failed: !!step && step.state === "failed"
                readonly property bool details: more || failed
                // the latest line this row's install wrote, and how far a download got ("… (40%)")
                readonly property string lastLine: {
                    if (!busy) return ""
                    var L = Store.installLog
                    for (var i = L.length - 1; i >= 0; i--) if (L[i].step === r.id && L[i].kind !== "cmd" && L[i].text) return L[i].text
                    return ""
                }
                readonly property real pct: { var m = /\((\d+)%\)/.exec(lastLine); return m ? Number(m[1]) / 100 : -1 }
                width: col.width; height: body.implicitHeight + 28
                Rectangle { visible: row.index > 0; x: 16; width: parent.width - 32; height: 1; color: Theme.rule }

                // the tile: what kind of thing it is; it lights up when Form Studio uses it
                Rectangle { id: tile; x: 16; y: 14; width: 34; height: 34; radius: Theme.rMd
                    readonly property bool lit: row.ok && (!row.r.use || row.used)
                    color: lit ? Theme.alpha(Theme.datum, Theme.dark ? 0.1 : 0.09) : Theme.alpha(Theme.lineBase, 0.04)
                    border.color: lit ? Theme.alpha(Theme.datum, 0.32) : Theme.rule
                    Behavior on color { Tint {} }
                    Icon { anchors.centerIn: parent; name: sl.glyph(row.r); size: 16; color: tile.lit ? Theme.datum : Theme.ink3 } }

                Column {
                    id: body; x: 62; y: 13; width: parent.width - 62 - 16; spacing: 8
                    // ── what it is, where it stands, what you can do ──
                    Item { width: parent.width; height: Math.max(names.implicitHeight, 36)
                        Column { id: names; width: parent.width - acts.width - 14; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                            Row { spacing: 8; width: parent.width
                                Txt { text: row.r.label; font.weight: Theme.wSemi; wrapMode: Text.NoWrap; elide: Text.ElideRight
                                    width: Math.min(implicitWidth, parent.width - (nc.visible ? nc.width + 8 : 0) - (lvl.visible ? lvl.width + 8 : 0))
                                    MouseArea { anchors.fill: parent; onClicked: row.more = !row.more } }
                                Tag { id: nc; visible: !!row.r.noncommercial; text: "non-commercial"; tint: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
                                Tag { id: lvl; visible: row.r.level !== "optional" && !row.ok; text: row.r.level; kind: row.r.level === "required" ? "WARN" : "specified"
                                    anchors.verticalCenter: parent.verticalCenter } }
                            Txt { kind: "fine"; tone: 2; width: parent.width; text: row.r.why; maximumLineCount: row.details ? 6 : 2; elide: Text.ElideRight } }
                        Row { id: acts; spacing: 10; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            // where it stands
                            Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
                                Spinner { visible: row.queued; size: 12; anchors.verticalCenter: parent.verticalCenter }
                                Rectangle { visible: !row.queued; width: 7; height: 7; radius: 3.5; color: sl.tint(row.r.status); anchors.verticalCenter: parent.verticalCenter }
                                Txt { objectName: "softwareStatus"; readonly property string sid: row.r.id; kind: "fine"; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                                    font.weight: Theme.wMedium; color: row.queued ? Theme.ink2 : row.ok ? Theme.pass : sl.tint(row.r.status)
                                    text: row.busy ? "Installing…" : row.queued ? "Waiting" : sl.word(row.r) } }
                            // tick it for "Install selected"
                            Check { objectName: "softwareCheck"; readonly property string sid: row.r.id; anchors.verticalCenter: parent.verticalCenter
                                visible: sl.selectable && row.open && row.r.installable && !row.r.noncommercial && !row.queued; checked: row.picked; enabled: !Store.installing
                                onToggled: function (on) { Store.setInstallPick(row.r.id, on) } }
                            Btn { objectName: "softwareInstall"; readonly property string sid: row.r.id; small: true; kind: "primary"; anchors.verticalCenter: parent.verticalCenter
                                visible: row.open && !row.queued && !row.confirming && row.r.installable; icon: "download"; text: "Install"; enabled: !Store.installing
                                onClicked: { if (row.r.noncommercial) row.confirming = true; else Store.installSoftware([row.r.id]) } }
                            Btn { objectName: "softwarePage"; readonly property string sid: row.r.id; small: true; icon: "external_link"; anchors.verticalCenter: parent.verticalCenter
                                text: row.hasPage ? "Download page" : "Its page"
                                visible: row.open && !row.queued && !row.r.installable && row.r.manual !== ""; onClicked: Bridge.openLink(row.r.manual) }
                            Btn { objectName: "softwareMore"; readonly property string sid: row.r.id; small: true; kind: "quiet"; anchors.verticalCenter: parent.verticalCenter
                                icon: row.details ? "chevron_up" : "chevron_down"; tip: row.details ? "Less" : "What it gives you, where it is and what an install runs"
                                onClicked: row.more = !row.more } } }

                    // size and licence, always on the card
                    Txt { objectName: "softwareMeta"; readonly property string sid: row.r.id; kind: "fine"; tone: 3; width: parent.width; wrapMode: Text.WordWrap
                        visible: text !== ""
                        text: [row.r.size ? "Size: " + row.r.size : "", row.r.licence ? "Licence: " + row.r.licence : ""].filter(function (x) { return x }).join("   ·   ") }

                    // ── Use in Form Studio: installed is one thing, used is another ──
                    Rectangle { objectName: "softwareUsePanel"; readonly property string sid: row.r.id; visible: row.hasUse
                        width: parent.width; height: useCol.implicitHeight + 22; radius: Theme.rMd
                        color: row.used ? Theme.alpha(Theme.datum, Theme.dark ? 0.06 : 0.055) : Theme.alpha(Theme.lineBase, 0.025)
                        border.color: row.used ? Theme.alpha(Theme.datum, 0.3) : Theme.rule
                        Behavior on color { Tint {} }
                        Behavior on border.color { Tint {} }
                        Column { id: useCol; x: 14; y: 11; width: parent.width - 28 - useSw.width - 16; spacing: 3
                            Row { spacing: 8
                                Txt { text: "Use in Form Studio"; font.weight: Theme.wMedium }
                                Txt { objectName: "softwareUseWord"; readonly property string sid: row.r.id; kind: "fine"; anchors.verticalCenter: parent.verticalCenter
                                    color: row.used ? Theme.datum : Theme.ink3; font.weight: Theme.wMedium
                                    text: row.used ? "On" : "Off: installed, never called" } }
                            Txt { objectName: "softwareUseEffect"; readonly property string sid: row.r.id; kind: "fine"; tone: 2; width: parent.width
                                text: row.r.use ? row.r.use.effect : "" }
                            Txt { kind: "fine"; width: parent.width; visible: !!row.r.licence
                                color: row.r.noncommercial ? Theme.amber : Theme.ink3
                                text: "Licence: " + (row.r.licence || "") }
                            Txt { kind: "fine"; tone: 3; width: parent.width; visible: row.locked
                                text: row.r.use ? "Set for this run by " + row.r.use.locked_by + ". That wins until Form Studio restarts without it." : "" } }
                        Toggle { id: useSw; objectName: "softwareUse"; readonly property string sid: row.r.id
                            anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                            checked: row.used; enabled: !row.locked && !Store.installing
                            onToggled: function (on) { Store.setUse(row.r, on) } } }

                    Txt { visible: row.open && !!row.r.blocked_by; kind: "fine"; width: parent.width; color: Theme.amber
                        text: row.r.blocked_by ? "Install " + row.r.blocked_by.map(function (b) { var it = Store.softwareItem(b); return it ? it.label : b }).join(", ") + " first." : "" }

                    // a non-commercial licence: one line, then Install accepts it
                    Rectangle { objectName: "licenceConfirm"; readonly property string sid: row.r.id; visible: row.confirming && row.open && !row.queued
                        width: parent.width; height: cf.implicitHeight + 22; radius: Theme.rMd; color: Theme.alpha(Theme.amber, 0.07); border.color: Theme.alpha(Theme.amber, 0.5)
                        Column { id: cf; x: 12; y: 11; width: parent.width - 24; spacing: 9
                            Txt { kind: "fine"; tone: 2; width: parent.width; wrapMode: Text.WordWrap; text: row.r.licence_notice || ("Licence: " + row.r.licence) }
                            Row { spacing: 8
                                Btn { objectName: "licenceAccept"; small: true; kind: "primary"; icon: "download"; text: "Install"; enabled: !Store.installing
                                    onClicked: { row.confirming = false; Store.installSoftware([row.r.id]) } }
                                Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: row.confirming = false }
                                Btn { small: true; kind: "quiet"; icon: "external_link"; text: "Read the licence"; visible: !!row.r.licence_url
                                    onClicked: Bridge.openLink(row.r.licence_url) } } } }

                    // what happened when it ran
                    Row { visible: !!row.step; spacing: 6
                        Icon { size: 13; anchors.verticalCenter: parent.verticalCenter
                            name: !row.step ? "dot" : row.step.state === "done" ? "circle_check" : row.step.state === "failed" ? "circle_alert" : row.step.state === "running" ? "loader_circle" : "dot"
                            color: !row.step ? Theme.ink3 : row.step.state === "done" ? Theme.pass : row.step.state === "failed" ? Theme.signal : Theme.ink2 }
                        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: body.width - 24
                            color: !!row.step && row.step.state === "failed" ? Theme.signal : Theme.ink2
                            text: !row.step ? "" : row.step.state === "waiting" ? "Waiting for its turn" : row.step.state === "running" ? (row.lastLine || "Working… the log shows each line")
                                : row.step.state === "done" && Store.installJob.fake ? "Simulated: nothing was installed"
                                : row.step.state === "done" ? (row.r.id.indexOf("agent.") === 0 ? "Added: " : "Installed and found: ") + row.step.message : row.step.state === "cancelled" ? "Cancelled"
                                : "Did not install: " + row.step.message + ". Nothing was changed; press Install to try again." } }
                    // how far a download got
                    Rectangle { objectName: "softwareProgress"; visible: row.busy && row.pct >= 0; width: parent.width; height: 3; radius: 1.5; color: Theme.rule
                        Rectangle { width: parent.width * Math.max(0, Math.min(1, row.pct)); height: parent.height; radius: 1.5; color: Theme.datum
                            Behavior on width { NumberAnimation { duration: 200 } } } }

                    // ── the rest, behind the chevron ──
                    Column { visible: row.details; width: parent.width; spacing: 7
                        Rectangle { width: parent.width; height: 1; color: Theme.rule }
                        // what it does for the person and when they would want it, then what it gives them
                        Txt { objectName: "softwareAbout"; readonly property string sid: row.r.id; tone: 2; width: parent.width; lineHeight: 1.3
                            visible: text !== row.r.why; text: row.r.about || row.r.why }
                        Txt { objectName: "softwareGives"; readonly property string sid: row.r.id; kind: "fine"; width: parent.width; visible: !!row.r.gives
                            textFormat: Text.StyledText; color: Theme.ink2
                            text: row.r.gives ? "<font color='" + Theme.ink3 + "'>What this gives you</font>&nbsp;&nbsp;" + row.r.gives.replace(/&/g, "&amp;").replace(/</g, "&lt;") : "" }
                        // where it is, once it is there; why not, when it is not
                        Txt { kind: "fine"; tone: 3; width: parent.width; visible: row.ok && row.r.detail !== ""; text: row.r.detail
                            wrapMode: Text.NoWrap; elide: Text.ElideMiddle }
                        Txt { visible: row.open && row.r.detail !== "" && row.r.detail.indexOf("Not installed.") !== 0
                            kind: "fine"; width: parent.width; text: row.r.detail; wrapMode: Text.Wrap }
                        // the exact command, before anything runs
                        Rectangle { visible: row.open && !!row.r.plan && row.r.plan.commands.length > 0 && row.r.plan.kind !== "login"
                            width: parent.width; height: cmds.implicitHeight + 16; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                            Txt { id: cmds; x: 10; y: 8; width: parent.width - 20; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.WrapAnywhere
                                text: row.r.plan ? row.r.plan.commands.map(function (c) { return (row.r.plan.kind === "action" ? "" : "$ ") + c }).join("\n") : "" } }
                        Txt { visible: row.open && !!row.r.plan && row.r.plan.note !== "" && row.r.plan.kind !== "login"; kind: "fine"; width: parent.width
                            text: row.r.plan ? row.r.plan.note : "" }
                        // why Form Studio cannot do it itself here
                        Txt { visible: row.open && !row.r.plan && row.r.methods.length > 0 && text !== ""; kind: "fine"; width: parent.width
                            text: {
                                var why = row.r.methods.filter(function (m) { return !m.available && m.reason }).map(function (m) { return m.label + ": " + m.reason })
                                var note = row.r.methods.filter(function (m) { return m.kind === "bundled" && m.note }).map(function (m) { return m.note })
                                return note.concat(why.length ? ["Form Studio cannot install this by itself here (" + why.join("; ") + ")."] : []).join(" ")
                            } }
                        Row { spacing: 8; visible: !row.removing
                            Btn { small: true; kind: "quiet"; icon: "external_link"; visible: row.open && row.r.installable && row.r.manual !== ""
                                text: row.hasPage ? "Download page instead" : "Project page"; onClicked: Bridge.openLink(row.r.manual) }
                            Btn { small: true; kind: "quiet"; icon: "external_link"; visible: row.ok && !!row.r.homepage; text: "Project page"
                                onClicked: Bridge.openLink(row.r.homepage) }
                            // Remove: what Form Studio downloaded for it (an engine's own Python, model weights, the corpus); asks first
                            Btn { objectName: "softwareRemove"; readonly property string sid: row.r.id; small: true; kind: "quiet"; icon: "trash_2"; text: "Remove…"
                                visible: !!row.r.removable && !Store.installing
                                tip: "Delete what Form Studio downloaded for it. You can install it again later."; onClicked: row.removing = true } }
                        Rectangle { objectName: "removeConfirm"; readonly property string sid: row.r.id; visible: row.removing && !!row.r.removable
                            width: parent.width; height: rc.implicitHeight + 22; radius: Theme.rMd; color: Theme.well; border.color: Theme.rule2
                            Column { id: rc; x: 12; y: 11; width: parent.width - 24; spacing: 9
                                Txt { kind: "fine"; width: parent.width; tone: 2
                                    text: "Remove " + row.r.label + "? This deletes what Form Studio downloaded for it"
                                          + " from this computer. Your designs are not affected, and you can install it again any time." }
                                Row { spacing: 8
                                    Btn { objectName: "removeAccept"; small: true; kind: "danger"; icon: "trash_2"; text: "Remove"
                                        onClicked: run(function () { return Store.removeSoftware(row.r.id).then(function () { row.removing = false }) }) }
                                    Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: row.removing = false } } } }
                    }
                }
            }
        }
    }
}
