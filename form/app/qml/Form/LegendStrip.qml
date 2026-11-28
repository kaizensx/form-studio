import QtQuick
import "F.js" as F

// The legend strip under the part for a result of the later engines (direction I, decision 7; ResultStrip is the same
// strip for the four analysis maps). It always carries three things: the scale with its unit, how the result is known
// (the evidence, and for a simulation the stated error) and what it does not tell. For a result that plays in time
// (a CNC setup, a mechanism's cycle) the scale is a timeline, scrubbed under the pointer.
// Everything it says is Results.r, the engine's description. With nothing current it is not shown at all.
Glass {
    id: ls
    objectName: "legendStrip"
    readonly property var r: Results.on && Results.kind !== "drawing" ? Results.r : null
    readonly property string kind: r ? r.kind : ""
    readonly property bool on: !!r
    property var _last: null             // what it showed, kept while it leaves
    onRChanged: if (r) _last = r
    readonly property var d: r || _last
    readonly property string dk: d ? d.kind : ""
    radius: 22
    height: Math.round(col.implicitHeight + 28)
    opacity: on ? 1 : 0; visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: ls.on ? Theme.strip : Theme.exit; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    property real lift: on ? 0 : Theme.shift(Theme.rise)
    Behavior on lift { NumberAnimation { duration: Theme.move(Theme.strip); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    transform: Translate { y: ls.lift }
    function esc(t) { return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true }; onPressed: Results.cut() }

    readonly property string title: !d ? "" : dk === "field" ? (d.quantity ? d.quantity.charAt(0).toUpperCase() + d.quantity.slice(1) : d.title)
        : dk === "dfm" ? "Manufacturability" : dk === "cam" ? "CNC, 3-axis" : dk === "flat" ? "Flat pattern" : dk === "motion" ? "Motion" : d.title || ""
    readonly property string sub: {
        if (!d) return ""
        var rev = F.pad(d.rev), bits = []
        if (dk === "field") { if (d.unit) bits.push(d.unit); bits.push(rev); if (d.name) bits.push(d.name) }
        else if (dk === "dfm") { bits.push(d.label); bits.push(rev); bits.push(d.verdict) }
        else if (dk === "cam") { var s = d.setups[Results.setup]; bits.push(rev); if (s) bits.push("setup " + s.n + " of " + d.setups.length + ", " + s.name); if (d.summary.cycle_time) bits.push(d.summary.cycle_time) }
        else if (dk === "flat") { bits.push(rev); if (d.size_mm) bits.push(F.fmt(d.size_mm[0], 1) + " × " + F.fmt(d.size_mm[1], 1) + " mm"); bits.push(d.bends.length + " bends"); bits.push("t " + d.t + " mm") }
        else if (dk === "motion") { bits.push(rev); bits.push((d.drivers || []).join("; ")) }
        return bits.filter(function (x) { return !!x }).join(" · ")
    }
    // how it is known, as the mockup letters it: SIMULATED · LINEAR STATIC
    readonly property string how: {
        if (!d) return ""
        var ev = String(d.evidence || ""), w = Results.evWord(ev), m = /\(([^,)]*)(?:,\s*([^,)]*))?/.exec(ev)
        if (dk === "field" && m && m[2]) return w + " · " + m[2]
        if (dk === "cam") return w + " · not proven on a machine"
        if (m && m[1]) return w + " · " + m[1]
        return w
    }
    // the error sentence: what a simulation states about itself, or why there is none to state
    readonly property string errorText: {
        if (!d) return ""
        if (dk === "field") {
            if (d.converged !== true) return "Did not converge: " + String(d.why || "no reason given").replace(/\.+$/, "") + "."
            var c = d.convergence || {}, n = c.points ? c.points.length : 0
            return "Discretisation error " + (d.stated && d.stated.text ? d.stated.text : "not stated") + (n ? " after " + n + " meshes" : "") + (d.singular && d.singular.length ? "; " + d.singular.length + " singular zone" + (d.singular.length > 1 ? "s" : "") + " left out (hatched)" : "") + "."
        }
        if (dk === "dfm") return d.what || ""
        if (dk === "cam") return "Gouge " + d.summary.gouge_max_mm + " mm, leftover " + d.summary.leftover_mm3 + " mm³, " + d.summary.rapid_collisions + " rapid and " + d.summary.holder_collisions + " holder collisions."
        if (dk === "flat") return d.verify && d.verify.max_mm !== undefined && d.verify.max_mm !== null ? "Folded back onto the part: largest difference " + Number(d.verify.max_mm).toExponential(1) + " mm over " + d.verify.samples + " points." : ""
        if (dk === "motion") return d.clearance ? d.clearance.detail : ""
        return ""
    }
    readonly property real late: Math.max(0, Math.min(1, (Results.settle - 0.4) / 0.6))      // the error line lights last

    Column {
        id: col; x: 18; y: 14; width: parent.width - 36; spacing: 9
        Item { width: parent.width; height: 18
            Txt { id: ttl; objectName: "legendTitle"; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; text: ls.title }
            Txt { objectName: "legendSub"; anchors.left: ttl.right; anchors.leftMargin: 10; anchors.baseline: ttl.baseline; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                width: Math.max(0, how.x - x - 10); text: ls.sub }
            Ev { id: how; objectName: "legendEvidence"; anchors.right: parent.right; anchors.baseline: ttl.baseline; color: Theme.ink2; text: ls.how } }

        // ── the scale of a field: continuous, with the peak at its end and the value under the pointer ──
        Item { id: scaleRow; width: parent.width; height: 34; visible: ls.dk === "field"; opacity: 0.25 + 0.75 * Results.settle
            readonly property real lo: ls.dk === "field" ? ls.d.range[0] : 0
            readonly property real hi: ls.dk === "field" ? ls.d.range[1] : 1
            Rectangle { id: bar; objectName: "legendScale"; width: parent.width; height: 10; radius: 5
                gradient: Gradient { orientation: Gradient.Horizontal
                    // sixteen steps of the ramp the shader draws (Results.rampAt): closer than a pixel's worth of error
                    GradientStop { position: 0.0; color: (Results.scale, Results.rampAt(0.0)) } GradientStop { position: 0.0667; color: (Results.scale, Results.rampAt(0.0667)) }
                    GradientStop { position: 0.1333; color: (Results.scale, Results.rampAt(0.1333)) } GradientStop { position: 0.2; color: (Results.scale, Results.rampAt(0.2)) }
                    GradientStop { position: 0.2667; color: (Results.scale, Results.rampAt(0.2667)) } GradientStop { position: 0.3333; color: (Results.scale, Results.rampAt(0.3333)) }
                    GradientStop { position: 0.4; color: (Results.scale, Results.rampAt(0.4)) } GradientStop { position: 0.4667; color: (Results.scale, Results.rampAt(0.4667)) }
                    GradientStop { position: 0.5333; color: (Results.scale, Results.rampAt(0.5333)) } GradientStop { position: 0.6; color: (Results.scale, Results.rampAt(0.6)) }
                    GradientStop { position: 0.6667; color: (Results.scale, Results.rampAt(0.6667)) } GradientStop { position: 0.7333; color: (Results.scale, Results.rampAt(0.7333)) }
                    GradientStop { position: 0.8; color: (Results.scale, Results.rampAt(0.8)) } GradientStop { position: 0.8667; color: (Results.scale, Results.rampAt(0.8667)) }
                    GradientStop { position: 0.9333; color: (Results.scale, Results.rampAt(0.9333)) } GradientStop { position: 1.0; color: (Results.scale, Results.rampAt(1.0)) } } }
            // the peak: the end of the scale
            Rectangle { visible: ls.dk === "field" && !!ls.d.peak; x: bar.width - 2; y: -3; width: 2; height: 16; radius: 1; color: Theme.ink }
            // the value under the pointer
            Rectangle { objectName: "legendProbe"; visible: !isNaN(Results.hoverValue); y: -3; width: 2; height: 16; radius: 1; color: Theme.ink
                x: Math.round(Math.max(0, Math.min(1, (Results.hoverValue - scaleRow.lo) / Math.max(1e-12, scaleRow.hi - scaleRow.lo))) * (bar.width - 2)) }
            Repeater { model: 5
                Txt { required property int index
                    readonly property bool last: index === 4
                    y: 19; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: last ? 1 : 3; lineHeight: 1; topPadding: 0; bottomPadding: 0; wrapMode: Text.NoWrap
                    text: Results.fmt(scaleRow.lo + (scaleRow.hi - scaleRow.lo) * index / 4, "") + (last && ls.dk === "field" && ls.d.peak ? "  peak" : "")
                    x: last ? bar.width - width : Math.round(bar.width * index / 4 - (index === 0 ? 0 : width / 2)) } }
            Txt { objectName: "legendProbeValue"; visible: !isNaN(Results.hoverValue); y: 19; x: Math.round(bar.width * 0.125 - width / 2); mono: true; font.pixelSize: 11; tone: 1; wrapMode: Text.NoWrap; lineHeight: 1; topPadding: 0; bottomPadding: 0
                text: ls.dk === "field" ? "here " + Results.fmt(Results.hoverValue, ls.d.unit) : "" }
        }

        // ── manufacturability: what each colour means ──
        Row { width: parent.width; spacing: 14; visible: ls.dk === "dfm"
            Repeater { model: ls.dk === "dfm" ? ls.d.stops : []
                Row { required property var modelData; spacing: 6
                    readonly property int n: { var c = 0, rows = ls.d.rows || []; for (var i = 0; i < rows.length; i++) if (rows[i].status === String(modelData.label).replace(" ", "_")) c++; return c }
                    Rectangle { width: 22; height: 10; radius: 5; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
                    Txt { mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 2; wrapMode: Text.NoWrap; text: modelData.label + " " + parent.n; anchors.verticalCenter: parent.verticalCenter } } }
            Txt { visible: ls.dk === "dfm" && !!ls.d.parting; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                text: "— parting line, proposed" ; color: Theme.datum } }

        // ── sheet metal: the bend lines ──
        Row { width: parent.width; spacing: 14; visible: ls.dk === "flat"
            Repeater { model: [["up", Theme.datum], ["down", Theme.amber]]
                Row { id: bk; required property var modelData; spacing: 6
                    readonly property int n: { var c = 0, b = ls.dk === "flat" ? ls.d.bends : []; for (var i = 0; i < b.length; i++) if ((b[i].direction === "down") === (modelData[0] === "down")) c++; return c }
                    Row { spacing: 2; anchors.verticalCenter: parent.verticalCenter; Repeater { model: 3; Rectangle { width: 6; height: 2; color: bk.modelData[1] } } }
                    Txt { mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 2; wrapMode: Text.NoWrap; text: "bend " + modelData[0] + " " + parent.n } } }
            Item { width: 1; height: 1 }
            Seg { objectName: "foldSeg"; height: 24; anchors.verticalCenter: parent.verticalCenter
                model: [{ value: false, text: "Folded" }, { value: true, text: "Flat" }]; value: Results.flat; onPicked: function (v) { Results.flat = v } } }

        // ── a timeline: the operations of a CNC setup, or a mechanism's smallest gap over its cycle ──
        Item { id: tl; objectName: "timeline"; width: parent.width; height: ls.dk === "motion" ? 54 : 34; visible: ls.dk === "cam" || ls.dk === "motion"
            readonly property real dur: Math.max(1e-9, Results.duration)
            readonly property real x0: 34
            readonly property real w: width - x0
            Rectangle { objectName: "playButton"; width: 26; height: 26; radius: 13; y: ls.dk === "motion" ? 14 : -4; color: pm.containsMouse ? Theme.washHover : Theme.alpha(Theme.lineBase, 0.06); border.color: Theme.rule
                Icon { anchors.centerIn: parent; name: Results.playing ? "pause" : "play"; size: 12; color: Theme.ink }
                MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; onClicked: Results.toggle() } }
            // CNC: one span per operation, in its colour, as long as it runs
            Item { x: tl.x0; width: tl.w; height: 10; visible: ls.dk === "cam"
                Rectangle { anchors.fill: parent; radius: 5; color: Theme.alpha(Theme.lineBase, 0.07) }
                Repeater { model: ls.dk === "cam" && ls.d.setups[Results.setup] ? ls.d.setups[Results.setup].ops.filter(function (o) { return o.kind === "feed" }) : []
                    Rectangle { required property var modelData; height: 10; radius: 2; color: modelData.color
                        x: Math.round(modelData.t0 / tl.dur * tl.w); width: Math.max(2, Math.round((modelData.t1 - modelData.t0) / tl.dur * tl.w) - 1)
                        opacity: modelData.t0 <= Results.t ? 1 : 0.45 } } }
            // motion: the smallest gap of every frame; the tolerance; where it first touches
            Canvas { id: plot; x: tl.x0; width: tl.w; height: 40; visible: ls.dk === "motion"
                readonly property var c: ls.dk === "motion" ? ls.d.clearance : null
                readonly property real span: { var m = 0, s = c ? c.series : []; for (var i = 0; i < s.length; i++) if (s[i].mm !== null && s[i].mm > m) m = s[i].mm; return Math.max(m * 1.15, c ? (c.tolerance_mm || 0) * 2 : 0, 1e-6) }
                onCChanged: requestPaint(); onWidthChanged: requestPaint(); Component.onCompleted: requestPaint()
                Connections { target: Theme; function onDarkChanged() { plot.requestPaint() } }
                onPaint: { var g = getContext("2d"); g.reset(); if (!c) return
                    var s = c.series, W = width, H = height, i
                    g.strokeStyle = Theme.rule2; g.lineWidth = 1; g.beginPath(); g.moveTo(0, H - 0.5); g.lineTo(W, H - 0.5); g.stroke()
                    if (c.tolerance_mm) { var ty = H - c.tolerance_mm / span * H; g.setLineDash([3, 3]); g.strokeStyle = Theme.amber; g.beginPath(); g.moveTo(0, ty); g.lineTo(W, ty); g.stroke(); g.setLineDash([]) }
                    g.strokeStyle = Theme.datum; g.lineWidth = 1.5; g.beginPath(); var pen = false
                    for (i = 0; i < s.length; i++) { if (s[i].mm === null || s[i].mm === undefined) { pen = false; continue }
                        var x = s[i].t / tl.dur * W, y = H - Math.max(0, s[i].mm) / span * H
                        if (pen) g.lineTo(x, y); else g.moveTo(x, y); pen = true }
                    g.stroke()
                    if (c.first_contact_t !== null && c.first_contact_t !== undefined) { var fx = c.first_contact_t / tl.dur * W; g.strokeStyle = Theme.signal; g.lineWidth = 1.5; g.beginPath(); g.moveTo(fx, 0); g.lineTo(fx, H); g.stroke() } } }
            Txt { visible: ls.dk === "motion" && !!plot.c; anchors.right: parent.right; y: parent.height - 14; lineHeight: 1; topPadding: 0; bottomPadding: 0; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
                text: plot.c ? "smallest gap, 0 to " + Results.fmt(plot.span, "mm") + (plot.c.first_contact_t !== null && plot.c.first_contact_t !== undefined ? " · first contact " + Results.fmt(plot.c.first_contact_t, "s") : " · no contact") : "" }
            // the moment shown
            Rectangle { objectName: "scrubHandle"; x: Math.round(tl.x0 + Results.t / tl.dur * tl.w - 1); y: ls.dk === "motion" ? 0 : -4; width: 2; height: ls.dk === "motion" ? 40 : 18; radius: 1; color: Theme.ink }
            MouseArea { objectName: "scrubArea"; x: tl.x0; width: tl.w; y: -6; height: parent.height - 8; cursorShape: Qt.SizeHorCursor
                function go(mx) { Results.scrub(Math.max(0, Math.min(1, mx / width)) * tl.dur) }
                onPressed: function (e) { go(e.x) } onPositionChanged: function (e) { if (pressed) go(e.x) } }
            Txt { x: tl.x0; y: parent.height - 14; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.NoWrap; lineHeight: 1; topPadding: 0; bottomPadding: 0
                objectName: "scrubTime"; text: Results.clock(Results.t) + " of " + Results.clock(tl.dur) + (Results.playRate > 1 ? "  · played " + Results.playRate.toFixed(0) + "× faster" : "") }
            Txt { visible: ls.dk === "cam"; anchors.right: parent.right; y: parent.height - 14; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; lineHeight: 1; topPadding: 0; bottomPadding: 0
                text: Results.t >= tl.dur - 1e-6 ? "stock: end of the setup" : "stock is drawn at the end of the setup" }
        }

        // ── how it is looked at ──
        Row { spacing: 10; visible: ls.dk === "field" || (ls.dk === "cam" && ls.d.setups.length > 1); height: visible ? 24 : 0
            Seg { objectName: "scaleSeg"; visible: ls.dk === "field"; height: 24; model: [{ value: "hue", text: "One hue" }, { value: "many", text: "Many colours" }]
                value: Results.scale; onPicked: function (v) { Results.scale = v } }
            Seg { objectName: "deformSeg"; visible: ls.dk === "field" && !ls.d.modes && ls.d.deform && ls.d.deform.auto > 0; height: 24
                model: [{ value: false, text: "As built" }, { value: true, text: "Deformed × " + Results.deformShown }]; value: Results.deformed; onPicked: function (v) { Results.cut(); Results.deformed = v } }
            Seg { objectName: "modeSeg"; visible: ls.dk === "field" && !!ls.d.modes; height: 24
                model: ls.dk === "field" && ls.d.modes ? ls.d.modes.map(function (m) { return { value: m.n - 1, text: m.text.replace(" × the load", " ×") } }) : []
                value: Results.mode; onPicked: function (v) { Results.mode = v } }
            Btn { objectName: "modePlay"; visible: ls.dk === "field" && !!ls.d.modes; small: true; height: 24; autoBusy: false
                icon: Results.playing ? "pause" : "play"; text: Results.playing ? "Stop" : "Swing"; onClicked: { Results.cut(); Results.playing = !Results.playing } }
            Seg { objectName: "setupSeg"; visible: ls.dk === "cam" && ls.d.setups.length > 1; height: 24
                model: ls.dk === "cam" ? ls.d.setups.map(function (s) { return { value: s.index, text: "Setup " + s.n + " " + s.name } }) : []
                value: Results.setup; onPicked: function (v) { Results.playing = false; Results.setup = v; Results.t = Results.duration } }
        }

        // the stated error (or why there is none), then what the result does not tell: always in sight
        Txt { objectName: "legendLimits"; width: parent.width; font.pixelSize: 12; tone: 2; lineHeight: 1.4; textFormat: Text.StyledText
            readonly property color to: ls.dk === "field" && ls.d.converged !== true ? Theme.signal : Theme.ink
            function hex(a, b, k) { function h(x, y) { return ("0" + Math.round((x + (y - x) * k) * 255).toString(16)).slice(-2) } return "#" + h(a.r, b.r) + h(a.g, b.g) + h(a.b, b.b) }
            text: !ls.d ? "" : "<font color=\"" + hex(Theme.ink2, to, ls.late) + "\">" + ls.esc(ls.errorText) + "</font> " + ls.esc(ls.d.not || "") }
    }
}
