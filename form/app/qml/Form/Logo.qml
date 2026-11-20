import QtQuick
import QtQuick.Shapes
import "LogoPaths.js" as LP

// The Form Studio mark and wordmark, drawn as vectors in Theme colours (sources and rules: brand/README.md).
// The mark is the letter F as a coordinate frame: top arm X, stem Y, and the joint, in datum, is the origin.
// `size` is the mark's height: a multiple of 12 (12, 24, 36) puts every edge on a whole pixel at 1×, of 6 (18) at 2×.
// The wordmark's cap height is size / 1.5, centred on the mark, 0.42 × size away (as brand/lockup.svg).
Item {
    id: lg
    property int size: 12
    property bool mark: true
    property bool word: true
    property color part: Theme.markPart
    property color origin: Theme.datum
    property color ink: Theme.ink          // "Form"
    property color ink2: Theme.ink2        // "Studio", lighter

    readonly property real u: size / 48                       // one unit of the 64 grid
    readonly property real cut: size >= 24 ? 2 * u : 0        // the hairline between origin and part; it would only blur below 24 px
    readonly property real markW: mark ? 40 * u : 0
    readonly property real cap: size / 1.5
    readonly property real k: cap / LP.capHeight
    readonly property real gap: mark && word ? 0.42 * size : 0
    readonly property real wordW: word ? LP.width * k : 0

    implicitWidth: Math.ceil(markW + gap + wordW)
    implicitHeight: size
    baselineOffset: Math.round((size - cap) / 2 + cap)

    Item {
        visible: lg.mark
        width: lg.markW; height: lg.size
        Rectangle { width: 12 * lg.u; height: 12 * lg.u; color: lg.origin }                                         // origin
        Rectangle { x: 12 * lg.u + lg.cut; width: 28 * lg.u - lg.cut; height: 12 * lg.u; color: lg.part }          // X: top arm
        Rectangle { y: 12 * lg.u + lg.cut; width: 12 * lg.u; height: 36 * lg.u - lg.cut; color: lg.part }          // Y: stem
        Rectangle { x: 12 * lg.u; y: 20 * lg.u; width: 20 * lg.u; height: 12 * lg.u; color: lg.part }              // middle arm
    }
    Shape {
        visible: lg.word
        x: lg.markW + lg.gap; y: Math.round((lg.size - lg.cap) / 2)
        width: lg.wordW; height: lg.cap
        preferredRendererType: Shape.CurveRenderer
        ShapePath { fillColor: lg.ink; strokeColor: "transparent"; fillRule: ShapePath.WindingFill; scale: Qt.size(lg.k, lg.k)
            PathSvg { path: LP.form } }
        ShapePath { fillColor: lg.ink2; strokeColor: "transparent"; fillRule: ShapePath.WindingFill; scale: Qt.size(lg.k, lg.k)
            PathSvg { path: LP.studio } }
    }
}
