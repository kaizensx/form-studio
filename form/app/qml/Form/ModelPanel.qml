import QtQuick
import "F.js" as F

// A picked feature, by hand (form/modelling.py): fillet or chamfer on the picked edges, a hole into the picked face, a
// shell open at it, or a pattern of one feature. Preview builds the result in the kernel without saving it: the part
// shows the draft over a ghost of the head, with the computed change in volume beside it. Add to design writes one
// feature method and its parameters into the design's code and builds a new revision; the checks then run again. A
// feature the kernel would leave out is refused with the reason, and Fix with your agent puts it in the conversation.
// No sheet: the part stays in view (it lives in the selection pane and under a line of the Program).
Column {
    id: mp
    objectName: "modelPanel"
    property var kinds: []                   // what the selection allows: ["fillet", "chamfer"] or ["hole", "shell"]
    property string kind: kinds.length ? kinds[0] : ""
    property var picks: []                   // [{ at: [x, y, z] }]
    property string of: ""                   // pattern: the feature it repeats
    property var vals: ({})
    property var draft: null                 // the preview's answer
    property string error: ""
    property string errorHint: ""
    property bool busy: false
    property bool adding: false
    signal done()
    spacing: 8
    onKindsChanged: if (kinds.indexOf(kind) < 0) kind = kinds.length ? kinds[0] : ""
    onKindChanged: reset()
    onPicksChanged: reset()

    readonly property var fields: ({
        fillet: [{ k: "radius", t: "Radius", v: "1" }],
        chamfer: [{ k: "length", t: "Length", v: "0.8" }],
        hole: [{ k: "depth", t: "Depth (0 = through)", v: "0" }],
        shell: [{ k: "thickness", t: "Wall", v: "1.6" }],
        pattern: vals.mode === "polar" ? [{ k: "count", t: "Count", v: "4", u: "" }, { k: "angle", t: "Angle step", v: "90", u: "°" }]
                                       : [{ k: "count", t: "Count", v: "3", u: "" }, { k: "pitch", t: "Pitch", v: "10" }] })
    readonly property var names: ({ fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", shell: "Shell", pattern: "Pattern" })
    function v(k, d) { return vals[k] !== undefined && String(vals[k]).trim() !== "" ? vals[k] : d }
    function set(k, x) { var o = Object.assign({}, vals); o[k] = x; vals = o; reset() }
    function body(preview) {
        var b = { kind: kind, picks: picks, preview: preview, expect_head: Store.project ? Store.project.head : null }
        var fs = fields[kind] || []
        for (var i = 0; i < fs.length; i++) b[fs[i].k] = Number(v(fs[i].k, fs[i].v))
        if (kind === "hole") {
            b.standard = v("standard", "clearance"); b.style = v("style", "plain")
            if (b.standard === "iso286") { b.nominal = Number(v("nominal", "8")); b.fit = v("fit", "H7") }
            else if (b.standard === "plain") b.d = Number(v("d", "5"))
            else b.size = v("size", "M3")
        }
        if (kind === "pattern") { b.of = of; b.mode = v("mode", "linear"); b.axis = v("axis", b.mode === "polar" ? "z" : "x") }
        return b
    }
    function reset() {
        if (draft && Store.viewer) Store.showHead()
        draft = null; error = ""; errorHint = ""
    }
    function preview() {
        busy = true; error = ""
        Store.ppost("/model", body(true)).then(function (r) {
            mp.busy = false
            mp.draft = r
            if (!r.preview.ok) { mp.error = r.preview.refused; mp.errorHint = r.preview.next || ""; return }
            if (Store.viewer && r.preview.view) { Store.viewer.setModel(r.preview.view); Store.viewer.setGhost(Store.view); Store.viewer.flagged = [r.feature] }
        }, function (e) { mp.busy = false; mp.error = e.message || "The kernel refused it."; mp.errorHint = e.hint || "" })
    }
    function add() {
        adding = true
        Store.ppost("/model", body(false)).then(function (r) {
            mp.adding = false
            Store.toast("You added " + r.said.replace(/^Added /, ""), "Written into the design's code as " + F.pad(r.head) + "; the checks run again.")
            if (r.job) Store.track(r.job)
            mp.draft = null
            Store.selClear()
            Store.refresh(true)
            mp.done()
        }, function (e) { mp.adding = false; mp.error = e.message || "Refused."; mp.errorHint = e.hint || "" })
    }
    function fixWithAgent() {
        Store.chatPrefill("My " + (names[kind] || kind).toLowerCase() + " did not build: " + error
                          + (errorHint ? " (" + errorHint + ")" : "") + ". Can you make it work, keeping it as one feature in the code?")
    }

    Row { spacing: 6; visible: mp.kinds.length > 1
        Repeater { model: mp.kinds
            Btn { required property var modelData; objectName: "model_" + modelData; small: true; kind: mp.kind === modelData ? "primary" : "quiet"
                text: mp.names[modelData]; onClicked: mp.kind = modelData } } }
    // the hole wizard: the standard its diameter comes from
    Column { width: parent.width; spacing: 6; visible: mp.kind === "hole"
        Seg { objectName: "holeStandard"; model: [{ value: "clearance", text: "Clearance" }, { value: "tapped", text: "Tapped" }, { value: "iso286", text: "ISO fit" }, { value: "plain", text: "Ø" }]
            value: mp.v("standard", "clearance"); onPicked: function (x) { mp.set("standard", x) } }
        Seg { visible: mp.v("standard", "clearance") === "clearance" || mp.v("standard", "clearance") === "tapped"
            model: ["M2", "M2.5", "M3", "M4", "M5", "M6"]; value: mp.v("size", "M3"); onPicked: function (x) { mp.set("size", x) } }
        Row { spacing: 8; visible: mp.v("standard", "clearance") === "iso286"
            Field { width: 90; numeric: true; unit: "mm"; text: mp.v("nominal", "8"); onEdited: mp.set("nominal", text) }
            Seg { model: ["H7", "H8", "G7", "F7", "JS7"]; value: mp.v("fit", "H7"); onPicked: function (x) { mp.set("fit", x) } } }
        Field { width: 110; numeric: true; unit: "mm"; visible: mp.v("standard", "clearance") === "plain"; text: mp.v("d", "5"); onEdited: mp.set("d", text) }
        Seg { model: [{ value: "plain", text: "Plain" }, { value: "counterbore", text: "Counterbore" }, { value: "countersink", text: "Countersink" }]
            visible: mp.v("standard", "clearance") === "clearance"; value: mp.v("style", "plain"); onPicked: function (x) { mp.set("style", x) } } }
    Seg { visible: mp.kind === "pattern"; model: [{ value: "linear", text: "Linear" }, { value: "polar", text: "Polar" }]
        value: mp.v("mode", "linear"); onPicked: function (x) { mp.set("mode", x) } }
    Seg { visible: mp.kind === "pattern"; model: ["x", "y", "z"]; value: mp.v("axis", mp.v("mode", "linear") === "polar" ? "z" : "x")
        onPicked: function (x) { mp.set("axis", x) } }
    Grid { width: parent.width; columns: 2; columnSpacing: 10; rowSpacing: 6
        Repeater { model: mp.fields[mp.kind] || []
            Column { required property var modelData; width: (mp.width - 10) / 2; spacing: 3
                Txt { kind: "fine"; text: modelData.t }
                Field { objectName: "model_" + modelData.k; width: parent.width; numeric: true; unit: modelData.u !== undefined ? modelData.u : "mm"
                    text: mp.v(modelData.k, modelData.v); onEdited: mp.set(modelData.k, text); onAccepted: mp.preview() } } } }
    // the draft's computed change, or why it is refused
    Rectangle { visible: !!mp.draft || mp.error !== ""; width: parent.width; height: dc.implicitHeight + 18; radius: 12; color: Theme.glass
        Column { id: dc; x: 12; y: 9; width: parent.width - 24; spacing: 4
            Txt { objectName: "modelSummary"; width: parent.width; font.pixelSize: 13; font.weight: Theme.wMedium; visible: !!mp.draft
                text: mp.draft ? mp.draft.summary : "" }
            Txt { objectName: "modelImpact"; width: parent.width; mono: true; font.pixelSize: 11; tone: 2; visible: !!mp.draft && mp.draft.preview.ok
                text: { if (!mp.draft || !mp.draft.preview.ok) return ""
                        var dv = mp.draft.preview.volume_mm3.change
                        return (dv >= 0 ? "+" : "−") + F.fmt(Math.abs(dv), 1) + " mm³ · " + mp.draft.preview.faces.after + " faces\ncomputed (B-rep)" } }
            Txt { width: parent.width; kind: "fine"; tone: 2; visible: !!mp.draft && mp.draft.preview.craft_notes.length > 0
                text: mp.draft ? mp.draft.preview.craft_notes.join(" ") : "" }
            Txt { objectName: "modelRefused"; width: parent.width; kind: "fine"; color: Theme.amber; visible: mp.error !== ""; text: mp.error }
            Txt { width: parent.width; kind: "fine"; tone: 2; visible: mp.errorHint !== ""; text: mp.errorHint } } }
    Flow { width: parent.width; spacing: 6
        Btn { objectName: "modelPreview"; small: true; icon: "eye"; text: "Preview"; busy: mp.busy; busyText: "Building…"; enabled: !!mp.kind && !mp.adding; onClicked: mp.preview() }
        Btn { objectName: "modelAdd"; small: true; kind: "primary"; icon: "plus"; text: "Add to design"; busy: mp.adding; busyText: "Building…"
            enabled: !!mp.draft && mp.draft.preview.ok && !mp.busy; onClicked: mp.add()
            tip: "Writes it into the design's code as one feature with its parameters, and builds a new revision" }
        Btn { objectName: "modelFixAgent"; small: true; kind: "quiet"; icon: "sparkles"; text: "Fix with your agent"; visible: mp.error !== ""; onClicked: mp.fixWithAgent() }
        Btn { small: true; kind: "quiet"; text: "Cancel"; visible: !!mp.draft || mp.error !== ""; onClicked: { mp.reset(); mp.done() } } }
}
