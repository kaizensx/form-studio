// The sketch pad's geometry, kept apart from the drawing so it can be reasoned about (and tested) on its own.
// Millimetres, y up. The engine checks the same structure again (form/sketch.py).
.pragma library

function r2(v) { return Math.round(v * 100) / 100 }
function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]) }

// points a new point can snap to: ends, corners, centres
function anchors(prims) {
    var out = []
    prims.forEach(function (p) {
        if (p.type === "line" || p.type === "dim") { out.push(p.a, p.b) }
        else if (p.type === "rect") { out.push(p.a, p.b, [p.a[0], p.b[1]], [p.b[0], p.a[1]], [(p.a[0] + p.b[0]) / 2, (p.a[1] + p.b[1]) / 2]) }
        else if (p.type === "circle") { out.push(p.c) }
        else if (p.type === "arc") { out.push(p.c, arcEnd(p, true), arcEnd(p, false)) }
        else if (p.type === "path" && p.points.length) { out.push(p.points[0], p.points[p.points.length - 1]) }
    })
    return out
}
function arcEnd(p, start) {
    var a = (start ? p.start_deg : p.end_deg) * Math.PI / 180
    return [p.c[0] + p.r * Math.cos(a), p.c[1] + p.r * Math.sin(a)]
}
// snap: to a point of the drawing within `reachMm`, else to the grid. Returns { p, kind: "point" | "grid" | "free" }
function snap(pt, prims, grid, reachMm, free) {
    if (free) return { p: [r2(pt[0]), r2(pt[1])], kind: "free" }
    var best = null, bd = reachMm
    anchors(prims).forEach(function (q) { var d = dist(pt, q); if (d <= bd) { bd = d; best = q } })
    if (best) return { p: [r2(best[0]), r2(best[1])], kind: "point" }
    return { p: [r2(Math.round(pt[0] / grid) * grid), r2(Math.round(pt[1] / grid) * grid)], kind: "grid" }
}
function angleDeg(c, p) { var a = Math.atan2(p[1] - c[1], p[0] - c[0]) * 180 / Math.PI; return a < 0 ? a + 360 : a }

// what a shape measures, as it is read aloud next to the pointer and in the list
function describe(p) {
    function f(v) { return (Math.round(v * 10) / 10).toString() }
    if (p.type === "line") return "Line " + f(dist(p.a, p.b)) + " mm"
    if (p.type === "rect") return "Rectangle " + f(Math.abs(p.b[0] - p.a[0])) + " × " + f(Math.abs(p.b[1] - p.a[1])) + " mm"
    if (p.type === "circle") return "Circle Ø " + f(2 * p.r) + " mm"
    if (p.type === "arc") { var s = ((p.end_deg - p.start_deg) % 360 + 360) % 360; return "Arc R " + f(p.r) + " mm, " + Math.round(s) + "°" }
    if (p.type === "path") return "Freehand, " + p.points.length + " points"
    if (p.type === "dim") return (p.value !== null && p.value !== undefined ? "Dimension " + f(p.value) + " mm (stated)" : "Dimension " + f(dist(p.a, p.b)) + " mm (drawn)") + (p.label ? " · " + p.label : "")
    return p.type
}

// the structure sent to the agent (form/sketch.py validates it again)
function toJson(prims, opts) {
    var n = 0
    function pt(q) { return [r2(q[0]), r2(q[1])] }
    return {
        version: 1, units: "mm", grid_mm: opts.grid || 5, view: opts.view || "top", intent: opts.intent || "",
        depth_mm: opts.depth > 0 ? r2(opts.depth) : null, notes: String(opts.notes || ""),
        primitives: prims.map(function (p) {
            var o = { id: "p" + (++n), type: p.type }
            if (p.type === "line" || p.type === "rect") { o.a = pt(p.a); o.b = pt(p.b) }
            else if (p.type === "circle") { o.c = pt(p.c); o.r = r2(p.r) }
            else if (p.type === "arc") { o.c = pt(p.c); o.r = r2(p.r); o.start_deg = r2(p.start_deg); o.end_deg = r2(p.end_deg) }
            else if (p.type === "path") { o.points = p.points.map(pt) }
            else if (p.type === "dim") { o.a = pt(p.a); o.b = pt(p.b); o.value = p.value === null || p.value === undefined ? null : r2(p.value); o.label = p.label || "" }
            return o
        })
    }
}

// thin a freehand stroke: keep a point only when it is at least `step` mm from the last kept one
function thin(points, step) {
    var out = []
    points.forEach(function (q) { if (!out.length || dist(out[out.length - 1], q) >= step) out.push(q) })
    return out
}
