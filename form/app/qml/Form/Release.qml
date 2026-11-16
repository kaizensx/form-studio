import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Stage 05 — Release. A release is a frozen copy of files whose hashes match the revision they claim to be.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var d: Store.data
    readonly property var p: Store.project
    readonly property var g: d ? d.gate : null
    readonly property var ap: d ? d.approval : null
    readonly property bool approved: !!ap && ap.state === "approved"
    readonly property var warnings: g && g.warnings ? g.warnings : []
    readonly property bool allAcked: warnings.every(function (w) { return Store.ack.indexOf(w.id) >= 0 })
    readonly property var revs: p ? p.revisions.slice().sort(function (a, b) { return b.n - a.n }) : []
    readonly property bool hasStep: !!d && !!d.exports && !!d.exports.files.step
    readonly property bool noStep: !!d && !!d.exports && !d.exports.files.step
    readonly property var fc: Store.studio && Store.studio.env.cad ? Store.studio.env.cad.freecad : ({ available: false })
    property var verified: ({})          // release name → result line from the last Verify
    property bool approving: false

    function origin(r) {
        var o = r.origin || "user", s = ""
        if (o === "user" || o === "recipe") s = ""
        else if (o.indexOf("agent") === 0) s = "by " + (o.replace("agent:", "").replace("agent", "") || "agent") + " · "
        else if (o === "cli") s = "from the command line · "
        else s = "via " + o.replace("proposal:", "") + " proposal · "
        s += r.parent ? "from " + F.pad(r.parent) : "start"
        if (p.approvals.some(function (a) { return a.rev === r.n })) s += " · released"
        return s
    }
    function approve() {
        approving = true
        Store.ppost("/approve", { acknowledged: Store.ack, note: note.text }).then(function (r) {
            approving = false
            Store.toast("Released " + r.release, "Files copied with a hash manifest.")
            Store.refresh()
        }, function (e) { approving = false; Store.fail(e) })
    }
    function verify(r) {
        Store.pget("/release/" + r).then(function (v) {
            var o = Object.assign({}, verified)
            o[r] = (v.intact ? "files intact" : "FILES ALTERED: " + v.files.filter(function (f) { return !f.ok }).map(function (f) { return f.file }).join(", "))
                + (v.matches_head ? " · matches the current design" : " · not the current design")
            verified = o
        }, Store.fail)
    }
    function saveAs(name, api, filter, reveal) {
        dlg.api = api; dlg.reveal = !!reveal; dlg.nameFilters = [filter, "All files (*)"]
        dlg.currentFolder = Bridge.downloads()
        dlg.currentFile = Bridge.downloads() + "/" + name
        dlg.open()
    }
    FileDialog {
        id: dlg
        property string api: ""
        property bool reveal: false
        title: "Save a copy"; fileMode: FileDialog.SaveFile
        onAccepted: {
            if (Bridge.save(api, selectedFile)) { Store.toast("Saved", String(selectedFile).replace(/^.*\//, "")); if (reveal) Bridge.reveal(selectedFile) }
            else Store.toast("Could not save the file", "Check that the folder is writable.", true)
        }
    }

    // ── gate ────────────────────────────────────────────────
    Sec { title: root.p ? "Gate for " + F.pad(root.p.head) : "Gate"
        Txt { kind: "fine"; width: parent.width; text: "A release is a frozen copy of files whose hashes match the revision they claim to be." }
        Note { visible: root.approved; kind: "green"
            title: root.approved ? F.pad(root.ap.rev) + " is released." : ""
            text: root.approved ? "Approved " + F.ago(root.ap.ts) + " as " + root.ap.release + ". " + root.g.evidence_level + "." : "" }
        Note { visible: !!root.ap && root.ap.state === "superseded"; kind: "amber"
            title: visible ? F.pad(root.ap.rev) + " was released; " + F.pad(root.p.head) + " has not been." : ""
            text: visible ? "Changed since: " + (root.ap.changed || []).join(", ") + ". The earlier release folder is intact but is a different design." : "" }
        Note { visible: !root.approved && !!root.g && root.g.reasons.length > 0; kind: "red"; title: "Not ready"
            text: root.g ? root.g.reasons.join("\n") : "" }
        Column { width: parent.width; spacing: 6; visible: !root.approved && root.warnings.length > 0
            Txt { kind: "fine"; width: parent.width; text: "Acknowledge each warning to release with it" }
            Repeater { model: root.approved ? [] : root.warnings
                Item { id: wr; required property var modelData
                    readonly property bool on: Store.ack.indexOf(modelData.id) >= 0
                    width: parent.width; implicitHeight: Math.max(wt.implicitHeight, 16) + 8
                    Check { id: wc; y: 5; checked: wr.on; onToggled: function (c) { Store.setAck(wr.modelData.id, c) } }
                    Column { id: wt; x: 26; y: 4; width: parent.width - 26; spacing: 1
                        Txt { text: wr.modelData.label; width: parent.width; font.weight: 600 }
                        Txt { kind: "fine"; tone: 2; text: String(wr.modelData.value); width: parent.width; color: Theme.amber } }
                    MouseArea { x: 20; width: parent.width - 20; height: parent.height; onClicked: Store.setAck(wr.modelData.id, !wr.on) } } } }
        Txt { visible: !root.approved; kind: "fine"; width: parent.width; text: root.g ? "Releasing states: " + root.g.evidence_level + "." : "" }
        Field { id: note; visible: !root.approved; width: parent.width; placeholder: "Release note (optional)" }
        Btn { visible: !root.approved; kind: "primary"; icon: "shield_check"
            text: root.p ? "Approve and release " + F.pad(root.p.head) : "Approve and release"
            enabled: !!root.g && root.g.ready && root.allAcked && !Store.hasDraft && !root.approving
            onClicked: root.approve() }
        Txt { kind: "fine"; width: parent.width; visible: !root.approved && Store.hasDraft
            text: "Commit or discard the draft first. Only a committed revision can be released." }
    }

    // ── releases ────────────────────────────────────────────
    Sec { title: "Releases"; visible: !!root.d && root.d.releases.length > 0
        Column { width: parent.width
            Repeater { model: root.d ? root.d.releases.slice().reverse() : []
                Item { id: rr; required property var modelData; required property int index
                    readonly property string state: root.verified[modelData] || (root.approved && root.ap.release === modelData ? "matches the current design" : "an earlier design")
                    width: parent.width; implicitHeight: rc.implicitHeight + 16
                    Rectangle { visible: rr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Column { id: rc; y: 8; width: parent.width; spacing: 3
                        Txt { text: rr.modelData; mono: true; font.pixelSize: 12; width: parent.width; wrapMode: Text.WrapAnywhere }
                        Txt { kind: "fine"; width: parent.width; text: rr.state
                            color: rr.state.indexOf("FILES ALTERED") === 0 ? Theme.signal : rr.state.indexOf("files intact") === 0 ? Theme.pass : Theme.ink3 }
                        Row { spacing: 4; x: -8
                            Btn { kind: "quiet"; small: true; icon: "badge_check"; text: "Verify"; tip: "Re-hash every file against the manifest"; onClicked: root.verify(rr.modelData) }
                            Btn { kind: "quiet"; small: true; icon: "download"; text: "Save report…"
                                onClicked: root.saveAs(rr.modelData + "-REPORT.md", "/projects/" + Store.pid + "/file/releases/" + rr.modelData + "/REPORT.md", "Markdown (*.md)", false) } } } } } }
    }

    // ── working files ───────────────────────────────────────
    Sec { title: root.d && root.d.exports ? "Working files for " + F.pad(root.d.exports.rev) : "Working files"; note: "not a release"
        visible: !!root.d && !!root.d.exports
        Column { width: parent.width
            Repeater { model: root.d && root.d.exports ? F.vals(root.d.exports.files) : []
                Item { id: xr; required property var modelData; required property int index
                    readonly property bool step: /\.(step|stp)$/i.test(String(modelData.name))
                    width: parent.width; implicitHeight: xc.implicitHeight + 14
                    Rectangle { visible: xr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Btn { id: fcb; visible: xr.step; kind: "quiet"; small: true; icon: "external_link"; text: "FreeCAD"
                        tip: root.fc.gui ? "Open this STEP in FreeCAD" : "FreeCAD was not found on this computer (freecad.org)"
                        anchors.right: xb.left; anchors.verticalCenter: parent.verticalCenter
                        enabled: !!root.fc.gui; onClicked: Store.openIn("step", "freecad") }
                    Column { id: xc; anchors.left: parent.left; anchors.right: xr.step ? fcb.left : xb.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                        Txt { text: xr.modelData.name; tone: 2; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; mono: true; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: (xr.modelData.bytes / 1024).toFixed(0) + " kB · sha256 " + String(xr.modelData.sha256).slice(0, 12) + "…" } }
                    Btn { id: xb; kind: "quiet"; small: true; icon: "download"; text: "Save…"; anchors.right: parent.right; anchors.rightMargin: -8; anchors.verticalCenter: parent.verticalCenter
                        onClicked: root.saveAs(xr.modelData.name, "/projects/" + Store.pid + "/file/exports/current/" + xr.modelData.name, "Same type (*." + String(xr.modelData.name).split(".").pop() + ")", true) } } } }
        // other CAD tools: a FreeCAD macro that rebuilds the part from the STEP, or why there is no STEP
        Note { visible: root.noStep; kind: "plain"; title: "No STEP file"
            text: root.d && root.d.exports && root.d.exports.unavailable ? root.d.exports.unavailable.step : "" }
        Row { visible: root.hasStep; spacing: 4; x: -8
            Btn { kind: "quiet"; small: true; icon: "file_down"; text: "Save FreeCAD macro…"
                tip: "A .FCMacro that opens the STEP next to it and adds a spreadsheet of these parameters"
                onClicked: root.saveAs(Store.pid + "_" + F.pad(root.d.exports.rev) + ".FCMacro", "/projects/" + Store.pid + "/freecad_macro", "FreeCAD macros (*.FCMacro)", true) } }
        Txt { kind: "fine"; width: parent.width; visible: root.hasStep
            text: root.fc.available ? "FreeCAD found: each export is also re-imported there as a check." : "FreeCAD was not found here, so it cannot open the STEP or re-check it. The macro works wherever FreeCAD is installed." }
    }

    // ── revisions ───────────────────────────────────────────
    Sec { title: "Revisions"; note: root.p ? root.revs.length + " · head " + F.pad(root.p.head) : ""
        Column { width: parent.width
            Repeater { model: root.revs
                Item { id: rv; required property var modelData; required property int index
                    readonly property bool head: modelData.n === root.p.head
                    readonly property bool compared: !!Store.compare && Store.compare.rev === modelData.n
                    width: parent.width; implicitHeight: vc.implicitHeight + 18
                    Rectangle { visible: rv.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Rectangle { id: chip; y: 9; width: 34; height: 18; radius: Theme.rXs
                        color: rv.head ? Theme.datum : "transparent"; border.width: rv.head ? 0 : 1; border.color: Theme.rule2
                        Txt { anchors.centerIn: parent; mono: true; font.pixelSize: 11; text: F.pad(rv.modelData.n); color: rv.head ? Theme.datumInk : Theme.ink2 } }
                    Column { id: vc; x: 42; y: 9; width: parent.width - 42; spacing: 3
                        Item { width: parent.width; implicitHeight: Math.max(nt.implicitHeight, 18)
                            Txt { id: nt; text: rv.modelData.note || "No note"; font.weight: 600; anchors.left: parent.left; anchors.right: ag.left; anchors.rightMargin: 8
                                maximumLineCount: 3; elide: Text.ElideRight; color: rv.modelData.note ? Theme.ink : Theme.ink3 }
                            Txt { id: ag; kind: "fine"; text: F.ago(rv.modelData.ts); anchors.right: parent.right; y: 2; wrapMode: Text.NoWrap } }
                        Txt { kind: "fine"; width: parent.width; text: root.origin(rv.modelData) }
                        Row { visible: !rv.head; spacing: 4; x: -8
                            Btn { kind: "quiet"; small: true; icon: "git_compare"; active: rv.compared
                                text: rv.compared ? "Hide comparison" : "Compare with head"; onClicked: Store.compareWith(rv.modelData.n) }
                            Btn { kind: "quiet"; small: true; text: "Make head"; tip: "Check this revision out as a new head"; onClicked: Store.checkout(rv.modelData.n) } }
                        Loader { width: parent.width; active: rv.compared; visible: active; sourceComponent: diffCard } } } } }
    }

    Component {
        id: diffCard
        Note { id: dc
            readonly property var im: Store.compare ? Store.compare.diff.impact : null
            readonly property var rows: im ? im.derived.map(function (x) { return { label: x.label, from: F.fmt(x.from, 2), to: F.fmt(x.to, 2), unit: x.unit } })
                .concat(im.metrics.map(function (m) { var k = m.unit === "%" ? 0 : 2; return { label: m.label, from: F.fmt(m.from, k), to: F.fmt(m.to, k), unit: m.unit } })) : []
            kind: "blue"
            Txt { kind: "cap"; color: Theme.blueprint; text: Store.compare && root.p ? F.pad(Store.compare.rev) + " → " + F.pad(root.p.head) : "" }
            Column { width: parent.width
                Repeater { model: dc.im ? dc.im.params : []
                    Delta { required property var modelData; label: modelData.label; from: F.trim(modelData.from); to: F.trim(modelData.to); unit: modelData.unit; tint: Theme.blueprint } } }
            Txt { kind: "fine"; width: parent.width; visible: !!dc.im && dc.im.params.length === 0; text: "Same parameters." }
            Flow { width: parent.width; spacing: 5; visible: !!dc.im && dc.im.features.length > 0
                Repeater { model: dc.im ? dc.im.features : []
                    Tag { required property var modelData; text: modelData.label + " · " + modelData.change; kind: modelData.change } } }
            Txt { width: parent.width; font.weight: 600; color: Theme.signal; visible: !!dc.im && dc.im.interfaces_touched.length > 0
                text: dc.im ? "Interface changed: " + dc.im.interfaces_touched.join(", ") : "" }
            Txt { kind: "fine"; width: parent.width; visible: !!dc.im && dc.im.interfaces_touched.length === 0 && dc.im.params.length > 0
                text: "No interface dimension differs between these revisions." }
            Column { width: parent.width; visible: dc.rows.length > 0
                Repeater { model: dc.rows
                    Delta { required property var modelData; label: modelData.label; from: modelData.from; to: modelData.to; unit: modelData.unit } } }
        }
    }

    // ── decision log ────────────────────────────────────────
    Sec { title: "Decision log"
        Txt { kind: "fine"; width: parent.width; visible: !!root.p && root.p.decisions.length === 0
            text: "Approvals, model consultations, orientation changes and physical results are logged here." }
        Column { width: parent.width
            Repeater { model: root.p ? root.p.decisions.slice().reverse().slice(0, 12) : []
                Item { id: dr; required property var modelData; required property int index
                    width: parent.width; implicitHeight: dcol.implicitHeight + 12
                    Rectangle { visible: dr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Column { id: dcol; y: 6; width: parent.width; spacing: 1
                        Txt { kind: "fine"; tone: 2; font.weight: 600; width: parent.width; text: F.pad(dr.modelData.rev) + " · " + dr.modelData.kind }
                        Txt { kind: "fine"; width: parent.width
                            text: dr.modelData.text + (dr.modelData.cost_usd !== null && dr.modelData.cost_usd !== undefined ? " ($" + Number(dr.modelData.cost_usd).toFixed(3) + ")" : "") } } } } }
    }

    // ── project file ────────────────────────────────────────
    Sec { title: "Project file"
        Txt { tone: 2; width: parent.width; text: "Everything in one archive: revisions, provenance, artifacts, releases." }
        Btn { text: "Save .formproj…"; icon: "download"
            onClicked: root.saveAs(Store.pid + ".formproj", "/projects/" + Store.pid + "/archive", "FORM projects (*.formproj)", true) }
    }
}
