import QtQuick

// Slider drawn as a caliper beam: thin rule, a jaw you drag. `base` marks the committed value.
Item {
    id: s
    property real from: 0
    property real to: 1
    property real step: 0.1
    property real value: 0
    property real base: NaN
    property color tint: Theme.ink
    signal moved(real value)
    implicitHeight: 18; implicitWidth: 160
    function _pos(v) { return to > from ? (Math.min(to, Math.max(from, v)) - from) / (to - from) * (width - 10) : 0 }
    Rectangle { y: 8; width: parent.width; height: 2; radius: 1; color: Theme.rule2 }
    Rectangle { y: 8; height: 2; radius: 1; color: Theme.alpha(s.tint, 0.55)
        visible: !isNaN(s.base) && Math.abs(s.base - s.value) > 1e-9
        x: Math.min(s._pos(s.base), s._pos(s.value)) + 5; width: Math.abs(s._pos(s.base) - s._pos(s.value)) }
    Rectangle { visible: !isNaN(s.base); x: s._pos(s.base) + 4; y: 4; width: 2; height: 10; radius: 1; color: Theme.ink4 }
    Rectangle {
        id: jaw; x: s._pos(s.value); y: 2; width: 10; height: 14; radius: 2
        color: ma.pressed || ma.containsMouse ? Theme.datum : s.tint
        scale: ma.pressed ? 1.15 : 1
        Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: Theme.fast } }
    }
    MouseArea {
        id: ma; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; preventStealing: true
        function set(mx) {
            var t = Math.min(1, Math.max(0, (mx - 4 - 5) / (s.width - 10)))
            var v = s.from + t * (s.to - s.from)
            if (s.step > 0) v = Math.round(v / s.step) * s.step
            v = Math.min(s.to, Math.max(s.from, parseFloat(v.toFixed(6))))
            if (v !== s.value) s.moved(v)
        }
        onPressed: function (e) { set(e.x) }
        onPositionChanged: function (e) { if (pressed) set(e.x) }
    }
}
