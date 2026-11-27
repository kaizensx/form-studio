import QtQuick
import QtQuick.Shapes

// A gradient that does not band: a scrim, a scroll shadow, a pool of light. Up to four stops, down the item
// (the default), across it (`across`) or out from its centre to its edges (`radial`: an ellipse when the item is
// not square).
//
//   Fade { width: 300; height: 18; c0: Theme.alpha(Theme.shade, 0.26); c1: "transparent" }
//   Fade { radial: true; c0: Theme.alpha(Theme.key, 0.3); c1: Theme.alpha(Theme.key, 0) }
//
// A Rectangle's gradient is written straight to an 8-bit screen: between near tones, or as a faint veil over a dark
// room, that shows as bands. This one is worked out per pixel by a shader (shaders/fade.frag) and dithered by one
// 8-bit step. The dither is fixed to the pixels, so a still gradient is never redrawn for it. Use it wherever a
// gradient is more than a few px wide and slow; a 1 px line or a small bright swatch can stay a Rectangle.
// After changing fade.frag, build it again:
//   pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/fade.frag.qsb shaders/fade.frag
// A software renderer has no shaders: there it is the plain gradient (and may band).
Item {
    id: f
    property bool across: false
    property bool radial: false
    property int stops: 2                    // how many of c0..c3 are used
    property color c0: "transparent"; property color c1: "transparent"; property color c2: c1; property color c3: c2
    property real p0: 0; property real p1: 1; property real p2: 1; property real p3: 1
    property real under: Theme.under         // the tone it mostly lies on (sizes a dark veil's dither; not the look)
    readonly property bool plain: GraphicsInfo.api === GraphicsInfo.Software
    readonly property color e2: stops > 2 ? c2 : c1
    readonly property color e3: stops > 3 ? c3 : e2
    readonly property real q2: stops > 2 ? p2 : 1
    readonly property real q3: stops > 3 ? p3 : 1
    ShaderEffect {
        anchors.fill: parent; visible: !f.plain
        fragmentShader: "shaders/fade.frag.qsb"
        property real kind: f.radial ? 2 : f.across ? 1 : 0
        property real under: f.under
        property real grain: 1
        property vector4d at: Qt.vector4d(f.p0, f.p1, f.q2, f.q3)
        property color c0: f.c0; property color c1: f.c1; property color c2: f.e2; property color c3: f.e3
    }
    Loader { anchors.fill: parent; active: f.plain
        sourceComponent: f.radial ? round : flat
        Component { id: flat
            Rectangle {
                gradient: Gradient { orientation: f.across ? Gradient.Horizontal : Gradient.Vertical
                    GradientStop { position: f.p0; color: f.c0 } GradientStop { position: f.p1; color: f.c1 }
                    GradientStop { position: f.q2; color: f.e2 } GradientStop { position: f.q3; color: f.e3 } } } }
        Component { id: round
            Item {
                Shape { id: sh; width: f.width; height: f.width
                    transform: Scale { yScale: f.height / Math.max(1, f.width) }
                    ShapePath {
                        strokeWidth: -1
                        fillGradient: RadialGradient {
                            centerX: sh.width / 2; centerY: sh.width / 2; centerRadius: sh.width / 2; focalX: centerX; focalY: centerY
                            GradientStop { position: f.p0; color: f.c0 } GradientStop { position: f.p1; color: f.c1 }
                            GradientStop { position: f.q2; color: f.e2 } GradientStop { position: f.q3; color: f.e3 } }
                        startX: 0; startY: 0
                        PathLine { x: sh.width; y: 0 } PathLine { x: sh.width; y: sh.width } PathLine { x: 0; y: sh.width } PathLine { x: 0; y: 0 }
                    } } } }
    }
}
