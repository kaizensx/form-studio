import QtQuick
import "F.js" as F
import "FeatureKinds.js" as K

// The property card of one feature made by hand (the reference's property manager, in our grammar): its sections
// per kind (FeatureKinds.js). Two kinds of change, one OK:
//  - a number that is already a parameter (a depth, a radius) is a value: Store.setParam drafts it and the kernel
//    previews it at once (POST /preview); the part shows it over a ghost of the head.
//  - a choice written in the feature's call (an end condition, reverse, a thin wall, a boolean's operation, a face
//    picked on the stage) rewrites that call: the card holds the change (pend, with any values typed beside it in
//    pvals) and the kernel builds it (POST /redefine, preview; form/feature_redefine.py), the part shows that draft.
// Either way the card says the computed change in volume, or why the kernel refused it. OK saves one revision; Cancel
// leaves the head as it was. While the card is open it holds the draft's only OK and Cancel (Store.cardFor: the
// draft panel at the pane's foot then shows its consequences without its own Commit and Discard).
Item {
    id: fc
    objectName: "featureCard"
    property string fid: ""
    property var params: []                 // the recipe's params whose feature is fid
    property string code: ""                // the feature's method, from GET /tree (its source lines)
    property var options: null              // GET /tree row.options: what the feature was made with (form/feature_redefine.py)
    readonly property string kind: options && options.kind ? options.kind : K.kindOf(fid)
    readonly property var spec: K.KINDS[kind] || null
    readonly property var keys: params.map(function (p) { return p.key })
    property var pend: ({})                 // choices changed here, not yet saved: option -> value (null removes it)
    property var pvals: ({})                // numbers typed while a choice is pending: param key -> value
    property var rd: null                   // POST /redefine's preview of pend
    property var rdError: null
    property bool rdBusy: false
    property bool saving: false
    property string picking: ""             // the option a pick on the stage fills ("to_at", "to2_at", "to")
    property int _seq: 0
    readonly property bool structural: F.keys(pend).length > 0
    readonly property bool pending: redo.running || rdBusy      // a choice still on its way to the kernel (journeys read it)
    readonly property var o: { var b = Object.assign({}, options || {}); for (var k in pend) b[k] = pend[k]
        if (pend.to_at) b.has_to = true; if (pend.to2_at) b.has_to2 = true; if (pend.to) b.has_to = true; return b }
    function param(s) { var k = fid + "_" + s; for (var i = 0; i < params.length; i++) if (params[i].key === k) return params[i]; return null }
    function val(p) {
        if (structural && pvals[p.key] !== undefined) return pvals[p.key]
        if (!structural && Store.draftValues[p.key] !== undefined) return Store.draftValues[p.key]
        return Store.values[p.key] !== undefined ? Store.values[p.key] : p.default }
    readonly property bool mine: structural || keys.some(function (k) { return Store.draftValues[k] !== undefined })
    readonly property bool others: !structural && F.keys(Store.draftValues).some(function (k) { return fc.keys.indexOf(k) < 0 })
    readonly property var vol: {
        if (structural) return rd && rd.preview && rd.preview.ok ? rd.preview.volume_mm3.change : null
        var pv = Store.preview; if (!pv || !pv.impact) return null
        var m = pv.impact.metrics.filter(function (x) { return x.key === "volume" })[0]; return m ? (m.to - m.from) * 1000 : null }
    readonly property var err: structural ? rdError : Store.draftError
    visible: !!spec
    implicitHeight: body.implicitHeight + 20
    height: implicitHeight
    onFidChanged: cancel()
    // the only OK / Cancel while the card is open (DraftCard reads it and hides its own pair)
    Binding { target: Store; property: "cardFor"; value: fc.fid; when: fc.visible && fc.fid !== ""; restoreMode: Binding.RestoreValue }
    Component.onDestruction: { if (fc.picking) Store.endPick() }
    Connections { target: Store; function onFacePickChanged() { if (!Store.facePick) fc.picking = "" } }

    // ── a choice: written in the feature's call, previewed through POST /redefine ──
    function choose(opt, v) {
        if (!structural) {                                // a value draft already typed for this feature goes along
            var carry = ({}), dv = Store.draftValues
            for (var k in dv) carry[k] = dv[k]
            pvals = carry
            if (F.keys(dv).length) Store.discard()
        }
        var p = Object.assign({}, pend), was = options ? options[opt] : undefined
        var same = (v === was) || (!v && !was) || (opt === "end" && !!options && !options.end && v === options.end_shown)
        if (same && opt !== "to_at" && opt !== "to2_at" && opt !== "to") delete p[opt]; else p[opt] = v
        // a second direction that is blind starts at the first one's depth (it needs one above 0)
        if (opt === "end2" && v === "blind" && !(options && options.depth2) && p.depth2 === undefined) {
            var d = param("depth"); p.depth2 = d ? Math.max(1, Number(val(d)) || 5) : 5 }
        if (opt === "end2" && !v) delete p.depth2
        pend = p
        if (!structural) {                                // back to the head's choices: the typed values stay a draft
            var back = pvals
            pvals = ({}); rd = null; rdError = null; _seq++
            if (F.keys(back).length) Store.loadDraft(back); else Store.showHead()
            return
        }
        redo.restart()
    }
    function setNum(f, x) {                               // a number of a field
        var p = f.s ? param(f.s) : null
        if (p && !structural) { Store.setParam(p.key, f.int ? Math.round(x) : x); return }
        if (p) { var q = Object.assign({}, pvals); q[p.key] = x; pvals = q; redo.restart(); return }
        if (f.opt) choose(f.opt, x)
    }
    Timer { id: redo; interval: 260; onTriggered: fc.preview() }
    function req(preview) {
        return { feature: fid, change: pend, values: pvals, preview: preview, expect_head: Store.project ? Store.project.head : null }
    }
    function preview() {
        if (!structural) return
        var seq = ++_seq
        rdBusy = true
        Store.ppost("/redefine", req(true)).then(function (r) {
            if (seq !== fc._seq) return
            fc.rdBusy = false; fc.rd = r
            fc.rdError = r.preview.ok ? null : { message: r.preview.refused, hint: r.preview.next || "" }
            if (r.preview.ok && Store.viewer && r.preview.view) {
                Store.viewer.setModel(r.preview.view); Store.viewer.setGhost(Store.view); Store.viewer.flagged = [fc.fid] }
        }, function (e) { if (seq !== fc._seq) return; fc.rdBusy = false; fc.rd = null; fc.rdError = e })
    }
    function ok() {
        if (!structural) return Store.commit()
        saving = true
        Store.ensureConv().then(function (cid) {
            return Store.ppost("/redefine", Object.assign(req(false), { conversation: cid }))
        }).then(function (r) {
            fc.saving = false
            Store.toast(r.said, "Written into the design's code as " + F.pad(r.head) + "; the checks run again.")
            if (r.job) Store.track(r.job)
            fc.pend = ({}); fc.pvals = ({}); fc.rd = null; fc.rdError = null
            Store.refresh(true)
            Store._chatTick()
        }, function (e) { fc.saving = false; fc.rdError = e })
    }
    function cancel() {
        _seq++; redo.stop()
        var had = structural
        pend = ({}); pvals = ({}); rd = null; rdError = null
        if (picking) { picking = ""; Store.endPick() }
        if (F.keys(Store.draftValues).length) Store.discard(); else if (had) Store.showHead()
    }
    function pick(f) {                                   // a face, or a point, picked on the stage
        if (picking === f.opt) { picking = ""; Store.endPick(); return }
        picking = f.opt
        Store.pickOnStage(f.what === "point" ? "point" : "face", function (at) {
            fc.picking = ""
            fc.choose(f.opt, at.map(function (x) { return Math.round(x * 1e4) / 1e4 }))
        })
    }

    function info(what) {
        var c = code
        if (what === "edges") { var n = (c.match(/"owners"/g) || []).length; return n ? F.plural(n, "picked edge") + ", found again on each rebuild by what made them" : "the picked edges" }
        if (what === "faces") return /shell\([^)]*None/.test(c.replace(/\s+/g, " ")) ? "closed: no face open" : "one picked face open, the rest walls"
        if (what === "standard") { var p = param("d"); return p && p.doc ? p.doc : "a plain diameter" }
        if (what === "axis") {
            var m = /\[(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\]/.exec(c), polar = /"polar"/.test(c)
            if (!m) return polar ? "around an axis" : "along a direction"
            var a = [Number(m[1]), Number(m[2]), Number(m[3])], names = ["x", "y", "z"], i = a.map(Math.abs).indexOf(Math.max.apply(null, a.map(Math.abs)))
            var simple = a.filter(function (x) { return Math.abs(x) > 1e-6 }).length === 1
            return (polar ? "around " : "along ") + (simple ? (a[i] < 0 ? "−" : "") + names[i] : "(" + a.map(function (x) { return F.trim(x, 3) }).join(", ") + ")") + (polar ? ", polar" : ", linear")
        }
        if (what === "sketch") { var dims = params.filter(function (p) { return !/_(depth|angle|end|reverse|draft|depth2|thin|thin2|offset|offset2|draft2|angle2|t)$/.test(p.key) }).length
            var pl = /"datum": "(XY|XZ|YZ)"/.exec(c)
            return F.plural(dims, "dimension") + " as parameters, on " + (pl ? "the " + pl[1] + " plane" : /"ref": "/.test(c) ? "a datum plane" : "a picked face") }
        if (what === "sweep") return /path = \{"edges"/.test(c) ? "the profile along picked edges of the part" : "the profile along a drawn path"
        if (what === "loft") { var s = (c.match(/"plane":/g) || []).length; return F.plural(s, "section") + ", each on its own plane" }
        if (what === "mirror") return options && options.of ? "the features " + options.of.join(", ") : "the whole body"
        if (what === "draftfaces" || what === "movefaces") { var f = (c.match(/"normal"/g) || []).length || (c.match(/"owners"/g) || []).length
            return (f ? F.plural(f, "picked face") : "the picked faces") + (what === "draftfaces" ? ", tilted about the neutral plane" : ", found again on each rebuild") }
        if (what === "thicken") return /surface = \{"face"/.test(c) ? "a picked face of the part" : "a drawn surface"
        if (what === "bodies") return "the target body and the tools, by a point inside each"
        if (what === "datum") return /"through"/.test(c) ? "through picked points" : /"edge"/.test(c) ? "along a picked edge" : /"planes"/.test(c) ? "where two planes meet" : (/"face"/.test(c) ? "on a picked face" : "on an origin plane or axis")
        return ""
    }
    function shows(x) { return !x.when || !!x.when(fc.o) }
    function optVal(f) { return f.value ? f.value(fc.o) : fc.o[f.opt] }

    // a local scrim under the card body: its labels stay legible where a light part shows through the pane's glass
    Rectangle { objectName: "cardScrim"; anchors.fill: parent; radius: 12; border.color: Theme.rule
        color: Theme.dark ? Qt.rgba(0.075, 0.075, 0.08, 0.8) : Qt.rgba(0.985, 0.98, 0.972, 0.86) }
    Column { id: body; x: 10; y: 10; width: fc.width - 20; spacing: 10
    Item { width: parent.width; height: 26
        Txt { kind: "cap"; text: fc.spec ? fc.spec.name + " · property card" : ""; anchors.verticalCenter: parent.verticalCenter }
        Ev { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "computed"; visible: fc.mine && fc.vol !== null; lit: true } }

    Repeater { model: fc.spec ? fc.spec.sections : []
        Column { id: sec; required property var modelData; width: body.width; spacing: 6
            objectName: "cardSection-" + modelData.title
            readonly property var fields: (modelData.fields || []).filter(function (f) {
                if (!fc.shows(f)) return false
                if (f.kind === "num") return !!fc.param(f.s) || (!!f.opt && !!fc.options)
                return !!fc.options                       // a choice needs the feature's call, read from its code
            })
            visible: fc.shows(modelData) && (modelData.info ? true : fields.length > 0)
            Rectangle { width: parent.width; height: 1; color: Theme.rule }
            Txt { text: sec.modelData.title; font.weight: Theme.wSemi; font.pixelSize: 12; topPadding: 4 + lead }
            Txt { visible: !!sec.modelData.info; width: parent.width; kind: "fine"; tone: 2; text: sec.modelData.info ? fc.info(sec.modelData.info) : "" }
            Btn { visible: sec.modelData.info === "sketch" && /^(extrude|cut|revolve)$/.test(fc.kind); small: true; kind: "quiet"; icon: "pen_tool"; text: "Edit sketch"; objectName: "cardEditSketch"
                onClicked: Store.pget("/sketch?feature=" + fc.fid).then(function (r) { Store.openSheet("handsketch", { mode: "edit", feature: fc.fid, sketch: r.sketch, values: r.values }) }, function (e) { Store.fail(e) }) }
            Repeater { model: sec.fields
                Item { id: fl; required property var modelData; width: sec.width
                    height: modelData.kind === "seg" && segW.implicitWidth > width * 0.6 ? 62 : 30
                    readonly property var p: modelData.kind === "num" && modelData.s ? fc.param(modelData.s) : null
                    objectName: "cardField-" + (modelData.s || modelData.opt)
                    Txt { y: fl.modelData.kind === "seg" && fl.height > 40 ? 4 : (30 - height) / 2; tone: 2; text: fl.modelData.t; wrapMode: Text.NoWrap
                        width: fl.modelData.kind === "toggle" ? parent.width - 40 : parent.width * 0.42; elide: Text.ElideRight }
                    // a choice of several, written in the call
                    Btn { id: menuBtn; objectName: "cardEnd" + (fl.modelData.opt === "end2" ? "2" : ""); visible: fl.modelData.kind === "menu"
                        anchors.right: parent.right; y: 2; small: true; kind: "quiet"; icon: "chevron_down"
                        readonly property var cur: fl.modelData.kind === "menu" ? fc.optVal(fl.modelData) : ""
                        property string value: cur === undefined || cur === null ? "" : String(cur)
                        text: { var cs = fl.modelData.choices || []; for (var i = 0; i < cs.length; i++) if (cs[i].value === value) return cs[i].text; return value }
                        tip: "Change the end condition; the kernel builds it before anything is saved"
                        onClicked: menu.openAt(menuBtn, 0, menuBtn.height + 4) }
                    PopMenu { id: menu; width: 200
                        model: fl.modelData.kind === "menu" ? fl.modelData.choices.map(function (c) {
                            return { text: c.text, name: "cardEndPick-" + (c.value || "none"), checked: c.value === menuBtn.value,
                                     run: function () { fc.choose(fl.modelData.opt, c.value) } } }) : [] }
                    Seg { id: segW; objectName: "cardSeg-" + (fl.modelData.opt || ""); visible: fl.modelData.kind === "seg"
                        anchors.right: parent.right; y: fl.height > 40 ? 30 : 2; height: 26
                        model: fl.modelData.kind === "seg" ? fl.modelData.choices : []
                        value: fl.modelData.kind === "seg" ? fc.optVal(fl.modelData) : null
                        onPicked: function (v) { fc.choose(fl.modelData.opt, v) } }
                    Toggle { objectName: "cardToggle-" + (fl.modelData.opt || ""); visible: fl.modelData.kind === "toggle"
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        checked: fl.modelData.kind === "toggle" && !!fc.optVal(fl.modelData)
                        onToggled: function (c) { fc.choose(fl.modelData.opt, c ? (fl.modelData.on !== undefined ? fl.modelData.on : true) : null) } }
                    Btn { objectName: "cardPick-" + (fl.modelData.opt || ""); visible: fl.modelData.kind === "pick"
                        anchors.right: parent.right; y: 2; small: true; kind: fc.picking === fl.modelData.opt ? "primary" : "quiet"
                        icon: fc.picking === fl.modelData.opt ? "x" : "mouse_pointer_click"
                        readonly property bool has: fl.modelData.kind === "pick" && (!!fc.pend[fl.modelData.opt] || (!!fc.options && !!fc.options[fl.modelData.has] && fc.pend[fl.modelData.opt] === undefined))
                        text: fc.picking === fl.modelData.opt ? "Picking… (Esc)" : has ? (fl.modelData.what === "point" ? "Change vertex" : "Change face") : (fl.modelData.what === "point" ? "Pick a vertex" : "Pick a face")
                        tip: fl.modelData.what === "point" ? "Click a corner of the part on the stage" : "Click the flat face on the stage it goes up to"
                        onClicked: fc.pick(fl.modelData) }
                    Field { id: fv; objectName: "cardValue-" + (fl.modelData.s || fl.modelData.opt); visible: fl.modelData.kind === "num"
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Math.min(132, parent.width * 0.5); height: 28; numeric: true
                        unit: fl.modelData.unit !== undefined ? fl.modelData.unit : (fl.p ? fl.p.unit : "mm")
                        readonly property real cur: fl.p ? fc.val(fl.p) : Number(fc.o[fl.modelData.opt] || 0)
                        readonly property real lo: fl.p ? fl.p.min : (fl.modelData.unit === "°" ? -30 : 0)
                        readonly property real hi: fl.p ? fl.p.max : (fl.modelData.unit === "°" ? 30 : 5000)
                        text: F.trim(cur, 3)
                        onCurChanged: if (!input.activeFocus || (fl.p && Store.draftValues[fl.p.key] === undefined && !fc.structural)) text = F.trim(cur, 3)
                        error: text !== "" && (Number(text) < lo || Number(text) > hi) ? "Between " + F.trim(lo) + " and " + F.trim(hi) : ""
                        onEdited: function (t) { var x = Number(t); if (t !== "" && isFinite(x) && x >= lo && x <= hi) fc.setNum(fl.modelData, x) }
                        onAccepted: function (t) { var x = Number(t); if (isFinite(x)) { fc.setNum(fl.modelData, Math.max(lo, Math.min(hi, fl.modelData.int ? Math.round(x) : x))); fc.preview() } } } } } } }

    // the draft's computed change, or why the kernel refused it. Its own glass under the text: the card stays
    // legible over a light part showing through the pane.
    Rectangle { objectName: "cardImpact"; visible: fc.mine || !!fc.err; width: parent.width; height: ic.implicitHeight + 18; radius: 12
        color: Theme.glassSolid; border.color: Theme.rule
        Column { id: ic; x: 12; y: 9; width: parent.width - 24; spacing: 3
            Txt { objectName: "cardVolume"; visible: !fc.err; width: parent.width; mono: true; font.pixelSize: 12
                text: fc.vol === null ? "Building in the kernel…" : (fc.vol >= 0 ? "+" : "−") + F.fmt(Math.abs(fc.vol), 1) + " mm³ of material" }
            Txt { visible: !fc.err && fc.vol !== null; width: parent.width; kind: "fine"; tone: 2
                text: fc.structural && fc.rd ? fc.rd.summary + ". Computed (B-rep), on the draft; nothing is saved until OK"
                                             : "computed (B-rep), on the draft; nothing is saved until OK" }
            Txt { objectName: "cardRefused"; visible: !!fc.err; width: parent.width; kind: "fine"; color: Theme.amber; text: fc.err ? (fc.err.message || "The kernel refused it.") + (fc.err.hint ? " " + fc.err.hint : "") : "" }
            Txt { visible: fc.others; width: parent.width; kind: "fine"; tone: 2; text: "The draft also changes values of other features; OK saves them together." } } }
    Row { spacing: 8
        Btn { objectName: "cardOk"; small: true; kind: "primary"; text: "OK"; busy: fc.saving; busyText: "Saving…"
            enabled: fc.structural ? !!fc.rd && fc.rd.preview.ok && !fc.rdBusy && !fc.saving : fc.mine && !Store.draftError && !!Store.preview
            tip: "Save the change as one revision; the checks run again"; onClicked: fc.ok() }
        Btn { objectName: "cardCancel"; small: true; kind: "quiet"; text: "Cancel"; enabled: fc.structural || F.keys(Store.draftValues).length > 0 || fc.picking !== ""
            tip: "Back to the head as it is"; onClicked: fc.cancel() } }
    }
}
