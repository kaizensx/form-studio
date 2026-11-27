import QtQuick

// A soft drop shadow for floating layers (popovers, sheets, toasts). Place it as the first child of the surface:
//   Rectangle { radius: Theme.rLg; Shadow { radius: parent.radius } ... }
// It is one smooth falloff around the surface's shape, drawn by a shader (shaders/shadow.frag) that works it out
// from the distance to the shape and dithers it: no steps and no 8-bit bands, and no offscreen layer. The dither is
// fixed to the pixels, so a still shadow is never redrawn for it. After changing shadow.frag, build it again:
//   pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/shadow.frag.qsb shaders/shadow.frag
// A software renderer has no shaders: there it is a few translucent rings (and shows as steps).
Item {
    id: s
    property real radius: Theme.rMd
    property int spread: 22
    property real strength: 1
    property int drop: 8
    readonly property bool plain: GraphicsInfo.api === GraphicsInfo.Software
    anchors.fill: parent; z: -1
    ShaderEffect {
        visible: !s.plain && s.width > 0 && s.height > 0
        readonly property real m: Math.ceil(s.spread * 1.08 + s.drop * 1.1) + 2
        x: -m; y: -m; width: s.width + 2 * m; height: s.height + 2 * m
        fragmentShader: "shaders/shadow.frag.qsb"
        property real radius: s.radius
        property real spread: Math.max(1, s.spread)
        property real drop: s.drop
        property real alpha: 0.17 * s.strength * Theme.shadow
        property real under: Theme.under
        property real grain: 1
        property size size: Qt.size(width, height)
        property point pad: Qt.point(m, m)
    }
    Loader { anchors.fill: parent; active: s.plain
        sourceComponent: Item {
            Repeater {
                model: 7
                Rectangle {
                    required property int index
                    readonly property real g: (index + 1) * s.spread / 7
                    x: -g; y: -g + s.drop * (index + 1) / 7; width: s.width + 2 * g; height: s.height + 2 * g
                    radius: s.radius + g; color: "transparent"
                    border.width: s.spread / 7 + 1
                    border.color: Qt.rgba(0, 0, 0, 0.17 * s.strength * Theme.shadow * Math.pow(1 - index / 7, 2))
                }
            }
        }
    }
}
