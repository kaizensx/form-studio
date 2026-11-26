import QtQuick

// A change: label, from → to.
// `tick`: a numeric `to` counts up (or down) to its value over Theme.cross instead of jumping, starting from `start`
// (default: `from`), so a consequence reads as a movement. With reduced motion it is set at once. `settled(value)`
// reports where it landed, so a list rebuilt on every draft can start the next tick where this one ended.
Item {
    id: d
    property string label: ""
    property string from: ""
    property string to: ""
    property string unit: ""
    property color tint: Theme.ink
    property bool tick: false
    property string start: from
    signal settled(real value)
    readonly property bool _num: d.tick && /^-?\d+(\.\d+)?$/.test(d.to)
    readonly property int _dp: d.to.indexOf(".") < 0 ? 0 : d.to.length - d.to.indexOf(".") - 1
    readonly property real _target: d._num ? parseFloat(d.to) : 0
    property real shown: NaN
    function _go(fromValue) {
        run.stop()
        if (!d._num) return
        var s = parseFloat(fromValue)
        if (isNaN(s) || Theme.reduced || s === d._target) { d.shown = d._target; d.settled(d._target); return }
        run.from = s; run.to = d._target; run.start()
    }
    on_TargetChanged: if (ready) d._go(isNaN(d.shown) ? d.start : d.shown)
    property bool ready: false
    Component.onCompleted: { ready = true; d._go(d.start) }
    NumberAnimation { id: run; target: d; property: "shown"; duration: Theme.move(Theme.cross)
        easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut
        onFinished: d.settled(d._target) }
    width: parent ? parent.width : 0; implicitHeight: 20
    Txt { text: d.label; tone: 2; font.pixelSize: 12; anchors.left: parent.left; anchors.right: v.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap }
    Row {
        id: v; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
        Txt { text: d.from; mono: true; tone: 3; font.pixelSize: 12; visible: d.from !== "" }
        Txt { text: "→"; tone: 4; font.pixelSize: 12; visible: d.from !== "" }
        Txt { objectName: "deltaTo"; text: (d._num && !isNaN(d.shown) ? d.shown.toFixed(d._dp) : d.to) + (d.unit ? " " + d.unit : ""); mono: true; font.pixelSize: 12; color: d.tint }
    }
}
