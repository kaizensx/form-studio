pragma Singleton
import QtQuick

// The result drawn on the part (direction I, decision 7): which Bench entry it belongs to, the engine's description
// of it (form/resultview.py) and how it is being looked at: the scale, the deformed shape, the mode, the moment in a
// CNC program or a mechanism's cycle, the lit rule, folded or flat, night or paper.
//
// It follows the Bench: the selected row of the mode's chapter is what is drawn, when that entry draws anything and
// is current for the head. Nothing here computes or keeps a result: a stale, failed or never-run entry leaves `r`
// with its state and its reason, and the part shows nothing ("not run"). ResultLayer draws `r` in the 3D view,
// LegendStrip is its legend under the part, ResultCard its numbers in the opened row, DrawingPane the sheet.
QtObject {
    id: rs
    readonly property var apps: ["strength", "dfm", "cam", "sheet", "drawing", "motion", "stack", "topology", "inverse", "printOrient", "lattice"]
    // engines that are not on this branch yet: their entries will name these apps (form/resultview.py LATER)
    readonly property var later: []
    function draws(e) { return !!e && apps.indexOf(e.app || "") >= 0 }

    property string id: ""               // the Bench entry shown
    property var r: null                 // its description; r.state says whether there is anything to draw
    property bool busy: false
    readonly property string kind: r && r.state === "current" ? r.kind : ""
    readonly property bool on: kind !== "" && !Store.hasDraft && !Store.compare
    readonly property bool onPart: on && kind !== "drawing" && kind !== "front"

    // ── how it is looked at ──
    property string scale: "hue"         // hue: clay, cyan, white (one accent) | many: a conventional many-colour scale
    property string study: ""            // strength: which study of the design
    property bool deformed: false        // strength: the deformed shape, drawn deformK times too large
    property real deformK: 0             // the factor; 0 = the engine's suggestion (r.deform.auto)
    readonly property real deformShown: !r || !r.deform ? 0 : (deformK > 0 ? deformK : r.deform.auto || 0)
    property int mode: 0                 // modal and buckling: which shape
    property bool playing: false         // a mode shape swinging, a program or a cycle playing
    property real t: 0                   // seconds into the CNC setup or the motion cycle
    property int setup: 0                // CNC: which setup
    property string litRule: ""          // manufacturability: the rule whose faces are lit (the pointer is on its row)
    property bool flat: false            // sheet metal: unfolded
    property bool paper: false           // the drawing: white paper instead of the night sheet
    property var fix: null               // manufacturability: a fix being previewed { id, busy, preview, view, after }
    property real hoverValue: NaN        // the field's value under the pointer
    property string selDim: ""           // the drawing: the selected dimension's id

    // ── "a result develops" (Theme.develop): played once per result, only for a converged study ──
    property real develop: 1             // 0..1 the map's front, from the peak outward
    property real settle: 1              // 0..1 the legend and the error line, after it
    property var _played: ({})
    property int developed: 0            // how many times the moment has played (the journeys read it)
    readonly property bool developing: _dev.running
    property var _dev: SequentialAnimation {
        NumberAnimation { target: rs; property: "develop"; from: 0; to: 1; duration: 320; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode }
        NumberAnimation { target: rs; property: "settle"; from: 0; to: 1; duration: Theme.develop - 320; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode }
    }
    property var _fade: NumberAnimation { target: rs; property: "settle"; from: 0; to: 1; duration: Theme.moment }
    function cut() {                                       // any input ends the moment
        if (_dev.running) { _dev.stop(); develop = 1; settle = 1 }
        if (_grow.running) { _grow.stop(); t = duration; settle = 1 }
    }
    // topology: the moment is the run itself, played once from the even start to the last iteration (the real
    // history the engine stored, one picture per iteration), then the legend settles. Reduce Motion: the last one.
    property var _grow: SequentialAnimation {
        NumberAnimation { target: rs; property: "t"; from: 0; to: rs.duration; duration: Math.max(600, Math.min(1600, rs.duration * 40)); easing.type: Easing.InOutSine }
        NumberAnimation { target: rs; property: "settle"; from: 0; to: 1; duration: Theme.develop - 320; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode }
    }
    function _arriveTopology() {
        t = duration
        var key = Store.pid + "|" + r.id + "|" + r.run
        if (_played[key]) return
        _played[key] = true
        developed++
        if (Theme.reduced || duration <= 0) { settle = 0; _fade.restart(); return }
        settle = 0; t = 0; _grow.restart()
    }
    function _arrive() {
        _dev.stop(); _fade.stop(); _grow.stop(); develop = 1; settle = 1
        if (r && r.state === "current" && r.kind === "topology") { _arriveTopology(); return }
        if (!r || r.state !== "current" || r.kind !== "field") return
        var key = Store.pid + "|" + r.id + "|" + r.study + "|" + (r.mesh ? r.mesh.key : "")
        if (_played[key]) return
        _played[key] = true
        if (r.converged !== true) return                 // a study that did not converge shows its reason instead
        if (Theme.reduced) { developed++; settle = 0; _fade.restart(); return }
        developed++
        develop = 0; settle = 0; _dev.restart()
    }

    // ── loading ──
    property int _seq: 0
    function show(e) {
        if (!e || !draws(e)) { clear(); return }
        if (id !== e.id) { _resetView(); id = e.id }
        load()
    }
    function clear() {
        if (id === "" && !r) return
        _seq++; id = ""; r = null; busy = false; _resetView()
    }
    function _resetView() {
        playing = false; t = 0; setup = 0; point = -1; previewDown = null; previewId = ""; litRule = ""; flat = false; mode = 0; deformed = false; deformK = 0; hoverValue = NaN; selDim = ""
        if (fix) dropFix()
        if (_posed) { Store.pose = ({}); Store.setAsmMode("print"); _posed = false }
    }
    function load() {
        if (!id || !Store.pid) return
        var seq = ++_seq, at = Store.pid, q = "/result?id=" + encodeURIComponent(id) + (study ? "&study=" + encodeURIComponent(study) : "")
        busy = true
        Store.pget(q).then(function (d) {
            if (seq !== rs._seq || at !== Store.pid) return
            rs.busy = false
            var was = rs.r
            rs.r = d
            if (d && d.kind === "field" && d.study) rs.study = d.study
            if (d && d.kind === "motion" && d.state === "current") rs._pose()
            // a stack's loop is drawn in the assembled frame at rest: the parts stand assembled while it is shown
            if (d && d.kind === "stack" && d.state === "current" && Store.assembly) { if (Store.asmMode !== "assembled") Store.setAsmMode("assembled"); rs._posed = true }
            // a CNC setup opens at its end: every path, and the stock the simulation left
            if (d && d.kind === "cam" && d.state === "current" && (!was || was.kind !== "cam")) rs.t = (d.setups[rs.setup] || {}).duration_s || 0
            if (!was || was.state !== d.state || (was.mesh && d.mesh && was.mesh.key !== d.mesh.key) || was.study !== d.study) rs._arrive()
        }, function (e) { if (seq === rs._seq) { rs.busy = false; rs.r = { kind: "none", id: rs.id, state: "failed", why: e.message || "It could not be read." } } })
    }
    // topology: which iteration is drawn (t counts iterations)
    readonly property int iteration: kind === "topology" ? Math.max(0, Math.min(duration, Math.round(t))) : 0
    // a front (inverse design, print orientation): the point whose numbers the card shows
    property int point: -1
    // print orientation: the picked point's down direction (design frame); the viewport turns the part to lie that
    // way, a preview only. Use this writes it to the print setup (form/printphys/orient.pick).
    property var previewDown: null
    property string previewId: ""
    property bool picking: false
    function openPoint(pt) {
        point = pt.index
        if (r && r.app === "inverse" && pt.values) Store.loadDraft(pt.values, "inverse design", "Inverse design " + (r.run || "") + ", point " + pt.index)
        if (r && r.app === "printOrient") { previewDown = pt.down && pt.down.length === 3 ? pt.down : null; previewId = pt.id || "" }
    }
    function clearPoint() { point = -1; previewDown = null; previewId = "" }
    function useOrientation() {
        if (!previewId || picking) return
        var oid = previewId
        picking = true
        Store.ppost("/orient_pick", { orientation: oid }).then(function (d) {
            rs.picking = false
            Store.toast(d.changed ? "Print orientation set" : "Already the print orientation", (d.label || oid) + ". " + (d.note || ""), false)
            if (d.job) Store.track(d.job)
            rs.clearPoint()
            Store.refresh(true); Store.loadBench()
        }, function (e) { rs.picking = false; Store.fail(e) })
    }
    function setStudy(sid) { if (sid === study) return; study = sid; mode = 0; playing = false; deformed = false; deformK = 0; load() }

    // the Bench decides what is shown: the selected row of the mode's chapter
    // In Design the pane is the tree; a Design entry that draws (topology, inverse design) is shown once it is opened
    // from the Bench sheet, and until its row is clicked again
    readonly property string chapter: Store.stage === "prove" ? "check" : Store.stage === "release" ? "make" : Store.stage === "document" ? "document"
        : Store.stage === "shape" && !!Store.benchSel.design ? "design" : ""
    readonly property var want: chapter && Store.bench && Store.data ? Store.benchSelected(chapter) : null
    readonly property string wantKey: want && draws(want) ? want.id + "|" + want.state + "|" + (want.rev || 0) + "|" + (want.head || 0) + "|" + (want.headline || "") : ""
    onWantKeyChanged: { if (wantKey === "") clear(); else show(want) }
    property var _proj: Connections { target: Store; function onPidChanged() { rs.study = ""; rs._played = ({}); rs.clear() } }

    // ── the scale: the same ramp the shader draws (shaders/field.frag), for the legend ──
    function _lin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4) }
    function _srgb(c) { c = Math.max(0, Math.min(1, c)); return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055 }
    function _mixLin(a, b, k) {
        return Qt.rgba(_srgb(_lin(a.r) + (_lin(b.r) - _lin(a.r)) * k), _srgb(_lin(a.g) + (_lin(b.g) - _lin(a.g)) * k), _srgb(_lin(a.b) + (_lin(b.b) - _lin(a.b)) * k), 1) }
    readonly property color rampLow: Theme.clay
    readonly property color rampMid: "#3ee6ff"          // the accent as light: the same on the part in both themes
    readonly property color rampHigh: "#ffffff"
    function _smooth(x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x) }
    function rampAt(v) {
        v = Math.max(0, Math.min(1, v))
        if (scale === "many") {                          // the polynomial of shaders/field.frag (Turbo, Mikhailov 2019)
            var x = v, r = 0.13572138 + x * (4.61539260 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))))
            var g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))))
            var b = 0.10667330 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))))
            return Qt.rgba(Math.max(0, Math.min(1, r)), Math.max(0, Math.min(1, g)), Math.max(0, Math.min(1, b)), 1)
        }
        return v < 0.6 ? _mixLin(rampLow, rampMid, _smooth(v / 0.6)) : _mixLin(rampMid, rampHigh, _smooth((v - 0.6) / 0.4))
    }
    function fmt(v, unit) {
        if (v === null || v === undefined || isNaN(v)) return ""
        var a = Math.abs(v), d = a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 3
        return v.toFixed(d) + (unit ? " " + unit : "")
    }
    function clock(s) { s = Math.max(0, s); var m = Math.floor(s / 60), x = s - m * 60; return m + ":" + (x < 10 ? "0" : "") + x.toFixed(x < 10 && m === 0 ? 1 : 0) }
    function evWord(ev) { return String(ev || "").split(/[ ,(×]/)[0] }

    // ── time: a CNC setup or a motion cycle (Stock or layer scrub: follows the pointer; playing: 8 s at most) ──
    readonly property real duration: !r ? 0 : kind === "cam" ? ((r.setups[setup] || {}).duration_s || 0) : kind === "motion" ? (r.duration_s || 0)
        : kind === "topology" ? Math.max(0, (r.frames || 1) - 1) : 0
    readonly property real playRate: kind === "topology" ? Math.max(1, duration / 3) : duration > 8 ? duration / 8 : 1
    function scrub(x) { playing = false; t = Math.max(0, Math.min(duration, x)); if (kind === "motion") _pose() }
    function toggle() { if (!playing && duration > 0 && t >= duration - 1e-6) t = 0; playing = !playing }
    property var _clock: FrameAnimation {
        // one clock for whatever plays; it stops with the play button, so a still result is never redrawn
        running: rs.playing && rs.on && (rs.kind === "cam" || rs.kind === "motion" || rs.kind === "topology")
        onTriggered: {
            var n = rs.t + frameTime * rs.playRate
            if (n >= rs.duration) { rs.t = rs.duration; rs.playing = false } else rs.t = n
            if (rs.kind === "motion") rs._pose()
        }
    }
    // motion: the pose of the frame at t (linear between the engine's frames), handed to the viewport
    property bool _posed: false
    readonly property int frame: {
        if (kind !== "motion" || !r.times || !r.times.length) return 0
        var ts = r.times, i = 0
        while (i < ts.length - 1 && ts[i + 1] <= t + 1e-9) i++
        return i
    }
    function _pose() {
        if (!r || r.kind !== "motion" || !r.poses || !r.poses.length) return
        var ts = r.times, i = frame, j = Math.min(ts.length - 1, i + 1), a = r.poses[i], b = r.poses[j]
        var u = j > i && ts[j] > ts[i] ? (t - ts[i]) / (ts[j] - ts[i]) : 0, out = {}
        for (var k in a) { var d = (b[k] === undefined ? a[k] : b[k]) - a[k]; out[k] = a[k] + d * Math.max(0, Math.min(1, u)) }
        if (Store.asmMode !== "assembled") Store.setAsmMode("assembled")
        Store.pose = out; _posed = true
    }
    // strength: a mode shape swings while it plays (phase in turns); stopped, it rests at its largest
    property real phase: 0.25
    property var _swing: FrameAnimation {
        running: rs.playing && rs.on && rs.kind === "field" && !!rs.r.modes
        onTriggered: rs.phase = (rs.phase + frameTime * 0.8) % 1
        onRunningChanged: if (!running) rs.phase = 0.25
    }

    // ── manufacturability: a fix, previewed as a ghost over the part, then applied ──
    function ruleFaces(id) {
        if (!r || r.kind !== "dfm" || !id) return []
        for (var i = 0; i < r.rows.length; i++) if (r.rows[i].id === id) return r.rows[i].faces
        return []
    }
    function fixFor(rule) {
        var fs = r && r.fixes ? r.fixes : []
        for (var i = 0; i < fs.length; i++) if (fs[i].can && fs[i].rules.indexOf(rule) >= 0) return fs[i]
        return null
    }
    function previewFix(fid) {
        if (!r || r.kind !== "dfm") return
        var seq = _seq, proc = r.process
        fix = { id: fid, busy: true, preview: null, view: null, after: true, why: "" }
        Store.ppost("/fix_preview", { process: proc, fix: fid, options: r.options || ({}) }).then(function (d) {
            if (seq !== rs._seq || !rs.fix || rs.fix.id !== fid) return
            rs.fix = { id: fid, busy: false, preview: d.preview || [], view: d.view || null, after: true, ok: !!d.previewed,
                       why: d.previewed ? (d.note || "") : (d.why || "No candidate passed in the preview."), trades: d.trades || [], summary: d.fix ? d.fix.summary : "" }
            if (d.view && Store.viewer) Store.viewer.setGhost(d.view)
        }, function (e) { if (rs.fix && rs.fix.id === fid) rs.fix = { id: fid, busy: false, preview: [], view: null, ok: false, why: e.message || "The preview failed." } })
    }
    function fixSide(after) {                              // before: the part alone; after: the candidate's ghost over it
        if (!fix || !fix.view) return
        fix = Object.assign({}, fix, { after: after })
        if (Store.viewer) Store.viewer.setGhost(after ? fix.view : null)
    }
    function dropFix() { if (fix && fix.view && Store.viewer) Store.viewer.setGhost(null); fix = null }
    function applyFix() {
        if (!fix || !fix.ok || !r) return
        var fid = fix.id, proc = r.process, head = Store.project ? Store.project.head : undefined
        fix = Object.assign({}, fix, { busy: true })
        Store.ppost("/fix_apply", { process: proc, fix: fid, options: r.options || ({}), expect_head: head }).then(function (d) {
            rs.dropFix()
            Store.toast(d.fixed ? "Fixed" : d.applied ? "Applied, not fixed" : "Nothing was saved", d.note || d.why || "", !d.applied)
            if (d.applied) { if (d.job) Store.track(d.job); Store.refresh(true) }
            Store.loadBench()
        }, function (e) { rs.dropFix(); Store.fail(e) })
    }

    // ── the drawing: a dimension typed over commits its parameter (form/drawing set_dimension) ──
    function setDimension(dim, value) {
        if (!r || r.kind !== "drawing") return
        var head = Store.project ? Store.project.head : undefined
        busy = true
        Store.ppost("/drawing_set", { dimension: dim, value: value, expect_head: head }).then(function (d) {
            rs.busy = false
            if (d && d.job) Store.track(d.job)
            Store.refresh(true)
            Store.ppost("/study", { id: "drawing" }).then(function (j) { if (j && typeof j.job === "string" && j.job) Store.track(j.job); Store.loadBench() }, function () { Store.loadBench() })
        }, function (e) { rs.busy = false; Store.fail(e) })
    }
}
