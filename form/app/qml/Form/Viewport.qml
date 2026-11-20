import QtQuick
import QtQuick3D
import FormNative
import "F.js" as F
import "Labels.js" as Labels

// The part on its build plate. Millimetres, Z up. Everything the engine returns is drawn as-is:
// one mesh per feature, the kernel's own edges, and overall dimensions as drawing-style dimension lines.
Item {
    id: vp
    // ── public state ─────────────────────────────────────────
    property var model: null                 // engine view: { mesh[], edges, bbox, companions }
    property var ghost: null                 // another revision drawn as blueprint edges
    property string selected: ""
    property string hovered: ""
    property var flagged: []
    property bool showCompanions: true
    property bool showDims: true
    property bool interactive: true
    property bool spin: false                // slow turntable (home screen)
    property bool lite: false                // thumbnails: no shadow map, no AO, lighter MSAA (many on screen at once)
    property real plateSize: 180
    property var bounds: ({ lo: Qt.vector3d(-40, -40, 0), hi: Qt.vector3d(40, 40, 40) })   // on the plate
    property vector3d shift: Qt.vector3d(0, 0, 0)
    property var marker: null                // { at:[x,y,z], to:[x,y,z] } in design coordinates
    property real labelRight: width          // labels of markers and measurements stay left of this x (the dock sits right of it)
    property string sectionAxis: ""
    property real sectionT: 0.5
    signal picked(string feature)
    property var hiddenFeatures: []          // feature ids not drawn (their edges stay, so the part still reads)
    signal contextRequested(string feature, real x, real y)     // right-click or long-press without dragging
    signal hoveredFeature(string feature, real x, real y)

    // ── analysis map and measuring (form/analysis.py) ────────
    // `analysis` is an engine map: its own refined mesh with a colour and a value per vertex, drawn instead of the clay
    // parts. mapMix cross-fades clay → map in the shader. Markers, the legend and the numbers come from the engine.
    property var analysis: null
    property var _map: null                  // what is drawn (kept while fading out)
    property real mapMix: 0
    readonly property bool mapShown: !!_map
    Behavior on mapMix { NumberAnimation { duration: Motion.slow; easing.type: Easing.OutCubic } }
    onAnalysisChanged: { if (analysis) { mapOff.stop(); _map = analysis; mapMix = 1 } else { mapMix = 0; mapOff.restart() } }
    Timer { id: mapOff; interval: 300; onTriggered: if (!vp.analysis) vp._map = null }
    signal hoveredValue(real value, real x, real y, bool on)
    property bool measuring: false           // a click probes the surface instead of selecting a feature
    property var measures: []                // drawn by MeasureLayer; labels below
    property var measureFrom: null
    signal probed(var hit, real reach)       // { at, shown, part, normal }: the surface point as printed (at) and as shown; snap radius in mm (about 10 px)
    signal probeMissed(real x, real y)       // a measuring click that found no surface
    // ── selecting (the Annotate tool, form/selection.py) ──
    property bool selecting: false
    property string selectMode: "face"       // point | edge | face | brush | lasso
    property real brushMm: 3                 // brush radius on the surface
    property var selection: []               // engine items of the live selection, drawn by SelectionLayer
    property var focusItems: []              // engine items of the kept annotation being looked at
    property var annotations: []             // kept annotations of this design (pins), each { id, name, rev, items, analysis }
    property int headRev: 0
    property string annFocusId: ""
    signal selPicked(var items, bool add)    // engine items to analyse; add = keep what is already selected (Shift)
    signal selMissed()
    signal annotationClicked(string id)
    property var stroke: []                  // the brush or lasso being drawn: screen points
    function annAnchor(a) {                  // where an annotation's pin sits: its first item, as shown now
        var res = a.analysis && a.analysis.items ? a.analysis.items : [], it = res.length ? res[0] : null, src = a.items[0]
        var p = it ? (it.on || it.centroid) : (src.at || (src.points ? src.points[0] : null))
        return p ? shownPoint(src.part || "", p) : null
    }
    readonly property var labels: {          // 2D labels pinned to 3D points (design frame)
        var out = [], i, mk = _map && mapMix > 0.5 ? (_map.markers || []) : []
        for (i = 0; i < mk.length && i < 8; i++)
            out.push({ p: mk[i].at, text: mk[i].label, tint: mk[i].kind === "thin" || mk[i].severity === "fail" ? Theme.signal : Theme.amber })
        for (i = 0; i < shownMeasures.length; i++) out.push({ p: shownMeasures[i].label_at, text: shownMeasures[i].label, tint: Theme.datum })
        var tag = frameTag
        for (i = 0; i < annotations.length && !lite; i++) {
            var a = annotations[i], q = annAnchor(a)
            if (q) out.push({ p: q, text: (i + 1) + "  " + a.name + (a.rev !== headRev ? "  · " + F.pad(a.rev) : ""), tint: Theme.annotate,
                              ann: a.id, old: a.rev !== headRev, on: a.id === annFocusId })
        }
        return out
    }

    // ── assembly (designs that declare one): parts drawn as printed, assembled, or pulled apart ──
    // The engine sends each part's meshes in the print frame plus its placement; parts move here, in the scene.
    property string asmMode: "print"         // print | assembled | exploded
    property real explode: 1.0               // exploded-view factor (1 = the design's separation offsets)
    property var pose: ({})                  // joint id → degrees (hinge) or mm (slide)
    property bool asmTween: false
    property vector3d shiftTo: Qt.vector3d(0, 0, 0)   // where shift is going (it animates between modes)
    readonly property var asm: model && model.assembly && !model.assembly.error ? model.assembly : null
    readonly property bool asmOn: !!asm && asmMode !== "print"
    onAsmModeChanged: { _stale(); asmTween = true; _frame(); asmTweenOff.restart(); if (interactive && model && model.assembly) setView(Store.viewName, true) }
    onExplodeChanged: { _frame(); _stale() }
    Timer { id: asmTweenOff; interval: Motion.part + 60 + Motion.stagger * (vp.asm ? Math.min(6, vp.asm.parts.length) : 0); onTriggered: vp.asmTween = false }
    function jointOf(id) {
        var js = asm ? asm.joints : []
        for (var i = 0; i < js.length; i++) if (js[i].part === id) return js[i]
        return null
    }
    function jointById(id) {
        var js = asm ? asm.joints : []
        for (var i = 0; i < js.length; i++) if (js[i].id === id) return js[i]
        return null
    }
    // The joints that move a part, outermost first (the engine sends them as `chain`): arm tilt, then cup tilt for the
    // cup bolt. Each joint's axis is given with every joint at 0, so they apply innermost first, then outward.
    function chainOf(x) {
        if (x.chain) return x.chain
        var j = jointOf(x.id)
        return j ? [j.id] : []
    }
    function partXf(x) {                     // part as printed → where it is drawn: { pos, rot }
        if (!asmOn) return { pos: Qt.vector3d(0, 0, 0), rot: Qt.quaternion(1, 0, 0, 0) }
        var pl = x.placement, t = Qt.vector3d(pl.t[0], pl.t[1], pl.t[2]), q = Qt.quaternion(pl.q[0], pl.q[1], pl.q[2], pl.q[3])
        var ch = chainOf(x)
        for (var i = ch.length - 1; i >= 0; i--) {
            var j = jointById(ch[i]), v = j ? (pose[j.id] || 0) : 0
            if (!j || !v || j.kind === "fixed") continue
            var ax = Qt.vector3d(j.axis[0], j.axis[1], j.axis[2]).normalized()
            if (j.kind === "hinge") {
                var r = Quaternion.fromAxisAndAngle(ax, v), o = Qt.vector3d(j.origin[0], j.origin[1], j.origin[2])
                t = r.times(t.minus(o)).plus(o); q = r.times(q)
            } else t = t.plus(ax.times(v))
        }
        if (asmMode === "exploded") { var e = x.explode_total || x.explode; t = t.plus(Qt.vector3d(e[0], e[1], e[2]).times(explode)) }
        return { pos: t, rot: q }
    }
    // ── points on parts, from the print frame (where the engine computes) to where the part is drawn now ──
    // Measurements and selections keep their points on the part as printed, with the part's id, so they ride along
    // when the view changes between print layout, assembled and exploded, or a joint moves.
    function partById(id) {
        var ps = asm ? asm.parts : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i]
        return null
    }
    function shownXf(part) { var x = part && asmOn ? partById(part) : null; return x ? partXf(x) : null }
    function shownPoint(part, p) {
        if (!p) return p
        var xf = shownXf(part)
        if (!xf) return p
        var q = xf.rot.times(Qt.vector3d(p[0], p[1], p[2])).plus(xf.pos)
        return [q.x, q.y, q.z]
    }
    function shownDir(part, d) {
        if (!d) return d
        var xf = shownXf(part)
        if (!xf) return d
        var q = xf.rot.times(Qt.vector3d(d[0], d[1], d[2]))
        return [q.x, q.y, q.z]
    }
    // the arrangement on screen, as one string: a distance between two parts belongs to the arrangement it was taken in
    readonly property string frameTag: !asmOn ? "print" : asmMode + (asmMode === "exploded" ? ":" + explode.toFixed(2) : "") + ":" + JSON.stringify(pose)
    readonly property var shownMeasures: {
        var tag = frameTag, out = []                  // re-evaluated when the arrangement changes
        for (var i = 0; i < measures.length; i++) {
            var m = measures[i], o = Object.assign({}, m)
            if (m.kind === "distance") {
                if (m.pa !== m.pb && m.frame && m.frame !== tag) continue         // across parts, in another arrangement
                o.a = shownPoint(m.pa, m.a); o.b = shownPoint(m.pb, m.b)
                o.label_at = [(o.a[0] + o.b[0]) / 2, (o.a[1] + o.b[1]) / 2, (o.a[2] + o.b[2]) / 2]
            } else {
                o.at = shownPoint(m.part, m.at)
                o.label_at = shownPoint(m.part, m.label_at)
                if (m.face) o.face = Object.assign({}, m.face, { normal: shownDir(m.part, m.face.normal) })
                if (m.circle && m.circle.center) o.circle = Object.assign({}, m.circle, { center: shownPoint(m.part, m.circle.center), axis: shownDir(m.part, m.circle.axis) })
            }
            out.push(o)
        }
        return out
    }
    readonly property var shownFrom: measureFrom ? { at: shownPoint(measureFrom.part, measureFrom.at) } : null
    function _frame() {                      // centre what is shown on the plate; bounds follow the mode
        if (!model) return
        // read the mode directly: this runs from onAsmModeChanged, possibly before the asmOn binding has updated
        var a = model.assembly && !model.assembly.error ? model.assembly : null, on = !!a && asmMode !== "print"
        var b = on ? a.bbox : model.bbox
        var sh = Qt.vector3d(-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2])
        shift = sh                           // may animate; bounds use the target, not the value mid-animation
        shiftTo = sh
        var lo = Qt.vector3d(b[0][0], b[0][1], b[0][2]), hi = Qt.vector3d(b[1][0], b[1][1], b[1][2])
        if (on && asmMode === "exploded") {
            var asm = a
            for (var i = 0; i < asm.parts.length; i++) {
                var x = asm.parts[i], xe = x.explode_total || x.explode, e = Qt.vector3d(xe[0], xe[1], xe[2]).times(explode)
                lo = Qt.vector3d(Math.min(lo.x, x.bbox[0][0] + e.x), Math.min(lo.y, x.bbox[0][1] + e.y), Math.min(lo.z, x.bbox[0][2] + e.z))
                hi = Qt.vector3d(Math.max(hi.x, x.bbox[1][0] + e.x), Math.max(hi.y, x.bbox[1][1] + e.y), Math.max(hi.z, x.bbox[1][2] + e.z))
            }
        }
        bounds = { lo: lo.plus(sh), hi: hi.plus(sh) }
    }
    Behavior on shift { enabled: vp.asmTween; Vector3dAnimation { duration: Motion.part; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }

    // ── what the part holds (companions): a reference outline, not part of the print ──
    // A device can be several times taller than the part that holds it. The camera frames the part, so a tall
    // companion is drawn only as far as a little above the part and fades out there; a label says what it is and how
    // tall it really is. One that already fits in that height is drawn whole.
    readonly property real compFrom: bounds.hi.z + Math.max(6, 0.15 * bounds.hi.z)                  // fully drawn up to here (mm above the plate)
    readonly property real compTo: bounds.hi.z + Math.max(20, Math.min(60, 0.7 * bounds.hi.z))      // gone from here
    function compAxis(c) { var a = (c.rot_x_deg || 0) * Math.PI / 180; return Qt.vector3d(0, -Math.sin(a), Math.cos(a)) }
    function compTop(c) {                    // its highest point, mm above the plate
        if (c.mesh) return c.origin[2] + c.size[2] + shiftTo.z
        var ax = compAxis(c)
        return c.origin[2] + c.size[2] * ax.z + c.size[1] / 2 * Math.abs(ax.y) + shiftTo.z
    }
    function compCut(c) { return compTop(c) > compTo + 4 }
    function compLabelAt(c) {                // where its outline ends, on its axis (design frame)
        if (c.mesh) return Qt.vector3d(c.origin[0], c.origin[1], compTo - shiftTo.z)
        var ax = compAxis(c), o = Qt.vector3d(c.origin[0], c.origin[1], c.origin[2])
        return o.plus(ax.times((compTo - shiftTo.z - o.z) / Math.max(0.2, ax.z)))
    }
    readonly property var compNotes: {       // one note per companion that is cut short
        var out = [], cs = showCompanions && !asmOn && !lite && interactive && model && model.companions ? model.companions : []
        for (var i = 0; i < cs.length; i++) if (compCut(cs[i])) {
            var c = cs[i], at = compLabelAt(c)
            out.push({ p: [at.x, at.y, at.z], text: (c.label || "Reference") + " · " + F.trim(c.size[2], 1) + " mm tall · not printed" })
        }
        return out
    }

    // ── camera (orbit around target; angles in degrees) ─────
    property vector3d target: Qt.vector3d(0, 0, 20)
    property real az: -34
    property real el: 28.4
    property real dist: 420
    property bool tween: false
    Behavior on az { enabled: vp.tween; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on el { enabled: vp.tween; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on dist { enabled: vp.tween; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on target { enabled: vp.tween; Vector3dAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }

    // ── the free area: pixels the HUD covers on each side. The camera keeps the part in what is left, so a legend
    // or an options bar never sits on it. The parent sets the targets; the camera glides there.
    property real insetLeft: 0
    property real insetRight: 0
    property real insetTop: 0
    property real insetBottom: 0
    property bool insetGlide: false          // off until the first frame, so the view does not slide in on load
    Behavior on insetLeft { enabled: vp.insetGlide; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on insetRight { enabled: vp.insetGlide; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on insetTop { enabled: vp.insetGlide; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    Behavior on insetBottom { enabled: vp.insetGlide; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    // A panel that opens or a window that shrinks can leave almost no free area, or an inset mid-glide that is not a
    // number yet: the free area never drops under 40 px, and the pull-back stays at most 4x, so the camera never runs
    // past its far plane and the view never goes black.
    function _fin(v, d) { return isFinite(v) ? v : d }
    readonly property real freeW: Math.max(40, Math.min(120, width), _fin(width - insetLeft - insetRight, width))
    readonly property real freeH: Math.max(40, Math.min(120, height), _fin(height - insetTop - insetBottom, height))
    // pull back when the free area is much smaller than the view, so the framing keeps its margin
    readonly property real fitK: Math.min(4, Math.max(1, _fin(0.78 * height / freeH, 1), Math.min(1.5, _fin(0.6 * height / freeW, 1))))
    readonly property real mmPerPx: _fin(dist, 420) * fitK * 2 * Math.tan(13 * Math.PI / 180) / Math.max(1, height)
    // the orbit centre stays near what is on the plate: a long pan or a jump never leaves the part in the dark
    readonly property real reach: Math.max(plateSize, 2 * radius(bounds)) * 1.5 + 200
    function clampTarget(t) {
        var c = center(bounds), r = reach
        if (!t || !isFinite(t.x) || !isFinite(t.y) || !isFinite(t.z)) return c
        return Qt.vector3d(Math.max(c.x - r, Math.min(c.x + r, t.x)), Math.max(c.y - r, Math.min(c.y + r, t.y)),
                           Math.max(Math.min(0, c.z) - r, Math.min(c.z + r, t.z)))
    }
    onTargetChanged: { if (!isFinite(target.x) || !isFinite(target.y) || !isFinite(target.z)) { tween = false; target = center(bounds) }; _stale() }
    onDistChanged: { if (!isFinite(dist) || dist <= 0) { tween = false; dist = frame(bounds, 1.5) }; _stale() }
    onAzChanged: { if (!isFinite(az)) { tween = false; az = -34 }; _stale() }
    onElChanged: { if (!isFinite(el)) { tween = false; el = 28.4 }; _stale() }
    // the camera's last good placement: a frame whose numbers are not finite keeps the one before it
    readonly property var _camGood: ({ pos: Qt.vector3d(0, -420, 220), aim: Qt.vector3d(0, 0, 20) })

    // which sides of the part face the camera (the dimension lines stand on those)
    readonly property bool camRight: Math.sin(az * Math.PI / 180) > 0.02
    readonly property bool camFront: Math.cos(az * Math.PI / 180) >= -0.02
    readonly property var views: ({ iso: [-34, 28.4], front: [0, 3.4], side: [90, 3.4], back: [153.4, 26], top: [0, 89], under: [-35.5, -41] })
    function scene(p) { return Qt.vector3d(p.x, p.z, -p.y) }           // Z-up millimetres → Qt Quick 3D's Y-up
    function center(b) { return Qt.vector3d((b.lo.x + b.hi.x) / 2, (b.lo.y + b.hi.y) / 2, (b.lo.z + b.hi.z) / 2) }
    function radius(b) { return Math.max(Math.hypot(b.hi.x - b.lo.x, b.hi.y - b.lo.y, b.hi.z - b.lo.z) / 2, 12) }
    function frame(b, slack) { return radius(b) / Math.sin(13 * Math.PI / 180) * slack }
    function setView(name, animate, box) {
        var v = views[name] || views.iso, b = box || bounds
        tween = animate !== false
        // take the short way round
        var a = v[0]; while (a - az > 180) a -= 360; while (a - az < -180) a += 360
        az = a; el = v[1]; target = center(b); dist = frame(b, box ? 1.25 : 1.5)
    }
    function featureBox(id) {
        for (var k = 0; k < asmParts.count; k++) {          // assembly: transform the feature's box with its part
            var n = asmParts.objectAt(k)
            for (var j = 0; n && j < n.meshes.count; j++) {
                var g = n.meshes.objectAt(j)
                if (!g || g.feature !== id) continue
                var a = g.geometry.lo, c = g.geometry.hi, lo = Qt.vector3d(1e9, 1e9, 1e9), hi = Qt.vector3d(-1e9, -1e9, -1e9)
                for (var m = 0; m < 8; m++) {
                    var p = n.rotation.times(Qt.vector3d(m & 1 ? c.x : a.x, m & 2 ? c.y : a.y, m & 4 ? c.z : a.z)).plus(n.position).plus(shift)
                    lo = Qt.vector3d(Math.min(lo.x, p.x), Math.min(lo.y, p.y), Math.min(lo.z, p.z))
                    hi = Qt.vector3d(Math.max(hi.x, p.x), Math.max(hi.y, p.y), Math.max(hi.z, p.z))
                }
                return { lo: lo, hi: hi }
            }
        }
        for (var i = 0; i < parts.count; i++) {
            var m = parts.objectAt(i)
            if (m && m.feature === id) return { lo: m.geometry.lo.plus(shift), hi: m.geometry.hi.plus(shift) }
        }
        return null
    }
    function focusFeature(id) {
        var b = featureBox(id); if (!b) return
        tween = true; target = center(b); dist = Math.max(14, radius(b)) / Math.sin(13 * Math.PI / 180) * 1.9
    }
    function setModel(v) {
        // a rebuilt part is shown, not popped: the last frame stays on top and fades while the new mesh is underneath.
        // Rapid rebuilds (dragging a slider) skip it, so direct manipulation stays direct.
        var now = Date.now(), calm = now - _lastModel > 420
        _lastModel = now
        if (model && v && calm && !_swapping && crossfade) swap(function () { vp.model = v; vp._frame() })
        else { model = v; if (v) _frame() }
    }
    // ── cross-fade: the one mechanism for "the geometry changed" (drafts, commits, the timeline, Store.fadeTo) ──
    property bool crossfade: interactive && !lite
    property real _lastModel: 0
    property bool _swapping: false
    // The still is a snapshot, not a live copy: it is refreshed (scheduleUpdate) a moment after the view settles, and
    // a swap uses it only while it shows what is on screen now. While the pointer is down (orbiting, panning, a
    // pinch) or the camera has moved since, the change is applied directly. Whatever happens in apply(), the still
    // goes back behind the view: a frame held on top is never left there.
    property bool _stillFresh: false
    function _stale() { _stillFresh = false; if (crossfade) stillRefresh.restart() }
    onWidthChanged: _stale()
    onHeightChanged: _stale()
    onFitKChanged: _stale()
    onModelChanged: _stale()
    onVisibleChanged: _stale()
    onSelectedChanged: _stale()
    onHoveredChanged: _stale()
    onFlaggedChanged: _stale()
    onHiddenFeaturesChanged: _stale()
    onGhostChanged: _stale()
    onSectionAxisChanged: _stale()
    onSectionTChanged: _stale()
    onShowDimsChanged: _stale()
    onShiftChanged: _stale()
    Timer { id: stillRefresh; interval: 160
        onTriggered: {
            if (ma.pressed || pinch.active) { restart(); return }
            still.scheduleUpdate(); stillReady.restart()
        } }
    Timer { id: stillReady; interval: 50; onTriggered: vp._stillFresh = true }   // the frame after the capture is drawn
    function _unfreeze() { thaw.stop(); still.opacity = 1; still.z = -1 }
    function swap(apply) {
        var fade = crossfade && visible && width >= 2 && _stillFresh && !ma.pressed && !pinch.active
        if (!fade) { _unfreeze(); apply(); return }
        thaw.stop(); still.opacity = 1; still.z = 1
        _swapping = true
        try { apply() }
        catch (e) { _unfreeze(); throw e }
        finally { _swapping = false }
        thaw.restart()
    }
    function setGhost(v) { ghost = v }
    // what is under a pixel: the point on the part as printed (the pick's local frame is the part's print frame,
    // whatever arrangement it is drawn in), the same point where it is drawn now, the part and the feature
    function hitAt(x, y) {
        var r = view.pick(x, y)
        if (!r.objectHit || r.objectHit.feature === undefined) return null
        var sp = r.scenePosition, d = Qt.vector3d(sp.x, -sp.z, sp.y).minus(shift), l = r.position, n = r.normal
        return { at: [l.x, l.y, l.z], shown: [d.x, d.y, d.z], part: r.objectHit.part || "", feature: r.objectHit.feature || "",
                 normal: [n.x, n.y, n.z], x: x, y: y }
    }
    function setSection(axis, t) { sectionAxis = axis || ""; sectionT = t === undefined ? 0.5 : t }
    function setMarker(m) {
        marker = m
        if (!m) return
        var a = Qt.vector3d(m.at[0], m.at[1], m.at[2]).plus(shift), c = Qt.vector3d(m.to[0], m.to[1], m.to[2]).plus(shift), p = 18
        setView(Store.viewName, true, { lo: Qt.vector3d(Math.min(a.x, c.x) - p, Math.min(a.y, c.y) - p, Math.min(a.z, c.z) - p),
                                        hi: Qt.vector3d(Math.max(a.x, c.x) + p, Math.max(a.y, c.y) + p, Math.max(a.z, c.z) + p) })
    }

    // section plane, in scene coordinates (the shader keeps what is on the near side)
    readonly property bool clipOn: sectionAxis !== ""
    readonly property real clipAt: {
        var i = sectionAxis
        if (!i) return 0
        var lo = bounds.lo[i], hi = bounds.hi[i]
        return lo + (hi - lo) * sectionT
    }
    // x: remove x > at ; y: remove the front (y < at) ; z: remove above
    readonly property vector3d clipN: sectionAxis === "x" ? Qt.vector3d(1, 0, 0) : sectionAxis === "y" ? Qt.vector3d(0, 0, 1) : Qt.vector3d(0, 1, 0)
    readonly property real clipD: sectionAxis === "y" ? -clipAt : clipAt

    // selection reads as an outline: a mint rim where the feature turns away from the eye, on top of a light tint.
    // Hover is the same idea, fainter, and immediate.
    function rimColor(id) { return id === selected ? Qt.rgba(0.42, 0.85, 0.7, 1) : id === hovered ? Qt.rgba(0.30, 0.30, 0.28, 1) : Qt.rgba(0, 0, 0, 1) }
    function partColor(id, part) {
        var b = colorOf(part || "")
        if (!b) return id === selected ? "#b9e8d7" : flagged.indexOf(id) >= 0 ? "#a9bff5" : id === hovered ? "#f1eee6" : "#d8d3c8"
        return id === selected ? Qt.tint(b, "#9065d4b0") : flagged.indexOf(id) >= 0 ? Qt.tint(b, "#80a9bff5") : id === hovered ? Qt.lighter(b, 1.12) : b
    }
    // colours of the design and its parts (Store.look: the part's own, else the design's, else its material's); none = clay
    property var colorOf: function (part) { return "" }
    function edgeColor(part) {               // the kernel's edges stay readable on a dark part
        var c = colorOf(part || "")
        if (!c) return "#2b2925"
        var k = Qt.color(c), l = 0.299 * k.r + 0.587 * k.g + 0.114 * k.b
        return l < 0.32 ? Qt.lighter(c, 2.1) : Qt.darker(c, 2.6)
    }

    FrameAnimation { running: vp.spin && vp.visible; onTriggered: { vp.tween = false; vp.az += frameTime * 9 } }

    View3D {
        id: view
        anchors.fill: parent
        camera: cam
        environment: SceneEnvironment {
            clearColor: Theme.plate; backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA; antialiasingQuality: vp.lite ? SceneEnvironment.Medium : SceneEnvironment.VeryHigh
            aoEnabled: !vp.lite; aoStrength: 55; aoDistance: 6; aoSoftness: 30; aoSampleRate: 3
            tonemapMode: SceneEnvironment.TonemapModeFilmic
        }
        PerspectiveCamera {
            id: cam
            fieldOfView: 26
            // the depth range follows the camera: near enough for a close look, far enough for the part, the plate and
            // the bench around it at any zoom (a fixed far plane went black once zoomed out with a panel open)
            readonly property real span: Math.max(vp.plateSize, 2 * vp.radius(vp.bounds))
            clipNear: Math.max(0.5, Math.min(20, far * 0.01))
            clipFar: Math.max(6000, far + span * 6 + 2000)
            readonly property real ra: vp.az * Math.PI / 180
            readonly property real re: Math.max(-89, Math.min(89, vp.el)) * Math.PI / 180
            // the look-at point, moved so the orbit centre lands in the middle of the free area
            readonly property real ox: (vp.insetLeft - vp.insetRight) / 2 * vp.mmPerPx
            readonly property real oy: (vp.insetTop - vp.insetBottom) / 2 * vp.mmPerPx
            readonly property vector3d aim: Qt.vector3d(vp.target.x - Math.cos(ra) * ox - Math.sin(ra) * Math.sin(re) * oy,
                                                        vp.target.y - Math.sin(ra) * ox + Math.cos(ra) * Math.sin(re) * oy,
                                                        vp.target.z + Math.cos(re) * oy)
            readonly property real far: Math.max(1, vp._fin(vp.dist * vp.fitK, 420))
            readonly property vector3d zpos: Qt.vector3d(aim.x + far * Math.sin(ra) * Math.cos(re),
                                                         aim.y - far * Math.cos(ra) * Math.cos(re),
                                                         aim.z + far * Math.sin(re))
            readonly property var place: {
                var p = zpos, a = aim, g = vp._camGood
                if (isFinite(p.x) && isFinite(p.y) && isFinite(p.z) && isFinite(a.x) && isFinite(a.y) && isFinite(a.z) && p.minus(a).length() > 1e-3) {
                    g.pos = p; g.aim = a                     // plain fields: remembering it does not re-run this binding
                    return { pos: p, aim: a }
                }
                return { pos: g.pos, aim: g.aim }
            }
            position: vp.scene(place.pos)
            rotation: Quaternion.lookAt(vp.scene(place.pos), vp.scene(place.aim))
        }
        // key from the upper left front (casts the shadow), a warm fill, a cool rim from behind that draws the
        // far silhouette, and a little light from straight above so top faces separate from walls
        DirectionalLight { eulerRotation: Qt.vector3d(-50, -34, 0); brightness: 2.0; color: "#fffaf2"
            castsShadow: !vp.lite; shadowFactor: 86; shadowMapQuality: Light.ShadowMapQualityVeryHigh; softShadowQuality: Light.PCF32; pcfFactor: 9; shadowMapFar: 1400; csmNumSplits: 1 }
        DirectionalLight { eulerRotation: Qt.vector3d(-16, 112, 0); brightness: 0.62; color: "#ffeedd" }
        DirectionalLight { eulerRotation: Qt.vector3d(-24, 164, 0); brightness: 0.9; color: "#c4dcff" }
        DirectionalLight { eulerRotation: Qt.vector3d(-90, 0, 0); brightness: 0.22 }

        Node {
            id: zup
            eulerRotation.x: -90                       // everything below is in Z-up millimetres

            // build plate: ground that catches the shadow, a 10 mm grid, a firm outline
            // the bench runs to the horizon and fades into the background; the plate is a slightly lighter slab on it
            Model { source: "#Rectangle"; scale: Qt.vector3d(60, 60, 1); z: -0.09; receivesShadows: true; castsShadows: false; pickable: false
                materials: CustomMaterial { shadingMode: CustomMaterial.Shaded; fragmentShader: "shaders/ground.frag"
                    property color uColor: Theme.benchGround; property color uFar: Theme.plate; property real uFade: Math.max(vp.plateSize * 1.6, vp.dist * 0.9) } }
            Model { source: "#Rectangle"; scale: Qt.vector3d(vp.plateSize / 100, vp.plateSize / 100, 1); z: -0.05; receivesShadows: true; castsShadows: false; pickable: false
                materials: PrincipledMaterial { baseColor: Theme.benchPlate; roughness: 1; specularAmount: 0 } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: {
                    var p = [], h = vp.plateSize / 2
                    for (var x = -h; x <= h + 1e-6; x += 10) { p.push(x, -h, 0, x, h, 0); p.push(-h, x, 0, h, x, 0) }
                    return p } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: Theme.benchGrid; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: { var h = vp.plateSize / 2; return [-h, -h, 0, h, -h, 0, h, -h, 0, h, h, 0, h, h, 0, -h, h, 0, -h, h, 0, -h, -h, 0] } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: Theme.benchEdge; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

            Node {
                id: design
                position: vp.shift
                Repeater3D {
                    id: parts
                    model: vp.model && !vp.asm ? vp.model.mesh : []
                    Model {
                        required property var modelData
                        readonly property string feature: modelData.feature || ""
                        readonly property string part: ""
                        pickable: !vp.mapShown; visible: !vp.mapShown && vp.hiddenFeatures.indexOf(feature) < 0
                        geometry: MeshGeometry { positions: modelData.positions; indices: modelData.indices }
                        materials: CustomMaterial {
                            shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
                            property real uMap: 0
                            property color uColor: vp.partColor(feature, "")
                            property color uGlow: feature === vp.selected ? "#0a2019" : "#000000"
                            property color uRim: vp.rimColor(feature)
                            property vector3d uClipN: vp.clipN
                            property real uClipD: vp.clipD
                            property real uClip: vp.clipOn ? 1 : 0
                            Behavior on uColor { ColorAnimation { duration: 70 } }
                        }
                    }
                }
                // assembly: one node per part, placed (and swung about its joint) in the scene
                Repeater3D {
                    id: asmParts
                    model: vp.asm ? vp.asm.parts : []
                    Node {
                        id: pn
                        required property var modelData
                        required property int index
                        readonly property var xf: vp.partXf(modelData)
                        readonly property alias meshes: pm
                        position: xf.pos
                        rotation: xf.rot
                        Behavior on position { enabled: vp.asmTween; SequentialAnimation {
                            PauseAnimation { duration: Motion.stagger * Math.min(6, pn.index) }
                            Vector3dAnimation { duration: Motion.part; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
                        Behavior on rotation { enabled: vp.asmTween; SequentialAnimation {
                            PauseAnimation { duration: Motion.stagger * Math.min(6, pn.index) }
                            QuaternionAnimation { duration: Motion.part; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
                        Repeater3D {
                            id: pm
                            model: vp.model ? vp.model.mesh.filter(function (m) { return m.part === pn.modelData.id }) : []
                            Model {
                                required property var modelData
                                readonly property string feature: modelData.feature || ""
                                readonly property string part: pn.modelData.id
                                pickable: !vp.mapShown; visible: !vp.mapShown && vp.hiddenFeatures.indexOf(feature) < 0
                                geometry: MeshGeometry { positions: modelData.positions; indices: modelData.indices }
                                materials: CustomMaterial {
                                    shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
                                    property real uMap: 0
                                    property color uColor: vp.partColor(feature, pn.modelData.id)
                                    property color uGlow: feature === vp.selected ? "#0a2019" : "#000000"
                                    property color uRim: vp.rimColor(feature)
                                    property vector3d uClipN: vp.clipN
                                    property real uClipD: vp.clipD
                                    property real uClip: vp.clipOn ? 1 : 0
                                    Behavior on uColor { ColorAnimation { duration: 70 } }
                                }
                            }
                        }
                        Model { pickable: false; castsShadows: false; depthBias: -2
                            geometry: LineGeometry { segments: pn.modelData.edges || "" }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                                property color uColor: vp.edgeColor(pn.modelData.id); property vector3d uClipN: vp.clipN; property real uClipD: vp.clipD; property real uClip: vp.clipOn ? 1 : 0 } }
                    }
                }
                Model { visible: !!(vp.model && vp.model.edges) && !vp.asm; pickable: false; castsShadows: false; depthBias: -2
                    geometry: LineGeometry { segments: vp.model && vp.model.edges ? vp.model.edges : "" }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                        property color uColor: vp.edgeColor(""); property vector3d uClipN: vp.clipN; property real uClipD: vp.clipD; property real uClip: vp.clipOn ? 1 : 0 } }
                Model { visible: !!(vp.ghost && vp.ghost.edges) && !vp.asmOn; pickable: false; castsShadows: false
                    geometry: LineGeometry { segments: vp.ghost && vp.ghost.edges ? vp.ghost.edges : "" }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"; depthDrawMode: Material.NeverDepthDraw
                        property color uColor: Theme.blueprint; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

                // the thing the part holds, as a blueprint volume
                Repeater3D {
                    model: vp.showCompanions && !vp.asmOn && vp.model && vp.model.companions ? vp.model.companions : []
                    Node {
                        id: comp
                        required property var modelData
                        readonly property bool isMesh: !!modelData.mesh      // an imported part (STEP/STL), in design coordinates
                        position: isMesh ? Qt.vector3d(0, 0, 0) : Qt.vector3d(modelData.origin[0], modelData.origin[1], modelData.origin[2])
                        eulerRotation.x: isMesh ? 0 : (modelData.rot_x_deg || 0)
                        readonly property bool cut: vp.compCut(modelData)
                        readonly property real f0: cut ? vp.compFrom : 1e9
                        readonly property real f1: cut ? vp.compTo : 2e9
                        Model { visible: comp.isMesh; pickable: false; castsShadows: false
                            geometry: MeshGeometry { positions: comp.isMesh ? comp.modelData.mesh.positions : ""; indices: comp.isMesh ? comp.modelData.mesh.indices : "" }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/companion.frag"; vertexShader: "shaders/line.vert"
                                cullMode: Material.NoCulling; depthDrawMode: Material.NeverDepthDraw
                                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                                property color uColor: Theme.alpha(Theme.blueprint, 0.14); property real uFade0: comp.f0; property real uFade1: comp.f1 } }
                        Model { visible: comp.isMesh && !!comp.modelData.edges; pickable: false; castsShadows: false
                            geometry: LineGeometry { segments: comp.isMesh ? (comp.modelData.edges || "") : "" }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/companion.frag"; vertexShader: "shaders/line.vert"
                                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                                property color uColor: Theme.alpha(Theme.blueprint, 0.75); property real uFade0: comp.f0; property real uFade1: comp.f1 } }
                        Model { visible: !comp.isMesh; source: "#Cube"; pickable: false; castsShadows: false
                            scale: Qt.vector3d(modelData.size[0] / 100, modelData.size[1] / 100, modelData.size[2] / 100); z: modelData.size[2] / 2
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/companion.frag"; vertexShader: "shaders/line.vert"
                                depthDrawMode: Material.NeverDepthDraw
                                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                                property color uColor: Theme.alpha(Theme.blueprint, 0.055); property real uFade0: comp.f0; property real uFade1: comp.f1 } }
                        Model { visible: !comp.isMesh; pickable: false; castsShadows: false
                            geometry: LineGeometry { points: {
                                if (comp.isMesh) return []
                                var w = modelData.size[0] / 2, t = modelData.size[1] / 2, l = modelData.size[2], p = []
                                var c = [[-w, -t], [w, -t], [w, t], [-w, t]]
                                for (var i = 0; i < 4; i++) { var a = c[i], b = c[(i + 1) % 4]
                                    p.push(a[0], a[1], 0, b[0], b[1], 0, a[0], a[1], l, b[0], b[1], l, a[0], a[1], 0, a[0], a[1], l) }
                                return p } }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/companion.frag"; vertexShader: "shaders/line.vert"
                                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                                property color uColor: Theme.blueprint; property real uFade0: comp.f0; property real uFade1: comp.f1 } }
                    }
                }

                // the analysis map: the whole part as one mesh, coloured per vertex by the engine
                Model {
                    id: amodel
                    readonly property string feature: ""
                    readonly property string part: ""
                    visible: vp.mapShown; pickable: vp.mapShown
                    geometry: MeshGeometry { id: ageo; source: vp._map }
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
                        property real uMap: vp.mapMix
                        property color uColor: Theme.clay
                        property color uGlow: "#000000"
                        property color uRim: "#000000"
                        property vector3d uClipN: vp.clipN
                        property real uClipD: vp.clipD
                        property real uClip: vp.clipOn ? 1 : 0
                    }
                }
                // what the map points at: a ray from each flagged sample to the face opposite, and outlines (the neck slice)
                Node {
                    visible: vp.mapShown && vp.mapMix > 0.5
                    Model { pickable: false; castsShadows: false
                        geometry: LineGeometry { points: {
                            var p = [], mk = vp._map ? (vp._map.markers || []) : []
                            for (var i = 0; i < mk.length; i++) p.push(mk[i].at[0], mk[i].at[1], mk[i].at[2], mk[i].to[0], mk[i].to[1], mk[i].to[2])
                            return p } }
                        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"; depthDrawMode: Material.NeverDepthDraw
                            property vector3d uOff: Qt.vector3d(0, 0, 0)
                            property color uColor: Theme.signal; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
                    Model { pickable: false; castsShadows: false; depthBias: -4
                        geometry: LineGeometry { segments: vp._map && vp._map.lines ? vp._map.lines : "" }
                        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                            property color uColor: Theme.amber; property vector3d uClipN: vp.clipN; property real uClipD: vp.clipD; property real uClip: vp.clipOn ? 1 : 0 } }
                    Repeater3D {
                        model: vp._map ? (vp._map.markers || []).slice(0, 60) : []
                        Model { required property var modelData; source: "#Sphere"; pickable: false; castsShadows: false
                            readonly property real k: vp.dist * 0.00003
                            scale: Qt.vector3d(k, k, k)
                            position: Qt.vector3d(modelData.at[0], modelData.at[1], modelData.at[2])
                            materials: PrincipledMaterial { baseColor: modelData.kind === "thin" || modelData.severity === "fail" ? Theme.signal : Theme.amber; lighting: PrincipledMaterial.NoLighting } }
                    }
                }
                SelectionLayer { vp: vp; items: vp.focusItems; strength: 0.6; opacity: vp.asmTween ? 0 : 1
                    dot: vp.dist * 0.000034; px: Qt.vector2d(2 / Math.max(1, vp.width), 2 / Math.max(1, vp.height)) }
                SelectionLayer { vp: vp; items: vp.selection; opacity: vp.asmTween ? 0 : 1
                    dot: vp.dist * 0.00004; px: Qt.vector2d(2 / Math.max(1, vp.width), 2 / Math.max(1, vp.height)) }
                // annotation pins: a dot where each kept annotation is
                Repeater3D {
                    model: vp.lite ? [] : vp.annotations
                    Model { required property var modelData; source: "#Sphere"; pickable: false; castsShadows: false
                        readonly property var at: (vp.frameTag, vp.annAnchor(modelData))
                        readonly property real k: vp.dist * (modelData.id === vp.annFocusId ? 0.000052 : 0.000036)
                        visible: !!at; opacity: vp.asmTween ? 0 : 1
                        scale: Qt.vector3d(k, k, k)
                        position: at ? Qt.vector3d(at[0], at[1], at[2]) : Qt.vector3d(0, 0, 0)
                        materials: PrincipledMaterial { baseColor: Theme.annotate; lighting: PrincipledMaterial.NoLighting } }
                }
                MeasureLayer { measures: vp.shownMeasures; from: vp.shownFrom; opacity: vp.asmTween ? 0 : 1; dot: vp.dist * 0.00004; px: Qt.vector2d(2 / Math.max(1, vp.width), 2 / Math.max(1, vp.height)) }

                // a check pointing at a place: thin signal line between two points
                Node {
                    visible: !!vp.marker
                    Model { pickable: false; castsShadows: false
                        geometry: LineGeometry { points: vp.marker ? [vp.marker.at[0], vp.marker.at[1], vp.marker.at[2], vp.marker.to[0], vp.marker.to[1], vp.marker.to[2]] : [] }
                        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"; depthDrawMode: Material.NeverDepthDraw
                            property color uColor: Theme.signal; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
                    Repeater3D {
                        model: vp.marker ? [vp.marker.at, vp.marker.to] : []
                        Model { required property var modelData; source: "#Sphere"; scale: Qt.vector3d(0.018, 0.018, 0.018); pickable: false; castsShadows: false
                            position: Qt.vector3d(modelData[0], modelData[1], modelData[2])
                            materials: PrincipledMaterial { baseColor: Theme.signal; lighting: PrincipledMaterial.NoLighting } }
                    }
                }
            }

            // overall dimensions, drawn like a drawing: extension lines, a dimension line, the number
            Model { visible: vp.showDims && !!vp.model && vp.asmMode !== "exploded"; pickable: false; castsShadows: false
                geometry: LineGeometry { points: {
                    var b = vp.bounds, o = 7, t = 2.2, p = []
                    var x0 = b.lo.x, x1 = b.hi.x, y0 = b.lo.y, y1 = b.hi.y, z1 = b.hi.z
                    var g = 0.12, sx = vp.camRight ? 1 : -1, sy = vp.camFront ? -1 : 1
                    var xe = vp.camRight ? x1 : x0, ye = vp.camFront ? y0 : y1, yf = vp.camFront ? y1 : y0
                    p.push(x0, ye + sy * o, g, x1, ye + sy * o, g, x0, ye + sy * (o + t), g, x0, ye + sy, g, x1, ye + sy * (o + t), g, x1, ye + sy, g)
                    p.push(xe + sx * o, y0, g, xe + sx * o, y1, g, xe + sx, y0, g, xe + sx * (o + t), y0, g, xe + sx, y1, g, xe + sx * (o + t), y1, g)
                    p.push(xe + sx * o, yf, 0, xe + sx * o, yf, z1, xe + sx, yf, z1, xe + sx * (o + t), yf, z1)
                    return p } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: Theme.alpha(Theme.datum, 0.72); property vector3d uClipN; property real uClipD; property real uClip: 0 } }
        }
    }
    // the frame before a geometry change, held on top and let go (see swap)
    // It is kept current by sitting, fully covered, behind the 3D view; a swap lifts it in front and fades it.
    ShaderEffectSource { id: still; objectName: "viewportStill"; anchors.fill: view; sourceItem: view; live: false; z: -1; visible: vp.crossfade }
    SequentialAnimation { id: thaw
        NumberAnimation { target: still; property: "opacity"; from: 1; to: 0; duration: Motion.slow; easing.type: Easing.InOutQuad }
        ScriptAction { script: vp._unfreeze() } }
    // a held frame that is somehow still on top with nothing fading it is let go
    Timer { interval: 1000; repeat: true; running: still.z > 0
        onTriggered: if (!thaw.running) vp._unfreeze() }

    // the brush stroke or lasso outline being drawn, on top of the part
    Canvas {
        id: strokeCanvas
        anchors.fill: view; visible: vp.stroke.length > 0
        readonly property var pts: vp.stroke
        onPtsChanged: requestPaint()
        onPaint: {
            var c = getContext("2d"), p = pts
            c.reset()
            if (!p.length) return
            var col = Theme.annotate
            c.lineJoin = "round"; c.lineCap = "round"
            c.beginPath(); c.moveTo(p[0].x, p[0].y)
            for (var i = 1; i < p.length; i++) c.lineTo(p[i].x, p[i].y)
            if (vp.selectMode === "brush") {
                c.strokeStyle = Qt.rgba(col.r, col.g, col.b, 0.38)
                c.lineWidth = Math.max(4, 2 * vp.brushMm / Math.max(1e-6, vp.mmPerPx))
                c.stroke()
            } else {
                c.closePath()
                c.fillStyle = Qt.rgba(col.r, col.g, col.b, 0.14); c.fill()
                c.strokeStyle = Qt.rgba(col.r, col.g, col.b, 0.9); c.lineWidth = 1.5
                if (c.setLineDash) c.setLineDash([5, 4]); c.stroke()
            }
        }
    }

    // ── 2D labels pinned to 3D points: dimension numbers, findings and measurements, notes on what the part holds.
    // One pass per frame projects their points and lets Labels.js seat them, so a marker never sits on a dimension.
    function _px(p) {                        // plate-frame millimetres → view pixels, or null behind the camera
        var s = view.mapFrom3DScene(vp.scene(p))
        return s.z > 0 ? Qt.point(s.x, s.y) : null
    }
    function _dimLine(i) {                   // the two ends of dimension line i, on the plate (see the Model above)
        var b = bounds, o = 7, xs = camRight ? b.hi.x + o : b.lo.x - o, ys = camFront ? b.lo.y - o : b.hi.y + o
        return i === 0 ? [Qt.vector3d(b.lo.x, ys, 0), Qt.vector3d(b.hi.x, ys, 0)]
             : i === 1 ? [Qt.vector3d(xs, b.lo.y, 0), Qt.vector3d(xs, b.hi.y, 0)]
             : [Qt.vector3d(xs, camFront ? b.hi.y : b.lo.y, 0), Qt.vector3d(xs, camFront ? b.hi.y : b.lo.y, b.hi.z)]
    }
    function _seatLabels() {
        var items = [], refs = [], i, k, it, w, h, p, c
        for (i = 0; i < dimLabels.count; i++) {
            it = dimLabels.itemAt(i); if (!it) continue
            var ends = _dimLine(i), a = _px(ends[0]), e = _px(ends[1]), ts = [0.5, 0.3, 0.7, 0.16, 0.84]
            w = it.width; h = it.height; c = []
            for (k = 0; a && e && k < ts.length; k++)
                c.push({ x: Math.round(a.x + (e.x - a.x) * ts[k] - w / 2), y: Math.round(a.y + (e.y - a.y) * ts[k] - h / 2) })
            items.push({ kind: "dim", w: w, h: h, cands: c, prev: it.cand }); refs.push(it)
        }
        for (i = 0; i < pinLabels.count; i++) {
            it = pinLabels.itemAt(i); if (!it) continue
            var q = it.modelData.p
            p = _px(Qt.vector3d(q[0], q[1], q[2]).plus(shift)); w = it.width; h = it.height
            // right of its point and above it, then the other three corners
            c = p ? [{ x: Math.round(p.x + 9), y: Math.round(p.y - h - 5) }, { x: Math.round(p.x - 9 - w), y: Math.round(p.y - h - 5) },
                     { x: Math.round(p.x + 9), y: Math.round(p.y + 5) }, { x: Math.round(p.x - 9 - w), y: Math.round(p.y + 5) }] : []
            items.push({ kind: "pin", w: w, h: h, cands: c, prev: it.cand }); refs.push(it)
        }
        for (i = 0; i < refLabels.count; i++) {
            it = refLabels.itemAt(i); if (!it) continue
            var g = it.modelData.p
            p = _px(Qt.vector3d(g[0], g[1], g[2]).plus(shift)); w = it.width; h = it.height
            c = p ? [{ x: Math.round(p.x - w / 2), y: Math.round(p.y - h - 6) }, { x: Math.round(p.x + 12), y: Math.round(p.y - h / 2) },
                     { x: Math.round(p.x - 12 - w), y: Math.round(p.y - h / 2) }] : []
            items.push({ kind: "ref", w: w, h: h, cands: c, prev: it.cand }); refs.push(it)
        }
        if (!items.length) return
        // labels of markers and measurements stay left of labelRight (the dock sits right of it)
        var out = Labels.place(items, { l: 4, t: 4, r: labelRight - 6, b: height - 4 })
        for (i = 0; i < refs.length; i++) {
            it = refs[i]; var r = out[i]
            if (it.cand !== r.c) it.cand = r.c
            if (it.shown !== r.visible) it.shown = r.visible
            if (r.visible && (it.x !== r.x || it.y !== r.y)) { it.x = r.x; it.y = r.y }
        }
    }
    FrameAnimation { running: vp.visible && (dimLabels.count + pinLabels.count + refLabels.count) > 0; onTriggered: vp._seatLabels() }

    // dimension numbers, on the 3D dimension lines
    Repeater {
        id: dimLabels
        model: vp.showDims && vp.model && !(vp.asmOn && vp.asmMode === "exploded") ? 3 : 0
        Rectangle {
            id: dl
            objectName: "dimLabel"
            required property int index
            property bool shown: false
            property int cand: -1
            readonly property var b: vp.bounds
            readonly property real mm: index === 0 ? b.hi.x - b.lo.x : index === 1 ? b.hi.y - b.lo.y : b.hi.z
            width: t.implicitWidth + 10; height: 17; radius: Theme.rXs; color: Theme.plate; border.color: Theme.alpha(Theme.datum, 0.28)
            visible: shown
            Text { id: t; anchors.centerIn: parent; text: F.fmt(dl.mm, 1); color: Theme.datum; font.family: Theme.mono; font.pixelSize: Theme.tFine; font.weight: 500; renderType: Text.NativeRendering }
        }
    }

    // labels of map markers and measurements, beside their 3D points
    Repeater {
        id: pinLabels
        model: vp.labels
        Rectangle {
            id: pl
            objectName: "pinLabel"
            required property var modelData
            property bool shown: false
            property int cand: -1
            width: pt.implicitWidth + 12; height: 19; radius: Theme.rXs
            color: pl.modelData.on ? Theme.alpha(pl.modelData.tint, 0.22) : plm.containsMouse ? Theme.alpha(Theme.plate3, 0.95) : Theme.alpha(Theme.plate, 0.88)
            border.color: Theme.alpha(modelData.tint, pl.modelData.on ? 0.8 : 0.45)
            opacity: pl.modelData.old ? 0.7 : 1
            z: pl.modelData.ann ? 3 : 0                 // an annotation's label is a button, above the orbit area
            visible: shown
            Text { id: pt; anchors.centerIn: parent; text: pl.modelData.text; color: pl.modelData.tint; font.family: pl.modelData.ann ? Theme.sans : Theme.mono
                font.pixelSize: Theme.tFine; font.weight: pl.modelData.ann ? 550 : 400; renderType: Text.NativeRendering }
            MouseArea { id: plm; anchors.fill: parent; enabled: !!pl.modelData.ann; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: vp.annotationClicked(pl.modelData.ann) }
        }
    }

    // what the part holds, where its outline is cut short: what it is, how tall it really is, and that it is not printed
    Repeater {
        id: refLabels
        model: vp.compNotes
        Rectangle {
            id: rl
            objectName: "companionNote"
            required property var modelData
            property bool shown: false
            property int cand: -1
            width: rt.implicitWidth + 12; height: 19; radius: Theme.rXs; color: Theme.alpha(Theme.plate, 0.88); border.color: Theme.alpha(Theme.blueprint, 0.4)
            visible: shown
            Txt { id: rt; anchors.centerIn: parent; kind: "fine"; text: rl.modelData.text; color: Theme.blueprint; wrapMode: Text.NoWrap }
        }
    }

    // ── input: drag to orbit, right-drag or shift to pan, wheel or pinch to zoom, click to select ──
    MouseArea {
        id: ma
        anchors.fill: parent; enabled: vp.interactive
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton; hoverEnabled: true
        property point last
        property point down
        property bool moved: false
        cursorShape: painting ? Qt.CrossCursor : pressed && moved ? Qt.ClosedHandCursor : vp.measuring || vp.selecting ? Qt.CrossCursor : vp.hovered ? Qt.PointingHandCursor : pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        function hit(x, y) { var r = view.pick(x, y); return r.objectHit && r.objectHit.feature !== undefined ? r.objectHit.feature : "" }
        property point hoverAt
        Timer { id: valueAt; interval: 30                // the map's value under the pointer: pick, then interpolate on the mesh
            onTriggered: {
                var r = view.pick(ma.hoverAt.x, ma.hoverAt.y)
                if (r.objectHit === amodel) vp.hoveredValue(ageo.valueAt(r.position), ma.hoverAt.x, ma.hoverAt.y, true)
                else vp.hoveredValue(0, 0, 0, false)
            } }
        function probe(x, y) {                           // a click while measuring: the surface point, in design millimetres
            var h = vp.hitAt(x, y)
            if (!h) { vp.probeMissed(x, y); return }
            vp.probed(h, vp.mmPerPx * 10)
        }
        // ── the Annotate tool: a click picks (Shift adds); with Brush or Lasso a left-drag paints or draws instead of
        // orbiting (Alt-drag still orbits). Every pick is a point on the part as printed, with the part's id.
        property bool painting: false
        property var _paint: []                          // brush: { at, part } samples on the surface
        property point _lastSample
        function pick(x, y, add) {
            var h = vp.hitAt(x, y)
            if (!h) { vp.selMissed(); return }
            vp.selPicked([{ kind: vp.selectMode, at: h.at, part: h.part }], add)
        }
        function sampleBrush(x, y) {
            var h = vp.hitAt(x, y)
            if (h) _paint.push({ at: h.at, part: h.part })
            _lastSample = Qt.point(x, y)
        }
        function regions(samples, radius, mode) {        // one region per part: each is analysed and drawn in its own frame
            var by = {}, order = []
            for (var i = 0; i < samples.length; i++) {
                var k = samples[i].part || ""
                if (!by[k]) { by[k] = []; order.push(k) }
                by[k].push(samples[i].at)
            }
            return order.map(function (k) { return { kind: "region", points: by[k].slice(0, 1500), radius: radius, part: k, mode: mode } })
        }
        function inside(poly, x, y) {
            var c = false
            for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                var a = poly[i], b = poly[j]
                if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) c = !c
            }
            return c
        }
        function finishLasso(poly) {                     // sample the visible surface inside the outline on an even grid
            if (poly.length < 3) return []
            var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9
            for (var i = 0; i < poly.length; i++) { x0 = Math.min(x0, poly[i].x); y0 = Math.min(y0, poly[i].y); x1 = Math.max(x1, poly[i].x); y1 = Math.max(y1, poly[i].y) }
            var step = Math.max(3, Math.sqrt((x1 - x0) * (y1 - y0) / 1400)), out = []
            for (var y = y0 + step / 2; y < y1; y += step)
                for (var x = x0 + step / 2; x < x1; x += step)
                    if (inside(poly, x, y)) { var h = vp.hitAt(x, y); if (h) out.push({ at: h.at, part: h.part }) }
            return regions(out, Math.max(0.3, step * vp.mmPerPx * 0.75), "lasso")
        }
        // a press on the part takes the keyboard from whatever text box had it, so V, M, F and the rest work again
        onPressed: function (e) {
            vp.forceActiveFocus(); last = Qt.point(e.x, e.y); down = last; moved = false; vp.tween = false
            if (vp.selecting && (vp.selectMode === "brush" || vp.selectMode === "lasso") && e.button === Qt.LeftButton && !(e.modifiers & Qt.AltModifier)) {
                painting = true; _paint = []; vp.stroke = [Qt.point(e.x, e.y)]
                if (vp.selectMode === "brush") sampleBrush(e.x, e.y)
            }
        }
        onPositionChanged: function (e) {
            if (painting) {
                if (Math.hypot(e.x - down.x, e.y - down.y) > 4) moved = true
                var lp = vp.stroke[vp.stroke.length - 1]
                if (Math.hypot(e.x - lp.x, e.y - lp.y) >= 2) vp.stroke = vp.stroke.concat([Qt.point(e.x, e.y)])
                if (vp.selectMode === "brush") {          // a sample every half brush radius along the stroke
                    var gap = Math.max(2, vp.brushMm / Math.max(1e-6, vp.mmPerPx) * 0.5), d = Math.hypot(e.x - _lastSample.x, e.y - _lastSample.y)
                    for (var t = gap; t <= d; t += gap)
                        sampleBrush(_lastSample.x + (e.x - _lastSample.x) * gap / d, _lastSample.y + (e.y - _lastSample.y) * gap / d)
                }
                return
            }
            if (!pressed) {
                if (vp.mapShown) { hoverAt = Qt.point(e.x, e.y); valueAt.restart(); return }
                var f = vp.measuring || vp.selecting ? "" : hit(e.x, e.y)
                if (f !== vp.hovered) vp.hovered = f
                vp.hoveredFeature(f, e.x, e.y)
                return
            }
            var dx = e.x - last.x, dy = e.y - last.y
            if (Math.hypot(e.x - down.x, e.y - down.y) > 4) moved = true
            last = Qt.point(e.x, e.y)
            if ((e.buttons & Qt.LeftButton) && !(e.modifiers & Qt.ShiftModifier)) {
                vp.az -= dx * 0.4; vp.el = Math.max(-89, Math.min(89, vp.el + dy * 0.4))
            } else {
                var k = vp.mmPerPx
                var ra = vp.az * Math.PI / 180, re = vp.el * Math.PI / 180
                var right = Qt.vector3d(Math.cos(ra), Math.sin(ra), 0)
                var up = Qt.vector3d(-Math.sin(ra) * Math.sin(re), Math.cos(ra) * Math.sin(re), Math.cos(re))
                vp.target = vp.clampTarget(vp.target.minus(right.times(dx * k)).plus(up.times(dy * k)))
            }
        }
        onReleased: function (e) {
            if (painting) {
                painting = false
                var add = !!(e.modifiers & Qt.ShiftModifier), items
                if (vp.selectMode === "brush") { sampleBrush(e.x, e.y); items = regions(_paint, vp.brushMm, "brush") }
                else if (!moved) {                        // a click with the lasso picks the face under it
                    vp.stroke = []
                    var h = vp.hitAt(e.x, e.y)
                    if (h) vp.selPicked([{ kind: "face", at: h.at, part: h.part }], add); else vp.selMissed()
                    return
                } else items = finishLasso(vp.stroke)
                vp.stroke = []
                if (items.length) vp.selPicked(items, add); else vp.selMissed()
                return
            }
            if (held) { held = false; return }
            if (moved) return
            if (e.button === Qt.RightButton) { vp.contextRequested(hit(e.x, e.y), e.x, e.y); return }
            if (e.button !== Qt.LeftButton) return
            if (vp.measuring) probe(e.x, e.y)
            else if (vp.selecting) pick(e.x, e.y, !!(e.modifiers & Qt.ShiftModifier))
            else if (!vp.mapShown) vp.picked(hit(e.x, e.y))
        }
        property bool held: false
        onPressAndHold: function (e) { if (!moved && !painting && e.button === Qt.LeftButton && !vp.measuring && !vp.selecting) { held = true; vp.contextRequested(hit(e.x, e.y), e.x, e.y) } }
        onExited: { if (vp.hovered) vp.hovered = ""; vp.hoveredFeature("", 0, 0); valueAt.stop(); vp.hoveredValue(0, 0, 0, false) }
        onWheel: function (w) {
            vp.tween = false
            var d = w.pixelDelta.y !== 0 ? w.pixelDelta.y * 0.0035 : w.angleDelta.y / 120 * 0.12
            vp.dist = Math.max(30, Math.min(3000, vp.dist * Math.exp(-d)))
        }
    }
    PinchHandler {
        id: pinch
        enabled: vp.interactive; target: null
        property real d0: 0
        onActiveChanged: if (active) { d0 = vp.dist; vp.tween = false }
        onScaleChanged: (delta) => { vp.dist = Math.max(30, Math.min(3000, vp.dist / delta)) }
    }
}
