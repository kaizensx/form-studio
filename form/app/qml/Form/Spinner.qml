import QtQuick

// Indeterminate progress: the Form Studio mark building itself over and over, small. The origin holds still, the
// X arm, the stem and the middle arm grow out of it in turn, then fold back. Quick on purpose: a fast loop reads as a
// fast app. With reduced motion it is the mark with a slow breathing origin.
Item {
    id: sp
    property bool running: visible
    property int size: 14
    property color color: Theme.datum                   // the origin; the arms are the same colour, quieter
    readonly property real u: size / 48
    implicitWidth: size; implicitHeight: size
    width: size; height: size
    property real t: 0                                   // 0..1 through one build
    NumberAnimation on t { running: sp.running && !Theme.reduced; from: 0; to: 1; duration: 1300; loops: Animation.Infinite }
    function grow(a, b) { var k = Math.max(0, Math.min(1, (sp.t - a) / (b - a))); return 1 - Math.pow(1 - k, 3) }
    // build in 0..0.6, hold, fold back 0.75..0.95
    readonly property real back: 1 - grow(0.75, 0.95)
    readonly property bool calm: Theme.reduced || !running
    Item {
        x: (sp.size - 40 * sp.u) / 2; width: 40 * sp.u; height: sp.size
        Rectangle { width: 12 * sp.u; height: width; color: sp.color; antialiasing: true
            opacity: sp.calm ? 1 : 0.55 + 0.45 * Math.abs(Math.cos(sp.t * Math.PI)) }
        Rectangle { x: 14 * sp.u; height: 12 * sp.u; color: Theme.alpha(sp.color, 0.6); antialiasing: true
            width: 26 * sp.u * (sp.calm ? 1 : Math.min(sp.grow(0.0, 0.25), sp.back)) }
        Rectangle { y: 14 * sp.u; width: 12 * sp.u; color: Theme.alpha(sp.color, 0.6); antialiasing: true
            height: 34 * sp.u * (sp.calm ? 1 : Math.min(sp.grow(0.15, 0.4), sp.back)) }
        Rectangle { x: 12 * sp.u; y: 20 * sp.u; height: 12 * sp.u; color: Theme.alpha(sp.color, 0.6); antialiasing: true
            width: 20 * sp.u * (sp.calm ? 1 : Math.min(sp.grow(0.35, 0.6), sp.back)) }
    }
}
