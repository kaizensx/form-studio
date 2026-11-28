import QtQuick
import QtQuick3D
import FormNative

// A result drawn on the part, in the part's own frame (millimetres, as built). What it draws is the engine's:
//   field   a strength field (form.fea.field/1): the scale per pixel, singular zones hatched, the deformed shape,
//           a mode shape swinging, the load arrows
//   dfm     the manufacturability overlay (form-dfm-overlay/1): pass, warn, fail per face, the faces of the rule
//           under the pointer lit, the parting line, the pull arrow, side actions
//   cam     a CNC setup (form-cam-view/1): toolpaths by operation up to the scrubbed second, the stock at the end
//           of the setup, the tool's tip
//   flat    the sheet-metal flat pattern on its base face, folding to the part and back
//   motion  a traced point's path and the smallest gap of the frame shown
// Everything that moves is a uniform (the scale, the deformation, the developing front, the scrubbed second), so a
// still result draws nothing new and orbiting it costs what the part costs.
Node {
    id: lay
    property var port: null
    property bool live: false            // the workspace's view: thumbnails never draw a result
    readonly property var r: live && Results.onPart ? Results.r : null
    readonly property string kind: r ? r.kind : ""
    // whether the result stands in for the clay part (the part is then not drawn under it)
    readonly property bool covers: kind === "field" || kind === "dfm" || kind === "cam" || (kind === "flat" && foldK < 0.5)
    readonly property real px: port ? port.dist * 0.00044 : 1        // about one pixel at the part, in millimetres
    property alias fieldGeo: fgeo
    property alias fieldModel: fmodel

    // ── strength ──
    readonly property bool isField: kind === "field"
    readonly property bool modal: isField && !!r.modes
    readonly property real deform: !isField ? 0 : modal ? Results.deformShown * (Results.playing ? Math.sin(Results.phase * 2 * Math.PI) : 1)
                                                        : (Results.deformed ? Results.deformShown : 0)
    property real deformNow: deform
    Behavior on deformNow { enabled: !Results.playing; NumberAnimation { duration: Motion.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    Model {
        id: fmodel
        readonly property string feature: ""
        readonly property string part: ""
        visible: lay.isField; pickable: lay.isField
        geometry: ResultGeometry { id: fgeo
            source: lay.isField ? ({ file: lay.r.mesh.file, kind: "field", field: lay.r.field, mode: Results.mode, lo: lay.r.range[0], hi: lay.r.range[1],
                                     peak: lay.r.peak ? lay.r.peak.at : null, reach: Results.deformShown }) : ({}) }
        materials: CustomMaterial {
            shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling
            vertexShader: "shaders/field.vert"; fragmentShader: "shaders/field.frag"
            property real uDeform: lay.deformNow
            property real uScale: Results.scale === "many" ? 1 : 0
            property real uDevelop: Results.develop
            property real uMix: 1
            property real uGlow: Theme.dark ? 0.85 : 0.0
            property color uLow: Results.rampLow
            property color uMid: Results.rampMid
            property color uHigh: Results.rampHigh
            property real uDither: lay.port ? lay.port.ditherK : 1; property real uFilmic: Theme.dark ? 1 : 0
            property vector3d uClipN: lay.port ? lay.port.clipN : Qt.vector3d(0, 1, 0)
            property real uClipD: lay.port ? lay.port.clipD : 0
            property real uClip: lay.port && lay.port.clipOn ? 1 : 0
        }
    }
    // loads: an arrow along the force, ending on the loaded face (drawn over the part, as a dimension is)
    OverLine { visible: lay.isField && Results.settle > 0.5; port: lay.port; depth: 0
        points: {
            var p = [], gs = lay.isField ? (lay.r.glyphs || []) : [], L = lay.isField ? Math.max(8, lay.r.mesh.diag_mm * 0.2) : 10
            for (var i = 0; i < gs.length; i++) { var g = gs[i]; if (g.role !== "load" || !g.vector) continue
                var d = Qt.vector3d(g.vector[0], g.vector[1], g.vector[2])
                p = p.concat(lay.arrow(Qt.vector3d(g.at[0], g.at[1], g.at[2]).minus(d.times(L)), d, L, L * 0.2)) }
            return p }
        color: Theme.dark ? "#ffffff" : "#161616" }

    // ── manufacturability ──
    readonly property bool isDfm: kind === "dfm"
    Model {
        id: dmodel
        readonly property string feature: ""
        readonly property string part: ""
        visible: lay.isDfm; pickable: false
        geometry: ResultGeometry { source: lay.isDfm ? ({ file: lay.r.mesh.file, kind: "dfm" }) : ({}) }
        materials: CustomMaterial {
            shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
            property real uDither: lay.port ? lay.port.ditherK : 1; property real uFilmic: Theme.dark ? 1 : 0
            property real uWipe: -1; property real uWipeSide: 1
            property real uMap: 1
            property color uColor: Theme.clay
            property color uGlow: "#000000"
            property color uRim: "#000000"
            property vector3d uClipN: lay.port ? lay.port.clipN : Qt.vector3d(0, 1, 0)
            property real uClipD: lay.port ? lay.port.clipD : 0
            property real uClip: lay.port && lay.port.clipOn ? 1 : 0
        }
    }
    readonly property var litFaces: isDfm && Results.litRule !== "" ? Results.ruleFaces(Results.litRule) : []
    Model { visible: lay.isDfm && lay.litFaces.length > 0; pickable: false; castsShadows: false; depthBias: -6
        geometry: ResultGeometry { source: lay.isDfm && lay.litFaces.length ? ({ file: lay.r.mesh.file, kind: "dfm", faces: lay.litFaces }) : ({}) }
        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/lit.frag"; cullMode: Material.NoCulling
            sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha; depthDrawMode: Material.NeverDepthDraw
            property color uColor: Qt.rgba(0.24, 0.9, 1, 0.5) } }
    // the parting line the engine proposes, and the pull: an arrow from above the part along the direction the tool opens
    Model { visible: lay.isDfm && !!lay.r.parting; pickable: false; castsShadows: false
        geometry: LineGeometry { segments: lay.isDfm && lay.r.parting ? lay.r.parting.lines : "" }
        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
            property color uColor: Theme.datum; property vector3d uClipN: lay.port ? lay.port.clipN : Qt.vector3d(0, 1, 0); property real uClipD: lay.port ? lay.port.clipD : 0; property real uClip: lay.port && lay.port.clipOn ? 1 : 0 } }
    function arrow(tail, d, L, h) {               // a line with a four-barbed head, as a list of points
        var tip = tail.plus(d.times(L)), a = Math.abs(d.z) < 0.9 ? Qt.vector3d(0, 0, 1) : Qt.vector3d(1, 0, 0), s = d.crossProduct(a).normalized(), u = d.crossProduct(s).normalized()
        var p = [tail.x, tail.y, tail.z, tip.x, tip.y, tip.z], back = tip.minus(d.times(h)), es = [s, s.times(-1), u, u.times(-1)]
        for (var k = 0; k < 4; k++) { var e = back.plus(es[k].times(h * 0.42)); p.push(tip.x, tip.y, tip.z, e.x, e.y, e.z) }
        return p
    }
    readonly property var pullAt: {               // where the pull arrow starts: above the part's box along the pull
        if (!isDfm || !r.pull || !r.box) return null
        var lo = r.box.lo, hi = r.box.hi, d = Qt.vector3d(r.pull.dir[0], r.pull.dir[1], r.pull.dir[2])
        var c = Qt.vector3d((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2)
        var half = (Math.abs(d.x) * (hi[0] - lo[0]) + Math.abs(d.y) * (hi[1] - lo[1]) + Math.abs(d.z) * (hi[2] - lo[2])) / 2
        var L = Math.max(8, 0.16 * Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))
        return { tail: c.plus(d.times(half + L * 0.2)), dir: d, len: L, tip: c.plus(d.times(half + L * 1.2)) }
    }
    OverLine { visible: lay.isDfm && (!!lay.pullAt || lay.r.side_actions.length > 0); port: lay.port; depth: 0
        points: {
            var p = []
            if (lay.pullAt) p = p.concat(lay.arrow(lay.pullAt.tail, lay.pullAt.dir, lay.pullAt.len, lay.pullAt.len * 0.16))
            var sa = lay.isDfm ? lay.r.side_actions : []
            for (var i = 0; i < sa.length; i++) if (sa[i].at && sa[i].dir) {
                var d = Qt.vector3d(sa[i].dir[0], sa[i].dir[1], sa[i].dir[2]), L = lay.pullAt ? lay.pullAt.len * 0.6 : 12
                p = p.concat(lay.arrow(Qt.vector3d(sa[i].at[0], sa[i].at[1], sa[i].at[2]).plus(d.times(2)), d, L, L * 0.2)) }
            return p }
        color: Theme.dark ? "#ffffff" : "#161616" }

    // ── CNC ──
    readonly property bool isCam: kind === "cam"
    readonly property var setup: isCam ? (r.setups[Results.setup] || null) : null
    // the stock the engine simulated is the end of the setup: it is drawn once the scrubber is at the end
    readonly property bool stockOn: isCam && !!setup && !!setup.stock && Results.t >= Results.duration - 1e-6
    property alias pathGeo: pgeo
    Model { visible: lay.stockOn; pickable: false
        readonly property string feature: ""; readonly property string part: ""
        geometry: ResultGeometry { source: lay.isCam && lay.setup && lay.setup.stock ? ({ file: lay.r.mesh.file, kind: "stock", setup: Results.setup }) : ({}) }
        materials: CustomMaterial {
            shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
            property real uDither: lay.port ? lay.port.ditherK : 1; property real uFilmic: Theme.dark ? 1 : 0
            property real uWipe: -1; property real uWipeSide: 1
            property real uMap: 1
            property color uColor: Theme.clay; property color uGlow: "#000000"; property color uRim: "#000000"
            property vector3d uClipN: lay.port ? lay.port.clipN : Qt.vector3d(0, 1, 0); property real uClipD: lay.port ? lay.port.clipD : 0
            property real uClip: lay.port && lay.port.clipOn ? 1 : 0 } }
    PathGeometry { id: pgeo; source: lay.isCam ? ({ file: lay.r.mesh.file, setup: Results.setup }) : ({}) }
    Repeater3D { model: lay.isCam ? [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]] : []
        Model { required property var modelData; pickable: false; castsShadows: false; geometry: pgeo
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/campath.frag"; vertexShader: "shaders/campath.vert"
                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                property vector3d uOff: Qt.vector3d(modelData[0] * 1.3 / Math.max(1, lay.port ? lay.port.width : 1000), modelData[1] * 1.3 / Math.max(1, lay.port ? lay.port.height : 1000), 0)
                property real uNow: Results.t
                property real uTail: Math.max(0.5, Results.duration * 0.04)
                property real uPast: lay.stockOn ? 0.42 : 0.5 } } }
    // the tool: its tip where the program is, and its axis
    readonly property vector3d toolAt: isCam && pgeo.segments > 0 ? (Results.t, pgeo.at(Results.t)) : Qt.vector3d(0, 0, 0)
    readonly property vector3d toolAxis: setup && setup.axis ? Qt.vector3d(setup.axis[0], setup.axis[1], setup.axis[2]) : Qt.vector3d(0, 0, 1)
    OverLine { visible: lay.isCam && pgeo.segments > 0 && !lay.stockOn; port: lay.port; depth: 0
        points: { var a = lay.toolAt, b = a.plus(lay.toolAxis.times(Math.max(12, 70 * lay.px))); return [a.x, a.y, a.z, b.x, b.y, b.z] }
        color: Theme.dark ? "#ffffff" : "#161616" }
    Model { visible: lay.isCam && pgeo.segments > 0 && !lay.stockOn; source: "#Sphere"; pickable: false; castsShadows: false
        readonly property real k: 0.07 * lay.px
        scale: Qt.vector3d(k, k, k); position: lay.toolAt
        materials: PrincipledMaterial { baseColor: Theme.dark ? "#ffffff" : "#161616"; lighting: PrincipledMaterial.NoLighting } }

    // ── sheet metal: the flat pattern on its base face, folding to the part ──
    readonly property bool isFlat: kind === "flat"
    property real foldK: Results.flat ? 0 : 1            // 1 folded (the part), 0 flat
    Behavior on foldK { NumberAnimation { duration: Motion.move(Theme.panel); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeFold } }
    function _bend(id) { var bs = r.bends; for (var i = 0; i < bs.length; i++) if (bs[i].id === id) return bs[i]; return null }
    function _fold2(pt, path, zone, k) {          // a point of the flat pattern (u, v, 0), folded k of the way along its bends
        var p = Qt.vector3d(pt[0], pt[1], 0)
        for (var i = path.length - 1; i >= 0; i--) {
            var b = _bend(path[i]); if (!b) continue
            // the bend's zone itself is a strip that rolls: at this sketch's level it turns half the angle about its middle line
            var half = zone === b.id && i === path.length - 1
            var q = Qt.vector3d(b.line[0][0], b.line[0][1], 0)
            var ax = Qt.vector3d(b.u[0], b.u[1], 0)
            var ang = (b.direction === "down" ? -1 : 1) * (b.s || 1) * b.angle * Math.PI / 180 * k * (half ? 0.5 : 1)
            var v = p.minus(q), c = Math.cos(ang), s = Math.sin(ang)
            p = q.plus(v.times(c)).plus(ax.crossProduct(v).times(s)).plus(ax.times(ax.dotProduct(v) * (1 - c)))
        }
        return p
    }
    function _to3(p) {                            // the flat frame → the design's
        var f = r.frame
        return [f.origin[0] + f.x[0] * p.x + f.y[0] * p.y + f.z[0] * p.z, f.origin[1] + f.x[1] * p.x + f.y[1] * p.y + f.z[1] * p.z, f.origin[2] + f.x[2] * p.x + f.y[2] * p.y + f.z[2] * p.z]
    }
    function _flatPoints(k, bendsOnly, dir) {
        var out = [], i, j
        if (!isFlat) return out
        function seg(a, b, path, zone) { var A = lay._to3(lay._fold2(a, path, zone, k)), B = lay._to3(lay._fold2(b, path, zone, k)); out.push(A[0], A[1], A[2], B[0], B[1], B[2]) }
        if (bendsOnly) {
            for (i = 0; i < r.bends.length; i++) { var b = r.bends[i]; if ((b.direction === "down") !== (dir === "down")) continue
                var a0 = b.line[0], a1 = b.line[1], L = Math.hypot(a1[0] - a0[0], a1[1] - a0[1]), n = Math.max(1, Math.round(L / 3.2))
                var rg = r.regions[String(b.id)] || { path: [b.id], zone: b.id }
                for (j = 0; j < n; j++) {                 // a bend line is dashed, as on a flat-pattern drawing
                    var t0 = j / n, t1 = (j + 0.6) / n
                    seg([a0[0] + (a1[0] - a0[0]) * t0, a0[1] + (a1[1] - a0[1]) * t0], [a0[0] + (a1[0] - a0[0]) * t1, a0[1] + (a1[1] - a0[1]) * t1], rg.path, rg.zone) } }
            return out
        }
        for (i = 0; i < r.entities.length; i++) { var e = r.entities[i]
            if (e.t === "line") seg(e.a, e.b, e.path, e.zone)
            else if (e.t === "arc" || e.t === "circle") {
                var a0d = e.t === "circle" ? 0 : e.a0, a1d = e.t === "circle" ? 360 : e.a1; if (a1d < a0d) a1d += 360
                var m = Math.max(6, Math.ceil((a1d - a0d) / 12)), prev = null
                for (j = 0; j <= m; j++) { var an = (a0d + (a1d - a0d) * j / m) * Math.PI / 180, pt = [e.c[0] + e.r * Math.cos(an), e.c[1] + e.r * Math.sin(an)]
                    if (prev) seg(prev, pt, e.path, e.zone); prev = pt } }
            else if (e.pts) for (j = 0; j + 1 < e.pts.length; j++) seg(e.pts[j], e.pts[j + 1], e.path, e.zone)
        }
        return out
    }
    OverLine { visible: lay.isFlat && lay.foldK < 0.999; port: lay.port; depth: 0.0002
        points: lay.isFlat && lay.foldK < 0.999 ? lay._flatPoints(lay.foldK, false, "") : []
        color: Theme.dark ? Qt.rgba(0.96, 0.95, 0.94, 1 - lay.foldK * 0.6) : Qt.rgba(0.09, 0.09, 0.09, 1 - lay.foldK * 0.6) }
    Repeater3D { model: ["up", "down"]
        OverLine { required property string modelData; visible: lay.isFlat; port: lay.port; depth: 0
            points: lay.isFlat ? lay._flatPoints(lay.foldK, true, modelData) : []
            color: modelData === "up" ? Theme.datum : Theme.amber } }
    // where a bend's note sits: the middle of its line, at the fold shown (design frame); ResultLabels projects it
    function bendAnchor(b) {
        if (!isFlat) return null
        var rg = r.regions[String(b.id)] || { path: [b.id], zone: b.id }
        return _to3(_fold2([(b.line[0][0] + b.line[1][0]) / 2, (b.line[0][1] + b.line[1][1]) / 2], rg.path, rg.zone, foldK))
    }

    // ── motion: the traced paths, and the smallest gap of the frame shown ──
    readonly property bool isMotion: kind === "motion"
    OverLine { visible: lay.isMotion; port: lay.port; depth: 0
        points: {
            var p = [], ts = lay.isMotion ? lay.r.traces : []
            for (var i = 0; i < ts.length; i++) { var q = ts[i].points
                for (var j = 0; j + 1 < q.length; j++) if (q[j] && q[j + 1]) p.push(q[j][0], q[j][1], q[j][2], q[j + 1][0], q[j + 1][1], q[j + 1][2]) }
            return p }
        color: Theme.alpha(Theme.datum, 0.85) }
    readonly property var gap: isMotion && r.clearance && r.clearance.series.length ? r.clearance.series[Math.min(Results.frame, r.clearance.series.length - 1)] : null
    OverLine { visible: lay.isMotion && !!lay.gap && !!lay.gap.at && !!lay.gap.to; port: lay.port; depth: 0
        points: lay.gap && lay.gap.at && lay.gap.to ? [lay.gap.at[0], lay.gap.at[1], lay.gap.at[2], lay.gap.to[0], lay.gap.to[1], lay.gap.to[2]] : []
        color: lay.gap && lay.gap.state !== "clear" ? Theme.signal : Theme.amber }
}
