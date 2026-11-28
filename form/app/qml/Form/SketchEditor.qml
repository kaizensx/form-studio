import QtQuick
import "F.js" as F

// The sketch editor (form/handsketch.py, form.sketch2d): draw a profile on a datum plane or a picked face, constrain
// it, give it dimensions, and extrude, cut or revolve it into a feature of the design's code. Every change is solved
// as you make it (the solver moves the points to satisfy what you said), with the degrees of freedom left in mono.
// A named dimension is a parameter of the design; changing it later re-solves the sketch.
//   props.mode   "new"  a design starts from this sketch (Start blank, by hand), on a datum plane
//                "add"  a new feature on the open design (props.plane: a datum, or a face from /sketch_plane with
//                       props.outline, the face's edges in the sketch's frame, drawn as a reference)
//                "edit" the sketch of an existing feature (props.feature, props.sketch)
// Lines drawn within 4 degrees of horizontal or vertical get that constraint; a click near a point joins it.
Item {
    id: se
    objectName: "sketchEditor"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property string mode: props.mode || "new"
    property string title: mode === "edit" ? "Edit the sketch of " + (Store.featureById(props.feature) || { label: props.feature }).label
                         : mode === "new" ? "Model it by hand" : "Sketch on " + (props.plane && props.plane.face ? "this face" : "a plane")
    property string note: "Millimetres. Draw, then constrain and dimension; the solver keeps what you said true."
    property int sheetWidth: Theme.sheetXl
    property int sheetHeight: 520
    implicitHeight: sheetHeight
    property var sk: ({ plane: { datum: "XY", offset: 0 }, points: [], fixed: [], entities: [], constraints: [] })
    property var sol: null
    property string tool: "line"               // line | rect | circle | select
    property int chainFrom: -1                 // the point a line being drawn starts at
    property var rubber: null                  // [x, y] under the pointer while drawing
    property var rectFrom: null
    property int sel: -1                       // the selected entity
    property int dragPt: -1
    property real k: 4.0
    property real ox: 80
    property real oy: 80
    property string kind: mode === "new" ? "extrude" : "extrude"
    property bool busy: false
    property string err: ""
    property Item firstFocus: area
    function clone(o) { return JSON.parse(JSON.stringify(o)) }

    Component.onCompleted: {
        if (props.sketch) sk = clone(props.sketch)
        else if (props.plane) sk = { plane: props.plane, points: [], fixed: [], entities: [], constraints: [] }
        if (mode === "edit" && props.values) {          // the literal holds the defaults; show the current values
            var s2 = clone(sk)
            for (var i = 0; i < s2.constraints.length; i++) {
                var c = s2.constraints[i], key = props.feature + "_" + c.name
                if (c.name && props.values[key] !== undefined) c.value = props.values[key]
            }
            sk = s2
        }
        fit(); solve()
    }
    // ── the view: millimetres to pixels, fitted to what is drawn (and the face's outline) ──
    function fit() {
        if (pad.width < 200 || pad.height < 200) return
        var xs = [], ys = []
        sk.points.forEach(function (p) { xs.push(p[0]); ys.push(p[1]) })
        ;(props.outline || []).forEach(function (pl) { pl.forEach(function (p) { xs.push(p[0]); ys.push(p[1]) }) })
        if (!xs.length) { xs = [-10, 70]; ys = [-10, 50] }
        var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys)
        var w = Math.max(20, x1 - x0), h = Math.max(20, y1 - y0)
        k = Math.min((pad.width - 120) / w, (pad.height - 100) / h)
        ox = (pad.width - w * k) / 2 - x0 * k
        oy = (pad.height - h * k) / 2 - y0 * k
        ink.requestPaint()
    }
    function px(p) { return Qt.point(ox + p[0] * k, pad.height - oy - p[1] * k) }
    function mm(x, y) { return [Math.round((x - ox) / k), Math.round((pad.height - y - oy) / k)] }   // 1 mm snap
    function nearPoint(x, y) {
        var best = -1, bd = 9
        for (var i = 0; i < sk.points.length; i++) { var q = px(sk.points[i]), d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = i } }
        return best
    }
    function nearEntity(x, y) {
        var best = -1, bd = 8
        for (var i = 0; i < sk.entities.length; i++) {
            var e = sk.entities[i], d = 1e9
            if (e.k === "line") {
                var a = px(sk.points[e.p[0]]), b = px(sk.points[e.p[1]]), vx = b.x - a.x, vy = b.y - a.y
                var t = Math.max(0, Math.min(1, ((x - a.x) * vx + (y - a.y) * vy) / Math.max(1e-9, vx * vx + vy * vy)))
                d = Math.hypot(a.x + t * vx - x, a.y + t * vy - y)
            } else if (e.k === "circle") { var c = px(sk.points[e.p[0]]); d = Math.abs(Math.hypot(c.x - x, c.y - y) - e.r * k) }
            if (d < bd) { bd = d; best = i }
        }
        return best
    }
    // ── edits of the sketch data (the same ops as edit_sketch) ──
    function pointIn(s2, m) {
        for (var i = 0; i < s2.points.length; i++) if (Math.abs(s2.points[i][0] - m[0]) < 1e-6 && Math.abs(s2.points[i][1] - m[1]) < 1e-6) return i
        s2.points.push(m)
        if (!s2.fixed.length) s2.fixed.push(s2.points.length - 1)       // the first point holds the sketch in place
        return s2.points.length - 1
    }
    function point(m) { var s2 = clone(sk); var i = pointIn(s2, m); return [s2, i] }
    function addLine(s2, a, b) {
        if (a === b) return s2
        s2.entities.push({ k: "line", p: [a, b] })
        var p = s2.points[a], q = s2.points[b], ang = Math.atan2(q[1] - p[1], q[0] - p[0]) * 180 / Math.PI
        ang = ((ang % 180) + 180) % 180
        if (Math.min(ang, 180 - ang) <= 4) s2.constraints.push({ k: "horizontal", e: [s2.entities.length - 1] })
        else if (Math.abs(ang - 90) <= 4) s2.constraints.push({ k: "vertical", e: [s2.entities.length - 1] })
        return s2
    }
    function set(s2) { sk = s2; solve() }
    function freeName(base) {
        var used = sk.constraints.map(function (c) { return c.name }), n = 1
        while (used.indexOf(base + n) >= 0) n++
        return base + n
    }
    function measure(i) {
        var e = sk.entities[i]
        if (!e) return 0
        if (e.k === "circle") return 2 * e.r
        var a = sk.points[e.p[0]], b = sk.points[e.p[1]]
        return Math.hypot(b[0] - a[0], b[1] - a[1])
    }
    function dimOf(i) { for (var j = 0; j < sk.constraints.length; j++) { var c = sk.constraints[j]; if ((c.k === "length" || c.k === "diameter") && c.e && c.e[0] === i) return j } return -1 }
    function dimension(i, value) {
        var s2 = clone(sk), j = dimOf(i), e = s2.entities[i]
        if (!e || !(value > 0)) return
        if (j >= 0) s2.constraints[j].value = value
        else s2.constraints.push(e.k === "circle" ? { k: "diameter", e: [i], value: value, name: freeName("d"), label: "Ø " + (sk.constraints.filter(function (c) { return c.k === "diameter" }).length + 1) }
                                                 : { k: "length", e: [i], value: value, name: freeName("l"), label: "Length " + (sk.constraints.filter(function (c) { return c.k === "length" }).length + 1) })
        set(s2)
    }
    function constrain(kind) {
        if (sel < 0) return
        var s2 = clone(sk)
        s2.constraints = s2.constraints.filter(function (c) { return !((c.k === "horizontal" || c.k === "vertical") && c.e && c.e[0] === se.sel) })
        s2.constraints.push({ k: kind, e: [sel] })
        set(s2)
    }
    function removeSel() {
        if (sel < 0) return
        var s2 = clone(sk), j = sel
        s2.entities.splice(j, 1)
        s2.constraints = s2.constraints.filter(function (c) { return !(c.e && c.e.indexOf(j) >= 0) })
            .map(function (c) { if (c.e) c.e = c.e.map(function (x) { return x > j ? x - 1 : x }); return c })
        sel = -1
        set(s2)
    }
    function solve() {
        Store.post("/sketch/solve", { sketch: sk }).then(function (r) {
            se.sol = r
            se.err = r.ok ? "" : r.error
            if (r.ok && r.points.length === se.sk.points.length) { var s2 = se.clone(se.sk); s2.points = r.points; se.sk = s2 }
            ink.requestPaint()
        }, function (e) { se.err = e.message || "The sketch does not solve." })
    }
    readonly property bool ready: !!sol && sol.ok && sol.closed && !busy && (kind !== "revolve" || (sel >= 0 && sk.entities[sel] && sk.entities[sel].k === "line"))
    function commit() {
        if (!ready) return
        busy = true; err = ""
        var depth = Number(depthField.text) || 0
        function done(r) { se.busy = false; Store.openSheet(null); if (r && r.job) Store.track(r.job) }
        function bad(e) { se.busy = false; se.err = e.message || "Refused."; if (e.hint) se.err += " " + e.hint }
        if (mode === "new") {
            Store.post("/start/sketch", { name: nameField.text || "Untitled design", sketch: sk, kind: kind === "revolve" ? "revolve" : "extrude", depth: depth,
                                          angle: 360, axis_entity: sel, purpose: Store.newPurposeEffective || "model" }).then(function (r) {
                return Store.reloadStudio().then(function () { return Store.open(r.id).then(function () { Store.track(r.job); Store.setStage("shape"); done(null) }) })
            }, bad)
            return
        }
        Store.ensureConv().then(function (cid) {
            var body = mode === "edit" ? { feature: props.feature, sketch: sk, conversation: cid, expect_head: Store.project.head }
                                       : { kind: kind, sketch: sk, depth: depth, angle: 360, axis_entity: sel, conversation: cid, expect_head: Store.project.head }
            return Store.ppost(mode === "edit" ? "/sketch" : "/model", body).then(function (r) {
                Store.toast("You " + (mode === "edit" ? "changed the sketch" : "added " + r.said.replace(/^Added /, "")),
                            "Written into the design's code as " + F.pad(r.head) + "; the checks run again.")
                Store._chatTick(); Store.refresh(true); done(r)
            }, bad)
        }, bad)
    }
    property bool typed: false                 // Return just set a dimension or a name: that is not "build it"
    function accept() { if (typed) { typed = false; return } if (area.activeFocus) commit() }

    property Component footerLeft: Component { Txt { objectName: "sketchStatus"; kind: "fine"; mono: true; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap
        color: se.err ? Theme.amber : Theme.ink2
        text: se.err ? se.err : !se.sol ? "" : !se.sk.entities.length ? "Draw with the line, rectangle or circle tool."
              : (se.sol.fully_constrained ? "fully constrained" : se.sol.dof + " degrees of freedom left") + " · " + (se.sol.closed ? "closed profile" : "not closed yet")
                + " · solved in " + F.fmt(se.sol.solve_ms, 2) + " ms" } }
    property Component footer: Component { Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { objectName: "sketchCommit"; kind: "primary"; icon: se.kind === "cut" ? "scissors" : "cuboid"; busy: se.busy; busyText: "Building…"; enabled: se.ready
            text: se.mode === "edit" ? "Save the sketch" : se.kind === "cut" ? "Cut" : se.kind === "revolve" ? "Revolve" : "Extrude"
            tip: "Writes it into the design's code as one feature, its dimensions as parameters, and builds it"; onClicked: se.commit() } } }

    // ── tools ──
    Column {
        id: rail; width: 40; spacing: 2
        Repeater {
            model: [{ id: "line", icon: "slash", label: "Line: click points, click the first to close", key: "L" }, { id: "rect", icon: "square", label: "Rectangle", key: "R" },
                    { id: "circle", icon: "circle", label: "Circle: centre, then radius", key: "C" }, { id: "select", icon: "mouse_pointer_click", label: "Select and drag", key: "V" }]
            RailBtn { required property var modelData; objectName: "sketchEdTool-" + modelData.id; icon: modelData.icon; label: modelData.label; keys: modelData.key
                active: se.tool === modelData.id; onClicked: { se.tool = modelData.id; se.chainFrom = -1; se.rubber = null; area.forceActiveFocus() } } }
    }
    // ── the pad: the sketch in the datum colour, the face it sits on as a reference ──
    Rectangle {
        id: pad; objectName: "sketchEdPad"
        x: rail.width + 12; width: parent.width - x - side.width - 20; height: se.sheetHeight - 8
        radius: Theme.rLg; color: Theme.glassWell; border.color: area.activeFocus ? Theme.alpha(Theme.datum, 0.45) : Theme.rule2; clip: true
        onWidthChanged: if (width > 200) se.fit()
        Canvas {
            id: ink; anchors.fill: parent
            onPaint: {
                var c = getContext("2d"); c.reset(); c.lineCap = "round"; c.lineJoin = "round"
                var step = 10 * se.k, o = se.px([0, 0])
                c.lineWidth = 1
                for (var gx = o.x % step; gx < width; gx += step) { c.strokeStyle = Theme.alpha(Theme.lineBase, 0.04); c.beginPath(); c.moveTo(Math.round(gx) + 0.5, 0); c.lineTo(Math.round(gx) + 0.5, height); c.stroke() }
                for (var gy = o.y % step; gy < height; gy += step) { c.strokeStyle = Theme.alpha(Theme.lineBase, 0.04); c.beginPath(); c.moveTo(0, Math.round(gy) + 0.5); c.lineTo(width, Math.round(gy) + 0.5); c.stroke() }
                c.strokeStyle = Theme.alpha(Theme.datum, 0.3); c.beginPath(); c.moveTo(o.x, 0); c.lineTo(o.x, height); c.moveTo(0, o.y); c.lineTo(width, o.y); c.stroke()
                c.setLineDash([4, 4]); c.strokeStyle = Theme.ink3; c.lineWidth = 1.2
                ;(se.props.outline || []).forEach(function (pl) { c.beginPath(); pl.forEach(function (p, i) { var q = se.px(p); if (i) c.lineTo(q.x, q.y); else c.moveTo(q.x, q.y) }); c.stroke() })
                c.setLineDash([])
                for (var i = 0; i < se.sk.entities.length; i++) {
                    var e = se.sk.entities[i]
                    c.lineWidth = i === se.sel ? 3 : 2
                    c.strokeStyle = i === se.sel ? Theme.datumHi : Theme.datum
                    if (e.construction) c.setLineDash([6, 4])
                    c.beginPath()
                    if (e.k === "line") { var a = se.px(se.sk.points[e.p[0]]), b = se.px(se.sk.points[e.p[1]]); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y) }
                    else if (e.k === "circle") { var cc = se.px(se.sk.points[e.p[0]]); c.moveTo(cc.x + e.r * se.k, cc.y); c.arc(cc.x, cc.y, e.r * se.k, 0, 2 * Math.PI, false) }
                    c.stroke(); c.setLineDash([])
                }
                if (se.chainFrom >= 0 && se.rubber) { var r0 = se.px(se.sk.points[se.chainFrom]), r1 = se.px(se.rubber); c.strokeStyle = Theme.alpha(Theme.datum, 0.6); c.lineWidth = 1.5; c.beginPath(); c.moveTo(r0.x, r0.y); c.lineTo(r1.x, r1.y); c.stroke() }
                if (se.rectFrom && se.rubber) { var q0 = se.px(se.rectFrom), q1 = se.px(se.rubber); c.strokeStyle = Theme.alpha(Theme.datum, 0.6); c.lineWidth = 1.5; c.strokeRect(Math.min(q0.x, q1.x), Math.min(q0.y, q1.y), Math.abs(q1.x - q0.x), Math.abs(q1.y - q0.y)) }
                c.fillStyle = Theme.datum
                for (var j = 0; j < se.sk.points.length; j++) { var pp = se.px(se.sk.points[j]); c.beginPath(); c.arc(pp.x, pp.y, se.sk.fixed.indexOf(j) >= 0 ? 4 : 2.5, 0, 2 * Math.PI); c.fill() }
            }
        }
        // the dimensions, in mono, beside what they drive
        Repeater { model: se.sk.constraints
            Rectangle { required property var modelData; required property int index
                readonly property var e: modelData.e && (modelData.k === "length" || modelData.k === "diameter") ? se.sk.entities[modelData.e[0]] : null
                visible: !!e
                readonly property point m: !e ? Qt.point(0, 0) : e.k === "circle" ? se.px([se.sk.points[e.p[0]][0] + e.r * 0.7, se.sk.points[e.p[0]][1] + e.r * 0.7])
                                                 : se.px([(se.sk.points[e.p[0]][0] + se.sk.points[e.p[1]][0]) / 2, (se.sk.points[e.p[0]][1] + se.sk.points[e.p[1]][1]) / 2])
                x: m.x - width / 2; y: m.y - height - 4; width: dt.implicitWidth + 10; height: 18; radius: Theme.rXs; color: Theme.plate; border.color: Theme.alpha(Theme.datum, 0.5)
                Txt { id: dt; anchors.centerIn: parent; mono: true; font.pixelSize: 11; color: Theme.datum
                    text: (parent.modelData.k === "diameter" ? "Ø" : "") + F.fmt(parent.modelData.value, 1) } } }
        MouseArea {
            id: area; anchors.fill: parent; hoverEnabled: true; focus: true; acceptedButtons: Qt.LeftButton
            onPressed: function (m) {
                forceActiveFocus()
                var at = se.mm(m.x, m.y), np = se.nearPoint(m.x, m.y)
                if (np >= 0) at = se.sk.points[np].slice()
                if (se.tool === "select") {
                    se.dragPt = np
                    if (np < 0) { se.sel = se.nearEntity(m.x, m.y); ink.requestPaint() }
                    return
                }
                if (se.tool === "rect") { se.rectFrom = at; se.rubber = at; return }
                if (se.tool === "circle") { se.rectFrom = at; se.rubber = at; return }
                // line: a point; a line from the last one; the first point again closes and ends the chain
                var r = se.point(at), s2 = r[0], i = r[1]
                if (se.chainFrom >= 0) { s2 = se.addLine(s2, se.chainFrom, i); se.chainFrom = (np >= 0 && se.sk.entities.length && np !== se.chainFrom && se.isChainStart(np)) ? -1 : i }
                else se.chainFrom = i
                se.set(s2)
            }
            onPositionChanged: function (m) {
                var at = se.mm(m.x, m.y)
                if (se.tool === "select" && pressed && se.dragPt >= 0) {
                    var s2 = se.clone(se.sk); s2.points[se.dragPt] = [(m.x - se.ox) / se.k, (pad.height - m.y - se.oy) / se.k]; se.set(s2); return
                }
                se.rubber = at; ink.requestPaint()
            }
            onReleased: function (m) {
                var at = se.mm(m.x, m.y)
                if ((se.tool === "rect" || se.tool === "circle") && se.rectFrom) {
                    var a = se.rectFrom; se.rectFrom = null
                    if (se.tool === "rect" && Math.abs(at[0] - a[0]) >= 1 && Math.abs(at[1] - a[1]) >= 1) {
                        var s2 = se.clone(se.sk)
                        var idx = [[a[0], a[1]], [at[0], a[1]], [at[0], at[1]], [a[0], at[1]]].map(function (p) { return se.pointIn(s2, p) })
                        for (var q = 0; q < 4; q++) s2 = se.addLine(s2, idx[q], idx[(q + 1) % 4])
                        se.set(s2)
                    } else if (se.tool === "circle") {
                        var rad = Math.round(Math.hypot(at[0] - a[0], at[1] - a[1]) * 2) / 2
                        if (rad >= 0.5) { var rc = se.point(a), s3 = rc[0]; s3.entities.push({ k: "circle", p: [rc[1]], r: rad }); se.set(s3) }
                    }
                }
                se.dragPt = -1
            }
            Keys.onEscapePressed: { se.chainFrom = -1; se.rubber = null; ink.requestPaint() }
            Keys.onDeletePressed: se.removeSel()
            Keys.onPressed: function (ev) {
                var m = { "L": "line", "R": "rect", "C": "circle", "V": "select" }[ev.text.toUpperCase()]
                if (m && !(ev.modifiers & (Qt.ControlModifier | Qt.MetaModifier))) { se.tool = m; se.chainFrom = -1; ev.accepted = true }
            }
        }
    }
    function isChainStart(i) {                 // a point that already starts a line: clicking it again closes the loop
        for (var j = 0; j < sk.entities.length; j++) { var e = sk.entities[j]; if (e.k === "line" && (e.p[0] === i || e.p[1] === i)) return true }
        return false
    }
    // ── beside the pad: the plane, what is selected, the dimensions, and what to make of it ──
    Column {
        id: side; anchors.right: parent.right; width: 250; spacing: 10
        Txt { kind: "cap"; text: "Plane" }
        Seg { objectName: "sketchDatum"; visible: !se.sk.plane.face; model: ["XY", "XZ", "YZ"]; value: se.sk.plane.datum || "XY"
            onPicked: function (v) { var s2 = se.clone(se.sk); s2.plane = { datum: v, offset: 0 }; se.sk = s2 } }
        Txt { visible: !!se.sk.plane.face; kind: "fine"; tone: 2; width: parent.width; text: "On the picked face (its outline dashed). It is found again on every rebuild." }
        Field { id: nameField; objectName: "sketchName"; visible: se.mode === "new"; width: parent.width; placeholder: "Name, e.g. Wall bracket" }
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Txt { kind: "cap"; text: se.sel >= 0 && se.sk.entities[se.sel] ? (se.sk.entities[se.sel].k === "circle" ? "Circle" : "Line") + " " + (se.sel + 1) : "Selection" }
        Txt { visible: se.sel < 0; kind: "fine"; tone: 2; width: parent.width; text: "Select a line or a circle (V) to dimension or constrain it." }
        Row { visible: se.sel >= 0; spacing: 6
            Field { id: dimField; objectName: "sketchDim"; width: 110; numeric: true; unit: "mm"
                text: se.sel >= 0 ? F.fmt(se.dimOf(se.sel) >= 0 ? se.sk.constraints[se.dimOf(se.sel)].value : se.measure(se.sel), 2) : ""
                onAccepted: function (t) { se.typed = true; se.dimension(se.sel, Number(t)); area.forceActiveFocus() } }
            Btn { objectName: "sketchDimAdd"; small: true; text: se.dimOf(se.sel) >= 0 ? "Set" : "Dimension"; onClicked: se.dimension(se.sel, Number(dimField.text)) } }
        Flow { visible: se.sel >= 0 && se.sk.entities[se.sel] && se.sk.entities[se.sel].k === "line"; width: parent.width; spacing: 6
            Btn { small: true; kind: "quiet"; text: "Horizontal"; onClicked: se.constrain("horizontal") }
            Btn { small: true; kind: "quiet"; text: "Vertical"; onClicked: se.constrain("vertical") }
            Btn { small: true; kind: "quiet"; icon: "x"; text: "Delete"; onClicked: se.removeSel() } }
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Txt { kind: "cap"; text: "Make" ; visible: se.mode !== "edit" }
        Seg { objectName: "sketchKind"; visible: se.mode !== "edit"
            model: se.mode === "new" ? [{ value: "extrude", text: "Extrude" }, { value: "revolve", text: "Revolve" }]
                                     : [{ value: "extrude", text: "Extrude" }, { value: "cut", text: "Cut" }, { value: "revolve", text: "Revolve" }]
            value: se.kind; onPicked: function (v) { se.kind = v } }
        Row { visible: se.mode !== "edit" && se.kind !== "revolve"; spacing: 8
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; text: se.kind === "cut" ? "Depth (0 = through)" : "Depth" }
            Field { id: depthField; objectName: "sketchDepth"; width: 100; numeric: true; unit: "mm"; text: se.kind === "cut" ? "0" : "10" } }
        Txt { visible: se.kind === "revolve" && se.mode !== "edit"; kind: "fine"; tone: 2; width: parent.width; text: "Select the line it turns about (360°)." }
        Txt { objectName: "sketchDofLine"; width: parent.width; kind: "fine"; mono: true; tone: 2
            text: !se.sol || !se.sol.ok ? "" : F.plural(se.sol.dims.filter(function (d) { return !!d.name }).length, "dimension") + " as parameters" }
    }
}
