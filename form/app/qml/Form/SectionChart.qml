import QtQuick
import "F.js" as F

// Area of the slice at each height of the print: area along x, height up. `chart` is the engine's section profile
// { z[], area[], height_mm, step_mm, neck: { z_mm, area_mm2 } | null }. Computed geometry, not a strength analysis.
Canvas {
    id: cv
    property var chart: null
    width: parent ? parent.width : 0
    implicitHeight: 150
    height: implicitHeight
    onChartChanged: requestPaint()
    onWidthChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (!chart || !chart.z || !chart.z.length || width <= 0) return
        var W = width, H = height, m = { l: 30, r: 8, t: 8, b: 20 }
        var z = chart.z, a = chart.area, zmax = Math.max(chart.height_mm, 1e-9), amax = 1e-9, i
        for (i = 0; i < a.length; i++) amax = Math.max(amax, a[i])
        function X(v) { return m.l + v / amax * (W - m.l - m.r) }
        function Y(v) { return H - m.b - v / zmax * (H - m.t - m.b) }
        var half = chart.step_mm / 2
        // the profile as stacked slabs: each level is one slice of the print
        ctx.beginPath(); ctx.moveTo(X(0), Y(0))
        for (i = 0; i < z.length; i++) { ctx.lineTo(X(a[i]), Y(Math.max(0, z[i] - half))); ctx.lineTo(X(a[i]), Y(Math.min(zmax, z[i] + half))) }
        ctx.lineTo(X(0), Y(zmax)); ctx.closePath()
        ctx.fillStyle = Theme.alpha(Theme.clay, 0.2); ctx.fill()
        ctx.beginPath()
        for (i = 0; i < z.length; i++) {
            if (i === 0) ctx.moveTo(X(a[i]), Y(Math.max(0, z[i] - half))); else ctx.lineTo(X(a[i]), Y(Math.max(0, z[i] - half)))
            ctx.lineTo(X(a[i]), Y(Math.min(zmax, z[i] + half)))
        }
        ctx.strokeStyle = Theme.ink; ctx.lineWidth = 1.3; ctx.stroke()
        // axes
        ctx.strokeStyle = Theme.ink4; ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(Math.round(X(0)) + 0.5, Y(zmax)); ctx.lineTo(Math.round(X(0)) + 0.5, Math.round(Y(0)) + 0.5); ctx.lineTo(W - m.r, Math.round(Y(0)) + 0.5); ctx.stroke()
        ctx.font = "10px '" + Theme.mono + "'"; ctx.fillStyle = Theme.ink3; ctx.textBaseline = "alphabetic"
        ctx.textAlign = "right"; ctx.fillText(F.fmt(zmax, 0), m.l - 5, Y(zmax) + 8); ctx.fillText("0", m.l - 5, Y(0))
        ctx.fillText("mm", m.l - 5, Y(zmax) + 20)
        ctx.textAlign = "right"; ctx.fillText(F.fmt(amax, 0) + " mm²", W - m.r, H - 5)
        ctx.textAlign = "left"; ctx.fillText("slice area", m.l, H - 5)
        var nk = chart.neck
        if (nk) {
            var y = Math.round(Y(nk.z_mm)) + 0.5, x = X(nk.area_mm2)
            ctx.strokeStyle = Theme.amber; ctx.lineWidth = 1
            ctx.beginPath(); ctx.moveTo(X(0), y); ctx.lineTo(W - m.r, y); ctx.stroke()
            ctx.fillStyle = Theme.amber; ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill()
            var label = "neck " + F.fmt(nk.area_mm2, 0) + " mm² at " + F.fmt(nk.z_mm, 1) + " mm"
            var above = y - m.t > 16
            ctx.textAlign = "right"; ctx.fillText(label, W - m.r, above ? y - 5 : y + 13)
        }
    }
}
