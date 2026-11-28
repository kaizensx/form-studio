import QtQuick
import QtQuick3D
import "Labels.js" as Labels

// What a result says on the part, as flat labels pinned to its points: the peak with its number, the load's size at
// the tail of its arrow, a lock on each held face, "left out" on a singular zone, a finding's rule, a gouge, a bend's
// angle, the smallest gap. Every point and every word is the engine's (Results.r).
// The points are projected when the camera, the view's size or the result changes, never per frame: a still view
// costs nothing. Then the labels are seated (Labels.js): beside their point on the first side where they cover
// neither another label nor a marker, a ring or a lock.
Item {
    id: root
    property var port: null
    property var lay3: null
    property var camera: null
    readonly property var r: Results.onPart ? Results.r : null
    readonly property string kind: r ? r.kind : ""
    property int tick: 0
    function bump() { tick++ }
    function later() { Qt.callLater(bump) }       // the camera's position and rotation change together: project once
    Connections { target: root.camera; function onScenePositionChanged() { root.later() } function onSceneRotationChanged() { root.later() } function onFieldOfViewChanged() { root.later() } }
    Connections { target: root.port; function onShiftChanged() { root.bump() } function onTouched() { Results.cut() } }
    onWidthChanged: bump(); onHeightChanged: bump()
    function at(p) {                        // a design-frame point → view pixels, or null
        if (!p || p.length !== 3 || !port) return null
        var t = tick, s = port.shift
        return port._px(Qt.vector3d(p[0] + s.x, p[1] + s.y, p[2] + s.z))
    }
    // ── seating: every Pill registers; after a projection they are placed clear of the markers and of each other ──
    property var _pills: []
    function _join(p) { _pills.push(p); seatLater() }
    function _leave(p) { var i = _pills.indexOf(p); if (i >= 0) _pills.splice(i, 1); seatLater() }
    function seatLater() { seatTimer.restart() }
    Timer { id: seatTimer; interval: 0; onTriggered: root.seat() }      // (a Timer, not Qt.callLater: it goes with the labels)
    onTickChanged: seatLater()
    onRChanged: seatLater()
    Connections { target: Results; function onLitRuleChanged() { root.seatLater() } }
    function _marks() {                    // the markers' rectangles in view pixels, with a little room round them
        var out = [], i, q, k = root.kind, r = root.r
        function add(p, s) { if (p) out.push({ kind: "keep", w: s + 4, h: s + 4, cands: [{ x: p.x - s / 2 - 2, y: p.y - s / 2 - 2 }] }) }
        if (!r) return out
        if (k === "dfm") for (i = 0; i < Math.min(24, (r.markers || []).length); i++) add(at(r.markers[i].at), Results.litRule === r.markers[i].rule ? 12 : 9)
        if (k === "cam" && lay3 && lay3.stockOn && lay3.setup) for (i = 0; i < Math.min(12, lay3.setup.marks.length); i++) add(at(lay3.setup.marks[i].at), 9)
        if (k === "field") {
            if (r.peak && lay3 && lay3.deformNow === 0) add(at(r.peak.at), 15)
            for (i = 0; i < (r.glyphs || []).length; i++) if (r.glyphs[i].role === "fixture") add(at(r.glyphs[i].at), 20)
        }
        return out
    }
    function seat() {
        var items = _marks(), pills = [], i, pl
        for (i = 0; i < _pills.length; i++) {
            pl = _pills[i]
            if (!pl || !pl.want || !pl.p) { if (pl && pl.placed) pl.placed = null; continue }
            var x = pl.p.x, y = pl.p.y, w = pl.width, h = pl.height, dx = pl.dx, dy = pl.dy
            // its own side first, then the other side, then under and over its point
            var c = [{ x: x + dx, y: y + dy - h / 2 }, { x: x - dx - w, y: y + dy - h / 2 }, { x: x + Math.abs(dx), y: y + Math.abs(dy) - h / 2 + h },
                     { x: x - Math.abs(dx) - w, y: y + Math.abs(dy) - h / 2 + h }, { x: x - w / 2, y: y + 12 }, { x: x - w / 2, y: y - h - 12 }]
            items.push({ kind: "pin", w: w, h: h, cands: c.map(function (q) { return { x: Math.round(q.x), y: Math.round(q.y) } }), prev: pl.cand })
            pills.push(pl)
        }
        if (!pills.length) return
        var out = Labels.place(items, { l: 4, t: 4, r: width - 4, b: height - 4 }), off = items.length - pills.length
        for (i = 0; i < pills.length; i++) {
            var o = out[off + i], q = { x: Math.max(4, Math.min(width - pills[i].width - 4, o.x)), y: Math.max(4, Math.min(height - pills[i].height - 4, o.y)) }
            pills[i].cand = o.c
            if (!pills[i].placed || pills[i].placed.x !== q.x || pills[i].placed.y !== q.y) pills[i].placed = q
        }
    }
    readonly property color plate: Theme.dark ? Qt.rgba(0.043, 0.043, 0.047, 0.88) : Qt.rgba(1, 1, 1, 0.92)
    readonly property real show: Results.settle

    component Pill: Rectangle {
        property string text: ""
        property string sub: ""
        property color tint: Theme.ink
        property var p: null                 // where it points, in view pixels
        property real dx: 12
        property real dy: -10
        property bool shown: true            // what the instance asks: whether it shows at all
        readonly property bool want: shown && !!p && text !== "" && parent && parent.visible
        property var placed: null            // where seat() put it
        property int cand: -1
        visible: want
        x: placed ? placed.x : p ? Math.round(Math.max(4, Math.min(root.width - width - 4, p.x + dx))) : 0
        y: placed ? placed.y : p ? Math.round(Math.max(4, Math.min(root.height - height - 4, p.y + dy - height / 2))) : 0
        onWantChanged: root.seatLater(); onWidthChanged: root.seatLater()
        Component.onCompleted: root._join(this); Component.onDestruction: root._leave(this)
        width: row.implicitWidth + 18; height: 24; radius: 12
        color: root.plate; border.color: Theme.rule2
        Row { id: row; anchors.centerIn: parent; spacing: 6
            Text { text: parent.parent.text; color: parent.parent.tint; font.family: Theme.mono; font.pixelSize: 12; font.weight: Theme.wMedium; renderType: Theme.textRender }
            Text { visible: text !== ""; text: parent.parent.sub; color: Theme.ink2; font.family: Theme.sans; font.pixelSize: 12; renderType: Theme.textRender } }
    }

    // ── strength ──
    Item { anchors.fill: parent; visible: root.kind === "field"; opacity: root.show
        // the peak: a ring where it is, a hairline to its number
        readonly property var pk: root.kind === "field" && root.r.peak && root.lay3 && root.lay3.deformNow === 0 ? root.at(root.r.peak.at) : null
        Rectangle { objectName: "peakRing"; visible: !!parent.pk; width: 15; height: 15; radius: 7.5; color: "transparent"; border.width: 1.5; border.color: "#ffffff"
            x: parent.pk ? Math.round(parent.pk.x - 7.5) : 0; y: parent.pk ? Math.round(parent.pk.y - 7.5) : 0 }
        Canvas { id: leader; anchors.fill: parent; visible: !!parent.pk
            readonly property var a: parent.pk; readonly property real bx: peakPill.x; readonly property real by: peakPill.y + peakPill.height / 2
            onAChanged: requestPaint(); onBxChanged: requestPaint(); onByChanged: requestPaint()
            onPaint: { var c = getContext("2d"); c.reset(); if (!a) return
                var dx = bx - a.x, dy = by - a.y, d = Math.hypot(dx, dy); if (d < 12) return
                c.strokeStyle = Qt.rgba(1, 1, 1, 0.55); c.lineWidth = 1; c.beginPath(); c.moveTo(a.x + dx / d * 8, a.y + dy / d * 8); c.lineTo(bx, by); c.stroke() } }
        Pill { id: peakPill; objectName: "peakLabel"; p: parent.pk; dx: 64; dy: 58
            text: root.kind === "field" && root.r.peak ? root.r.peak.text : ""; sub: "peak" }
        Repeater { model: root.kind === "field" ? root.r.glyphs : []
            Item { id: gl; required property var modelData
                readonly property var p: root.at(modelData.at)
                // a load: its size at the tail of the arrow
                readonly property var tail: modelData.role === "load" && modelData.vector ? root.at([modelData.at[0] - modelData.vector[0] * root.r.mesh.diag_mm * 0.2,
                    modelData.at[1] - modelData.vector[1] * root.r.mesh.diag_mm * 0.2, modelData.at[2] - modelData.vector[2] * root.r.mesh.diag_mm * 0.2]) : null
                Pill { objectName: "loadLabel"; shown: gl.modelData.role === "load"; p: gl.tail; dx: -width / 2; dy: -16; text: gl.modelData.label }
                // a held face: a lock
                Rectangle { objectName: "fixtureGlyph"; visible: gl.modelData.role === "fixture" && !!gl.p; width: 20; height: 20; radius: 6; color: root.plate; border.color: Theme.rule2
                    x: gl.p ? Math.round(gl.p.x - 10) : 0; y: gl.p ? Math.round(gl.p.y - 10) : 0
                    Icon { anchors.centerIn: parent; name: "lock"; size: 11; color: "#3ee6ff" }
                    HoverHandler { id: fh } Tip { show: fh.hovered; text: "Held: " + gl.modelData.label + ", " + Math.round(gl.modelData.area_mm2) + " mm²" } } } }
        // singular zones: named where they are, with why they are not in the verdict
        Repeater { model: root.kind === "field" ? root.r.singular : []
            Item { id: sg; required property var modelData
                readonly property var p: root.lay3 && root.lay3.deformNow === 0 ? root.at(modelData.at) : null
                Pill { objectName: "singularLabel"; p: sg.p; dx: 10; dy: -22; text: "left out"; tint: Theme.ink2
                    HoverHandler { id: sh } Tip { show: sh.hovered; text: (sg.modelData.label || "A singular zone") + ": " + (sg.modelData.why || "") } } } }
    }

    // ── manufacturability: the findings, the pull, the parting line ──
    Item { anchors.fill: parent; visible: root.kind === "dfm"
        Repeater { model: root.kind === "dfm" ? root.r.markers.slice(0, 24) : []
            Item { id: mk; required property var modelData; required property int index
                readonly property var p: root.at(modelData.at)
                readonly property bool lit: Results.litRule === modelData.rule
                readonly property color c: modelData.status === "fail" ? Theme.signal : modelData.status === "warn" ? Theme.amber : Theme.datum
                Rectangle { objectName: "dfmMarker"; visible: !!mk.p; width: mk.lit ? 12 : 9; height: width; radius: width / 2; color: mk.c; border.width: 1.5; border.color: root.plate
                    x: mk.p ? Math.round(mk.p.x - width / 2) : 0; y: mk.p ? Math.round(mk.p.y - height / 2) : 0
                    HoverHandler { id: mh } }
                readonly property bool first: { var ms = root.r.markers; for (var i = 0; i < index; i++) if (ms[i].rule === modelData.rule) return false; return true }
                readonly property string word: { var t = String(modelData.label).split(":")[0].split(" (")[0]; return t.length > 34 ? t.slice(0, 32) + "…" : t }
                Pill { objectName: "dfmLabel"; shown: mh.hovered || (mk.first && (mk.lit || Results.litRule === "")); p: mk.p; dx: 12; dy: -14; tint: mk.c; z: mh.hovered ? 2 : 0
                    text: mk.word } } }
        Pill { objectName: "pullLabel"; p: root.kind === "dfm" && root.lay3 && root.lay3.pullAt ? (root.tick, root.at([root.lay3.pullAt.tip.x, root.lay3.pullAt.tip.y, root.lay3.pullAt.tip.z])) : null
            dx: 10; dy: 0; text: root.kind === "dfm" && root.r.pull ? "pull " + root.r.pull.name : "" }
    }

    // ── CNC: what the simulation marked ──
    Item { anchors.fill: parent; visible: root.kind === "cam" && !!root.lay3 && root.lay3.stockOn
        Repeater { model: root.kind === "cam" && root.lay3 && root.lay3.setup ? root.lay3.setup.marks.slice(0, 12) : []
            Item { id: cm; required property var modelData; required property int index
                readonly property var p: root.at(modelData.at)
                readonly property color c: modelData.kind === "gouge" || modelData.kind === "collision" ? Theme.signal : Theme.amber
                Rectangle { objectName: "camMark"; visible: !!cm.p; width: 9; height: 9; radius: 4.5; color: cm.c; border.width: 1.5; border.color: root.plate
                    x: cm.p ? Math.round(cm.p.x - 4.5) : 0; y: cm.p ? Math.round(cm.p.y - 4.5) : 0
                    HoverHandler { id: cmh } }
                readonly property bool first: { var ms = root.lay3.setup.marks; for (var i = 0; i < index; i++) if (ms[i].kind === modelData.kind) return false; return true }
                Pill { objectName: "camLabel"; shown: cm.first || cmh.hovered; p: cm.p; dx: 10; dy: -14; tint: cm.c; text: cm.modelData.label } } }
    }

    // ── tolerance stack-up: each link's length at its middle, the gap's own lit ──
    Item { anchors.fill: parent; visible: root.kind === "stack"
        Repeater { model: root.kind === "stack" ? root.r.draw.segments : []
            Item { id: sk; required property var modelData
                readonly property var mid: [(modelData.from[0] + modelData.to[0]) / 2, (modelData.from[1] + modelData.to[1]) / 2, (modelData.from[2] + modelData.to[2]) / 2]
                Pill { objectName: sk.modelData.kind === "gap" ? "stackGapLabel" : "stackLinkLabel"; p: root.at(sk.mid); dx: 12; dy: 0
                    tint: sk.modelData.kind === "gap" ? "#3ee6ff" : Theme.ink
                    shown: sk.modelData.kind === "gap" || Math.abs(sk.modelData.length) > 1e-6
                    text: Results.fmt(sk.modelData.length, "mm"); sub: sk.modelData.kind === "gap" ? "gap" : (sk.modelData.part || "") } } }
    }

    // ── sheet metal: each bend's angle and side ──
    Item { anchors.fill: parent; visible: root.kind === "flat"
        Repeater { model: root.kind === "flat" ? root.r.bends : []
            Item { id: bn; required property var modelData
                readonly property var p: root.lay3 ? (root.lay3.foldK, root.at(root.lay3.bendAnchor(modelData))) : null
                Pill { objectName: "bendNote"; p: bn.p; dx: -width / 2; dy: -16; tint: bn.modelData.direction === "down" ? Theme.amber : Theme.datum
                    text: Math.round(bn.modelData.angle * 10) / 10 + "° " + bn.modelData.direction; sub: "R " + Math.round(bn.modelData.r * 100) / 100 } } }
    }

    // ── motion: the smallest gap of the frame shown ──
    Item { anchors.fill: parent; visible: root.kind === "motion"
        readonly property var g: root.lay3 ? root.lay3.gap : null
        Pill { objectName: "gapLabel"; p: parent.g && parent.g.at ? (Store.pose, root.at(parent.g.at)) : null; dx: 12; dy: -14
            tint: parent.g && parent.g.state !== "clear" ? Theme.signal : Theme.ink
            text: parent.g && parent.g.mm !== null && parent.g.mm !== undefined ? Results.fmt(parent.g.mm, "mm") : ""; sub: "gap" }
    }
}
