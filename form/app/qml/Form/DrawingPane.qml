import QtQuick
import "F.js" as F

// The drawing sheet on the stage (direction I: Document). It draws the engine's own scene graph (form/drawing/scene.py,
// sheet.json): the same tree the PDF, the SVG and the DXF are made from, in sheet millimetres with y up. Two styles,
// both the engine's themes: the night sheet (ink in light on a dark plate, dimensions in cyan) and white paper as it
// prints; P switches. The wheel zooms about the pointer, a drag pans, a double-click on the paper fits it again.
// A dimension is an object: click selects it, and one bound to a parameter is typed over (double-click or Enter):
// that commits the parameter through the engine (set_dimension) and the sheet is made again for the new revision.
//
// "The sheet unfolds from the part" (Theme.unfold, once per sheet and visit): the plate arrives with the front view,
// the other views swing out on the hinges their projection implies, dimensions and notes come last. Any input cuts
// it; Reduce Motion makes it a cross-fade.
Item {
    id: pane
    objectName: "drawingPane"
    readonly property var r: Results.kind === "drawing" ? Results.r : null
    property var _last: null
    onRChanged: { if (r) { var fresh = !_last || _last.rev !== r.rev || JSON.stringify(_last.size) !== JSON.stringify(r.size); _last = r; if (fresh) fit(); index(); cv.requestPaint(); if (!_played) { _played = true; play() } } }
    readonly property var d: r || _last
    readonly property var sheet: d ? d.sheet : null
    readonly property bool paper: Theme.dark ? Results.paper : !Results.paper      // night in the dark room, paper in the light one; P switches
    readonly property var colors: d ? d.themes[paper ? "paper" : "night"] : ({})
    onPaperChanged: cv.requestPaint()
    clip: true

    // ── the view: px per mm and where the sheet's lower-left corner is ──
    property real zoom: 1
    property real ox: 0
    property real oy: 0
    readonly property real sw: d && d.size ? d.size[0] : 420
    readonly property real sh: d && d.size ? d.size[1] : 297
    function fit() { var m = 18; zoom = Math.max(0.2, Math.min((width - 2 * m) / sw, (height - 2 * m) / sh)); ox = Math.round((width - sw * zoom) / 2); oy = Math.round((height - sh * zoom) / 2) }
    onWidthChanged: if (!_touched) fit()
    onHeightChanged: if (!_touched) fit()
    property bool _touched: false
    function sx(x) { return ox + x * zoom }
    function sy(y) { return oy + (sh - y) * zoom }
    function zoomAt(px, py, k) {
        var z = Math.max(0.3, Math.min(40, zoom * k)), f = z / zoom
        ox = px - (px - ox) * f; oy = py - (py - oy) * f; zoom = z; _touched = true
    }
    onZoomChanged: cv.requestPaint(); onOxChanged: cv.requestPaint(); onOyChanged: cv.requestPaint()

    // ── the unfold ──
    property bool _played: false
    property real k: 1                   // 0..1 through the moment
    readonly property bool unfolding: unfold.running
    NumberAnimation { id: unfold; target: pane; property: "k"; from: 0; to: 1; duration: Theme.reduced ? Theme.moment : Theme.unfold; easing.type: Easing.Linear }
    function play() { k = 0; unfold.restart() }
    function cut() { if (unfold.running) { unfold.stop(); k = 1 } }
    onKChanged: cv.requestPaint()
    function ramp(a, b) { var x = Math.max(0, Math.min(1, (k * Theme.unfold - a) / (b - a))); return x * x * (3 - 2 * x) }
    function fold(a, b) { var x = Math.max(0, Math.min(1, (k * Theme.unfold - a) / (b - a))); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2 }

    // ── dimensions as objects ──
    property var dims: []
    property var front: null
    function index() {
        var cur = r || _last; dims = cur ? cur.dims : []
        front = null
        var ch = cur && cur.sheet ? cur.sheet.children : []
        for (var i = 0; i < ch.length; i++) if (ch[i].role === "view" && ch[i].meta && ch[i].meta.view === "front") front = ch[i].bbox
    }
    function dimAt(px, py) {
        var x = (px - ox) / zoom, y = sh - (py - oy) / zoom, pad = 3 / zoom + 0.6, best = null, area = 1e18
        for (var i = 0; i < dims.length; i++) { var b = dims[i].bbox; if (!b) continue
            if (x >= b[0] - pad && x <= b[2] + pad && y >= b[1] - pad && y <= b[3] + pad) { var a = (b[2] - b[0]) * (b[3] - b[1]); if (a < area) { area = a; best = dims[i] } } }
        return best
    }
    function dimById(id) { for (var i = 0; i < dims.length; i++) if (dims[i].id === id) return dims[i]; return null }
    readonly property var sel: (dims, dimById(Results.selDim))
    property string hot: ""
    onHotChanged: cv.requestPaint()
    Connections { target: Results; function onSelDimChanged() { cv.requestPaint() } }
    function edit(dm) { if (!dm || !dm.editable) return; Results.selDim = dm.id; field.text = String(dm.value); editor.dim = dm; editor.visible = true; field.forceActiveFocus(); field.selectAll() }

    // the room shows around the sheet; the sheet is a plate with a soft edge
    Rectangle { objectName: "sheetPlate"; x: Math.round(pane.sx(0)); y: Math.round(pane.sy(pane.sh)); width: Math.round(pane.sw * pane.zoom); height: Math.round(pane.sh * pane.zoom)
        color: pane.colors.paper || "transparent"; radius: 3; border.color: pane.paper ? Qt.rgba(0, 0, 0, 0.25) : Qt.rgba(1, 1, 1, 0.1)
        opacity: Theme.reduced ? pane.k : pane.ramp(0, 140)
        scale: Theme.reduced ? 1 : 0.94 + 0.06 * pane.ramp(0, 200) }
    Canvas {
        id: cv
        objectName: "sheetCanvas"
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        Connections { target: Theme; function onDarkChanged() { cv.requestPaint() } }
        function col(layer, role) { var c = pane.colors; return c[layer] || c.text || "#888888" }
        function prim(g, p, z, lit) {
            var c = lit ? (pane.paper ? "#0a7fa0" : "#9ff3ff") : col(p.layer), L = p.layer, i
            var w = L === "visible" || L === "section" ? Math.max(1.15, 0.5 * z) : L === "frame" ? Math.max(1, 0.35 * z) : Math.max(0.8, 0.25 * z)
            if (lit) w += 0.6
            g.strokeStyle = c; g.fillStyle = c; g.lineWidth = w
            g.setLineDash(L === "hidden" ? [3 * Math.max(1, z * 0.6) / w, 1.6 * Math.max(1, z * 0.6) / w] : L === "center" ? [7 * Math.max(1, z * 0.6) / w, 1.6 * Math.max(1, z * 0.6) / w, 1.2 * Math.max(1, z * 0.6) / w, 1.6 * Math.max(1, z * 0.6) / w] : [])
            if (p.kind === "line") { g.beginPath(); g.moveTo(pane.sx(p.a[0]), pane.sy(p.a[1])); g.lineTo(pane.sx(p.b[0]), pane.sy(p.b[1])); g.stroke() }
            else if (p.kind === "polyline" || p.kind === "polygon") { g.beginPath()
                for (i = 0; i < p.pts.length; i++) { if (i) g.lineTo(pane.sx(p.pts[i][0]), pane.sy(p.pts[i][1])); else g.moveTo(pane.sx(p.pts[i][0]), pane.sy(p.pts[i][1])) }
                if (p.kind === "polygon") { g.closePath(); g.fill() } else { if (p.closed) g.closePath(); g.stroke() } }
            else if (p.kind === "circle") { g.beginPath(); g.arc(pane.sx(p.c[0]), pane.sy(p.c[1]), p.r * z, 0, 2 * Math.PI); if (p.fill) g.fill(); else g.stroke() }
            else if (p.kind === "arc") { g.beginPath(); g.arc(pane.sx(p.c[0]), pane.sy(p.c[1]), p.r * z, -p.a0 * Math.PI / 180, -p.a1 * Math.PI / 180, true); g.stroke() }
            else if (p.kind === "text") {
                var px = Math.max(1, p.h * z * 1.38)
                g.setLineDash([]); g.font = (L === "title" ? "500 " : "400 ") + px.toFixed(2) + "px '" + (L === "dimension" || L === "gdt" ? Theme.mono : Theme.sans) + "'"
                g.textAlign = p.anchor === "middle" ? "center" : p.anchor === "end" ? "right" : "left"
                g.textBaseline = p.valign === "middle" ? "middle" : p.valign === "top" ? "top" : "alphabetic"
                g.save(); g.translate(pane.sx(p.at[0]), pane.sy(p.at[1])); if (p.rot) g.rotate(-p.rot * Math.PI / 180); g.fillText(p.s, 0, 0); g.restore() }
        }
        function group(g, n, z, lit) {
            var ch = n.children || []
            for (var i = 0; i < ch.length; i++) { var c = ch[i]
                if (c.kind === "group") group(g, c, z, lit || (c.role === "dimension" && (c.id === Results.selDim || c.id === pane.hot)))
                else prim(g, c, z, lit) }
        }
        onPaint: {
            var g = getContext("2d"); g.reset()
            var s = pane.sheet; if (!s) return
            var z = pane.zoom, ch = s.children || [], T = Theme.unfold, moving = pane.k < 1 && !Theme.reduced
            g.lineCap = "round"; g.lineJoin = "round"
            for (var i = 0; i < ch.length; i++) { var n = ch[i], role = n.role || ""
                g.save()
                if (pane.k < 1 && Theme.reduced) g.globalAlpha = pane.k
                else if (moving) {
                    var b = n.bbox, f = pane.front
                    if (role === "view" && n.meta && n.meta.view === "front") g.globalAlpha = pane.ramp(0, 140)
                    else if (role === "view" && b && f && n.meta && n.meta.view !== "iso") {
                        // a projected view swings out from the edge it shares with the front view
                        var kf = pane.fold(140, 340), below = b[3] <= f[1] + 1, above = b[1] >= f[3] - 1, left = b[2] <= f[0] + 1
                        var hx = pane.sx(left ? b[2] : b[0]), hy = pane.sy(below ? b[3] : above ? b[1] : b[1])
                        g.globalAlpha = Math.min(1, kf * 1.6)
                        if (below || above) { g.translate(0, hy); g.scale(1, Math.max(0.001, kf)); g.translate(0, -hy) }
                        else { g.translate(hx, 0); g.scale(Math.max(0.001, kf), 1); g.translate(-hx, 0) }
                    }
                    else if (role === "border") g.globalAlpha = pane.ramp(60, 240)
                    else if (role === "view" || role === "section" || role === "detail" || role === "cutting_plane") g.globalAlpha = pane.ramp(240, 400)
                    else g.globalAlpha = pane.ramp(360, T)              // dimensions, notes and the title block come last
                }
                if (n.kind === "group") group(g, n, z, role === "dimension" && (n.id === Results.selDim || n.id === pane.hot)); else prim(g, n, z, false)
                g.restore() }
        }
    }
    // the selected dimension: its box, and what it is bound to
    Rectangle { objectName: "dimSelected"; visible: !!pane.sel && !!pane.sel.bbox && pane.k >= 1; color: "transparent"; radius: 4
        border.color: (pane.paper ? Qt.rgba(0.04, 0.5, 0.63, 0.7) : Qt.rgba(0.24, 0.9, 1, 0.7)); border.width: 1
        x: pane.sel && pane.sel.bbox ? Math.round(pane.sx(pane.sel.bbox[0]) - 5) : 0; y: pane.sel && pane.sel.bbox ? Math.round(pane.sy(pane.sel.bbox[3]) - 5) : 0
        width: pane.sel && pane.sel.bbox ? Math.round((pane.sel.bbox[2] - pane.sel.bbox[0]) * pane.zoom + 10) : 0; height: pane.sel && pane.sel.bbox ? Math.round((pane.sel.bbox[3] - pane.sel.bbox[1]) * pane.zoom + 10) : 0 }

    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        property point last; property bool moved: false
        cursorShape: pressed && moved ? Qt.ClosedHandCursor : pane.hot !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
        onPressed: function (e) { pane.cut(); last = Qt.point(e.x, e.y); moved = false; editor.commitOrClose(false); pane.forceActiveFocus() }
        onPositionChanged: function (e) {
            if (pressed) { var dx = e.x - last.x, dy = e.y - last.y; if (!moved && Math.hypot(dx, dy) < 4) return; moved = true; pane.ox += dx; pane.oy += dy; pane._touched = true; last = Qt.point(e.x, e.y) }
            else { var h = pane.dimAt(e.x, e.y); pane.hot = h ? h.id : "" }
        }
        onReleased: function (e) { if (moved) return; var h = pane.dimAt(e.x, e.y); Results.selDim = h ? h.id : "" }
        onDoubleClicked: function (e) { var h = pane.dimAt(e.x, e.y); if (h && h.editable) pane.edit(h); else if (!h) { pane._touched = false; pane.fit() } }
        onWheel: function (w) { pane.cut(); var dy = w.angleDelta.y || w.pixelDelta.y; if (dy) pane.zoomAt(w.x, w.y, Math.pow(1.0016, dy)); w.accepted = true }
        onExited: pane.hot = ""
    }
    PinchHandler { target: null; onScaleChanged: function (delta) { pane.cut(); pane.zoomAt(centroid.position.x, centroid.position.y, delta) } }
    focus: visible
    Keys.onPressed: function (e) {
        pane.cut()
        if (e.key === Qt.Key_P && !(e.modifiers & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier))) { Results.paper = !Results.paper; e.accepted = true }
        else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && pane.sel && pane.sel.editable) { pane.edit(pane.sel); e.accepted = true }
        else if (e.key === Qt.Key_Escape && Results.selDim !== "") { Results.selDim = ""; e.accepted = true }
        else if (e.key === Qt.Key_0) { pane._touched = false; pane.fit(); e.accepted = true }
    }

    // typing over a dimension
    Rectangle {
        id: editor; objectName: "dimEditor"; visible: false
        property var dim: null
        function commitOrClose(commit) {
            if (!visible) return
            var v = Number(String(field.text).replace(",", "."))
            visible = false; pane.forceActiveFocus()
            if (commit && dim && isFinite(v) && v !== Number(dim.value)) Results.setDimension(dim.id, v)
        }
        width: 132; height: 30; radius: 9; color: Theme.plate3; border.color: Theme.focus
        x: dim && dim.bbox ? Math.round(Math.max(4, Math.min(pane.width - width - 4, pane.sx((dim.bbox[0] + dim.bbox[2]) / 2) - width / 2))) : 0
        y: dim && dim.bbox ? Math.round(Math.max(4, Math.min(pane.height - height - 4, pane.sy(dim.bbox[3]) - height - 8))) : 0
        TextInput { id: field; objectName: "dimField"; x: 10; width: 60; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink; font.family: Theme.mono; font.pixelSize: 13; selectByMouse: true
            selectionColor: Theme.alpha(Theme.datum, 0.35); selectedTextColor: Theme.ink; validator: DoubleValidator { notation: DoubleValidator.StandardNotation; locale: "C" }
            Keys.onReturnPressed: editor.commitOrClose(true); Keys.onEnterPressed: editor.commitOrClose(true); Keys.onEscapePressed: editor.commitOrClose(false) }
        Txt { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
            text: editor.dim ? "mm · " + editor.dim.param : "" }
    }

    // the sheet's own line: what it is, how it is known, the style, the selection
    Rectangle { objectName: "sheetFoot"; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 10
        width: Math.min(parent.width - 24, foot.implicitWidth + 28); height: 30; radius: 15; color: Theme.dark ? Qt.rgba(0.043, 0.043, 0.047, 0.86) : Qt.rgba(1, 1, 1, 0.9); border.color: Theme.rule2
        opacity: pane.k >= 1 ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        Row { id: foot; anchors.centerIn: parent; spacing: 10
            Txt { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; font.weight: Theme.wSemi; wrapMode: Text.NoWrap
                text: pane.d ? (pane.d.name || "Sheet") + " · " + F.pad(pane.d.rev) : "" }
            Ev { anchors.verticalCenter: parent.verticalCenter; text: pane.d ? Results.evWord(pane.d.evidence) : "" }
            Txt { objectName: "sheetSel"; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap
                text: Results.busy ? "committing…" : pane.sel ? (pane.sel.text || pane.sel.value) + (pane.sel.editable ? " · parameter " + pane.sel.param + " · Enter to change" : " · read off the model, not a parameter")
                    : Math.round(pane.zoom / 3.7795 * 100) + " % · wheel zooms, drag pans" }
            Rectangle { objectName: "paperToggle"; anchors.verticalCenter: parent.verticalCenter; width: pt.implicitWidth + 16; height: 22; radius: 11; color: pm.containsMouse ? Theme.washHover : Theme.alpha(Theme.lineBase, 0.06)
                Txt { id: pt; anchors.centerIn: parent; font.pixelSize: 11; wrapMode: Text.NoWrap; text: (pane.paper ? "Paper" : "Night") + "  P" }
                MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; onClicked: Results.paper = !Results.paper } } } }
}
