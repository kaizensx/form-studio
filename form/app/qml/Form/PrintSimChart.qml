import QtQuick

// One bar per layer (slicer time, or extrusion path length). It is also the scrubber: press or drag to go to a layer.
// A tick above a bar marks a layer with a bridge (bridge colour) or an overhang wall (overhang colour).
Item {
    id: ch
    property var values: []                  // one number per layer
    property var bridges: []                 // layer indices
    property var overhangs: []
    property int current: 0                   // the layer being printed
    property real fraction: 0                // how much of it is done
    property color bridgeColor: Theme.signal
    property color overhangColor: Theme.amber
    property int hover: -1
    signal scrub(int layer)
    implicitHeight: 52
    readonly property int count: values ? values.length : 0
    function at(x) { return count ? Math.max(0, Math.min(count - 1, Math.floor(x / width * count))) : -1 }
    onValuesChanged: cv.requestPaint()
    onCurrentChanged: cv.requestPaint()
    onBridgesChanged: cv.requestPaint()
    onOverhangsChanged: cv.requestPaint()
    onHoverChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onAvailableChanged: if (available) requestPaint()
        onPaint: {
            var c = getContext("2d")
            c.reset()
            var n = ch.count
            if (!n || width < 10) return
            var top = 7, h = height - top, max = 0, i
            // scale to the typical layer: a few very long layers (the first ones) are cut off and capped, not allowed to flatten the rest
            var sorted = ch.values.slice().sort(function (a, b) { return a - b })
            max = Math.min(sorted[n - 1], sorted[Math.floor((n - 1) * 0.9)] * 1.6)
            if (max <= 0) max = sorted[n - 1] > 0 ? sorted[n - 1] : 1
            var bw = width / n, gap = bw >= 4 ? 1 : 0
            var mark = {}, k
            for (k = 0; k < ch.overhangs.length; k++) mark[ch.overhangs[k]] = 1
            for (k = 0; k < ch.bridges.length; k++) mark[ch.bridges[k]] = 2
            for (i = 0; i < n; i++) {
                var x = Math.floor(i * bw), w = Math.max(1, Math.floor((i + 1) * bw) - x - gap)
                var over = ch.values[i] > max * 1.001
                var bh = Math.max(1, Math.round(Math.min(1, ch.values[i] / max) * (h - 5)))
                c.fillStyle = i === ch.current ? Theme.datum : i === ch.hover ? Theme.ink : i < ch.current ? Theme.ink3 : Theme.plate4
                c.fillRect(x, top + h - bh, w, bh)
                if (over) c.fillRect(x, top + h - bh - 3, w, 2)          // a cap: this bar is taller than the scale
                if (mark[i]) { c.fillStyle = mark[i] === 2 ? ch.bridgeColor : ch.overhangColor; c.fillRect(x, 0, w, 3) }
            }
        }
    }
    // where in the current layer the nozzle is: a hairline that moves without repainting the bars
    Rectangle {
        visible: ch.count > 0
        x: Math.round((ch.current + ch.fraction) / Math.max(1, ch.count) * ch.width); y: 5; width: 1; height: parent.height - 5
        color: Theme.ink
    }
    MouseArea {
        anchors.fill: parent; hoverEnabled: true; preventStealing: true; cursorShape: Qt.PointingHandCursor
        onPressed: function (e) { ch.scrub(ch.at(e.x)) }
        onPositionChanged: function (e) { ch.hover = ch.at(e.x); if (pressed) ch.scrub(ch.hover) }
        onExited: ch.hover = -1
    }
}
