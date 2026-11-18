import QtQuick

// A plain technical drawing of what to measure: a block, a cylinder, a hole, a gap or a wall, in isometric line work,
// with the dimension to take drawn in amber along the asked axis. diagram: { shape: box|cylinder|hole|gap|thickness,
// axis: x|y|z|d }. It shows where to put the jaws, not the part's real proportions.
Canvas {
    id: md
    property var diagram: ({ shape: "box", axis: "x" })
    property string label: "?"
    onDiagramChanged: requestPaint(); onLabelChanged: requestPaint(); onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"); c.reset()
        var W = width, H = height, s = Math.min(W, H) * 0.3, cx = W / 2, cy = H / 2 + s * 0.15
        var shape = diagram && diagram.shape ? diagram.shape : "box", axis = diagram && diagram.axis ? diagram.axis : "x"
        var ink = Qt.rgba(0.91, 0.93, 0.92, 0.7), faint = Qt.rgba(1, 1, 1, 0.12)
        // isometric: x to the lower right, y to the upper right, z up
        function P(x, y, z) { return [cx + (x - y) * 0.866 * s, cy + (x + y) * 0.5 * s - z * s] }
        function line(a, b, col, w) { c.strokeStyle = col; c.lineWidth = w || 1.4; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke() }
        function poly(pts, col, fill) { c.beginPath(); c.moveTo(pts[0][0], pts[0][1]); for (var i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]); c.closePath()
            if (fill) { c.fillStyle = fill; c.fill() } c.strokeStyle = col; c.lineWidth = 1.4; c.stroke() }
        function ellipse(x, y, z, r, col, fill) { c.beginPath(); for (var i = 0; i <= 48; i++) { var t = i / 48 * 2 * Math.PI, p = P(x + r * Math.cos(t), y + r * Math.sin(t), z); if (i === 0) c.moveTo(p[0], p[1]); else c.lineTo(p[0], p[1]) }
            if (fill) { c.fillStyle = fill; c.fill() } c.strokeStyle = col; c.lineWidth = 1.4; c.stroke() }
        function dim(a, b, off) {           // amber dimension: extension lines, the line with arrows, the value
            var amber = Theme.amber, dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L * off, ny = dx / L * off
            var a2 = [a[0] + nx, a[1] + ny], b2 = [b[0] + nx, b[1] + ny]
            line(a, [a2[0] + nx * 0.25, a2[1] + ny * 0.25], Theme.alpha(amber, 0.5), 1); line(b, [b2[0] + nx * 0.25, b2[1] + ny * 0.25], Theme.alpha(amber, 0.5), 1)
            line(a2, b2, amber, 1.8)
            ;[[a2, 1], [b2, -1]].forEach(function (e) { var p = e[0], k = e[1], ux = dx / L * k, uy = dy / L * k
                c.fillStyle = amber; c.beginPath(); c.moveTo(p[0], p[1]); c.lineTo(p[0] + ux * 9 - uy * 4, p[1] + uy * 9 + ux * 4); c.lineTo(p[0] + ux * 9 + uy * 4, p[1] + uy * 9 - ux * 4); c.closePath(); c.fill() })
            var mx = (a2[0] + b2[0]) / 2 + nx * 0.6, my = (a2[1] + b2[1]) / 2 + ny * 0.6
            c.font = "600 13px '" + Theme.mono + "'"; var tw = c.measureText(md.label).width
            c.fillStyle = Theme.plate; c.fillRect(mx - tw / 2 - 6, my - 10, tw + 12, 20)
            c.fillStyle = amber; c.textAlign = "center"; c.textBaseline = "middle"; c.fillText(md.label, mx, my)
        }
        if (shape === "cylinder" || shape === "hole") {
            var r = 0.75, h = shape === "hole" ? 0.5 : 1.2
            if (shape === "hole") { poly([P(-1.2, -1.2, 0), P(1.2, -1.2, 0), P(1.2, 1.2, 0), P(-1.2, 1.2, 0)], faint, Theme.alpha(Theme.plate3, 0.5))
                ellipse(0, 0, 0, r, ink, Theme.well) }
            else { ellipse(0, 0, 0, r, faint); var l1 = P(-r * 0.707, r * 0.707, 0), l2 = P(r * 0.707, -r * 0.707, 0)
                line(P(-r * 0.707, r * 0.707, 0), P(-r * 0.707, r * 0.707, h), ink); line(P(r * 0.707, -r * 0.707, 0), P(r * 0.707, -r * 0.707, h), ink)
                ellipse(0, 0, h, r, ink, Theme.alpha(Theme.plate3, 0.6)) }
            if (axis === "z" && shape === "cylinder") dim(P(r * 0.707, -r * 0.707, 0), P(r * 0.707, -r * 0.707, h), -40)
            else { var zz = shape === "hole" ? 0 : h; dim(P(-r * 0.707, r * 0.707, zz), P(r * 0.707, -r * 0.707, zz), shape === "hole" ? 0.001 : -34) }
            return
        }
        // a block (box), a wall (thickness) or two blocks with a gap
        var X = shape === "thickness" ? 0.25 : 1.1, Y = 0.8, Z = shape === "thickness" ? 1.1 : 0.7
        function block(x0, X1, col) {
            poly([P(x0, -Y, Z), P(X1, -Y, Z), P(X1, Y, Z), P(x0, Y, Z)], col, Theme.alpha(Theme.plate4, 0.55))
            poly([P(X1, -Y, 0), P(X1, Y, 0), P(X1, Y, Z), P(X1, -Y, Z)], col, Theme.alpha(Theme.plate3, 0.7))
            poly([P(x0, Y, 0), P(X1, Y, 0), P(X1, Y, Z), P(x0, Y, Z)], col, Theme.alpha(Theme.plate2, 0.85))
        }
        if (shape === "gap") { block(-1.3, -0.25, ink); block(0.25, 1.3, ink); dim(P(-0.25, Y, Z), P(0.25, Y, Z), 30); return }
        block(-X, X, ink)
        if (axis === "y") dim(P(X, -Y, 0), P(X, Y, 0), 30)
        else if (axis === "z") dim(P(-X, Y, 0), P(-X, Y, Z), 30)
        else dim(P(-X, Y, 0), P(X, Y, 0), 30)
    }
}
