import QtQuick
import "F.js" as F

// The uncommitted change and everything it would cause, computed by the kernel. Pinned to the foot of the inspector
// on every stage: what changed and the decision first, so Commit is always in reach; the consequences scroll below.
Rectangle {
    id: d
    objectName: "draftCard"
    readonly property var im: Store.preview ? Store.preview.impact : null
    // where each consequence last landed (label and old value → number), so a draft rebuilt while a slider moves
    // ticks on from the shown number rather than starting again from the old value. Mutated in place: no rebinding.
    property var seen: ({})
    function seenFrom(label, from) { var v = d.seen[label + "|" + from]; return v === undefined ? from : String(v) }
    readonly property string next: Store.project ? F.pad(Math.max.apply(null, Store.project.revisions.map(function (r) { return r.n })) + 1) : ""
    visible: Store.hasDraft || !!Store.draftError
    width: parent ? parent.width : 0
    implicitHeight: visible ? col.implicitHeight + 28 : 0
    color: Theme.glass; radius: Theme.rLg; border.color: Theme.alpha(Theme.blueprint, 0.35)
    Column {
        id: col; x: 14; y: 14; width: parent.width - 28; spacing: 8
        Item { width: parent.width; height: 16
            Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "cap"; text: Store.draftAgent ? "Draft by " + Store.draftAgent : "Draft change"; color: Theme.blueprint } }
            Txt { kind: "fine"; mono: true; anchors.right: parent.right; text: Store.preview ? "rebuilt in " + Math.round(Store.preview.timing.total_s * 1000) + " ms" : "" } }
        Note { visible: !!Store.draftError; kind: "red"; title: Store.draftError ? Store.draftError.message : ""
            text: (Store.draftError && Store.draftError.hint ? Store.draftError.hint + " " : "") + "The view still shows the last version that built. Nothing has been saved."
            FixBtn { subject: "this draft does not build"
                details: Store.draftError ? "Error: " + Store.draftError.message + (Store.draftError.hint ? "\nHint: " + Store.draftError.hint : "")
                    + "\nDraft values: " + JSON.stringify(Store.draftValues) : "" } }
        Column { width: parent.width; visible: !!d.im
            Repeater { model: d.im ? d.im.params : []
                Delta { required property var modelData; label: modelData.label; from: F.trim(modelData.from); to: F.trim(modelData.to); unit: modelData.unit; tint: Theme.blueprint } } }
        Field { width: parent.width; placeholder: "Why this change? (optional, kept in history)"; text: Store.draftNote; onEdited: function (t) { Store.draftNote = t } }
        Row { spacing: 8
            Btn { kind: "primary"; text: "Commit as " + d.next; icon: "git_commit_horizontal"
                enabled: !Store.draftError && (!!Store.preview || F.keys(Store.draftProv).length > 0); onClicked: Store.commit() }
            Btn { kind: "quiet"; text: "Discard"; onClicked: Store.discard() } }
        Item { width: parent.width; height: 2; visible: !!d.im }
        Flow { width: parent.width; spacing: 5; visible: !!(d.im && d.im.features.length)
            Repeater { model: d.im ? d.im.features : []
                Tag { required property var modelData; text: modelData.label + " · " + modelData.change; kind: modelData.change } } }
        Column { width: parent.width; spacing: 2
            visible: !!d.im && d.im.derived.some(function (x) { return x.interface })
            Txt { kind: "cap"; text: "Interface dimensions change"; color: Theme.signal }
            Repeater { model: d.im ? d.im.derived.filter(function (x) { return x.interface }) : []
                Delta { required property var modelData; label: modelData.label; from: F.fmt(modelData.from); to: F.fmt(modelData.to); unit: modelData.unit; tint: Theme.signal
                    tick: true; start: d.seenFrom(label, from); onSettled: function (v) { d.seen[label + "|" + from] = v } } } }
        Txt { kind: "fine"; width: parent.width
            visible: !!d.im && d.im.params.length > 0 && !d.im.derived.some(function (x) { return x.interface })
            text: "No interface dimension changes. Fit is unaffected by this draft." }
        Column { width: parent.width; spacing: 2
            readonly property var rows: d.im ? d.im.derived.filter(function (x) { return !x.interface }).map(function (x) { return { label: x.label, from: F.fmt(x.from), to: F.fmt(x.to), unit: x.unit } })
                .concat(d.im.metrics.map(function (m) { var k = m.unit === "%" ? 0 : 2; return { label: m.label, from: F.fmt(m.from, k), to: F.fmt(m.to, k), unit: m.unit } })) : []
            visible: rows.length > 0
            Txt { kind: "cap"; text: "Consequences" }
            Repeater { model: parent.rows
                Delta { required property var modelData; label: modelData.label; from: modelData.from; to: modelData.to; unit: modelData.unit
                    tick: true; start: d.seenFrom(label, from); onSettled: function (v) { d.seen[label + "|" + from] = v } } } }
        Txt { kind: "fine"; width: parent.width; color: Theme.amber
            visible: !!d.im && d.im.invalidates.length > 0
            text: d.im ? "Committing makes " + d.im.invalidates.join(", ") + " stale; they are regenerated for " + d.next + "."
                + (d.im.revokes_approval && Store.data.approval.rev ? " The release of " + F.pad(Store.data.approval.rev) + " will no longer describe the current design." : "") : "" }
        Repeater { model: F.keys(Store.draftProv)
            Delta { required property string modelData
                label: (Store.spec(modelData) ? Store.spec(modelData).label : modelData) + " source"
                to: Store.draftProv[modelData].source + " ±" + F.trim(Store.draftProv[modelData].sigma) } }
    }
}
