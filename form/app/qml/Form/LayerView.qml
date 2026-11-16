import QtQuick
import FormNative
import "F.js" as F

// The print, simulated from the slicer's G-code: every toolpath in 3D on the plate, played back in the slicer's
// own time, or inspected one layer at a time from above. Simulated, not a print.
// Replaces the 3D viewport while Store.layers is set. Scene: PrintSimView. Transport: PrintSimBar.
Item {
    id: sim
    // ── state ────────────────────────────────────────────────
    property var info: null                   // per-layer numbers from the engine (toolpath summary)
    property real now: 0                      // layer + fraction of that layer
    property bool playing: false
    property real speed: 64                   // × the slicer's time
    property bool loop: false
    property bool ghost: false
    property string mode: "3d"                // 3d | 2d | plate
    property var hidden: ({})                 // line type → true when filtered out
    property var here: ({})                   // where the nozzle is: { x, y, z, type }
    property string error: ""
    property int copies: 2
    property var packed: null                 // plate mode: the packing result
    property real clock: 0                    // seconds of slicer time, while playing
    readonly property int count: info ? info.layers : 0
    readonly property int cur: Math.max(0, Math.min(count - 1, Math.floor(now)))
    readonly property real frac: now - cur
    readonly property bool finished: count > 0 && now >= count - 0.001
    readonly property bool timed: !!info && info.total_time_s !== null && info.total_time_s !== undefined
    readonly property real elapsed: !timed ? 0 : finished ? info.total_time_s : info.t0_s[cur] + frac * info.time_s[cur]
    readonly property var types: info ? info.types : []
    readonly property var special: ["Bridge", "Overhang wall", "Floating vertical shell"]
    readonly property bool onlySpecial: types.length > 0 && types.every(function (t) { return (special.indexOf(t) >= 0) !== !!hidden[t] })
    readonly property int foot: bar.height + 84 + 10   // kept clear at the bottom: transport and the pipeline strip

    readonly property var inks: ({
        "Outer wall": Theme.ink, "Inner wall": Theme.ink3, "Sparse infill": Theme.amber,
        "Internal solid infill": Theme.blueprint, "Top surface": Theme.datum, "Bottom surface": Qt.darker(Theme.datum, 1.7),
        "Bridge": Theme.signal, "Overhang wall": Theme.signal, "Floating vertical shell": Qt.lighter(Theme.signal, 1.25),
        "Gap infill": Theme.ink4, "Support": Theme.pass, "Support interface": Theme.pass,
        "Skirt": Theme.ink2, "Brim": Theme.ink2, "Prime tower": Theme.ink2, "Custom": Theme.ink2, "Unlabelled": Theme.ink2 })
    function typeColor(t) { return inks[t] || Theme.ink2 }

    // ── moving through the print ─────────────────────────────
    function setNow(p) {
        if (!count) return
        now = Math.max(0, Math.min(count, p))
        here = view.geometry.at(Math.min(now, count - 0.0001))
    }
    function progressAt(seconds) {            // slicer time → layer + fraction
        var t0 = info.t0_s, lo = 0, hi = count - 1
        if (seconds >= info.total_time_s) return count
        while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (t0[mid] <= seconds) lo = mid; else hi = mid - 1 }
        var d = info.time_s[lo]
        return lo + (d > 0 ? Math.min(0.9999, (seconds - t0[lo]) / d) : 0)
    }
    function pause() { playing = false }
    function toggle() {
        if (!count) return
        if (playing) { playing = false; return }
        if (finished) setNow(0)
        clock = elapsed
        if (mode === "plate") mode = "3d"
        playing = true
    }
    function jump(list) {                     // to the next layer in `list` after this one (wraps round)
        if (!list || !list.length) return
        var next = list[0]
        for (var i = 0; i < list.length; i++) if (list[i] > cur) { next = list[i]; break }
        pause(); setNow(next + 0.9999)
    }
    function toggleType(t) { var h = Object.assign({}, hidden); if (h[t]) delete h[t]; else h[t] = true; hidden = h }
    function showOnly(list) {                 // list of type names; null = everything
        var h = {}
        if (list) types.forEach(function (t) { if (list.indexOf(t) < 0) h[t] = true })
        hidden = h
    }
    function pack(n) {
        copies = Math.max(1, Math.min(200, Math.round(n) || 1))
        var want = copies
        Store.pget("/pack?copies=" + want).then(function (r) { if (sim && sim.copies === want) sim.packed = r }, Store.fail)
    }
    function apply(o) {                       // Store.simulate({ at, layer, ghost, only, mode, copies, play, speed })
        if (!o || !count) return
        if (o.mode) mode = o.mode
        if (o.ghost !== undefined) ghost = !!o.ghost
        if (o.only !== undefined) showOnly(o.only)
        if (o.speed) speed = o.speed
        if (o.copies) { mode = "plate"; pack(o.copies) }
        if (o.layer !== undefined) { pause(); setNow(Math.max(0, o.layer - 1) + (o.fraction !== undefined ? Math.min(o.fraction, 0.9999) : 0.9999)) }
        else if (o.at !== undefined) { pause(); setNow(timed ? progressAt(o.at * info.total_time_s) : o.at * count) }
        if (o.play) { clock = elapsed; playing = true }
    }
    onModeChanged: if (mode === "plate" && !packed) pack(copies)
    // the rest of the app speaks in whole layers (Store.layers.n, Store.setLayer)
    onCurChanged: if (Store.layers && count && Store.layers.n !== cur) Store.setLayer(cur)
    Connections {
        target: Store
        function onLayersChanged() { if (Store.layers && sim.count && Store.layers.n !== sim.cur) { sim.pause(); sim.setNow(Store.layers.n + 0.9999) } }
        function onSimAskChanged() { sim.apply(Store.simAsk) }
    }
    FrameAnimation {
        running: sim.playing && sim.count > 0
        onTriggered: {
            var dt = Math.min(frameTime, 0.1)
            if (sim.timed) {
                sim.clock += dt * sim.speed
                if (sim.clock >= sim.info.total_time_s) {
                    if (sim.loop) sim.clock = 0
                    else { sim.playing = false; sim.setNow(sim.count); return }
                }
                sim.setNow(sim.progressAt(sim.clock))
            } else {                          // no slicer time: one layer per second at 64×
                var p = sim.now + dt * sim.speed / 64
                if (p >= sim.count) { if (sim.loop) p = 0; else { sim.playing = false; p = sim.count } }
                sim.setNow(p)
            }
        }
    }

    PrintSimView {
        id: view
        anchors.fill: parent
        url: Store.pid ? Bridge.baseUrl + "/api/projects/" + Store.pid + "/toolpath" : ""
        colors: sim.inks
        now: sim.now; total: Math.max(1, sim.count); mode: sim.mode; ghost: sim.ghost
        nozzle: sim.here; footer: sim.foot
        box: sim.info ? sim.info.bbox : null
        bed: Store.slicer && Store.slicer.envelope_mm ? [Store.slicer.envelope_mm[0], Store.slicer.envelope_mm[1]] : [180, 180]
        layout: sim.packed
        shown: { var s = []; for (var i = 0; i < 16; i++) s.push(i < sim.types.length && sim.hidden[sim.types[i]] ? 0 : 1); return s }
        onLoaded: function (summary) {
            sim.error = ""
            sim.info = summary
            if (Store.simAsk) sim.apply(Store.simAsk)
            else sim.setNow(summary.layers)                 // open on the finished toolpaths; Play starts from the plate
        }
        onFailed: function (message) { sim.error = message }
    }
    // the plate falls away at the edges, as in the design viewport
    Rectangle { anchors.fill: parent
        gradient: Gradient { orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.55) } GradientStop { position: 0.16; color: "transparent" }
            GradientStop { position: 0.8; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.7) } } }

    // ── top left: way back, and what this is ─────────────────
    Column { x: 16; y: 14; spacing: 10
        Row { spacing: 10
            Btn { icon: "arrow_left"; text: "Back to the design"; onClicked: Store.showLayers(false) }
            Tag { text: "simulated"; anchors.verticalCenter: parent.verticalCenter } }
        Txt { kind: "fine"; tone: 2; text: "Simulated from the slicer's G-code. Not a print."; wrapMode: Text.NoWrap }

        // line types: click to hide or show
        Rectangle { visible: sim.types.length > 0 && sim.mode !== "plate"
            width: 214; height: lg.implicitHeight + 16; radius: Theme.rMd; color: Theme.alpha(Theme.plate1, 0.9); border.color: Theme.rule
            Column { id: lg; x: 6; y: 8; width: parent.width - 12; spacing: 0
                Item { width: parent.width; height: 22
                    Txt { kind: "cap"; x: 6; text: "Line types"; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter; text: "m of path" } }
                Repeater { model: sim.types
                    Rectangle { id: tr; required property string modelData
                        readonly property bool on: !sim.hidden[modelData]
                        width: parent.width; height: 22; radius: Theme.rXs; color: tma.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent"
                        Rectangle { x: 6; width: 10; height: 10; radius: 2; anchors.verticalCenter: parent.verticalCenter
                            color: tr.on ? sim.typeColor(tr.modelData) : "transparent"; border.width: 1; border.color: tr.on ? "transparent" : Theme.ink4 }
                        Txt { x: 24; width: parent.width - 24 - 52; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: tr.on ? 1 : 4
                            text: tr.modelData; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { mono: true; font.pixelSize: 11; tone: tr.on ? 3 : 4; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                            text: sim.info ? F.fmt(sim.info.type_length_mm[tr.modelData] / 1000, 1) : "" }
                        MouseArea { id: tma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: sim.toggleType(tr.modelData) } } }
                Item { width: parent.width; height: 6 }
                Row { x: 6; spacing: 6
                    Btn { small: true; text: "All"; enabled: F.keys(sim.hidden).length > 0; onClicked: sim.showOnly(null) }
                    Btn { small: true; text: "Bridges and overhangs"; active: sim.onlySpecial
                        enabled: sim.types.some(function (t) { return sim.special.indexOf(t) >= 0 })
                        tip: "Show only bridges, overhang walls and walls with nothing under them"
                        onClicked: sim.showOnly(sim.onlySpecial ? null : sim.special) } }
            }
        }
    }

    // ── top right: how to look at it ─────────────────────────
    Column { anchors.right: parent.right; anchors.rightMargin: 16; y: 14; spacing: 8
        Row { anchors.right: parent.right; spacing: 8
            Btn { kind: "quiet"; icon: "ghost"; text: "Ghost"; active: sim.ghost; visible: sim.mode === "3d"
                tip: "Show the toolpaths still to come, faintly"; onClicked: sim.ghost = !sim.ghost }
            Btn { kind: "quiet"; icon: "maximize_2"; tip: "Frame the print"; onClicked: view.frame(true) }
            Seg { model: [{ value: "3d", text: "3D" }, { value: "2d", text: "Layer" }, { value: "plate", text: "Copies" }]
                value: sim.mode; onPicked: function (m) { sim.pause(); sim.mode = m } } }
        // copies on the plate
        Rectangle { visible: sim.mode === "plate"; anchors.right: parent.right
            width: 300; height: pk.implicitHeight + 24; radius: Theme.rMd; color: Theme.alpha(Theme.plate1, 0.94); border.color: Theme.rule
            Column { id: pk; x: 14; y: 12; width: parent.width - 28; spacing: 8
                Item { width: parent.width; height: 28
                    Txt { text: "Copies on one plate"; font.weight: 600; anchors.verticalCenter: parent.verticalCenter }
                    Row { anchors.right: parent.right; spacing: 4; anchors.verticalCenter: parent.verticalCenter
                        Btn { small: true; icon: "minus"; enabled: sim.copies > 1; onClicked: sim.pack(sim.copies - 1); anchors.verticalCenter: parent.verticalCenter }
                        Field { width: 46; numeric: true; text: String(sim.copies); onAccepted: function (t) { var n = parseInt(t); if (n > 0 && n !== sim.copies) sim.pack(n) } }
                        Btn { small: true; icon: "plus"; onClicked: sim.pack(sim.copies + 1); anchors.verticalCenter: parent.verticalCenter } } }
                Row { spacing: 8; visible: !!sim.packed
                    Tag { text: sim.packed && sim.packed.fits ? "fits" : "does not fit"; kind: sim.packed && sim.packed.fits ? "PASS" : "FAIL"; anchors.verticalCenter: parent.verticalCenter }
                    Tag { text: "computed"; anchors.verticalCenter: parent.verticalCenter } }
                Txt { width: parent.width; tone: 2; visible: !!sim.packed; text: sim.packed ? sim.packed.summary : "" }
                Txt { kind: "fine"; width: parent.width; visible: !!sim.packed && sim.packed.max_copies !== undefined
                    text: sim.packed && sim.packed.max_copies !== undefined ? "Most this arrangement finds room for: " + sim.packed.max_copies + "." : "" }
                Txt { kind: "fine"; width: parent.width; visible: !!sim.packed && sim.packed.parts_per_copy > 1
                    text: "This design prints as " + (sim.packed ? sim.packed.parts_per_copy : 0) + " parts; the outlines are their bounding boxes. Toolpaths are shown once, as sliced." }
                Txt { kind: "fine"; width: parent.width
                    text: "Bounding boxes with " + (sim.packed ? F.trim(sim.packed.spacing_mm) : 6) + " mm between parts, 90° turns allowed. A preview only: FORM still exports one part per plate, and your slicer arranges copies itself." }
            }
        }
    }

    Txt { anchors.centerIn: parent; visible: sim.error !== ""; text: sim.error; tone: 2; width: Math.min(parent.width - 80, 420); horizontalAlignment: Text.AlignHCenter }

    PrintSimBar {
        id: bar
        sim: sim
        visible: sim.mode !== "plate"
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 84
        width: Math.min(parent.width - 32, 780)
    }
}
