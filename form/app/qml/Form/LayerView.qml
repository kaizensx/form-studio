import QtQuick
import "F.js" as F

// The slice, one layer at a time: the toolpaths the slicer would send. Simulated, not a print.
// Replaces the 3D viewport while Store.layers is set.
Item {
    id: root
    readonly property var meta: Store.layers          // { count, z, types, n }
    readonly property int n: meta ? meta.n : -1
    property var cur: null                          // the layer being drawn: { index, count, z, paths }
    property var box: null                            // [x0, x1, y0, y1] in mm, fixed by the first layer drawn
    property var cache: ({})                          // plain object, mutated in place on purpose
    readonly property int foot: bar.height + 96 + 14  // kept clear at the bottom: control bar and pipeline strip
    readonly property bool bridge: !!cur && cur.paths.some(function (p) { return p.t === "Bridge" })

    function typeColor(t) {
        switch (t) {
        case "Outer wall": return Theme.ink
        case "Inner wall": return Theme.ink3
        case "Sparse infill": return Theme.amber
        case "Internal solid infill": return Theme.blueprint
        case "Top surface": return Theme.datum
        case "Bottom surface": return Qt.darker(Theme.datum, 1.7)
        case "Bridge": case "Overhang wall": case "Floating vertical shell": return Theme.signal
        case "Gap infill": return Theme.ink4
        case "Support": case "Support interface": return Theme.pass
        }
        return Theme.ink2
    }
    function show(l) {
        if (!box) {
            var x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9
            for (var k = 0; k < l.paths.length; k++) {
                var p = l.paths[k].p
                for (var i = 0; i < p.length; i += 2) { x0 = Math.min(x0, p[i]); x1 = Math.max(x1, p[i]); y0 = Math.min(y0, p[i + 1]); y1 = Math.max(y1, p[i + 1]) }
            }
            if (x1 >= x0) box = [x0 - 14, x1 + 14, y0 - 14, y1 + 14]
        }
        cur = l
        cv.requestPaint()
    }
    function load() {
        if (n < 0) return
        var want = n
        if (cache[want]) { show(cache[want]); return }
        Store.pget("/layers?n=" + want).then(function (l) {
            if (!root || !root.cache) return
            root.cache[want] = l
            if (root.n === want) root.show(l)
        }, Store.fail)
    }
    onNChanged: load()
    Component.onCompleted: load()

    Rectangle { anchors.fill: parent; color: Theme.plate }

    Canvas {
        id: cv
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onAvailableChanged: if (available) requestPaint()
        onPaint: {
            var c = getContext("2d")
            c.reset()
            var L = root.cur, b = root.box
            if (!L || !b || width < 40 || height - root.foot < 40) return
            var x0 = b[0], x1 = b[1], y0 = b[2], y1 = b[3]
            var top = 54, availH = height - root.foot - top
            var s = Math.min((width - 32) / (x1 - x0), availH / (y1 - y0))
            var ox = (width - (x1 - x0) * s) / 2, oy = top + (availH - (y1 - y0) * s) / 2
            function X(x) { return ox + (x - x0) * s }
            function Y(y) { return oy + (y1 - y) * s }
            var g
            c.strokeStyle = Theme.rule; c.lineWidth = 1
            c.beginPath()
            for (g = Math.ceil(x0 / 10) * 10; g <= x1; g += 10) { c.moveTo(Math.round(X(g)) + 0.5, Y(y0)); c.lineTo(Math.round(X(g)) + 0.5, Y(y1)) }
            for (g = Math.ceil(y0 / 10) * 10; g <= y1; g += 10) { c.moveTo(X(x0), Math.round(Y(g)) + 0.5); c.lineTo(X(x1), Math.round(Y(g)) + 0.5) }
            c.stroke()
            c.lineWidth = Math.max(0.8, 0.42 * s * 0.9); c.lineCap = "round"; c.lineJoin = "round"
            // one stroke per type, in a fixed order so the walls stay on top
            var by = {}, order = [], k, i, p
            for (k = 0; k < L.paths.length; k++) { var t = L.paths[k].t; if (!by[t]) { by[t] = []; order.push(t) } by[t].push(L.paths[k].p) }
            for (k = 0; k < order.length; k++) {
                c.strokeStyle = root.typeColor(order[k])
                c.beginPath()
                var set = by[order[k]]
                for (var j = 0; j < set.length; j++) {
                    p = set[j]
                    for (i = 0; i < p.length; i += 2) { if (i) c.lineTo(X(p[i]), Y(p[i + 1])); else c.moveTo(X(p[i]), Y(p[i + 1])) }
                }
                c.stroke()
            }
        }
    }

    // top left: way back, and what this is
    Row { x: 16; y: 14; spacing: 10
        Btn { icon: "arrow_left"; text: "Back to 3D"; onClicked: Store.showLayers(false) }
        Tag { text: "simulated"; anchors.verticalCenter: parent.verticalCenter }
        Txt { kind: "fine"; text: "toolpaths from the slicer · grid 10 mm"; anchors.verticalCenter: parent.verticalCenter } }

    // bottom centre: layer control
    Rectangle {
        id: bar
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 96
        width: Math.min(parent.width - 32, 620); height: bc.implicitHeight + 24
        radius: Theme.rMd; color: Theme.alpha(Theme.plate1, 0.92); border.color: Theme.rule
        Column { id: bc; x: 16; y: 12; width: parent.width - 32; spacing: 8
            Row { anchors.horizontalCenter: parent.horizontalCenter
                Txt { mono: true; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap
                    text: root.meta ? "Layer " + (root.n + 1) + " / " + root.meta.count
                        + (root.cur && root.cur.index === root.n ? " · z " + F.fmt(root.cur.z) + " mm · " : " · loading…") : "" }
                Txt { mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                    visible: !!root.cur && root.cur.index === root.n
                    color: root.bridge ? Theme.signal : Theme.ink2; font.weight: root.bridge ? 600 : 420
                    text: root.cur ? (root.bridge ? "bridge here" : F.plural(root.cur.paths.length, "path")) : "" } }
            Beam { width: parent.width; from: 0; to: root.meta ? Math.max(1, root.meta.count - 1) : 1; step: 1; value: Math.max(0, root.n)
                onMoved: function (v) { Store.setLayer(Math.round(v)) } }
            Flow { width: parent.width; spacing: 12
                Repeater { model: root.meta ? root.meta.types : []
                    Row { required property string modelData; spacing: 5
                        Rectangle { width: 10; height: 3; radius: 1.5; color: root.typeColor(modelData); anchors.verticalCenter: parent.verticalCenter }
                        Txt { kind: "fine"; text: modelData; wrapMode: Text.NoWrap } } } }
        }
    }
}
