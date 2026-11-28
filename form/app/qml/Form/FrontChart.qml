import QtQuick

// A Pareto chart in the Bench card (an inverse design search, the print orientations): two objectives, every
// evaluated point, the front joined in the order of the first axis. Failed and missing points are shown, not
// dropped. A point under the pointer names itself; a click opens it (Results.openPoint): an inverse design point
// becomes the draft, built and previewed; an orientation shows its numbers. Everything drawn is Results.r.
Item {
    id: fc
    property var r: null
    readonly property var axes: r ? r.axes : []
    readonly property var pts: r ? r.points : []
    readonly property real padL: 16
    readonly property real padB: 30
    readonly property real padT: 26                 // the second axis's name sits on one line above the plot
    readonly property real w: width - padL - 16
    readonly property real h: height - padB - padT
    function span(k) {
        var lo = Infinity, hi = -Infinity
        for (var i = 0; i < pts.length; i++) { var v = pts[i].at[k]; if (v === null || v === undefined) continue; lo = Math.min(lo, v); hi = Math.max(hi, v) }
        if (!isFinite(lo)) return [0, 1]
        var pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1
        return [lo - pad, hi + pad]
    }
    readonly property var sx: span(0)
    readonly property var sy: span(1)
    function xAt(v) { return padL + (v - sx[0]) / (sx[1] - sx[0]) * w }
    function yAt(v) { return padT + h - (v - sy[0]) / (sy[1] - sy[0]) * h }
    readonly property color accent: Theme.dark ? "#3ee6ff" : Theme.datum
    function colorOf(p) { return p.state === "front" ? accent : p.state === "feasible" ? Theme.ink2 : p.state === "failed" ? Theme.signal : Theme.ink3 }
    property int hot: -1
    onRChanged: plot.requestPaint()
    onWidthChanged: plot.requestPaint()
    Connections { target: Theme; function onDarkChanged() { plot.requestPaint() } }
    Connections { target: Results; function onPointChanged() { plot.requestPaint() } }

    Rectangle { anchors.fill: parent; radius: 10; color: Theme.alpha(Theme.lineBase, 0.035); border.color: Theme.rule }
    Canvas {
        id: plot; anchors.fill: parent
        onPaint: {
            var g = getContext("2d"); g.reset()
            if (!fc.r || !fc.pts.length) return
            g.strokeStyle = Theme.rule2; g.lineWidth = 1
            g.beginPath(); g.moveTo(fc.padL + 0.5, fc.padT); g.lineTo(fc.padL + 0.5, fc.padT + fc.h + 0.5); g.lineTo(fc.padL + fc.w, fc.padT + fc.h + 0.5); g.stroke()
            // the front, in the order of the first axis
            var fr = fc.pts.filter(function (p) { return p.state === "front" }).sort(function (a, b) { return a.at[0] - b.at[0] })
            if (fr.length > 1) {
                g.strokeStyle = Theme.alpha(fc.accent, 0.55); g.lineWidth = 1.5; g.beginPath()
                for (var i = 0; i < fr.length; i++) { var x = fc.xAt(fr[i].at[0]), y = fc.yAt(fr[i].at[1]); if (i) g.lineTo(x, y); else g.moveTo(x, y) }
                g.stroke()
            }
            for (var j = 0; j < fc.pts.length; j++) {
                var p = fc.pts[j], px = fc.xAt(p.at[0]), py = fc.yAt(p.at[1]), on = p.index === Results.point, big = p.state === "front" ? 3.5 : 2.5
                g.fillStyle = fc.colorOf(p); g.beginPath(); g.arc(px, py, on ? 5 : big, 0, 2 * Math.PI); g.fill()
                if (on || p.current) { g.strokeStyle = Theme.ink; g.lineWidth = 1.5; g.beginPath(); g.arc(px, py, 7.5, 0, 2 * Math.PI); g.stroke() }
            }
        }
    }
    // the axes' names, each with which way is better
    Txt { x: fc.padL; y: fc.height - 18; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
        text: fc.axes.length ? fc.axes[0].label + (fc.axes[0].unit ? ", " + fc.axes[0].unit : "") + " · " + fc.axes[0].better + " is better" : "" }
    Txt { x: fc.padL; y: 6; width: fc.w; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight
        text: fc.axes.length > 1 ? fc.axes[1].label + (fc.axes[1].unit ? ", " + fc.axes[1].unit : "") + (fc.axes[1].better ? " · " + fc.axes[1].better + " is better" : "") : "" }
    Txt { objectName: "frontHot"; visible: fc.hot >= 0; x: Math.min(fc.width - width - 8, Math.max(fc.padL, hm.mouseX + 10)); y: Math.max(4, hm.mouseY - 26)
        font.pixelSize: 11; mono: true; wrapMode: Text.NoWrap
        text: { if (fc.hot < 0 || !fc.pts[fc.hot]) return ""; var p = fc.pts[fc.hot]
            return (p.label ? p.label + " · " : "#" + p.index + " · ") + Results.fmt(p.at[0], fc.axes[0].unit) + ", " + Results.fmt(p.at[1], fc.axes[1].unit) + (p.state !== "front" ? " · " + p.state : "") } }
    MouseArea {
        id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: fc.hot >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
        function near(mx, my) {
            var best = -1, bd = 12 * 12
            for (var i = 0; i < fc.pts.length; i++) { var dx = fc.xAt(fc.pts[i].at[0]) - mx, dy = fc.yAt(fc.pts[i].at[1]) - my, d = dx * dx + dy * dy; if (d < bd) { bd = d; best = i } }
            return best
        }
        onPositionChanged: function (e) { fc.hot = near(e.x, e.y) }
        onExited: fc.hot = -1
        onClicked: function (e) { var i = near(e.x, e.y); if (i >= 0) Results.openPoint(fc.pts[i]) }
    }
}
