import QtQuick
import FormNative
import QtQuick.Controls
import "F.js" as F
import "Sketch.js" as S

// The sketch pad: draw the part's outline in millimetres. Lines, rectangles, circles, arcs, freehand strokes and
// dimensions, snapped to a 5 mm grid and to the points already drawn (hold Alt to draw freely). The agent receives
// the shapes as structured geometry (form/sketch.py) and the picture, so it can extrude or revolve them faithfully.
// A dimension you type is "stated" and overrides the drawn length.
Item {
    id: sk
    objectName: "sketchSheet"
    property string title: "Sketch it"
    property string note: "Millimetres, y up. The agent gets the shapes with their sizes, and the picture."
    property int sheetWidth: Theme.sheetXl
    property int sheetHeight: 560
    implicitHeight: sheetHeight
    property string tool: "rect"                  // line | rect | circle | arc | path | dim
    property var prims: []
    property var redo: []
    property var draft: null                      // the shape being drawn
    property var hoverPt: null                    // { p, kind } under the pointer, snapped
    property real k: 3.2                          // pixels per millimetre
    property real ox: 40; property real oy: 40    // where 0,0 is, from the pad's bottom left, in pixels
    property string view: "top"
    property string intent: ""
    property bool sending: false
    property int editingDim: -1                   // the dimension whose value is being typed
    readonly property real grid: 5
    property Item firstFocus: padArea

    function push(p) { prims = prims.concat([p]); redo = []; ink.requestPaint() }
    function undo() { if (!prims.length) return; redo = redo.concat([prims[prims.length - 1]]); prims = prims.slice(0, -1); editingDim = -1; ink.requestPaint() }
    function again() { if (!redo.length) return; prims = prims.concat([redo[redo.length - 1]]); redo = redo.slice(0, -1); ink.requestPaint() }
    function clearAll() { if (!prims.length) return; redo = prims.slice().reverse(); prims = []; editingDim = -1; ink.requestPaint() }
    function toMm(x, y) { return [(x - ox) / k, (pad.height - y - oy) / k] }
    function toPx(p) { return Qt.point(ox + p[0] * k, pad.height - oy - p[1] * k) }
    function snapAt(x, y, free) { return S.snap(toMm(x, y), prims, grid, 8 / k, free) }
    function done() {
        if (!prims.length || sending) return
        sending = true
        var json = S.toJson(prims, { grid: grid, view: view, intent: intent, depth: parseFloat(depth.text) || 0, notes: notes.text })
        var file = Bridge.tempFile("sketch.png")
        pad.grabToImage(function (res) {
            res.saveToFile(file)
            Store.attachSketch(json, Bridge.fileUrl(file)).then(function (r) {
                sk.sending = false
                if (r) { Store.openSheet(null); Store.startFocus++ }
            })
        })
    }
    property bool typed: false                    // Return just ended a dimension's value: it is not "add to the design"
    function accept() { if (typed) { typed = false; return } if (padArea.activeFocus) done() }

    Shortcut { sequences: [StandardKey.Undo]; onActivated: sk.undo() }
    Shortcut { sequences: [StandardKey.Redo]; onActivated: sk.again() }

    property Component footerLeft: Component { Txt { kind: "fine"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap
        text: sk.prims.length ? F.plural(sk.prims.length, "shape") + " · snapped to " + sk.grid + " mm and to your points · Alt draws freely" : "Drag on the pad to draw. Wheel zooms." } }
    property Component footer: Component { Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { objectName: "sketchDone"; kind: "primary"; icon: "check"; text: "Add to the design"; busy: sk.sending; enabled: sk.prims.length > 0; keys: "Return"
            tip: "Attaches the shapes and the picture to Home's composer"; onClicked: sk.done() } } }

    // ── tools ──
    Column {
        id: rail; width: 40; spacing: 2
        Repeater {
            model: [{ id: "line", icon: "slash", label: "Line", key: "L" }, { id: "rect", icon: "square", label: "Rectangle", key: "R" },
                    { id: "circle", icon: "circle", label: "Circle", key: "C" }, { id: "arc", icon: "spline", label: "Arc: centre, start, end", key: "A" },
                    { id: "path", icon: "pencil_line", label: "Freehand", key: "F" }, { id: "dim", icon: "ruler_dim", label: "Dimension", key: "D" }]
            RailBtn { required property var modelData; objectName: "sketchTool-" + modelData.id; icon: modelData.icon; label: modelData.label; keys: modelData.key
                active: sk.tool === modelData.id; onClicked: { sk.tool = modelData.id; sk.draft = null; padArea.forceActiveFocus() } } }
        Item { width: 1; height: 10 }
        RailBtn { objectName: "sketchUndo"; icon: "undo_2"; label: "Undo"; keys: "Ctrl+Z"; enabled: sk.prims.length > 0; onClicked: sk.undo() }
        RailBtn { icon: "redo_2"; label: "Redo"; keys: "Ctrl+Shift+Z"; enabled: sk.redo.length > 0; onClicked: sk.again() }
        RailBtn { icon: "eraser"; label: "Clear"; enabled: sk.prims.length > 0; onClicked: sk.clearAll() }
    }

    // ── the pad ──
    Rectangle {
        id: pad; objectName: "sketchPad"
        x: rail.width + 12; width: parent.width - x - side.width - 20; height: sk.sheetHeight - 8
        radius: Theme.rLg; color: Theme.glassWell; border.color: padArea.activeFocus ? Theme.alpha(Theme.datum, 0.45) : Theme.rule2; clip: true
        // grid: 5 mm lines, 25 mm stronger, the axes in datum
        Canvas {
            id: gridC; anchors.fill: parent
            onPaint: {
                var c = getContext("2d"); c.reset()
                var step = sk.grid * sk.k
                for (var i = -Math.ceil(sk.ox / step); sk.ox + i * step < width; i++) {
                    var x = Math.round(sk.ox + i * step) + 0.5
                    c.strokeStyle = i === 0 ? Theme.alpha(Theme.datum, 0.35) : i % 5 === 0 ? Theme.rule : Theme.alpha(Theme.lineBase, 0.03)
                    c.beginPath(); c.moveTo(x, 0); c.lineTo(x, height); c.stroke()
                }
                for (var j = -Math.ceil(sk.oy / step); sk.oy + j * step < height; j++) {
                    var y = Math.round(height - sk.oy - j * step) + 0.5
                    c.strokeStyle = j === 0 ? Theme.alpha(Theme.datum, 0.35) : j % 5 === 0 ? Theme.rule : Theme.alpha(Theme.lineBase, 0.03)
                    c.beginPath(); c.moveTo(0, y); c.lineTo(width, y); c.stroke()
                }
            }
            Connections { target: sk; function onKChanged() { gridC.requestPaint() } function onOxChanged() { gridC.requestPaint() } function onOyChanged() { gridC.requestPaint() } }
            onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
        }
        // the drawing
        Canvas {
            id: ink; anchors.fill: parent
            function shape(c, p, dash) {
                c.beginPath()
                if (p.type === "line" || p.type === "dim") { var a = sk.toPx(p.a), b = sk.toPx(p.b); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y) }
                else if (p.type === "rect") { var r0 = sk.toPx(p.a), r1 = sk.toPx(p.b); c.rect(Math.min(r0.x, r1.x), Math.min(r0.y, r1.y), Math.abs(r1.x - r0.x), Math.abs(r1.y - r0.y)) }
                else if (p.type === "circle") { var cc = sk.toPx(p.c); c.moveTo(cc.x + p.r * sk.k, cc.y); c.arc(cc.x, cc.y, p.r * sk.k, 0, 2 * Math.PI, false) }
                else if (p.type === "arc") { var ac = sk.toPx(p.c), s0 = -p.start_deg * Math.PI / 180, s1 = -p.end_deg * Math.PI / 180
                    c.moveTo(ac.x + p.r * sk.k * Math.cos(s0), ac.y + p.r * sk.k * Math.sin(s0)); c.arc(ac.x, ac.y, p.r * sk.k, s0, s1, true) }
                else if (p.type === "path") { for (var i = 0; i < p.points.length; i++) { var q = sk.toPx(p.points[i]); if (i === 0) c.moveTo(q.x, q.y); else c.lineTo(q.x, q.y) } }
                c.stroke()
                if (p.type === "dim") {                    // ticks at both ends and the value at the middle
                    var d0 = sk.toPx(p.a), d1 = sk.toPx(p.b), ang = Math.atan2(d1.y - d0.y, d1.x - d0.x) + Math.PI / 2
                    c.beginPath(); [d0, d1].forEach(function (e) { c.moveTo(e.x - 6 * Math.cos(ang), e.y - 6 * Math.sin(ang)); c.lineTo(e.x + 6 * Math.cos(ang), e.y + 6 * Math.sin(ang)) }); c.stroke()
                }
            }
            onPaint: {
                var c = getContext("2d"); c.reset(); c.lineCap = "round"; c.lineJoin = "round"
                sk.prims.forEach(function (p) { c.lineWidth = p.type === "dim" ? 1.2 : 2; c.strokeStyle = p.type === "dim" ? Theme.amber : Theme.ink; shape(c, p) })
                if (sk.draft) { c.lineWidth = 2; c.strokeStyle = Theme.datum; shape(c, sk.draft) }
            }
            Connections { target: sk; function onKChanged() { ink.requestPaint() } function onDraftChanged() { ink.requestPaint() } function onPrimsChanged() { ink.requestPaint() } }
            onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
        }
        // dimension values on the drawing
        Repeater { model: sk.prims
            Rectangle { required property var modelData; required property int index
                visible: modelData.type === "dim" && sk.editingDim !== index
                readonly property point m: modelData.type === "dim" ? sk.toPx([(modelData.a[0] + modelData.b[0]) / 2, (modelData.a[1] + modelData.b[1]) / 2]) : Qt.point(0, 0)
                x: m.x - width / 2; y: m.y - height - 6; width: dl.implicitWidth + 10; height: 18; radius: Theme.rXs; color: Theme.plate; border.color: Theme.alpha(Theme.amber, 0.5)
                Txt { id: dl; anchors.centerIn: parent; mono: true; font.pixelSize: 11; color: Theme.amber
                    text: parent.modelData.type !== "dim" ? "" : (parent.modelData.value !== null && parent.modelData.value !== undefined ? F.fmt(parent.modelData.value, 1) : F.fmt(S.dist(parent.modelData.a, parent.modelData.b), 1)) + " mm" + (parent.modelData.label ? " " + parent.modelData.label : "") }
                MouseArea { anchors.fill: parent; onClicked: sk.editingDim = parent.index } } }
        // typing a dimension's value
        Field {
            id: dimField; objectName: "sketchDimValue"; visible: sk.editingDim >= 0; width: 110; numeric: true; unit: "mm"; z: 3
            readonly property var d: sk.editingDim >= 0 && sk.editingDim < sk.prims.length ? sk.prims[sk.editingDim] : null
            readonly property point m: d ? sk.toPx([(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]) : Qt.point(0, 0)
            x: Math.max(4, Math.min(pad.width - width - 4, m.x - width / 2)); y: Math.max(4, m.y - height - 6)
            placeholder: d ? F.fmt(S.dist(d.a, d.b), 1) : ""
            onVisibleChanged: if (visible) { text = d && d.value !== null && d.value !== undefined ? String(d.value) : ""; input.forceActiveFocus() }
            onAccepted: function (t) {
                var v = parseFloat(String(t).replace(",", ".")), l = sk.prims.slice(), d = Object.assign({}, l[sk.editingDim])
                d.value = isNaN(v) || v <= 0 ? null : v; l[sk.editingDim] = d; sk.prims = l; sk.editingDim = -1
                sk.typed = true; Qt.callLater(function () { sk.typed = false }); padArea.forceActiveFocus()
            }
            Keys.onEscapePressed: { sk.editingDim = -1; padArea.forceActiveFocus() } }
        // the snap point and what is being drawn, read aloud
        Rectangle { visible: !!sk.hoverPt; readonly property point q: sk.hoverPt ? sk.toPx(sk.hoverPt.p) : Qt.point(0, 0)
            x: q.x - 4; y: q.y - 4; width: 8; height: 8; radius: sk.hoverPt && sk.hoverPt.kind === "point" ? 4 : 1; color: "transparent"
            border.width: 1.5; border.color: sk.hoverPt && sk.hoverPt.kind === "point" ? Theme.datum : Theme.ink3 }
        Rectangle { visible: !!sk.draft || !!sk.hoverPt; readonly property point q: sk.hoverPt ? sk.toPx(sk.hoverPt.p) : Qt.point(0, 0)
            x: Math.min(pad.width - width - 6, q.x + 14); y: Math.max(6, q.y - 30); width: rl.implicitWidth + 12; height: 20; radius: Theme.rXs; color: Theme.alpha(Theme.plate3, 0.95); border.color: Theme.rule2
            Txt { id: rl; objectName: "sketchReadout"; anchors.centerIn: parent; mono: true; font.pixelSize: 11
                text: sk.draft ? S.describe(sk.draft) : sk.hoverPt ? F.fmt(sk.hoverPt.p[0], 1) + ", " + F.fmt(sk.hoverPt.p[1], 1) + " mm" : "" } }
        // empty: what to do
        Column { visible: !sk.prims.length && !sk.draft; anchors.centerIn: parent; spacing: 6
            Icon { name: "pen_tool"; size: 22; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { tone: 3; text: "Draw the outline you have in mind"; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { kind: "fine"; tone: 4; text: "Then add dimensions for the sizes that matter"; anchors.horizontalCenter: parent.horizontalCenter } }

        MouseArea {
            id: padArea; anchors.fill: parent; hoverEnabled: true; focus: true; activeFocusOnTab: true
            preventStealing: true              // the sheet scrolls; a stroke on the pad must not become a scroll
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
            cursorShape: Qt.CrossCursor
            property var start: null
            property var panFrom: null
            function free(m) { return !!(m & Qt.AltModifier) }
            onPositionChanged: function (e) {
                if (panFrom) { sk.ox = panFrom.ox + e.x - panFrom.x; sk.oy = panFrom.oy - (e.y - panFrom.y); return }
                var s = sk.snapAt(e.x, e.y, free(e.modifiers)); sk.hoverPt = s
                var t = sk.tool, a = start
                if (t === "arc" && sk.draft && sk.draft.stage === 2) { var d2 = Object.assign({}, sk.draft); d2.end_deg = S.angleDeg(d2.c, s.p); sk.draft = d2; return }
                if (!a) return                                   // start is set by the press and cleared by the release
                if (t === "line" || t === "dim") sk.draft = { type: t, a: a, b: s.p, value: null, label: "" }
                else if (t === "rect") sk.draft = { type: "rect", a: a, b: s.p }
                else if (t === "circle") sk.draft = { type: "circle", c: a, r: S.dist(a, s.p) }
                else if (t === "arc") sk.draft = { type: "arc", c: a, r: S.dist(a, s.p), start_deg: S.angleDeg(a, s.p), end_deg: S.angleDeg(a, s.p) + 1, stage: 1 }
                else if (t === "path") { var raw = sk.toMm(e.x, e.y), pts = sk.draft ? sk.draft.points.concat([[S.r2(raw[0]), S.r2(raw[1])]]) : [a]; sk.draft = { type: "path", points: S.thin(pts, 0.8) } }
            }
            onExited: sk.hoverPt = null
            onPressed: function (e) {
                forceActiveFocus()
                if (e.button === Qt.MiddleButton) { panFrom = { x: e.x, y: e.y, ox: sk.ox, oy: sk.oy }; return }
                sk.editingDim = -1
                var s = sk.snapAt(e.x, e.y, free(e.modifiers))
                if (sk.tool === "arc" && sk.draft && sk.draft.stage === 2) {           // the third click ends the arc
                    var d = Object.assign({}, sk.draft); delete d.stage; d.end_deg = S.angleDeg(d.c, s.p); sk.draft = null
                    if (d.r > 0.5) sk.push(d); start = null; return
                }
                start = s.p; sk.draft = null
            }
            onReleased: finish()
            onCanceled: finish()               // the pointer was taken away mid-stroke: keep what was drawn
            function finish() {
                if (panFrom) { panFrom = null; return }
                var d = sk.draft
                if (sk.tool === "arc" && d && d.stage === 1) { var d2 = Object.assign({}, d); d2.stage = 2; sk.draft = d2; return }
                sk.draft = null; start = null
                if (!d) return
                var big = d.type === "circle" ? d.r > 0.5 : d.type === "path" ? d.points.length > 1 : S.dist(d.a, d.b) > 0.5
                if (!big) return
                sk.push(d)
                if (d.type === "dim") sk.editingDim = sk.prims.length - 1          // type the value now, or press Esc to keep the drawn length
            }
            onWheel: function (w) {                                                  // zoom about the pointer
                var before = sk.toMm(w.x, w.y)
                sk.k = Math.max(1, Math.min(12, sk.k * (w.angleDelta.y > 0 ? 1.12 : 1 / 1.12)))
                sk.ox = w.x - before[0] * sk.k; sk.oy = pad.height - w.y - before[1] * sk.k
            }
            Keys.onPressed: function (e) {
                var keys = { 76: "line", 82: "rect", 67: "circle", 65: "arc", 70: "path", 68: "dim" }
                if (!(e.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) && keys[e.key]) { sk.tool = keys[e.key]; sk.draft = null; e.accepted = true }
                else if (e.key === Qt.Key_Escape && sk.draft) { sk.draft = null; e.accepted = true }
                else if ((e.key === Qt.Key_Backspace || e.key === Qt.Key_Delete) && sk.prims.length) { sk.undo(); e.accepted = true }
            }
        }
    }

    // ── how it becomes 3D, and the list ──
    Column {
        id: side; width: 230; anchors.right: parent.right; spacing: 14
        Column { width: parent.width; spacing: 6
            Txt { kind: "cap"; text: "Seen from" }
            Seg { objectName: "sketchView"; value: sk.view; onPicked: function (v) { sk.view = v }
                model: [{ value: "top", text: "Top" }, { value: "front", text: "Front" }, { value: "side", text: "Side" }] } }
        Column { width: parent.width; spacing: 6
            Txt { kind: "cap"; text: "Becomes 3D by" }
            Seg { value: sk.intent; onPicked: function (v) { sk.intent = v }
                model: [{ value: "extrude", text: "Extrude" }, { value: "revolve", text: "Revolve" }, { value: "", text: "Agent decides" }] }
            Field { id: depth; objectName: "sketchDepth"; width: parent.width; numeric: true; unit: "mm"; visible: sk.intent === "extrude"; placeholder: "Thickness, if you know it" } }
        Column { width: parent.width; spacing: 6
            Txt { kind: "cap"; text: "Notes for the agent" }
            Area { id: notes; width: parent.width; minLines: 3; placeholder: "e.g. the hole takes an M4 screw; the left edge sits against the wall" } }
        Column { width: parent.width; spacing: 3; visible: sk.prims.length > 0
            Txt { kind: "cap"; text: "Shapes" }
            Repeater { model: sk.prims.slice(-8)
                Txt { required property var modelData; kind: "fine"; tone: 2; width: side.width; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: S.describe(modelData) } } }
    }
}
