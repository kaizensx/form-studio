import QtQuick
import "F.js" as F

// Stage 03 — Fit. Will it slide in without rattling? A model from stated inputs, each shown with where it came from.
// A recipe without a fit (the coupon) shows "Calibrate" instead: its job is to feed the printer's calibration.
Column {
    id: root
    width: parent ? parent.width : 0

    readonly property var d: Store.data
    readonly property bool hasFit: !!(Store.recipe && Store.recipe.fit)
    readonly property var f: Store.preview && Store.preview.fit ? Store.preview.fit : (d ? d.fit : null)
    readonly property bool on: hasFit && !!f
    readonly property var cal: d ? d.calibration : null
    readonly property var c: cal ? cal.correction : null
    readonly property var src: f ? f.sources : null
    readonly property var tp: d && d.costs ? d.costs.test_piece : null
    readonly property int yld: f ? Math.round(f.yield * 100) : 0
    readonly property var geo: Store.preview || Store.view
    readonly property var cav: on && geo && geo.derived ? geo.derived.find(function (x) { return x.key === root.f.cavity_key }) : null
    readonly property var slots: Store.view && Store.view.derived ? Store.view.derived.filter(function (x) { return x.interface }) : []
    readonly property var evidence: !d || !d.project || !d.project.evidence ? []
        : d.project.evidence.filter(function (e) { return e.rev === root.d.project.head && (e.kind === "fit" || e.source === "part") })
    property var measured: ({})          // coupon: slot index → text typed
    property bool cutting: false

    function signed(v, n) { return (v >= 0 ? "+" : "") + F.fmt(v, n) }
    function pct(v) { return Math.round(v * 100) + "%" }
    function two(i) { return (i + 1 < 10 ? "0" : "") + (i + 1) }
    function words(s) { return String(s).replace(/_/g, " ") }

    function recordWidths(pairs, source) {
        pairs = pairs.filter(function (p) { return isFinite(p.measured) })
        if (!pairs.length) { Store.toast("Enter at least one measured width.", "", true); return }
        Store.ppost("/evidence", { kind: "widths", pairs: pairs, source: source }).then(function (r) {
            Store.track(r.job); Store.toast("Recorded", "Calibration updated; checks are being recomputed.")
            root.measured = ({}); meas.text = ""
            return Store.refresh()
        }).catch(Store.fail)
    }
    function recordFit(result) {
        Store.ppost("/evidence", { kind: "fit", result: result }).then(function (r) {
            Store.track(r.job); Store.toast("Recorded physical result"); return Store.refresh()
        }).catch(Store.fail)
    }
    function sliceRing() {
        if (cutting) return
        cutting = true
        Store.ppost("/test_piece", {}).then(function (r) {
            return Store.refresh().then(function () { root.cutting = false; Store.openSheet("ring", { result: r }) })
        }).catch(function (e) { root.cutting = false; Store.fail(e) })
    }
    function setWindow() {
        var a = parseFloat(lo.text), b = parseFloat(hi.text)
        if (!f || !isFinite(a) || !isFinite(b)) return
        if (Math.abs(a - f.window[0]) < 1e-9 && Math.abs(b - f.window[1]) < 1e-9) return
        Store.settings({ fit: { gap_min: a, gap_max: b } })
    }
    function removeRecord(id) {
        Store.ppost("/calibration_remove", { id: id }).then(function (j) { Store.track(j.job); return Store.refresh() }).catch(Store.fail)
    }

    // heading
    Item { width: parent.width; height: 10 }
    Txt { kind: "h2"; width: parent.width; text: root.hasFit ? (root.f ? root.f.label : "Fit") : "Calibrate" }
    Txt { tone: 2; width: parent.width; topPadding: 4 + lead
        text: root.hasFit ? "Will it slide in without rattling? A model built from stated inputs, shown with where each came from."
                          : "Print this coupon on the profile below, measure each slot with caliper inside jaws, and enter what you read." }

    // ── calibrate (the coupon) ─────────────────────────────────
    Sec { title: "Measured slot widths"; tag: "physical"; visible: !root.hasFit
        Column { width: parent.width
            Item { width: parent.width; height: 22
                Txt { kind: "fine"; text: "Slot"; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Nominal"; anchors.right: parent.right; anchors.rightMargin: 112; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Measured"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
            Repeater { model: root.hasFit ? [] : root.slots
                Item { id: sr; required property var modelData; required property int index
                    width: parent.width; height: 38
                    Rectangle { width: parent.width; height: 1; color: Theme.rule }
                    Txt { text: sr.modelData.label; tone: 2; anchors.left: parent.left; anchors.right: nom.left; anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Txt { id: nom; text: F.fmt(sr.modelData.value); mono: true; anchors.right: parent.right; anchors.rightMargin: 112; anchors.verticalCenter: parent.verticalCenter }
                    Field { width: 96; numeric: true; unit: "mm"; placeholder: F.fmt(sr.modelData.value)
                        text: root.measured[sr.index] || ""
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        onEdited: function (t) { var m = Object.assign({}, root.measured); m[sr.index] = t; root.measured = m } } } } }
        Txt { kind: "fine"; width: parent.width; text: "Leave blank any slot you did not measure. Only enter numbers read from a real print." }
        Btn { kind: "primary"; text: "Record measurements"; icon: "ruler"
            onClicked: root.recordWidths(root.slots.map(function (s, i) { return { nominal: s.value, measured: parseFloat(root.measured[i]) } }), "coupon") }
    }

    // ── the modelled yield ─────────────────────────────────────
    Column { visible: root.on; width: parent.width; topPadding: 18; spacing: 10
        Row { width: parent.width; spacing: 14
            Txt { id: hero; kind: "hero"; mono: true; text: root.yld + "%"; wrapMode: Text.NoWrap }
            Column { width: parent.width - hero.width - 14; anchors.verticalCenter: hero.verticalCenter; spacing: 5
                Txt { tone: 2; width: parent.width; text: "modelled chance the gap lands in your window" }
                Row { spacing: 6
                    Tag { text: "modelled" }
                    Tag { text: "draft"; visible: !!(Store.preview && Store.preview.fit) } } } }
        FitChart { f: root.on ? root.f : null }
        Row { width: parent.width
            Repeater {
                model: !root.on ? [] : [
                    { v: F.fmt(root.f.p_tight * 100, 0) + "%", l: "too tight", a: Text.AlignLeft, c: Theme.signal },
                    { v: F.fmt(root.f.expected_gap) + " mm", l: "expected gap ±" + F.fmt(2 * root.f.sd), a: Text.AlignHCenter, c: Theme.ink },
                    { v: F.fmt(root.f.p_loose * 100, 0) + "%", l: "too loose", a: Text.AlignRight, c: Theme.amber }]
                Column { id: n3; required property var modelData; required property int index
                    width: index === 1 ? parent.width * 0.44 : parent.width * 0.28; spacing: 1
                    Txt { kind: "lead"; mono: true; width: parent.width; text: n3.modelData.v; color: n3.modelData.c; horizontalAlignment: n3.modelData.a; wrapMode: Text.NoWrap }
                    Txt { kind: "fine"; width: parent.width; text: n3.modelData.l; horizontalAlignment: n3.modelData.a; wrapMode: Text.NoWrap } } } }
        Txt { kind: "fine"; width: parent.width; visible: !!(Store.preview && Store.preview.fit); color: Theme.blueprint; text: "Showing the draft." }
    }

    Sec { title: "Where the uncertainty comes from"; visible: root.on
        Column { width: parent.width
            KV { first: true; k: root.on ? (root.f.mating_label || "Device width") : ""
                sub: root.on ? F.fmt(root.f.mating) + " mm ±" + F.fmt(root.src.mating.sigma) + " · " + root.pct(root.src.mating.share) + " of variance" : ""
                tag: root.on ? root.src.mating.source : "" }
            KV { k: "Printed pocket"
                sub: root.on ? F.fmt(root.f.cavity_nominal) + " mm " + root.signed(root.src.printer.bias, 3) + " bias ±" + F.fmt(root.src.printer.sigma) + " · " + root.pct(root.src.printer.share) + " of variance" : ""
                tag: root.on ? (root.src.printer.source === "calibrated" ? "calibrated" : "assumed") : "" }
            KV { k: "Acceptable total gap"; sub: "your definition of a good fit"
                Field { id: lo; objectName: "fitLo"; width: 58; numeric: true; text: root.on ? F.trim(root.f.window[0]) : ""; onAccepted: root.setWindow() }
                Txt { text: "–"; tone: 3; anchors.verticalCenter: parent.verticalCenter }
                Field { id: hi; objectName: "fitHi"; width: 58; numeric: true; text: root.on ? F.trim(root.f.window[1]) : ""; onAccepted: root.setWindow() }
                Txt { text: "mm"; kind: "fine"; anchors.verticalCenter: parent.verticalCenter } } }
        Txt { kind: "fine"; width: parent.width; text: root.on ? (root.f.model || "") : "" }
    }

    Sec { title: "Most useful next step"; note: "by modelled yield gained"; visible: root.on && acts.count > 0
        Column { width: parent.width
            Repeater { id: acts
                model: root.on && root.d.actions ? root.d.actions : []
                Item { id: act; required property var modelData; required property int index
                    readonly property bool gains: modelData.gain > 0.005
                    width: parent.width; height: body.implicitHeight + 22
                    Rectangle { visible: act.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Txt { y: 11; text: root.two(act.index); mono: true; font.pixelSize: 12; color: act.index === 0 ? Theme.datum : Theme.ink4 }
                    Column { id: body; x: 30; y: 10; width: parent.width - 30; spacing: 4
                        Txt { width: parent.width; text: act.modelData.title; font.weight: 600 }
                        Txt { kind: "fine"; tone: 2; width: parent.width; text: act.modelData.why || "" }
                        Item { width: parent.width; height: 10
                            Rectangle { id: track; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 4; radius: 2; color: Theme.well
                                Rectangle { height: 4; radius: 2; color: Theme.ink3; width: track.width * Math.max(0, Math.min(1, root.f.yield)) }
                                Rectangle { visible: act.gains; height: 4; radius: 2; color: Theme.datum
                                    x: track.width * Math.max(0, Math.min(1, root.f.yield))
                                    width: Math.min(track.width - x, track.width * Math.max(0, act.modelData.gain)) } } }
                        Item { width: parent.width; height: 16
                            Txt { mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                                text: act.gains ? root.yld + "% → " + root.pct(act.modelData.after) : root.pct(act.modelData.after) }
                            Txt { kind: "fine"; text: act.modelData.cost || ""; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
                        Row { spacing: 8; topPadding: 2; visible: !!act.modelData.change || act.modelData.id === "measure"
                            Btn { small: true; text: "Load as draft"; visible: !!act.modelData.change; enabled: !Store.hasDraft
                                tip: Store.hasDraft ? "Keep or discard the current draft first" : ""
                                onClicked: { Store.setStage("shape"); Store.loadDraft(Object.assign({}, Store.head.values, act.modelData.change)) } }
                            Btn { small: true; text: "Enter the measurement"; icon: "ruler"; visible: act.modelData.id === "measure"; onClicked: Store.setStage("brief") } } } } } }
    }

    Sec { title: "Pocket ring test piece"; tag: root.tp ? "simulated" : ""; visible: root.on
        Txt { tone: 2; width: parent.width; text: "A 6 mm slice of this revision’s real pocket with 3 mm walls: the cheapest physical test of this exact interface." }
        KV { first: true; visible: !!root.tp; k: "Slicer estimate"; value: root.tp ? F.dur(root.tp.time_s) + " · " + F.fmt(root.tp.filament_g, 1) + " g" : "" }
        Btn { text: root.cutting ? "Cutting and slicing…" : root.tp ? "Files" : "Cut and slice it"; icon: root.tp ? "file_down" : "scissors"
            enabled: !root.cutting; onClicked: root.sliceRing() }
    }

    Sec { title: "Record a printed result for " + (root.d && root.d.project ? F.pad(root.d.project.head) : ""); tag: "physical"; visible: root.on
        KV { first: true; k: "Measured pocket width"; sub: "nominal " + F.fmt(root.cav ? root.cav.value : null) + " mm; feeds calibration"
            Field { id: meas; width: 104; numeric: true; unit: "mm"; placeholder: root.on ? F.fmt(root.f.cavity_nominal) : "" } }
        Btn { text: "Record width"; icon: "ruler"
            onClicked: root.recordWidths([{ nominal: root.f.cavity_nominal, measured: parseFloat(meas.text) }], "part") }
        Item { width: parent.width; height: 28
            Txt { kind: "fine"; text: "Or how it fitted"; anchors.verticalCenter: parent.verticalCenter }
            Row { spacing: 6; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Repeater { model: ["too_tight", "good", "too_loose"]
                    Btn { required property string modelData; small: true; text: root.words(modelData); onClicked: root.recordFit(modelData) } } } }
        Repeater { model: root.on ? root.evidence : []
            Note { required property var modelData; kind: "green"
                text: F.ago(modelData.ts) + " · " + (modelData.kind === "fit" ? "fit was " + root.words(modelData.result)
                    : (modelData.pairs || []).map(function (x) { return F.fmt(x.nominal) + " → " + F.fmt(x.measured) + " mm" }).join(", ")) } }
    }

    // ── printer calibration (both modes) ───────────────────────
    Sec { title: "Printer accuracy on this profile"; tag: root.c ? (root.c.source === "calibrated" ? "calibrated" : "assumed") : ""; visible: !!root.c
        Txt { kind: "fine"; width: parent.width; text: root.cal ? (root.cal.profile || "") : "" }
        Column { width: parent.width
            KV { first: true; k: "Bias on internal widths"; value: root.c ? root.signed(root.c.bias, 3) + " mm" : "" }
            KV { k: "Spread (1σ)"; value: root.c ? "±" + F.fmt(root.c.sigma, 3) + " mm" : "" } }
        Txt { kind: "fine"; width: parent.width
            text: (root.c && root.c.note ? root.c.note + " " : "") + "Measurements from any project on this profile are pooled and reused." }
        Column { width: parent.width; visible: recs.count > 0
            Item { width: parent.width; height: 22
                Txt { kind: "fine"; text: "Recorded"; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Source"; x: 96; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Widths"; anchors.right: parent.right; anchors.rightMargin: 108; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Mean Δ"; anchors.right: parent.right; anchors.rightMargin: 34; anchors.verticalCenter: parent.verticalCenter } }
            Repeater { id: recs
                model: root.cal && root.cal.records ? root.cal.records : []
                Item { id: rr; required property var modelData
                    readonly property var pairs: modelData.pairs || []
                    width: parent.width; height: 32
                    Rectangle { width: parent.width; height: 1; color: Theme.rule }
                    Txt { text: F.ago(rr.modelData.ts); tone: 2; width: 90; elide: Text.ElideRight; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: rr.modelData.source || ""; tone: 2; x: 96; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: rr.pairs.length; mono: true; anchors.right: parent.right; anchors.rightMargin: 108; anchors.verticalCenter: parent.verticalCenter }
                    Txt { mono: true; anchors.right: parent.right; anchors.rightMargin: 34; anchors.verticalCenter: parent.verticalCenter
                        text: rr.pairs.length ? root.signed(rr.pairs.reduce(function (a, x) { return a + x.measured - x.nominal }, 0) / rr.pairs.length, 3) : "—" }
                    Btn { kind: "quiet"; small: true; icon: "x"; tip: "Remove this record"; anchors.right: parent.right; anchors.rightMargin: -6; anchors.verticalCenter: parent.verticalCenter
                        onClicked: root.removeRecord(rr.modelData.id) } } } }
    }
    Item { width: parent.width; height: 20 }
}
