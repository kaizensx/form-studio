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
    // failed checks: a person may release over them, each one acknowledged and a reason written (never an agent)
    readonly property var failures: g && g.can_override ? g.failures : []
    readonly property bool overriding: failures.length > 0
    readonly property bool allOverridden: failures.every(function (f) { return Store.ack.indexOf("fail:" + f.id) >= 0 })
    property string noteText: ""
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
        var over = overriding ? failures.map(function (f) { return f.id }) : []
        Store.ppost("/approve", { acknowledged: Store.ack, note: note.text, override_failures: over }).then(function (r) {
            approving = false
            Store.toast("Released " + r.release, over.length ? "Released with " + over.length + " failed check" + (over.length > 1 ? "s" : "") + ", recorded in its report."
                                                              : "Files copied with a hash manifest.")
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
        Store.ask(dlg)
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
    readonly property bool superseded: !!ap && ap.state === "superseded"
    readonly property bool ready: !!g && g.ready
    readonly property color gateInk: approved ? Theme.pass : ready ? Theme.datum : superseded ? Theme.amber : Theme.signal
    property bool allRevs: false
    Column { width: parent.width; topPadding: 16; spacing: 12
        Row { width: parent.width; spacing: 14
            Rectangle { id: seal; width: 48; height: 48; radius: 24; color: Theme.alpha(root.gateInk, 0.12); border.color: Theme.alpha(root.gateInk, 0.35)
                Icon { anchors.centerIn: parent; size: 22; color: root.gateInk; name: root.approved ? "badge_check" : root.ready ? "shield_check" : "lock" } }
            Column { width: parent.width - 62; anchors.verticalCenter: seal.verticalCenter; spacing: 3
                Txt { kind: "h2"; width: parent.width
                    text: root.approved ? "Released" : root.ready ? (root.allAcked ? "Ready to approve" : "Ready, with warnings")
                        : root.overriding ? "Failed checks" : "Not ready" }
                Txt { kind: "fine"; tone: 2; width: parent.width
                    text: root.p ? "Gate for " + F.pad(root.p.head) + (root.g ? " · " + root.g.evidence_level : "") : "" } } }
        Txt { kind: "fine"; width: parent.width; text: "A release is a frozen copy of files whose hashes match the revision they claim to be." }
    }
    Sec { topPadding: 4
        Note { visible: root.approved; kind: "green"
            title: root.approved ? F.pad(root.ap.rev) + " is released." : ""
            text: root.approved ? "Approved " + F.ago(root.ap.ts) + " as " + root.ap.release + ". " + root.g.evidence_level + "." : "" }
        Note { visible: !!root.ap && root.ap.state === "superseded"; kind: "amber"
            title: visible ? F.pad(root.ap.rev) + " was released; " + F.pad(root.p.head) + " has not been." : ""
            text: visible ? "Changed since: " + (root.ap.changed || []).join(", ") + ". The earlier release folder is intact but is a different design." : "" }
        Note { visible: !root.approved && !!root.g && root.g.reasons.length > 0 && !root.overriding; kind: "red"; title: "Not ready"
            text: root.g ? root.g.reasons.join("\n") : "" }
        Column { width: parent.width; spacing: 6; visible: !root.approved && root.overriding
            Note { width: parent.width; kind: "red"; title: root.failures.length === 1 ? "1 check failed" : root.failures.length + " checks failed"
                text: "Fix them, or release anyway: tick each one and say why in the release note. The release and its report will state that it was released with failed checks." }
            Repeater { model: root.approved ? [] : root.failures
                Item { id: fr; required property var modelData
                    readonly property bool on: Store.ack.indexOf("fail:" + modelData.id) >= 0
                    width: parent.width; implicitHeight: Math.max(ft.implicitHeight, 16) + 8
                    Check { objectName: "overrideCheck"; y: 5; checked: fr.on; onToggled: function (c) { Store.setAck("fail:" + fr.modelData.id, c) } }
                    Column { id: ft; x: 26; y: 4; width: parent.width - 26; spacing: 1
                        Txt { text: "Release with: " + fr.modelData.label; width: parent.width; font.weight: 600 }
                        Txt { kind: "fine"; tone: 2; text: String(fr.modelData.value) + " · failed"; width: parent.width; color: Theme.signal } }
                    MouseArea { x: 20; width: parent.width - 20; height: parent.height; onClicked: Store.setAck("fail:" + fr.modelData.id, !fr.on) } } } }
        Column { width: parent.width; spacing: 6; visible: !root.approved && root.warnings.length > 0
            Txt { kind: "fine"; width: parent.width; text: "Acknowledge each warning to release with it" }
            Repeater { model: root.approved ? [] : root.warnings
                Item { id: wr; required property var modelData
                    readonly property bool on: Store.ack.indexOf(modelData.id) >= 0
                    width: parent.width; implicitHeight: Math.max(wt.implicitHeight, 16) + 8
                    Check { id: wc; objectName: "ackCheck"; y: 5; checked: wr.on; onToggled: function (c) { Store.setAck(wr.modelData.id, c) } }
                    Column { id: wt; x: 26; y: 4; width: parent.width - 26; spacing: 1
                        Txt { text: wr.modelData.label; width: parent.width; font.weight: 600 }
                        Txt { kind: "fine"; tone: 2; text: String(wr.modelData.value); width: parent.width; color: Theme.amber } }
                    MouseArea { x: 20; width: parent.width - 20; height: parent.height; onClicked: Store.setAck(wr.modelData.id, !wr.on) } } } }
        Txt { visible: !root.approved; kind: "fine"; width: parent.width; text: root.g ? "Releasing states: " + root.g.evidence_level + "." : "" }
        Field { id: note; objectName: "releaseNote"; visible: !root.approved; width: parent.width
            placeholder: root.overriding ? "Why release with failed checks? (required)" : "Release note (optional)"
            onEdited: function (t) { root.noteText = t } }
        Btn { visible: !root.approved; kind: "primary"; icon: "shield_check"
            text: root.p ? (root.overriding ? "Release " + F.pad(root.p.head) + " with failed checks" : "Approve and release " + F.pad(root.p.head)) : "Approve and release"
            enabled: !!root.g && (root.g.ready || (root.overriding && root.allOverridden && root.noteText.trim().length >= 3))
                     && root.allAcked && !Store.hasDraft && !root.approving
            onClicked: root.approve() }
        Txt { kind: "fine"; width: parent.width; visible: !root.approved && Store.hasDraft
            text: "Commit or discard the draft first. Only a committed revision can be released." }
    }

    // ── design review (in the chat) ─────────────────────────
    Item { width: 1; height: 10 }
    Fold { title: "Design review"; note: "subjective"; key: "release.review"
        Txt { kind: "fine"; width: parent.width
            text: "Claude looks at " + (root.p ? F.pad(root.p.head) : "the head revision") + " at three scales (silhouette, relationships, details) as designer, engineer and print technician, scores six criteria and lists concrete fixes. It changes nothing." }
        Btn { kind: "default"; icon: "eye"; text: Store.chatBusy ? "Claude is answering…" : "Ask Claude for a design review"
            enabled: Store.canAskReview; onClicked: Store.askReview() }
        Txt { kind: "fine"; width: parent.width; visible: !Store.chat.available; color: Theme.amber; text: Store.chat.note || "Claude is not connected." }
    }

    // ── share (design tools) ────────────────────────────────
    Fold { title: "Share"; key: "release.share"; note: "card, variants, timeline"
        Txt { kind: "fine"; width: parent.width
            text: "A 1600 × 900 image of " + (root.p ? F.pad(root.p.head) : "the head revision") + ": the part with its dimensions, what is computed and what is simulated, and the revision. It states only what Form Studio knows." }
        Row { spacing: 6
            Btn { icon: "share_2"; text: "Share card…"; enabled: !Store.hasDraft; onClicked: Store.openSheet("share") }
            Btn { kind: "quiet"; icon: "layout_grid"; text: "Variants"; onClicked: Store.openSheet("variants") }
            Btn { kind: "quiet"; icon: "history"; text: "Timeline"; active: Store.timelineOpen; onClicked: Store.timelineOpen = !Store.timelineOpen } }
    }

    // ── releases ────────────────────────────────────────────
    Fold { title: "Releases"; key: "release.releases"; openByDefault: true; visible: !!root.d && root.d.releases.length > 0
        note: root.d ? String(root.d.releases.length) : ""
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
                                onClicked: root.saveAs(rr.modelData + "-REPORT.md", "/projects/" + Store.pid + "/file/releases/" + rr.modelData + "/REPORT.md", "Markdown (*.md)", false) }
                            Btn { kind: "quiet"; small: true; icon: "download"; text: "Documents…"; tip: "BOM, assembly, print report and measurement plan of this release (.zip)"
                                onClicked: root.saveAs(rr.modelData + "-docs.zip", "/projects/" + Store.pid + "/docs/docs.zip?release=" + rr.modelData, "Zip archives (*.zip)", true) } } } } } }
    }

    // ── working files ───────────────────────────────────────
    Fold { title: root.d && root.d.exports ? "Working files for " + F.pad(root.d.exports.rev) : "Working files"; note: "not a release"; key: "release.files"
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

    // ── maker documents: BOM, assembly steps, print report, measurement plan (form/maker_docs.py) ──
    readonly property var docInfo: ({
        "BOM.csv": "Printed parts with grams from the slice, and bought hardware",
        "ASSEMBLY.md": "Numbered steps, an exploded image for each",
        "PRINT_REPORT.md": "Checks with evidence classes, presets, blanks for measured results",
        "MEASUREMENT_PLAN.md": "Which brief dimensions are assumed, and how to measure each",
        "MOTION_CHECKS.csv": "Every joint position checked, with overlap and clearance" })
    Fold { title: root.p ? "Maker documents for " + F.pad(root.p.head) : "Maker documents"; note: "not a release"; key: "release.docs"
        visible: !!root.d && !!root.d.documents && root.d.documents.length > 0
        Txt { kind: "fine"; width: parent.width
            text: "Made from this revision's solids, checks and slice when you save them. A value Form Studio does not have stays blank or NOT RUN. A release keeps its own copy." }
        Column { width: parent.width
            Repeater { model: root.d && root.d.documents ? root.d.documents : []
                Item { id: mr; required property var modelData; required property int index
                    width: parent.width; implicitHeight: mc.implicitHeight + 14
                    Rectangle { visible: mr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Column { id: mc; anchors.left: parent.left; anchors.right: mb.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                        Txt { text: mr.modelData; tone: 2; mono: true; font.pixelSize: 12; width: parent.width; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { kind: "fine"; width: parent.width; text: root.docInfo[mr.modelData] || "" } }
                    Btn { id: mb; kind: "quiet"; small: true; icon: "download"; text: "Save…"; anchors.right: parent.right; anchors.rightMargin: -8; anchors.verticalCenter: parent.verticalCenter
                        onClicked: root.saveAs(Store.pid + "_" + F.pad(root.p.head) + "_" + mr.modelData, "/projects/" + Store.pid + "/docs/" + mr.modelData,
                                               "Same type (*." + String(mr.modelData).split(".").pop() + ")", true) } } } }
        Btn { text: "Save all with images (.zip)…"; icon: "download"
            onClicked: root.saveAs(Store.pid + "_" + F.pad(root.p.head) + "_docs.zip", "/projects/" + Store.pid + "/docs/docs.zip", "Zip archives (*.zip)", true) }
    }

    // ── revisions ───────────────────────────────────────────
    Fold { title: "Revisions"; note: root.p ? root.revs.length + " · head " + F.pad(root.p.head) : ""; key: "release.revs"; openByDefault: true
        Column { width: parent.width
            Repeater { model: root.allRevs || root.revs.length <= 5 ? root.revs : root.revs.slice(0, 4)
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
        Btn { kind: "quiet"; small: true; x: -8; visible: root.revs.length > 5
            icon: root.allRevs ? "chevron_up" : "chevron_down"; text: root.allRevs ? "Show the latest four" : "Show all " + root.revs.length + " revisions"
            onClicked: root.allRevs = !root.allRevs }
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
    Fold { title: "Decision log"; key: "release.log"; note: root.p ? String(root.p.decisions.length) : ""
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
    Fold { title: "Project file"; key: "release.archive"; note: ".formproj"
        Txt { tone: 2; width: parent.width; text: "Everything in one archive: revisions, provenance, artifacts, releases." }
        Btn { text: "Save .formproj…"; icon: "download"
            onClicked: root.saveAs(Store.pid + ".formproj", "/projects/" + Store.pid + "/archive", "Form Studio projects (*.formproj)", true) }
    }
}
