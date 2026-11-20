import QtQuick
import "F.js" as F

// Drag a face, change the parameter behind it (form/dragface.py). Cmd-drag (Ctrl-drag on Windows and Linux) on a face
// of the part: the engine finds the parameter that moves that face (one rebuild per parameter, measured along the
// face's normal), then the pointer's travel along the normal on screen becomes the parameter's value. The value goes
// into the draft (Store.setParam), so the part rebuilds as it moves and the draft's impact (volume, interfaces, fit)
// is the usual one. Releasing keeps the draft; commit or discard it as with any other change.
// Every other press passes through to the viewport underneath (orbit, pick, measure, annotate).
Item {
    id: fd
    objectName: "faceDrag"
    required property var vp
    property bool active: false              // a drag is under way
    property bool asking: false              // waiting for the engine to say which parameter
    property var info: null                  // the engine's answer: { best, candidates, feature_label, text }
    property real travel: 0                  // mm along the face's normal
    property real value: NaN
    property real from: NaN
    property point down
    property point at
    property var dir: null                   // screen pixels per mm along the face's normal
    readonly property var best: info && info.best ? info.best : null

    function valueFor(mm) {                  // dragface.value_for: travel → value, on its step, in its range
        var b = best
        var v = b.value + mm / b.rate
        if (b.step) v = Math.round(v / b.step) * b.step
        return Math.min(b.max, Math.max(b.min, v))
    }
    function impact() {                      // the draft's computed volume change, when the preview has it
        var pv = Store.preview
        if (!pv || !pv.impact || !pv.impact.metrics) return ""
        var m = pv.impact.metrics.filter(function (x) { return x.key === "volume" })[0]
        if (!m) return ""
        var d = m.to - m.from
        return "Volume " + F.fmt(m.to, 1) + " cm³ (" + (d >= 0 ? "+" : "−") + F.fmt(Math.abs(d), 2) + ")"
    }

    MouseArea {
        id: area
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: function (e) {
            var cmd = !!(e.modifiers & Qt.ControlModifier)
            if (!cmd || !fd.vp.interactive || fd.vp.measuring || fd.vp.selecting || fd.vp.mapShown || !Store.pid) { e.accepted = false; return }
            var h = fd.vp.hitAt(e.x, e.y)
            if (!h) { e.accepted = false; return }
            fd.down = Qt.point(e.x, e.y); fd.at = fd.down
            fd.travel = 0; fd.info = null; fd.value = NaN; fd.from = NaN; fd.active = true; fd.asking = true
            // which way the face's normal points on screen, in pixels per millimetre
            var s = Qt.vector3d(h.shown[0], h.shown[1], h.shown[2]).plus(fd.vp.shift)
            var n = Qt.vector3d(h.normal[0], h.normal[1], h.normal[2])
            var a = fd.vp._px(s), b = fd.vp._px(s.plus(n.times(10)))
            var dx = a && b ? (b.x - a.x) / 10 : 0, dy = a && b ? (b.y - a.y) / 10 : 0
            // a face seen square-on: pull up to push it out
            fd.dir = Math.hypot(dx, dy) > 0.15 / Math.max(1e-6, fd.vp.mmPerPx) ? Qt.point(dx, dy) : Qt.point(0, -1 / Math.max(1e-6, fd.vp.mmPerPx))
            Store.ppost("/drag_face", { at: h.at, normal: h.normal }).then(function (r) {
                fd.asking = false
                if (!fd.active) return
                fd.info = r
                if (r.best) { fd.from = r.best.value; fd.apply() }
            }, function (err) { fd.asking = false; fd.info = { text: err && err.message ? err.message : "This face could not be traced to a parameter." } })
        }
        onPositionChanged: function (e) {
            if (!fd.active) return
            fd.at = Qt.point(e.x, e.y)
            var d = fd.dir, mx = e.x - fd.down.x, my = e.y - fd.down.y
            fd.travel = (mx * d.x + my * d.y) / (d.x * d.x + d.y * d.y)
            fd.apply()
        }
        onReleased: { fd.active = false; hide.restart() }
        onCanceled: { fd.active = false; hide.restart() }
    }
    function apply() {
        if (!best) return
        var v = valueFor(travel)
        if (v === value) return
        value = v
        Store.setParam(best.key, v)
    }
    Timer { id: hide; interval: 2600; onTriggered: if (!fd.active) fd.info = null }

    // the readout beside the pointer: what is changing, from what to what, and what it does
    Rectangle {
        id: tag
        objectName: "faceDragTag"
        visible: fd.active || !!fd.info
        x: Math.min(fd.at.x + 16, fd.width - width - 8); y: Math.max(8, fd.at.y - height - 14)
        width: col.implicitWidth + 18; height: col.implicitHeight + 12; radius: Theme.rXs
        color: Theme.alpha(Theme.plate2, 0.96); border.color: Theme.alpha(Theme.datum, 0.55)
        Column {
            id: col
            x: 9; y: 6; spacing: 2
            Txt {
                objectName: "faceDragLabel"
                kind: "fine"; tone: 1; mono: !!fd.best; wrapMode: Text.NoWrap; color: Theme.datum
                text: fd.asking ? "Finding what drives this face…"
                    : fd.best ? fd.best.label + "  " + F.fmt(fd.from, 2) + " → " + F.fmt(isNaN(fd.value) ? fd.from : fd.value, 2) + " " + (fd.best.unit || "")
                    : fd.info && fd.info.text ? fd.info.text : ""
            }
            Txt {
                kind: "fine"; tone: 3; wrapMode: Text.NoWrap
                visible: !!fd.best
                text: fd.best ? (fd.info.feature_label || "") + " · " + F.fmt(Math.abs(fd.best.rate), 2) + " mm per " + (fd.best.unit || "unit")
                                + (fd.impact() ? " · " + fd.impact() : "") : ""
            }
        }
    }
}
