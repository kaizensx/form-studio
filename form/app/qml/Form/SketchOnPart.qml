import QtQuick
import "F.js" as F

// A sketch drawn on the part itself (docs/design/directions/i/IA.md; form/handsketch.py, form.sketch2d).
// Pick a flat face or a datum plane; the camera eases to look straight at it, the face is tinted, and the profile
// is drawn on that plane in the 3D view: every point is a point of the plane, projected through the view's own
// camera, so the sketch stays on the face when the view is turned. The solver runs on every change; what is left
// free is counted in the tool capsule. Extrude, Cut or Revolve at the foot of the stage builds it as one feature of
// the design's code (the same routes the sheet used: /model, /sketch, /start/sketch).
// While a sketch is open the view is orthographic (Viewport.sketching): the far end of an extrusion and the kernel's
// preview stand straight over the profile. The rest of the part is a ghost, the face keeps its tint, and the
// profile's lines are drawn in the part's own depth (Viewport.inkLines): what stands in front of them hides them,
// and the hidden part is still drawn, faintly, here. A dimension is drawn as on a drawing: witness lines, a
// dimension line with arrows, its value in a tag that is typed over. Symbols and tags are seated so that none covers
// another or the profile (layout()).
//   pick(kind)      wait for a face or a plane (the dock's Sketch, Extrude, Cut, Revolve)
//   begin(props)    props as the sheet took them: { mode: "new" | "add" | "edit", plane, outline, feature, sketch, values }
// The old sheet (SketchEditor.qml) stays as the fallback where there is no 3D view (a software renderer).
Item {
    id: so
    objectName: "sketchOnPart"
    property Item vp: null                     // the Viewport this sketch is drawn in
    property Item source: null                 // what the capsules blur
    property real capX: 0                      // the tool capsule's fixed place, and how wide it may be
    property real capY: 0
    property real capMax: 600
    property real midX: width / 2              // the stage's centre line, and its foot
    property real footL: capX                  // the foot of the stage is free from here to here (no view cube down there)
    property real footR: capX + capMax
    property real footY: height - 20
    readonly property bool usable: !!vp && GraphicsInfo.api !== GraphicsInfo.Software
    property var props: null
    property bool picking: false
    readonly property bool on: !!props
    readonly property bool busyHere: on || picking
    readonly property string mode: props ? props.mode || "add" : "add"
    property var sk: ({ plane: { datum: "XY", offset: 0 }, points: [], fixed: [], entities: [], constraints: [] })
    property var sol: null
    property string tool: "line"               // select | line | arc | circle | rect | dim
    property var chain: []                     // points clicked so far for the entity being drawn (indices)
    property var from: null                    // rect and circle: where the drag began, [x, y]
    property var rubber: null                  // [x, y] under the pointer
    property var snap: null                    // { p: [x, y], kind: "point" | "mid" | "corner" | "origin" }
    property var selE: []
    property var selP: []
    property int dragPt: -1
    property int editing: -1                   // the constraint whose value is being typed
    property string kind: "extrude"
    property string depth: "10"
    property string name: ""
    property bool busy: false
    property string err: ""
    property var draft: null                   // the kernel's preview of the feature: { preview: { ok, volume_mm3, view } }
    property int tick: 0                       // the camera moved: everything pinned to the plane is placed again
    // the plane's frame, in design coordinates
    property vector3d o: Qt.vector3d(0, 0, 0)
    property vector3d xd: Qt.vector3d(1, 0, 0)
    property vector3d yd: Qt.vector3d(0, 1, 0)
    property vector3d nd: Qt.vector3d(0, 0, 1)
    readonly property var datums: ({ XY: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], XZ: [[1, 0, 0], [0, 0, 1], [0, -1, 0]], YZ: [[0, 1, 0], [0, 0, 1], [1, 0, 0]] })
    function v3(a) { return Qt.vector3d(a[0], a[1], a[2]) }
    function clone(x) { return JSON.parse(JSON.stringify(x)) }
    function rnd(v, d) { var k = Math.pow(10, d); return Math.round(v * k) / k }
    function frameOf(pl) {
        if (!pl) return null
        if (pl.datum && datums[pl.datum]) { var D = datums[pl.datum], n = v3(D[2]); return { o: n.times(Number(pl.offset) || 0), x: v3(D[0]), y: v3(D[1]), n: n } }
        if (pl.origin && pl.x && pl.normal) { var x = v3(pl.x), nn = v3(pl.normal); return { o: v3(pl.origin), x: x, y: pl.y ? v3(pl.y) : nn.crossProduct(x), n: nn } }
        return null
    }
    function setFrame(pl) {
        var f = frameOf(pl)
        if (!f) return false
        o = f.o; xd = f.x; yd = f.y; nd = f.n
        return true
    }

    // ── in and out ──
    function pick(k) {                         // the dock's tool: wait for a face or a plane
        if (!usable) { Store.openSheet("handsketch", { mode: "add", plane: { datum: "XY", offset: 0 }, sheet: true }); return }
        if (on) { kind = k || kind; return }
        kind = k || "extrude"; picking = true; err = ""; hover = null
        area.forceActiveFocus()
    }
    function begin(p) {                        // true when the sketch is drawn here; false: the caller opens the sheet
        if (!usable || !p || p.sheet) return false
        var pl = p.sketch ? p.sketch.plane : p.plane
        if (!setFrame(pl)) return false
        var s = p.sketch ? clone(p.sketch) : { plane: pl, points: [], fixed: [], entities: [], constraints: [] }
        if (p.mode === "edit" && p.values) for (var i = 0; i < s.constraints.length; i++) {      // the literal holds the defaults; show the current values
            var c = s.constraints[i], key = p.feature + "_" + c.name
            if (c.name && p.values[key] !== undefined) c.value = p.values[key]
        }
        sol = null; draft = null; err = ""; chain = []; from = null; rubber = null; snap = null; selE = []; selP = []; editing = -1
        tool = s.entities.length ? "select" : "line"
        if (p.kind) kind = p.kind
        if (p.mode === "new" && kind === "cut") kind = "extrude"
        depth = kind === "cut" ? "0" : "10"
        sk = s; props = p; picking = false
        hover = null; vp.sketching = true
        look()
        solve()
        area.forceActiveFocus()
        return true
    }
    function look() {                          // ease the camera normal to the plane, framing the face or what is drawn
        var xs = [], ys = []
        sk.points.forEach(function (q) { xs.push(q[0]); ys.push(q[1]) })
        ;((props && props.outline) || []).forEach(function (pl) { pl.forEach(function (q) { xs.push(q[0]); ys.push(q[1]) }) })
        var c = o, r = vp.model ? vp.radius(vp.bounds) * 0.8 : 46
        if (xs.length) {
            var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys)
            c = at3([(x0 + x1) / 2, (y0 + y1) / 2]); r = Math.max(14, Math.hypot(x1 - x0, y1 - y0) / 2 * 1.15)
        }
        vp.lookNormal(nd, xd, c, r)
    }
    function end() {
        if (!on && !picking) return
        var had = on
        props = null; picking = false; draft = null; sol = null; chain = []; from = null; rubber = null; snap = null; selE = []; selP = []; editing = -1; busy = false
        pv.stop()
        hover = null; hv.stop()
        if (vp) {
            vp.sketching = false; vp.inkLines = []; vp.inkLit = []
            if (had && Store.viewer === vp) { Store.showHead(); vp.setView(Store.viewName, true) }
        }
        if (vp) vp.forceActiveFocus()
    }
    function leave() {                         // Esc: the line being drawn first, then the selection, then an empty sketch
        if (editing >= 0) { editing = -1; area.forceActiveFocus(); return }
        if (chain.length || from) { chain = []; from = null; rubber = null; ink.requestPaint(); return }
        if (selE.length || selP.length) { selE = []; selP = []; return }
        if (picking || !sk.entities.length) end()
    }
    Component.onDestruction: if (vp) { vp.sketching = false; vp.inkLines = []; vp.inkLit = [] }

    // ── the plane and the screen ──
    function at3(p) { return o.plus(xd.times(p[0])).plus(yd.times(p[1])) }
    function px(p, h) {
        var q = vp ? vp.designPx(h ? at3(p).plus(nd.times(h)) : at3(p)) : null
        return q || Qt.point(-1e5, -1e5)
    }
    function mmAt(x, y) {
        var h = vp ? vp.rayPlane(x, y, o, nd) : null
        if (!h) return null
        var r = h.minus(o)
        return [r.dotProduct(xd), r.dotProduct(yd)]
    }
    readonly property real grid: vp && vp.mmPerPx < 0.07 ? 0.5 : 1          // the step a free click lands on, mm
    readonly property var corners: {           // the face's own corners: ends of its outline's edges
        var out = []
        ;((props && props.outline) || []).forEach(function (pl) { if (pl.length) { out.push(pl[0]); out.push(pl[pl.length - 1]) } })
        return out
    }
    function mids() {
        var out = []
        for (var i = 0; i < sk.entities.length; i++) { var e = sk.entities[i]; if (e.k === "line") { var a = sk.points[e.p[0]], b = sk.points[e.p[1]]; out.push({ p: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], e: i }) } }
        return out
    }
    // what a click at this pixel means: an existing point, a line's midpoint, a corner of the face, the origin, or the grid
    function snapAt(x, y, skip) {
        var best = null, bd = 10, i, q, d
        for (i = 0; i < sk.points.length; i++) { if (i === skip) continue; q = px(sk.points[i]); d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = { p: sk.points[i].slice(), kind: "point", i: i } } }
        if (best) return best
        var ms = mids()
        for (i = 0; i < ms.length; i++) { q = px(ms[i].p); d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = { p: ms[i].p, kind: "mid", e: ms[i].e } } }
        for (i = 0; i < corners.length; i++) { q = px(corners[i]); d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = { p: corners[i].slice(), kind: "corner" } } }
        q = px([0, 0]); d = Math.hypot(q.x - x, q.y - y); if (d < bd) best = { p: [0, 0], kind: "origin" }
        if (best) return best
        var m = mmAt(x, y)
        return m ? { p: [Math.round(m[0] / grid) * grid, Math.round(m[1] / grid) * grid], kind: "grid" } : null
    }
    function nearPoint(x, y) { var best = -1, bd = 9; for (var i = 0; i < sk.points.length; i++) { var q = px(sk.points[i]), d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = i } } return best }
    function arcOf(e) {                        // centre, radius and the two angles of an arc entity (counter-clockwise)
        var c = sk.points[e.p[0]], s = sk.points[e.p[1]], t = e._end || sk.points[e.p[2]]
        var a0 = Math.atan2(s[1] - c[1], s[0] - c[0]), a1 = Math.atan2(t[1] - c[1], t[0] - c[0])
        if (a1 <= a0) a1 += 2 * Math.PI
        return { c: c, r: Math.hypot(s[0] - c[0], s[1] - c[1]), a0: a0, a1: a1 }
    }
    function sample(e) {                       // an entity as points of the plane
        if (e.k === "line") return [sk.points[e.p[0]], sk.points[e.p[1]]]
        var c, r, a0, a1, out = [], n
        if (e.k === "circle") { c = sk.points[e.p[0]]; r = e.r; a0 = 0; a1 = 2 * Math.PI }
        else { var a = arcOf(e); c = a.c; r = a.r; a0 = a.a0; a1 = a.a1 }
        n = Math.max(8, Math.ceil((a1 - a0) / (Math.PI / 24)))
        for (var i = 0; i <= n; i++) { var t = a0 + (a1 - a0) * i / n; out.push([c[0] + r * Math.cos(t), c[1] + r * Math.sin(t)]) }
        return out
    }
    function nearEntity(x, y) {
        var best = -1, bd = 8
        for (var i = 0; i < sk.entities.length; i++) {
            var pts = sample(sk.entities[i])
            for (var j = 0; j + 1 < pts.length; j++) {
                var a = px(pts[j]), b = px(pts[j + 1]), vx = b.x - a.x, vy = b.y - a.y
                var t = Math.max(0, Math.min(1, ((x - a.x) * vx + (y - a.y) * vy) / Math.max(1e-9, vx * vx + vy * vy)))
                var d = Math.hypot(a.x + t * vx - x, a.y + t * vy - y)
                if (d < bd) { bd = d; best = i }
            }
        }
        return best
    }

    // ── edits of the sketch data (the same data edit_sketch's ops work on) ──
    function pointIn(s2, m) {
        for (var i = 0; i < s2.points.length; i++) if (Math.abs(s2.points[i][0] - m[0]) < 1e-6 && Math.abs(s2.points[i][1] - m[1]) < 1e-6) return i
        s2.points.push([m[0], m[1]])
        if (!s2.fixed.length) s2.fixed.push(s2.points.length - 1)       // the first point holds the sketch in place
        return s2.points.length - 1
    }
    function place(s2, sn) {                   // a snapped click as a point of the sketch; a midpoint keeps its meaning
        var n0 = s2.points.length, i = pointIn(s2, sn.p)
        if (sn.kind === "mid" && i >= n0) s2.constraints.push({ k: "midpoint", p: [i], e: [sn.e] })
        return i
    }
    function addLine(s2, a, b) {
        if (a === b) return
        s2.entities.push({ k: "line", p: [a, b] })
        var p = s2.points[a], q = s2.points[b], ang = ((Math.atan2(q[1] - p[1], q[0] - p[0]) * 180 / Math.PI) % 180 + 180) % 180
        if (Math.min(ang, 180 - ang) <= 4) s2.constraints.push({ k: "horizontal", e: [s2.entities.length - 1] })
        else if (Math.abs(ang - 90) <= 4) s2.constraints.push({ k: "vertical", e: [s2.entities.length - 1] })
    }
    function set(s2) { sk = s2; solve() }
    function freeName(base) { var used = sk.constraints.map(function (c) { return c.name }), n = 1; while (used.indexOf(base + n) >= 0) n++; return base + n }
    function isChainStart(i) { for (var j = 0; j < sk.entities.length; j++) { var e = sk.entities[j]; if (e.k === "line" && (e.p[0] === i || e.p[1] === i)) return true } return false }
    function count(k) { return sk.constraints.filter(function (c) { return c.k === k }).length + 1 }
    function dimOf(i) { for (var j = 0; j < sk.constraints.length; j++) { var c = sk.constraints[j]; if ((c.k === "length" || c.k === "diameter" || c.k === "radius") && c.e && c.e.length === 1 && c.e[0] === i) return j } return -1 }
    function dimension(i) {                    // a driving dimension on one entity, at what it measures now; then its value is typed in place
        var e = sk.entities[i], j = dimOf(i)
        if (!e) return
        if (j < 0) {
            var s2 = clone(sk)
            if (e.k === "circle") s2.constraints.push({ k: "diameter", e: [i], value: so.rnd(2 * e.r, 2), name: freeName("d"), label: "Ø " + count("diameter") })
            else if (e.k === "arc") s2.constraints.push({ k: "radius", e: [i], value: so.rnd(arcOf(e).r, 2), name: freeName("r"), label: "Radius " + count("radius") })
            else { var a = sk.points[e.p[0]], b = sk.points[e.p[1]]
                s2.constraints.push({ k: "length", e: [i], value: so.rnd(Math.hypot(b[0] - a[0], b[1] - a[1]), 2), name: freeName("l"), label: "Length " + count("length") }) }
            j = s2.constraints.length - 1
            set(s2)
        }
        edit(j)
    }
    function dirOf(i) { var e = sk.entities[i], a = sk.points[e.p[0]], b = sk.points[e.p[1]]; return Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI }
    function addCon(c, thenEdit) { var s2 = clone(sk); s2.constraints.push(c); set(s2); if (thenEdit) edit(s2.constraints.length - 1) }
    function edit(j) { editing = j; Qt.callLater(function () { ed.text = F.fmt(so.sk.constraints[j].value, 2).replace(/\.?0+$/, ""); ed.forceActiveFocus(); ed.selectAll() }) }
    function setValue(j, v) {
        if (!(v > 0) || !sk.constraints[j]) return
        var s2 = clone(sk); s2.constraints[j].value = v; set(s2)
    }
    // what can be said about the selection: constraints, and dimensions between things
    readonly property var offers: {
        var E = selE.map(function (i) { return so.sk.entities[i] }).filter(function (e) { return !!e }), P = selP, out = []
        if (E.length !== selE.length || tool !== "select") return out
        var lines = E.filter(function (e) { return e.k === "line" }).length, rounds = E.length - lines
        function c(text, kind, tip) { out.push({ text: text, tip: tip || "", run: function () { var k = { k: kind }; if (so.selE.length) k.e = so.selE.slice(); if (so.selP.length) k.p = so.selP.slice(); so.addCon(k) } }) }
        function d(text, kind, base, value, tip) { out.push({ text: text, tip: tip || "", dim: true, run: function () { var k = { k: kind, value: so.rnd(value(), 2), name: so.freeName(base), label: text + " " + so.count(kind) }
            if (so.selE.length) k.e = so.selE.slice(); if (so.selP.length) k.p = so.selP.slice(); so.addCon(k, true) } }) }
        if (!P.length && E.length === 1) {
            if (lines) { c("Horizontal", "horizontal"); c("Vertical", "vertical") }
            out.push({ text: "Dimension", dim: true, tip: "Its length, diameter or radius, typed in place", run: function () { so.dimension(so.selE[0]) } })
        } else if (!P.length && E.length === 2) {
            if (lines === 2) { c("Parallel", "parallel"); c("Perpendicular", "perpendicular"); c("Equal", "equal", "The same length")
                d("Angle", "angle", "a", function () { return ((so.dirOf(so.selE[1]) - so.dirOf(so.selE[0])) % 360 + 360) % 360 }, "From the first line to the second, counter-clockwise") }
            else if (lines === 1) c("Tangent", "tangent")
            else { c("Equal", "equal", "The same radius"); c("Tangent", "tangent") }
        } else if (P.length === 2 && !E.length) {
            c("Coincident", "coincident", "The two points become one place")
            d("Distance", "distance", "dist", function () { var a = so.sk.points[so.selP[0]], b = so.sk.points[so.selP[1]]; return Math.hypot(b[0] - a[0], b[1] - a[1]) })
            d("Across", "hdist", "dist", function () { return Math.abs(so.sk.points[so.selP[1]][0] - so.sk.points[so.selP[0]][0]) }, "The horizontal distance")
            d("Up", "vdist", "dist", function () { return Math.abs(so.sk.points[so.selP[1]][1] - so.sk.points[so.selP[0]][1]) }, "The vertical distance")
        } else if (P.length === 2 && E.length === 1 && lines) c("Symmetric", "symmetric", "The two points mirror each other about the line")
        else if (P.length === 1 && E.length === 1) { if (lines) c("Midpoint", "midpoint", "The point stays at the middle of the line"); c("On it", "on", "The point stays on the line or the circle") }
        else if (P.length === 1 && !E.length) out.push({ text: "Fix", tip: "The point stays where it is", run: function () { var s2 = so.clone(so.sk); if (s2.fixed.indexOf(so.selP[0]) < 0) s2.fixed.push(so.selP[0]); so.set(s2) } })
        return out
    }
    function removeSel() {
        if (!selE.length) return
        var s2 = clone(sk), gone = selE.slice().sort(function (a, b) { return b - a })
        gone.forEach(function (j) {
            s2.entities.splice(j, 1)
            s2.constraints = s2.constraints.filter(function (c) { return !(c.e && c.e.indexOf(j) >= 0) })
                .map(function (c) { if (c.e) c.e = c.e.map(function (x) { return x > j ? x - 1 : x }); return c })
        })
        selE = []; selP = []; editing = -1
        set(s2)
    }
    function removeCon(j) { var s2 = clone(sk); s2.constraints.splice(j, 1); editing = -1; set(s2) }

    // ── the solver, and the kernel's preview of the feature ──
    property int _n: 0
    function solve() {
        var n = ++_n
        if (draft) { draft = null; if (Store.viewer === vp && mode !== "new") Store.showHead() }
        Store.post("/sketch/solve", { sketch: sk }).then(function (r) {
            if (n !== so._n || !so.on) return
            so.sol = r
            so.err = r.ok ? "" : r.error
            if (r.ok && r.points.length === so.sk.points.length) { var s2 = so.clone(so.sk); s2.points = r.points; so.sk = s2 }
            ink.requestPaint()
            if (so.ready && so.mode === "add") pv.restart()
        }, function (e) { if (n === so._n) so.err = e.message || "The sketch does not solve." })
    }
    readonly property int axis: selE.length === 1 && sk.entities[selE[0]] && sk.entities[selE[0]].k === "line" ? selE[0] : -1
    readonly property bool ready: on && !!sol && sol.ok && sol.closed && !busy && (kind !== "revolve" || mode === "edit" || axis >= 0)
    readonly property real depthMm: Number(depth) || 0
    function body(preview) {
        return { kind: kind, sketch: sk, depth: depthMm, angle: 360, axis_entity: Math.max(0, axis), preview: preview, expect_head: Store.project ? Store.project.head : null }
    }
    Timer { id: pv; interval: 420; onTriggered: so.preview() }
    onKindChanged: { if (on) { depth = kind === "cut" ? "0" : depth === "0" ? "10" : depth; requeue() } }
    onDepthMmChanged: requeue()
    onAxisChanged: if (on && kind === "revolve") requeue()
    function requeue() {
        if (!on) return
        if (draft) { draft = null; if (Store.viewer === vp && mode !== "new") Store.showHead() }
        ink.requestPaint()
        if (ready && mode === "add") pv.restart()
    }
    function preview() {                       // the feature built in the kernel, saved nowhere: shown on the part, with its change in volume
        if (!ready || mode !== "add" || (kind === "extrude" && !(depthMm > 0))) return
        var n = _n, k = kind, dp = depthMm
        Store.ppost("/model", body(true)).then(function (r) {
            if (n !== so._n || !so.on || k !== so.kind || dp !== so.depthMm) return
            so.draft = r
            if (!r.preview.ok) { so.err = r.preview.refused || "The kernel refused it."; return }
            so.err = ""
            if (Store.viewer === so.vp && r.preview.view) { so.vp.setModel(r.preview.view); so.vp.setGhost(Store.view); so.vp.flagged = [r.feature] }
        }, function (e) { if (n === so._n) so.err = (e.message || "Refused.") + (e.hint ? " " + e.hint : "") })
    }
    function commit() {
        if (!ready) return
        busy = true; err = ""
        function bad(e) { so.busy = false; so.err = (e.message || "Refused.") + (e.hint ? " " + e.hint : "") }
        if (mode === "new") {
            Store.post("/start/sketch", { name: name || "Untitled design", sketch: sk, kind: kind === "revolve" ? "revolve" : "extrude", depth: depthMm,
                                          angle: 360, axis_entity: Math.max(0, axis), purpose: Store.newPurposeEffective || "model" }).then(function (r) {
                so.end()
                return Store.reloadStudio().then(function () { return Store.open(r.id).then(function () { Store.track(r.job); Store.setStage("shape") }) })
            }, bad)
            return
        }
        var edit = mode === "edit", feature = props.feature
        Store.ensureConv().then(function (cid) {
            var b = edit ? { feature: feature, sketch: so.sk, conversation: cid, expect_head: Store.project.head } : so.body(false)
            b.conversation = cid
            return Store.ppost(edit ? "/sketch" : "/model", b).then(function (r) {
                Store.toast("You " + (edit ? "changed the sketch" : "added " + r.said.replace(/^Added /, "")),
                            "Written into the design's code as " + F.pad(r.head) + "; the checks run again.")
                so.end()
                Store._chatTick(); Store.refresh(true)
                if (r && r.job) Store.track(r.job)
            }, bad)
        }, bad)
    }

    // ── the camera moved: place everything again (never on a timer; a still view repaints nothing) ──
    readonly property var cam: vp ? [vp.az, vp.el, vp.dist, vp.target, vp.shift, vp.shownLeft, vp.shownRight, vp.shownTop, vp.shownBottom, vp.width, vp.height] : []
    onCamChanged: if (on || hover) { tick++; ink.requestPaint() }
    onSkChanged: { sync3(); ink.requestPaint() }
    onSelEChanged: { sync3(); ink.requestPaint() }
    onSelPChanged: ink.requestPaint()
    onSnapChanged: ink.requestPaint()
    onOnChanged: { sync3(); ink.requestPaint() }
    onHoverChanged: ink.requestPaint()
    onLayChanged: ink.requestPaint()
    // the profile as 3D lines in the part's own depth (construction lines stay dashed, in the ink)
    function sync3() {
        if (!vp) return
        var all = [], lit = []
        if (on) for (var i = 0; i < sk.entities.length; i++) {
            var e = sk.entities[i]
            if (e.construction) continue
            var pts = sample(e), to = selE.indexOf(i) >= 0 ? lit : all
            for (var j = 0; j + 1 < pts.length; j++) { var a = at3(pts[j]), b = at3(pts[j + 1]); to.push(a.x, a.y, a.z, b.x, b.y, b.z) }
        }
        vp.inkLines = all; vp.inkLit = lit
    }

    // ── the face under the pointer, before it is picked: its outline lit, from the kernel (never guessed from the mesh) ──
    property var hover: null                   // { plane, outline, loops, f: frame, at }
    property point _hp: Qt.point(0, 0)
    property int _hn: 0
    Timer { id: hv; interval: 45; onTriggered: so.probe() }
    function loopsOf(outline) {                // the face's edges chained into closed loops (plane coordinates)
        var left = (outline || []).filter(function (p) { return p.length > 1 }).map(function (p) { return p.slice() }), loops = []
        function near(a, b) { return Math.abs(a[0] - b[0]) < 2e-3 && Math.abs(a[1] - b[1]) < 2e-3 }
        while (left.length) {
            var cur = left.shift(), grew = true
            while (grew && !near(cur[0], cur[cur.length - 1])) {
                grew = false
                for (var i = 0; i < left.length; i++) {
                    var c = left[i], end = cur[cur.length - 1]
                    if (near(c[0], end)) { cur = cur.concat(c.slice(1)); left.splice(i, 1); grew = true; break }
                    if (near(c[c.length - 1], end)) { cur = cur.concat(c.slice().reverse().slice(1)); left.splice(i, 1); grew = true; break }
                }
            }
            loops.push(cur)
        }
        return loops
    }
    function inLoops(loops, m) {               // even-odd: inside the face, outside its holes
        var inside = false
        for (var l = 0; l < loops.length; l++) { var lp = loops[l]
            for (var i = 0, j = lp.length - 1; i < lp.length; j = i++) {
                var a = lp[i], b = lp[j]
                if ((a[1] > m[1]) !== (b[1] > m[1]) && m[0] < (b[0] - a[0]) * (m[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside
            } }
        return inside
    }
    function onFace(h, x, y) {                 // is this pixel still on the face that is lit
        if (!h || !vp) return false
        var hit = vp.hitAt(x, y)
        if (!hit) return false
        var r = Qt.vector3d(hit.shown[0], hit.shown[1], hit.shown[2]).minus(h.f.o)
        return Math.abs(r.dotProduct(h.f.n)) < 0.02 && inLoops(h.loops, [r.dotProduct(h.f.x), r.dotProduct(h.f.y)])
    }
    function probe() {
        if (!picking || !vp) { hover = null; return }
        if (onFace(hover, _hp.x, _hp.y)) return
        var hit = vp.hitAt(_hp.x, _hp.y), n = ++_hn
        if (!hit) { hover = null; return }
        Store.ppost("/sketch_plane", { at: hit.at }).then(function (r) {
            if (n !== so._hn || !so.picking) return
            var fr = so.frameOf(r.plane)
            so.hover = fr ? { plane: r.plane, outline: r.outline, loops: so.loopsOf(r.outline), f: fr } : null
        }, function () { if (n === so._hn) so.hover = null })      // a curved face: nothing lights, and a click says why
    }
    function pxF(fr, p) { var q = vp ? vp.designPx(fr.o.plus(fr.x.times(p[0])).plus(fr.y.times(p[1]))) : null; return q || Qt.point(-1e5, -1e5) }

    // ── where the dimensions and the constraints' symbols sit (screen px), so that none covers another or the profile ──
    function _hit(r, rects) { for (var i = 0; i < rects.length; i++) { var q = rects[i]; if (r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h) return true } return false }
    function _cuts(r, segs) {                  // does one of the segments pass through the rectangle (Liang-Barsky)
        for (var i = 0; i < segs.length; i++) {
            var g = segs[i], dx = g[2] - g[0], dy = g[3] - g[1], t0 = 0, t1 = 1, ok = true
            var p = [-dx, dx, -dy, dy], q = [g[0] - r.x, r.x + r.w - g[0], g[1] - r.y, r.y + r.h - g[1]]
            for (var k = 0; k < 4 && ok; k++) {
                if (Math.abs(p[k]) < 1e-9) { if (q[k] < 0) ok = false }
                else { var t = q[k] / p[k]; if (p[k] < 0) { if (t > t1) ok = false; else if (t > t0) t0 = t } else { if (t < t0) ok = false; else if (t < t1) t1 = t } }
            }
            if (ok) return true
        }
        return false
    }
    readonly property var lay: { tick; sk; sol; return on && vp ? layout() : ({ dims: ({}), glyphs: [], lines: [], arrows: [] }) }
    function layout() {
        var L = { dims: ({}), glyphs: [], lines: [], arrows: [] }
        var mm = Math.max(1e-6, vp.mmPerPx), i, j, n = sk.points.length, cx = 0, cy = 0, segs = [], rects = []
        for (j = 0; j < n; j++) { cx += sk.points[j][0] / n; cy += sk.points[j][1] / n }
        for (i = 0; i < sk.entities.length; i++) {
            var pts = sample(sk.entities[i])
            for (j = 0; j + 1 < pts.length; j++) { var a0 = px(pts[j]), b0 = px(pts[j + 1]); segs.push([a0.x, a0.y, b0.x, b0.y]) }
        }
        for (j = 0; j < n; j++) { var q0 = px(sk.points[j]); rects.push({ x: q0.x - 5, y: q0.y - 5, w: 10, h: 10 }) }
        // the capsule at the head of the stage and the foot with Extrude: nothing is seated under them
        ;[cap, foot].forEach(function (it) { if (it && it.visible && it.width > 0) rects.push({ x: it.x - 6, y: it.y - 6, w: it.width + 12, h: it.height + 12 }) })
        function tagW(k) { return Math.ceil(dimText(k).length * 6.7) + 16 }
        function inView(r) { return r.x >= 2 && r.y >= 2 && r.x + r.w <= so.width - 2 && r.y + r.h <= so.height - 2 }
        function free(r) { return inView(r) && !so._hit(r, rects) && !so._cuts(r, segs) }
        function keep(ci, c) {
            L.dims[ci] = { x: c.x, y: c.y }
            rects.push(c.r)
            for (var t = 0; t < c.lines.length; t++) { L.lines.push(c.lines[t]); segs.push(c.lines[t]) }
            for (t = 0; t < c.arrows.length; t++) L.arrows.push(c.arrows[t])
        }
        // a length between two points of the plane, measured along the line through them or across (hdist, vdist):
        // nrm is the side the dimension line stands off to; the nearest free seat on that side, then on the other
        function linear(ci, k, P, Q, nrm) {
            var w = tagW(k), h = 22, first = null, clear = null, seen = null
            for (var side = 0; side < 2; side++) for (var t = 0; t < 4; t++) {
                var sg = side ? -1 : 1, nx = nrm[0] * sg, ny = nrm[1] * sg, off = (28 + 24 * t) * mm
                var dp = P[0] * nx + P[1] * ny, dq = Q[0] * nx + Q[1] * ny, far = Math.max(dp, dq) + off
                var A = [P[0] + nx * (far - dp), P[1] + ny * (far - dp)], B = [Q[0] + nx * (far - dq), Q[1] + ny * (far - dq)]
                var a = px(A), b = px(B), len = Math.hypot(b.x - a.x, b.y - a.y)
                if (len < 1e-3) continue
                var ux = (b.x - a.x) / len, uy = (b.y - a.y) / len, ext = Math.abs(ux) * w / 2 + Math.abs(uy) * h / 2
                var inside = len >= 2 * ext + 22, tx = inside ? (a.x + b.x) / 2 : b.x + ux * (ext + 13), ty = inside ? (a.y + b.y) / 2 : b.y + uy * (ext + 13)
                var g = 4 * mm, o = 7 * mm
                var w1a = px([P[0] + nx * g, P[1] + ny * g]), w1b = px([A[0] + nx * o, A[1] + ny * o]), w2a = px([Q[0] + nx * g, Q[1] + ny * g]), w2b = px([B[0] + nx * o, B[1] + ny * o])
                var c = { x: tx, y: ty, r: { x: tx - w / 2 - 2, y: ty - h / 2 - 2, w: w + 4, h: h + 4 },
                          lines: [[w1a.x, w1a.y, w1b.x, w1b.y], [w2a.x, w2a.y, w2b.x, w2b.y],
                                  inside ? [a.x, a.y, b.x, b.y] : [a.x - ux * 14, a.y - uy * 14, tx, ty]],
                          arrows: inside ? [[a.x, a.y, -ux, -uy], [b.x, b.y, ux, uy]] : [[a.x, a.y, ux, uy], [b.x, b.y, -ux, -uy]] }
                if (!first) first = c
                if (!seen && inView(c.r)) seen = c
                if (!clear && inView(c.r) && !so._hit(c.r, rects)) clear = c
                if (free(c.r)) { keep(ci, c); return }
            }
            // clear of the tags in sight, else any seat in sight, else the nearest
            if (clear || seen || first) keep(ci, clear || seen || first)
        }
        // a diameter or a radius: a leader through the centre, its arrow on the curve, the value beyond it
        function round(ci, k, C, r, dia, mid) {
            var w = tagW(k), h = 22, first = null, turns = [0, 1, -1, 2, -2, 3]
            for (var t = 0; t < turns.length; t++) {
                var an = mid + turns[t] * Math.PI / 4, dx = Math.cos(an), dy = Math.sin(an)
                var P2 = px([C[0] + r * dx, C[1] + r * dy]), P1 = px(dia ? [C[0] - r * dx, C[1] - r * dy] : C)
                var len = Math.hypot(P2.x - P1.x, P2.y - P1.y)
                if (len < 1e-3) continue
                var ux = (P2.x - P1.x) / len, uy = (P2.y - P1.y) / len, ext = Math.abs(ux) * w / 2 + Math.abs(uy) * h / 2
                var tx = P2.x + ux * (ext + 16), ty = P2.y + uy * (ext + 16)
                var c = { x: tx, y: ty, r: { x: tx - w / 2 - 2, y: ty - h / 2 - 2, w: w + 4, h: h + 4 }, lines: [[P1.x, P1.y, tx, ty]],
                          arrows: dia ? [[P1.x, P1.y, -ux, -uy], [P2.x, P2.y, ux, uy]] : [[P2.x, P2.y, ux, uy]] }
                if (!first) first = c
                if (!so._hit(c.r, rects)) { keep(ci, c); return }
            }
            if (first) keep(ci, first)
        }
        for (i = 0; i < sk.constraints.length; i++) {
            var k = sk.constraints[i]
            if (k.value === undefined) continue
            var e = k.e && k.e.length === 1 && !(k.p && k.p.length) ? sk.entities[k.e[0]] : null
            if (e && e.k === "line" && k.k === "length") {
                var P = sk.points[e.p[0]], Q = sk.points[e.p[1]], ll = Math.max(1e-9, Math.hypot(Q[0] - P[0], Q[1] - P[1]))
                var nn = [-(Q[1] - P[1]) / ll, (Q[0] - P[0]) / ll]
                if (((P[0] + Q[0]) / 2 - cx) * nn[0] + ((P[1] + Q[1]) / 2 - cy) * nn[1] < 0) nn = [-nn[0], -nn[1]]
                linear(i, k, P, Q, nn)
            } else if (e && e.k === "circle") round(i, k, sk.points[e.p[0]], e.r, true, Math.PI / 4)
            else if (e && e.k === "arc") { var ar = arcOf(e); round(i, k, ar.c, ar.r, false, (ar.a0 + ar.a1) / 2) }
            else if (k.p && k.p.length === 2 && !(k.e && k.e.length) && sk.points[k.p[0]] && sk.points[k.p[1]] && (k.k === "distance" || k.k === "hdist" || k.k === "vdist")) {
                var P3 = sk.points[k.p[0]], Q3 = sk.points[k.p[1]], l3 = Math.max(1e-9, Math.hypot(Q3[0] - P3[0], Q3[1] - P3[1]))
                var n3 = k.k === "hdist" ? [0, 1] : k.k === "vdist" ? [1, 0] : [-(Q3[1] - P3[1]) / l3, (Q3[0] - P3[0]) / l3]
                if (((P3[0] + Q3[0]) / 2 - cx) * n3[0] + ((P3[1] + Q3[1]) / 2 - cy) * n3[1] < 0) n3 = [-n3[0], -n3[1]]
                linear(i, k, P3, Q3, n3)
            } else {
                var at = conAt(k), w0 = tagW(k)
                if (at) { L.dims[i] = { x: at.x, y: at.y }; rects.push({ x: at.x - w0 / 2 - 2, y: at.y - 13, w: w0 + 4, h: 26 }) }
            }
        }
        // the symbols: beside what they hold, on the outer side first, clear of the lines, the tags and each other
        // Greedy, one symbol at a time, each at the cheapest seat round what it holds: a seat that covers nothing
        // (no line, tag, pill or symbol) costs its distance from the anchor, more on the profile's inner side and
        // inside the view's edge; when every seat covers something, the one that covers least (area of tags and
        // symbols, then lines crossed). A small profile has few free seats, so the rings reach further out.
        var cpx = px([cx, cy]), vw = so.width, vh = so.height
        function overlap(r) {
            var a = 0
            for (var q = 0; q < rects.length; q++) { var o = rects[q], ix = Math.min(r.x + r.w, o.x + o.w) - Math.max(r.x, o.x), iy = Math.min(r.y + r.h, o.y + o.h) - Math.max(r.y, o.y)
                if (ix > 0 && iy > 0) a += ix * iy }
            return a
        }
        function seat(kind, cands, ax, ay) {
            var best = null, bestC = Infinity, least = null, leastC = Infinity
            var ix = cpx.x - ax, iy = cpx.y - ay, il = Math.max(1e-6, Math.hypot(ix, iy))
            for (var t = 0; t < cands.length; t++) {
                var x = cands[t][0], y = cands[t][1], r = { x: x - 11, y: y - 11, w: 22, h: 22 }
                var d = Math.hypot(x - ax, y - ay), inward = ((x - ax) * ix + (y - ay) * iy) / il
                var edge = x < 14 || y < 14 || x > vw - 14 || y > vh - 14 ? 400 : 0
                var cost = d + Math.max(0, inward) * 0.8 + edge
                if (free(r)) { if (cost < bestC) { bestC = cost; best = cands[t] } continue }
                var cover = overlap(r) * 4 + (so._cuts(r, segs) ? 300 : 0) + cost
                if (cover < leastC) { leastC = cover; least = cands[t] }
            }
            var pick = best || least || cands[0]
            rects.push({ x: pick[0] - 11, y: pick[1] - 11, w: 22, h: 22 })
            L.glyphs.push({ x: pick[0], y: pick[1], kind: kind, ax: ax, ay: ay })
        }
        function around(q) {
            var out = []
            for (var d = 0; d < 6; d++) for (var t = 0; t < 16; t++) {
                var an = t * Math.PI / 8 + (d % 2) * Math.PI / 16, rr = 16 + 12 * d
                out.push([q.x + Math.cos(an) * rr, q.y + Math.sin(an) * rr]) }
            return out
        }
        for (i = 0; i < sk.constraints.length; i++) {
            var c2 = sk.constraints[i]
            if (c2.value !== undefined) continue
            if (c2.e && c2.e.length && !(c2.p && c2.p.length)) {
                var m = midOf(c2.e[c2.e.length > 1 ? 1 : 0])
                if (!m) continue
                var cs = [], tx2 = -m.ny, ty2 = m.nx, sh = [0, 1, -1, 2, -2, 3, -3]
                // along the entity on its outer side first, then on the inner side, then round its middle
                for (var d2 = 0; d2 < 6; d2++) for (var s2 = 0; s2 < sh.length; s2++) for (var side2 = 1; side2 >= -1; side2 -= 2)
                    cs.push([m.x + side2 * m.nx * (16 + 12 * d2) + tx2 * 23 * sh[s2], m.y + side2 * m.ny * (16 + 12 * d2) + ty2 * 23 * sh[s2]])
                seat(c2.k, cs.concat(around(Qt.point(m.x, m.y))), m.x, m.y)
            } else if (c2.p && c2.p.length === 2 && sk.points[c2.p[0]] && sk.points[c2.p[1]]) {
                var pa = px(sk.points[c2.p[0]]), pb = px(sk.points[c2.p[1]])
                seat(c2.k, around(Qt.point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)), (pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
            } else if (c2.p && c2.p.length && sk.points[c2.p[0]]) { var pc = px(sk.points[c2.p[0]]); seat(c2.k, around(pc), pc.x, pc.y) }
        }
        for (i = 0; i < sk.fixed.length; i++) if (sk.points[sk.fixed[i]]) {
            var qf = px(sk.points[sk.fixed[i]]), cf = around(qf)
            seat("fix", cf, qf.x, qf.y)
        }
        return L
    }

    // ── the ink: the plane, the profile, its points, the constraints as small symbols ──
    Canvas {
        id: ink; anchors.fill: parent; visible: so.on || (so.picking && !!so.hover)
        renderStrategy: Canvas.Cooperative
        function poly(c, pts, h) { for (var i = 0; i < pts.length; i++) { var q = so.px(pts[i], h); if (i) c.lineTo(q.x, q.y); else c.moveTo(q.x, q.y) } }
        function glyph(c, x, y, kind) {        // an 18 px tag with the constraint's symbol
            c.save(); c.shadowBlur = 0; c.shadowColor = "transparent"; c.setLineDash([])
            c.fillStyle = Theme.dark ? "#10262b" : "#e6f4f7"; c.strokeStyle = Theme.alpha(Theme.datum, 0.5); c.lineWidth = 1
            c.beginPath(); c.roundedRect(Math.round(x) - 9.5, Math.round(y) - 9.5, 19, 19, 5, 5); c.fill(); c.stroke()
            c.strokeStyle = Theme.dark ? "#c9f6ff" : Theme.datum; c.lineWidth = 1.4; c.lineCap = "round"
            c.translate(Math.round(x), Math.round(y)); c.beginPath()
            if (kind === "horizontal") { c.moveTo(-4, 0); c.lineTo(4, 0) }
            else if (kind === "vertical") { c.moveTo(0, -4); c.lineTo(0, 4) }
            else if (kind === "parallel") { c.moveTo(-3, 4); c.lineTo(0, -4); c.moveTo(0, 4); c.lineTo(3, -4) }
            else if (kind === "perpendicular") { c.moveTo(-4, 4); c.lineTo(4, 4); c.moveTo(0, 4); c.lineTo(0, -4) }
            else if (kind === "equal") { c.moveTo(-4, -2); c.lineTo(4, -2); c.moveTo(-4, 2); c.lineTo(4, 2) }
            else if (kind === "tangent") { c.arc(0, 1.5, 3, 0, 2 * Math.PI); c.moveTo(-4.5, -3.5); c.lineTo(4.5, -3.5) }
            else if (kind === "coincident") { c.arc(0, 0, 3.4, 0, 2 * Math.PI); c.moveTo(0.6, 0); c.arc(0, 0, 0.6, 0, 2 * Math.PI) }
            else if (kind === "midpoint") { c.moveTo(-4.5, 3); c.lineTo(4.5, 3); c.moveTo(0, 0.5); c.lineTo(-2.6, -3.6); c.lineTo(2.6, -3.6); c.closePath() }
            else if (kind === "symmetric") { c.moveTo(0, -4.5); c.lineTo(0, 4.5); c.moveTo(-3.5, -2.5); c.lineTo(-3.5, 2.5); c.moveTo(3.5, -2.5); c.lineTo(3.5, 2.5) }
            else if (kind === "on") { c.moveTo(-4.5, 3); c.lineTo(4.5, -3); c.moveTo(1.4, 0); c.arc(0, 0, 1.4, 0, 2 * Math.PI) }
            else { c.rect(-3.5, -1, 7, 5); c.moveTo(-2, -1); c.lineTo(-2, -2.6); c.arc(0, -2.6, 2, Math.PI, 0); c.lineTo(2, -1) }       // fix: a lock
            c.stroke(); c.restore()
        }
        onPaint: {
            var c = getContext("2d"); c.reset()
            if (!so.vp) return
            c.lineCap = "round"; c.lineJoin = "round"
            if (!so.on) {                      // waiting for a face: the one under the pointer, lit
                var hf = so.picking ? so.hover : null
                if (!hf) return
                var hp = function (pts) { for (var t = 0; t < pts.length; t++) { var z = so.pxF(hf.f, pts[t]); if (t) c.lineTo(z.x, z.y); else c.moveTo(z.x, z.y) } }
                c.beginPath(); hf.loops.forEach(function (lp) { hp(lp); c.closePath() })
                c.fillStyle = Theme.alpha(Theme.datum, Theme.dark ? 0.2 : 0.16); c.fill("evenodd")
                c.beginPath(); hf.outline.forEach(function (pl) { hp(pl) })
                c.strokeStyle = Theme.alpha(Theme.datum, 0.9); c.lineWidth = 1.5; c.stroke()
                return
            }
            var acc = Theme.datum, i, q, e, lit = Theme.dark ? 0.55 : 0.0
            // the face it lies on (tinted inside its own outline, holes left open), or the datum plane as a faint grid
            var out = so.props.outline || []
            if (out.length) {
                c.beginPath(); so.faceLoops.forEach(function (lp) { ink.poly(c, lp); c.closePath() })
                c.fillStyle = Theme.alpha(acc, Theme.dark ? 0.09 : 0.08); c.fill("evenodd")
                c.beginPath(); out.forEach(function (pl) { ink.poly(c, pl) })
                c.strokeStyle = Theme.alpha(acc, 0.6); c.lineWidth = 1; c.stroke()
            } else {
                var R = so.vp.model ? Math.ceil(so.vp.radius(so.vp.bounds) / 10) * 10 : 60, st = 10
                c.lineWidth = 1; c.strokeStyle = Theme.alpha(acc, Theme.dark ? 0.11 : 0.16); c.beginPath()
                for (var g = -R; g <= R + 0.01; g += st) { ink.poly(c, [[g, -R], [g, R]]); ink.poly(c, [[-R, g], [R, g]]) }
                c.stroke()
                c.beginPath(); ink.poly(c, [[-R, -R], [R, -R], [R, R], [-R, R], [-R, -R]]); c.fillStyle = Theme.alpha(acc, 0.04); c.fill()
                c.strokeStyle = Theme.alpha(acc, 0.4); c.stroke()
                c.setLineDash([7, 4, 1.5, 4]); c.strokeStyle = Theme.alpha(acc, 0.55); c.beginPath(); ink.poly(c, [[-R, 0], [R, 0]]); ink.poly(c, [[0, -R], [0, R]]); c.stroke(); c.setLineDash([])
            }
            // a closed profile is filled; with a depth it is also drawn where the extrusion will end
            var loops = so.sol && so.sol.ok && so.sol.closed ? so.sol.polygons || [] : []
            if (loops.length) { c.beginPath(); loops.forEach(function (lp) { ink.poly(c, lp); c.closePath() }); c.fillStyle = Theme.alpha(acc, 0.2); c.fill("evenodd") }
            if (loops.length && so.kind !== "revolve" && so.mode !== "edit" && so.depthMm > 0 && !(so.draft && so.draft.preview.ok)) {
                // (looking straight at the plane it lies exactly under the profile: nothing more to draw)
                var h = so.kind === "cut" ? -so.depthMm : so.depthMm, f0 = so.px(loops[0][0]), f1 = so.px(loops[0][0], h)
                if (Math.hypot(f1.x - f0.x, f1.y - f0.y) > 1.5) {
                    c.strokeStyle = Theme.alpha(acc, 0.55); c.lineWidth = 1; c.setLineDash([4, 3]); c.beginPath()
                    loops.forEach(function (lp) { ink.poly(c, lp, h); c.closePath()
                        var stp = Math.max(1, Math.round(lp.length / 12))
                        for (var j = 0; j < lp.length; j += stp) { var a = so.px(lp[j]), b = so.px(lp[j], h); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y) } })
                    c.stroke(); c.setLineDash([])
                }
            }
            // a revolve: the outline of the body the profile sweeps, dashed: its other half across the axis, and the
            // circles its corners travel (seen as lines when looking straight at the plane)
            if (loops.length && so.kind === "revolve" && so.mode !== "edit" && so.axis >= 0 && !(so.draft && so.draft.preview.ok)) {
                var ax = so.sk.entities[so.axis], A0 = so.sk.points[ax.p[0]], A1 = so.sk.points[ax.p[1]], al = Math.max(1e-9, Math.hypot(A1[0] - A0[0], A1[1] - A0[1]))
                var ux = (A1[0] - A0[0]) / al, uy = (A1[1] - A0[1]) / al
                var foot = function (p) { var t = (p[0] - A0[0]) * ux + (p[1] - A0[1]) * uy; return [A0[0] + ux * t, A0[1] + uy * t] }
                c.strokeStyle = Theme.alpha(acc, 0.6); c.lineWidth = 1; c.setLineDash([5, 4]); c.beginPath()
                loops.forEach(function (lp) {
                    ink.poly(c, lp.map(function (p) { var m = foot(p); return [2 * m[0] - p[0], 2 * m[1] - p[1]] })); c.closePath()
                    // the circles its farthest and its nearest point travel
                    var far = null, near = null
                    lp.forEach(function (p) { var m = foot(p), r = Math.hypot(p[0] - m[0], p[1] - m[1]); if (!far || r > far.r) far = { m: m, r: r }; if (!near || r < near.r) near = { m: m, r: r } })
                    ;[far, near].forEach(function (g, gi) {
                        if (!g || g.r < 0.2 || (gi === 1 && far.r - near.r < 0.2)) return
                        for (var t = 0; t <= 64; t++) {
                            var an = 2 * Math.PI * t / 64, z = so.px([g.m[0] - uy * g.r * Math.cos(an), g.m[1] + ux * g.r * Math.cos(an)], g.r * Math.sin(an))
                            if (t) c.lineTo(z.x, z.y); else c.moveTo(z.x, z.y)
                        }
                    })
                })
                c.stroke()
                // the axis itself: a centre line, past both ends
                c.setLineDash([9, 3, 2, 3]); c.strokeStyle = Theme.alpha(acc, 0.75); c.beginPath()
                ink.poly(c, [[A0[0] - ux * al * 0.25, A0[1] - uy * al * 0.25], [A1[0] + ux * al * 0.25, A1[1] + uy * al * 0.25]]); c.stroke(); c.setLineDash([])
            }
            // the entities, lit
            for (i = 0; i < so.sk.entities.length; i++) {
                e = so.sk.entities[i]
                var sel = so.selE.indexOf(i) >= 0
                // the line itself is drawn in the 3D view, in the part's depth (Viewport.inkLines). Here: the same line
                // faintly, which is all that shows of it behind the part, and its light around it
                c.lineWidth = e.construction ? 1.4 : sel ? 2 : 1.4; c.strokeStyle = e.construction ? Theme.alpha(acc, 0.8) : Theme.alpha(sel ? Theme.datumHi : acc, 0.34)
                c.shadowColor = Theme.alpha(acc, lit); c.shadowBlur = lit > 0 ? 6 : 0
                if (e.construction) c.setLineDash([6, 4])
                c.beginPath(); ink.poly(c, so.sample(e)); c.stroke(); c.setLineDash([])
            }
            c.shadowBlur = 0; c.shadowColor = "transparent"
            // what is being drawn
            c.strokeStyle = Theme.alpha(acc, 0.7); c.lineWidth = 1.4
            var rb = so.snap ? so.snap.p : so.rubber
            if (rb && so.chain.length && so.tool === "line") { c.beginPath(); ink.poly(c, [so.sk.points[so.chain[0]], rb]); c.stroke() }
            if (rb && so.tool === "arc" && so.chain.length === 1) { c.setLineDash([3, 3]); c.beginPath(); ink.poly(c, [so.sk.points[so.chain[0]], rb]); c.stroke(); c.setLineDash([]) }
            if (rb && so.tool === "arc" && so.chain.length === 2) { c.beginPath(); ink.poly(c, so.sample({ k: "arc", p: [so.chain[0], so.chain[1], -1], _end: rb })); c.stroke() }
            if (rb && so.from && so.tool === "rect") { c.beginPath(); ink.poly(c, [so.from, [rb[0], so.from[1]], rb, [so.from[0], rb[1]], so.from]); c.stroke() }
            if (rb && so.from && so.tool === "circle") { var cr = Math.hypot(rb[0] - so.from[0], rb[1] - so.from[1]); c.beginPath(); ink.poly(c, so.ring(so.from, cr)); c.stroke() }
            // the points
            for (i = 0; i < so.sk.points.length; i++) {
                q = so.px(so.sk.points[i]); var ps = so.selP.indexOf(i) >= 0
                c.beginPath(); c.arc(q.x, q.y, ps ? 4.2 : 3.2, 0, 2 * Math.PI); c.fillStyle = ps ? acc : Theme.plate; c.fill()
                c.lineWidth = 1.6; c.strokeStyle = acc; c.stroke()
            }
            // the dimensions, as on a drawing: witness lines, the dimension line, its arrows (the value is a tag, below)
            var L = so.lay
            c.strokeStyle = Theme.alpha(acc, Theme.dark ? 0.62 : 0.75); c.lineWidth = 1; c.lineCap = "butt"; c.beginPath()
            for (i = 0; i < L.lines.length; i++) { var ln = L.lines[i]; c.moveTo(Math.round(ln[0]) + 0.5, Math.round(ln[1]) + 0.5); c.lineTo(Math.round(ln[2]) + 0.5, Math.round(ln[3]) + 0.5) }
            c.stroke(); c.lineCap = "round"
            c.fillStyle = Theme.dark ? "#9fe9f7" : acc
            for (i = 0; i < L.arrows.length; i++) {
                var ar = L.arrows[i], tx = ar[0], ty = ar[1], dx = ar[2], dy = ar[3]
                c.beginPath(); c.moveTo(tx, ty); c.lineTo(tx - dx * 8 - dy * 2.6, ty - dy * 8 + dx * 2.6); c.lineTo(tx - dx * 8 + dy * 2.6, ty - dy * 8 - dx * 2.6); c.closePath(); c.fill()
            }
            // the constraints, each a small symbol beside what it holds
            c.strokeStyle = Theme.alpha(acc, 0.42); c.lineWidth = 1; c.beginPath()
            for (i = 0; i < L.glyphs.length; i++) { var gl = L.glyphs[i]; if (Math.hypot(gl.x - gl.ax, gl.y - gl.ay) > 27) { c.moveTo(gl.ax, gl.ay); c.lineTo(gl.x, gl.y) } }
            c.stroke()
            for (i = 0; i < L.glyphs.length; i++) ink.glyph(c, L.glyphs[i].x, L.glyphs[i].y, L.glyphs[i].kind)
            // the snap under the pointer
            if (so.snap && so.snap.kind !== "grid" && so.tool !== "select") {
                q = so.px(so.snap.p); c.strokeStyle = Theme.dark ? "#ffffff" : "#000000"; c.lineWidth = 1.2; c.beginPath()
                if (so.snap.kind === "mid") { c.moveTo(q.x, q.y - 6); c.lineTo(q.x + 6, q.y + 5); c.lineTo(q.x - 6, q.y + 5); c.closePath() }
                else c.rect(q.x - 5.5, q.y - 5.5, 11, 11)
                c.stroke()
            }
        }
    }
    function ring(c, r) { var out = []; for (var i = 0; i <= 48; i++) { var t = 2 * Math.PI * i / 48; out.push([c[0] + r * Math.cos(t), c[1] + r * Math.sin(t)]) } return out }
    function midOf(i) {                        // the middle of an entity, on the screen, and the unit normal of it there
        var e = sk.entities[i]
        if (!e) return null
        var pts = sample(e), a = px(pts[Math.floor((pts.length - 1) / 2)]), b = px(pts[Math.floor((pts.length - 1) / 2) + 1])
        var m = e.k === "line" ? Qt.point((a.x + b.x) / 2, (a.y + b.y) / 2) : a, L = Math.max(1e-6, Math.hypot(b.x - a.x, b.y - a.y))
        var nx = -(b.y - a.y) / L, ny = (b.x - a.x) / L, cx = 0, cy = 0, n = sk.points.length
        for (var j = 0; j < n; j++) { cx += sk.points[j][0] / n; cy += sk.points[j][1] / n }
        var c = px([cx, cy])
        if ((m.x - c.x) * nx + (m.y - c.y) * ny < 0) { nx = -nx; ny = -ny }
        return { x: m.x, y: m.y, nx: nx, ny: ny }
    }
    function conAt(k) {                        // where a constraint's symbol or a dimension's value sits
        var m
        if (k.e && k.e.length && !(k.p && k.p.length)) { m = midOf(k.e[k.e.length > 1 && k.value === undefined ? 1 : 0]); return m ? Qt.point(m.x - m.nx * 15, m.y - m.ny * 15) : null }
        if (k.p && k.p.length === 2 && sk.points[k.p[0]] && sk.points[k.p[1]]) { var a = px(sk.points[k.p[0]]), b = px(sk.points[k.p[1]]); return Qt.point((a.x + b.x) / 2 + 14, (a.y + b.y) / 2 - 14) }
        if (k.p && k.p.length && sk.points[k.p[0]]) { var q = px(sk.points[k.p[0]]); return Qt.point(q.x + 14, q.y - 14) }
        return null
    }
    readonly property var faceLoops: props && props.outline ? loopsOf(props.outline) : []
    function dimSeat(j) { var d = lay.dims[j]; if (d) return Qt.point(d.x, d.y); var k = sk.constraints[j]; return k ? dimAt(k) : null }
    function dimAt(k) {
        var e = k.e && k.e.length ? sk.entities[k.e[0]] : null
        if (e && k.e.length === 1 && e.k !== "line") { var c0 = sk.points[e.p[0]], r = e.k === "circle" ? e.r : arcOf(e).r, t = e.k === "circle" ? Math.PI / 4 : (arcOf(e).a0 + arcOf(e).a1) / 2
            var q = px([c0[0] + r * Math.cos(t), c0[1] + r * Math.sin(t)]), cc = px(c0), L = Math.max(1e-6, Math.hypot(q.x - cc.x, q.y - cc.y)); return Qt.point(q.x + (q.x - cc.x) / L * 26, q.y + (q.y - cc.y) / L * 16) }
        if (e && k.e.length === 1) { var m = midOf(k.e[0]); return Qt.point(m.x + m.nx * 22, m.y + m.ny * 22) }
        return conAt(k)
    }
    function dimText(k) { var v = F.fmt(k.value, 1); return k.k === "diameter" ? "Ø" + v : k.k === "radius" ? "R " + v : k.k === "angle" ? v + "°" : v }

    // ── the dimensions: mono values beside what they drive; a click types a new one in place ──
    Repeater {
        model: so.on ? so.sk.constraints : []
        Rectangle {
            id: tag
            required property var modelData
            required property int index
            readonly property bool dim: modelData.value !== undefined
            readonly property bool editing: so.editing === index
            readonly property point at: { so.lay; return dim ? so.dimSeat(index) || Qt.point(-1e5, 0) : Qt.point(-1e5, 0) }
            objectName: "sketchDim-" + index
            visible: dim && !editing && at.x > -1e4
            x: Math.round(at.x - width / 2); y: Math.round(at.y - height / 2); width: Math.ceil(tt.implicitWidth) + 16; height: 22; radius: 11
            color: Theme.dark ? "#10262b" : "#e6f4f7"; border.color: Theme.alpha(Theme.datum, tm.containsMouse ? 0.9 : 0.5)
            Txt { id: tt; anchors.centerIn: parent; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; color: Theme.dark ? "#c9f6ff" : Theme.datum; text: so.dimText(tag.modelData) }
            MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.IBeamCursor; onClicked: so.edit(tag.index) }
        }
    }
    Rectangle {
        id: edBox; objectName: "sketchDimEdit"
        readonly property var k: so.editing >= 0 ? so.sk.constraints[so.editing] : null
        readonly property point at: { so.lay; return k ? so.dimSeat(so.editing) || Qt.point(0, 0) : Qt.point(0, 0) }
        visible: !!k
        x: Math.round(at.x - width / 2); y: Math.round(at.y - height / 2); width: Math.ceil(er.implicitWidth) + 22; height: 28; radius: 14; z: 3
        color: Theme.plate; border.color: Theme.datum; border.width: 1
        Glow { blur: 16; strength: Theme.dark ? 0.5 : 0.25 }
        Rectangle { anchors.fill: parent; anchors.margins: -3; radius: 17; color: "transparent"; border.width: 3; border.color: Theme.alpha(Theme.datum, 0.22) }
        Row { id: er; anchors.centerIn: parent; spacing: 5
            TextInput { id: ed; objectName: "sketchDimInput"; width: Math.max(26, contentWidth + 2); font.family: Theme.mono; font.pixelSize: 12; font.weight: Theme.wMedium; color: Theme.ink
                selectionColor: Theme.alpha(Theme.datum, 0.35); selectedTextColor: Theme.ink; selectByMouse: true
                validator: DoubleValidator { bottom: 0; decimals: 3; notation: DoubleValidator.StandardNotation; locale: "C" }
                cursorDelegate: Rectangle { width: 1.5; color: Theme.datum; visible: ed.activeFocus }
                Keys.onReturnPressed: accept(); Keys.onEnterPressed: accept()
                Keys.onEscapePressed: { so.editing = -1; area.forceActiveFocus() }
                Keys.onDeletePressed: function (ev) { if (text === "") so.removeCon(so.editing); else ev.accepted = false }
                function accept() { var j = so.editing, v = Number(text.replace(",", ".")); so.editing = -1; so.setValue(j, v); area.forceActiveFocus() }
                onActiveFocusChanged: if (!activeFocus && so.editing >= 0) so.editing = -1 }
            Txt { mono: true; font.pixelSize: 12; tone: 3; text: edBox.k && edBox.k.k === "angle" ? "°" : "mm"; anchors.verticalCenter: parent.verticalCenter } }
    }

    // ── the pointer on the plane (Alt-drag, the right button and the wheel still move the view) ──
    MouseArea {
        id: area; objectName: "sketchArea"; anchors.fill: parent; visible: so.busyHere; hoverEnabled: so.busyHere; acceptedButtons: Qt.LeftButton
        cursorShape: so.picking || so.tool !== "select" ? Qt.CrossCursor : Qt.ArrowCursor
        property bool moved: false
        onPressed: function (m) {
            if (m.modifiers & Qt.AltModifier) { m.accepted = false; return }
            forceActiveFocus(); moved = false
            if (so.picking) { so.pickAt(m.x, m.y); return }
            if (so.editing >= 0) so.editing = -1
            var sn = so.snapAt(m.x, m.y, -1)
            if (!sn) return
            var s2, i
            if (so.tool === "select" || so.tool === "dim") {
                var np = so.nearPoint(m.x, m.y), ne = np >= 0 ? -1 : so.nearEntity(m.x, m.y), add = !!(m.modifiers & Qt.ShiftModifier)
                if (so.tool === "dim") { if (ne >= 0) { so.selE = [ne]; so.selP = []; so.dimension(ne) } return }
                so.dragPt = np
                if (np >= 0) so.selP = add ? (so.selP.indexOf(np) >= 0 ? so.selP.filter(function (x) { return x !== np }) : so.selP.concat([np])) : [np]
                else if (!add) so.selP = []
                if (ne >= 0) so.selE = add ? (so.selE.indexOf(ne) >= 0 ? so.selE.filter(function (x) { return x !== ne }) : so.selE.concat([ne])) : [ne]
                else if (!add) so.selE = []
                return
            }
            if (so.tool === "rect" || so.tool === "circle") { so.from = sn.p; so.rubber = sn.p; return }
            s2 = so.clone(so.sk); i = so.place(s2, sn)
            if (so.tool === "line") {
                // a point; a line from the last one; a point that already starts a line closes the loop and ends the chain
                if (so.chain.length) { var closes = sn.kind === "point" && sn.i !== so.chain[0] && so.isChainStart(sn.i); so.addLine(s2, so.chain[0], i); so.chain = closes ? [] : [i] }
                else so.chain = [i]
                so.set(s2); return
            }
            // arc: its centre, where it starts, where it ends (counter-clockwise)
            if (so.chain.length < 2) { so.chain = so.chain.concat([i]); so.sk = s2; return }
            if (i !== so.chain[1]) { s2.entities.push({ k: "arc", p: [so.chain[0], so.chain[1], i] }); so.chain = []; so.set(s2) }
        }
        onPositionChanged: function (m) {
            if (so.picking) { so._hp = Qt.point(m.x, m.y); if (!hv.running) hv.start(); return }
            if (!so.on) return
            moved = true
            if (so.tool === "select" && pressed && so.dragPt >= 0) {
                var f = so.mmAt(m.x, m.y); if (!f) return
                var s2 = so.clone(so.sk); s2.points[so.dragPt] = f; so.set(s2); return
            }
            var sn = so.snapAt(m.x, m.y, -1)
            so.snap = sn; so.rubber = sn ? sn.p : null
        }
        onReleased: function (m) {
            if ((so.tool === "rect" || so.tool === "circle") && so.from) {
                var a = so.from, sn = so.snapAt(m.x, m.y, -1), at = sn ? sn.p : a, s2 = so.clone(so.sk)
                so.from = null
                if (so.tool === "rect" && Math.abs(at[0] - a[0]) >= so.grid && Math.abs(at[1] - a[1]) >= so.grid) {
                    var idx = [[a[0], a[1]], [at[0], a[1]], [at[0], at[1]], [a[0], at[1]]].map(function (p) { return so.pointIn(s2, p) })
                    for (var q = 0; q < 4; q++) so.addLine(s2, idx[q], idx[(q + 1) % 4])
                    so.set(s2)
                } else if (so.tool === "circle") {
                    var rad = Math.round(Math.hypot(at[0] - a[0], at[1] - a[1]) / (so.grid / 2)) * (so.grid / 2)
                    if (rad >= 0.5) { var ci = so.pointIn(s2, a); s2.entities.push({ k: "circle", p: [ci], r: rad }); so.set(s2) }
                }
            }
            so.dragPt = -1
        }
        onExited: { so.snap = null; if (so.picking) { hv.stop(); so._hn++; so.hover = null } }
        Keys.onEscapePressed: so.leave()
        Keys.onDeletePressed: so.removeSel()
        Keys.onReturnPressed: so.commit()
        Keys.onEnterPressed: so.commit()
        Keys.onPressed: function (ev) {
            if (ev.modifiers & (Qt.ControlModifier | Qt.MetaModifier) || !so.on) return
            if (ev.key === Qt.Key_Backspace) { so.removeSel(); ev.accepted = true; return }
            var t = { "L": "line", "A": "arc", "C": "circle", "R": "rect", "V": "select", "D": "dim" }[ev.text.toUpperCase()]
            if (t) { so.setTool(t); ev.accepted = true }
        }
    }
    function setTool(t) { tool = t; chain = []; from = null; rubber = null; if (t !== "select") { selE = []; selP = [] } area.forceActiveFocus(); ink.requestPaint() }
    function pickAt(x, y) {                    // the flat face under the pointer becomes the sketch's plane
        var hit = vp.hitAt(x, y)
        if (!hit) { err = "Nothing there. Click a flat face of the part, or choose a plane."; return }
        err = ""
        if (onFace(hover, x, y)) {             // the lit face: no second question. Its frame moves to the clicked point, the sketch's origin
            var f0 = hover.f, r0 = Qt.vector3d(hit.shown[0], hit.shown[1], hit.shown[2]).minus(f0.o), dx = rnd(r0.dotProduct(f0.x), 4), dy = rnd(r0.dotProduct(f0.y), 4)
            var o2 = f0.o.plus(f0.x.times(dx)).plus(f0.y.times(dy)), pl = clone(hover.plane)
            pl.origin = [rnd(o2.x, 4), rnd(o2.y, 4), rnd(o2.z, 4)]
            begin({ mode: "add", plane: pl, outline: hover.outline.map(function (e) { return e.map(function (p) { return [rnd(p[0] - dx, 4), rnd(p[1] - dy, 4)] }) }), kind: kind })
            return
        }
        Store.ppost("/sketch_plane", { at: hit.at }).then(function (r) {
            if (so.picking) so.begin({ mode: "add", plane: r.plane, outline: r.outline, kind: so.kind })
        }, function (e) { so.err = (e.message || "A sketch goes on a flat face.") + (e.hint ? " " + e.hint : "") })
    }
    function onDatum(d) { begin({ mode: mode === "new" && on ? "new" : "add", plane: { datum: d, offset: 0 }, kind: kind }) }

    // ── the tool capsule: the sketch's tools, what the selection allows, and what is left free ──
    // It is one line at any width. When the stage is narrow the labels shorten (Rect, Dim; the free count without its
    // word), and what the selection allows goes behind "More" as far as it does not fit.
    FontMetrics { id: fmS; font.family: Theme.sans; font.pixelSize: 13; font.weight: Theme.wMedium }
    FontMetrics { id: fmM; font.family: Theme.mono; font.pixelSize: 12; font.weight: Theme.wMedium }
    readonly property var tools: [{ id: "select", text: "Select", key: "V", tip: "Select, drag a point. Shift adds to the selection" }, { id: "line", text: "Line", key: "L", tip: "Click points; a click on the first one closes the profile" },
                                  { id: "arc", text: "Arc", key: "A", tip: "Its centre, where it starts, where it ends (counter-clockwise)" }, { id: "circle", text: "Circle", key: "C", tip: "Drag from the centre" },
                                  { id: "rect", text: "Rectangle", short: "Rect", key: "R", tip: "Rectangle: drag from corner to corner" }, { id: "dim", text: "Dimension", short: "Dim", key: "D", tip: "Dimension: click a line, circle or arc and type its size" }]
    readonly property string dofLong: !sol ? "…" : !sol.ok ? "does not solve" : !sk.entities.length ? "nothing drawn" : sol.fully_constrained ? "0 free · constrained" : sol.dof + " free"
    readonly property string dofShort: !sol ? "…" : !sol.ok ? "unsolved" : !sk.entities.length ? "empty" : sol.fully_constrained ? "0 free" : sol.dof + " free"
    function chipW(t, icon) { return Math.ceil(fmS.advanceWidth(t)) + 22 + (icon ? 20 : 0) + 4 }
    readonly property var fit: {               // { compact, shown: how many of the offers stand in the capsule }
        var room = cap.room, n = offers.length, i
        function total(compact, k) {
            var w = 0
            for (i = 0; i < tools.length; i++) w += chipW(compact && tools[i].short ? tools[i].short : tools[i].text, false)
            if (n) w += 13
            for (i = 0; i < k; i++) w += chipW(offers[i].text, !!offers[i].dim)
            if (k < n) w += chipW("More", true)
            return w + Math.ceil(fmM.advanceWidth(compact ? dofShort : dofLong)) + 27
        }
        if (!on || mode === "new" && !sk.entities.length) return { compact: false, shown: n }
        if (total(false, n) <= room) return { compact: false, shown: n }
        for (var k = n; k > 0; k--) if (total(true, k) <= room) return { compact: true, shown: k }
        return { compact: true, shown: 0 }
    }
    ToolCapsule {
        id: cap; objectName: "sketchCapsule"; source: so.source; visible: so.busyHere; z: 5
        x: so.capX; y: so.capY; maxWidth: so.capMax; wrap: false; titleMax: Math.max(72, Math.min(200, so.capMax * 0.26))
        title: so.picking ? ({ extrude: "Extrude", cut: "Cut", revolve: "Revolve" }[so.kind] || "Sketch")
             : so.mode === "edit" ? "Sketch of " + (Store.featureById(so.props.feature) || { label: so.props.feature }).label
             : "Sketch " + F.pad((Store.recipe && so.mode !== "new" ? Store.recipe.features.length : 0) + 1).slice(1)
        Txt { visible: so.picking; height: 28; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; wrapMode: Text.NoWrap
            color: so.err ? Theme.strong(Theme.amber) : Theme.ink2; text: so.err ? so.err : "Click a flat face, or a plane:" }
        Repeater { model: so.picking || (so.on && so.mode === "new" && !so.sk.entities.length) ? ["XY", "XZ", "YZ"] : []
            CapChip { required property string modelData; objectName: "sketchPlane-" + modelData; text: modelData; mono: true
                on: so.on && so.sk.plane.datum === modelData; tip: "The " + modelData + " plane through the origin"; onClicked: so.onDatum(modelData) } }
        Item { visible: so.on && so.mode === "new" && !so.sk.entities.length; width: 9; height: 28; Rectangle { x: 4; y: 6; width: 1; height: 16; color: Theme.rule2 } }
        Repeater { model: so.on ? so.tools : []
            CapChip { required property var modelData; objectName: "sketchTool-" + modelData.id; text: so.fit.compact && modelData.short ? modelData.short : modelData.text; on: so.tool === modelData.id
                tip: modelData.tip + " · " + modelData.key; onClicked: so.setTool(modelData.id) } }
        Item { visible: so.on && so.offers.length > 0; width: 9; height: 28; Rectangle { x: 4; y: 6; width: 1; height: 16; color: Theme.rule2 } }
        Repeater { model: so.on ? so.offers.slice(0, so.fit.shown) : []
            CapChip { required property var modelData; objectName: "sketchOffer-" + modelData.text; text: modelData.text; tip: modelData.tip; tint: Theme.datum
                icon: modelData.dim ? "ruler_dim" : ""; onClicked: modelData.run() } }
        CapChip { id: more; objectName: "sketchMore"; visible: so.on && so.fit.shown < so.offers.length; text: "More"; icon: "ellipsis"; on: moreMenu.opened
            tip: "What else the selection allows"; onClicked: moreMenu.opened ? moreMenu.close() : moreMenu.open()
            PopMenu { id: moreMenu; objectName: "sketchMoreMenu"; y: parent.height + 10; x: Math.min(0, parent.width - width); width: 208
                model: so.offers.slice(so.fit.shown).map(function (o) { return { name: "sketchOffer-" + o.text, text: o.text, icon: o.dim ? "ruler_dim" : "", run: o.run } })
                onClosed: area.forceActiveFocus() } }
        // the degrees of freedom the solver still has: 0 is a profile that can only be what was said
        Item { visible: so.on; objectName: "sketchDof"; height: 28; width: Math.ceil(dofT.implicitWidth) + 25
            readonly property int dof: so.sol && so.sol.ok ? so.sol.dof : -1
            Rectangle { x: 2; y: 6; width: 1; height: 16; color: Theme.rule2 }
            Txt { id: dofT; x: 15; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap
                color: !so.sol || !so.sol.ok ? Theme.strong(Theme.amber) : so.sol.fully_constrained ? Theme.pass : Theme.ink2
                text: so.fit.compact ? so.dofShort : so.dofLong }
            MouseArea { id: dofM; anchors.fill: parent; hoverEnabled: true }
            Tip { show: dofM.containsMouse; below: true; text: "Degrees of freedom the solver still has (computed). At 0 the profile can only be what you said." } }
    }

    // ── the foot of the stage: what to make of the profile, and the way out ──
    Glass {
        id: foot; objectName: "sketchFoot"; source: so.source; visible: so.on; z: 5; radius: 22
        width: Math.round(fr.implicitWidth + 16); height: 44
        x: Math.round(Math.max(so.footL, Math.min(so.footR - width, so.midX - width / 2))); y: Math.round(so.footY - height)
        readonly property string say: so.err ? so.err
            : so.draft && so.draft.preview.ok ? (so.draft.preview.volume_mm3.change >= 0 ? "+" : "−") + F.fmt(Math.abs(so.draft.preview.volume_mm3.change), 1) + " mm³ · computed"
            : !so.sol || !so.sk.entities.length ? "Draw a closed profile"
            : !so.sol.closed ? "Not closed yet"
            : so.kind === "revolve" && so.mode !== "edit" && so.axis < 0 ? "Select the line it turns about"
            : so.kind === "cut" && so.depthMm === 0 ? "Through everything" : so.mode === "edit" ? "Closed profile" : "Enter builds it"
        readonly property bool sayMono: !so.err && !!so.draft && so.draft.preview.ok
        readonly property real sayW: Math.ceil((sayMono ? fmM : fmS).advanceWidth(say)) + 6
        readonly property real restW: 16 + (nameField.visible ? nameField.width + 8 : 0) + (kindSeg.visible ? kindSeg.width + 8 : 0) + (depthField.visible ? depthField.width + 8 : 0)
                                      + cancelBtn.width + 8 + commitBtn.width
        readonly property bool sayIn: restW + sayW + 8 <= so.footR - so.footL
        Row { id: fr; x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Field { id: nameField; objectName: "sketchName"; visible: so.mode === "new"; width: 150; height: 30; placeholder: "Name the design"; text: so.name; onEdited: function (t) { so.name = t }; onAccepted: area.forceActiveFocus() }
            Seg { id: kindSeg; objectName: "sketchKind"; visible: so.mode !== "edit"; anchors.verticalCenter: parent.verticalCenter
                model: so.mode === "new" ? [{ value: "extrude", text: "Extrude" }, { value: "revolve", text: "Revolve" }]
                                         : [{ value: "extrude", text: "Extrude" }, { value: "cut", text: "Cut" }, { value: "revolve", text: "Revolve" }]
                value: so.kind; onPicked: function (v) { so.kind = v; area.forceActiveFocus() } }
            Field { id: depthField; objectName: "sketchDepth"; visible: so.mode !== "edit" && so.kind !== "revolve"; width: 92; height: 30; numeric: true; unit: "mm"
                text: so.depth; onEdited: function (t) { so.depth = t }; onAccepted: area.forceActiveFocus() }
            Txt { objectName: foot.sayIn ? "sketchSay" : ""; visible: foot.sayIn; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; wrapMode: Text.NoWrap
                mono: foot.sayMono; color: so.err ? Theme.strong(Theme.amber) : Theme.ink2; text: foot.say }
            Btn { id: cancelBtn; objectName: "sketchCancel"; small: true; kind: "quiet"; text: "Cancel"; tip: "Leave the sketch. Nothing is saved"; anchors.verticalCenter: parent.verticalCenter; onClicked: so.end() }
            Btn { id: commitBtn; objectName: "sketchCommit"; small: true; kind: "primary"; anchors.verticalCenter: parent.verticalCenter
                icon: so.kind === "cut" ? "scissors" : "cuboid"; busy: so.busy; busyText: "Building…"; enabled: so.ready
                text: so.mode === "edit" ? "Save the sketch" : so.kind === "cut" ? "Cut" : so.kind === "revolve" ? "Revolve" : "Extrude"
                tip: "Writes it into the design's code as one feature, its dimensions as parameters, and builds it"; onClicked: so.commit() } }
    }
    Glass {
        objectName: "sketchSayPill"; source: so.source; visible: so.on && !foot.sayIn; z: 5; radius: 14; height: 28
        width: Math.min(so.footR - so.footL, Math.ceil(sayT.implicitWidth) + 26)
        x: Math.round(Math.max(so.footL, Math.min(so.footR - width, foot.x + foot.width / 2 - width / 2))); y: foot.y - height - 8
        Txt { id: sayT; objectName: foot.sayIn ? "" : "sketchSay"; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.width - 22); font.pixelSize: 12
            wrapMode: Text.NoWrap; elide: Text.ElideRight; mono: foot.sayMono; color: so.err ? Theme.strong(Theme.amber) : Theme.ink2; text: foot.say
            MouseArea { id: sayM; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            Tip { show: sayM.containsMouse && parent.truncated; text: parent.text } }
    }
}
