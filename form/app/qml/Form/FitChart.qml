import QtQuick
import "F.js" as F

// The modelled distribution of the total gap against the acceptable window.
// Red = too tight, mint = inside the window, amber = too loose. `f` is a fit object.
Canvas {
    id: cv
    property var f: null
    width: parent ? parent.width : 0
    implicitHeight: 136
    height: implicitHeight
    onFChanged: requestPaint()
    onWidthChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (!f || !f.window || width <= 0) return
        var W = width, H = height, m = { l: 6, r: 6, t: 10, b: 28 }
        var lo = f.window[0], hi = f.window[1], mu = f.expected_gap, sd = Math.max(f.sd, 1e-4)
        var x0 = Math.min(lo - 0.25, mu - 3.6 * sd, -0.05), x1 = Math.max(hi + 0.25, mu + 3.6 * sd)
        function X(x) { return m.l + (x - x0) / (x1 - x0) * (W - m.l - m.r) }
        function Y(y) { return H - m.b - y * (H - m.t - m.b) }
        function pdf(x) { var z = (x - mu) / sd; return Math.exp(-0.5 * z * z) }
        function area(a, b, col) {
            if (b <= a) return
            ctx.beginPath(); ctx.moveTo(X(a), Y(0))
            for (var i = 0; i <= 60; i++) { var x = a + (b - a) * i / 60; ctx.lineTo(X(x), Y(pdf(x))) }
            ctx.lineTo(X(b), Y(0)); ctx.closePath(); ctx.fillStyle = col; ctx.fill()
        }
        function line(xa, ya, xb, yb, col, w, dash) {
            ctx.beginPath(); ctx.strokeStyle = col; ctx.lineWidth = w
            if (dash) {
                var len = Math.abs(yb - ya), dir = yb > ya ? 1 : -1
                for (var p = 0; p < len; p += 5) { ctx.moveTo(xa, ya + dir * p); ctx.lineTo(xa, ya + dir * Math.min(p + 3, len)) }
            } else { ctx.moveTo(xa, ya); ctx.lineTo(xb, yb) }
            ctx.stroke()
        }
        function px(v) { return Math.round(v) + 0.5 }

        // acceptable window
        ctx.fillStyle = Theme.alpha(Theme.pass, 0.07)
        ctx.fillRect(X(lo), m.t - 4, X(hi) - X(lo), H - m.b - m.t + 4)
        // the three outcomes
        area(x0, Math.min(lo, x1), Theme.alpha(Theme.signal, 0.38))
        area(Math.max(hi, x0), x1, Theme.alpha(Theme.amber, 0.36))
        area(Math.max(lo, x0), Math.min(hi, x1), Theme.alpha(Theme.datum, 0.24))
        // curve
        ctx.beginPath()
        for (var i = 0; i <= 160; i++) { var x = x0 + (x1 - x0) * i / 160; if (i) ctx.lineTo(X(x), Y(pdf(x))); else ctx.moveTo(X(x), Y(pdf(x))) }
        ctx.strokeStyle = Theme.ink; ctx.lineWidth = 1.4; ctx.stroke()
        // baseline
        line(m.l, px(Y(0)), W - m.r, px(Y(0)), Theme.ink3, 1, false)

        ctx.font = "10px '" + Theme.mono + "'"
        ctx.textBaseline = "alphabetic"
        // window limits
        var lim = [[lo, "right", -4], [hi, "left", 4]]
        for (var k = 0; k < 2; k++) {
            var lx = px(X(lim[k][0]))
            line(lx, m.t - 4, lx, Y(0) + 4, Theme.pass, 1, true)
            ctx.fillStyle = Theme.pass; ctx.textAlign = lim[k][1]
            ctx.fillText(F.fmt(lim[k][0]), lx + lim[k][2], H - 14)
        }
        // expected value
        var mx = px(X(mu))
        line(mx, Y(1), mx, Y(0) + 4, Theme.ink, 1, false)
        var label = "expected " + F.fmt(mu) + " mm", half = ctx.measureText(label).width / 2
        ctx.fillStyle = Theme.ink; ctx.textAlign = "center"
        ctx.fillText(label, Math.max(half + 2, Math.min(W - half - 2, mx)), H - 2)
        // zero: below it the parts interfere
        if (x0 < 0) {
            var zx = px(X(0))
            line(zx, Y(0) - 3, zx, Y(0) + 4, Theme.signal, 1, false)
            if (X(lo) - X(0) > 44) { ctx.fillStyle = Theme.signal; ctx.textAlign = "center"; ctx.fillText("0", zx, H - 14) }
        }
    }
}
