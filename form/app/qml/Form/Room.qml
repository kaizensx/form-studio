import QtQuick
import QtQuick.Shapes

// The room: the studio every screen stands in. A wall that falls to a lit floor, a pool of warm key light, and a
// vignette that lets the corners fall away. Home and the first-run screen use the whole of it (`wall: true`); a
// workspace lays only the vignette over its 3D view, whose own floor carries the pool (`wall: false`).
//
//   poolX, poolY   where the key light falls, as fractions of the room
//   poolW, poolH   its size in px
//   breathe        the pool breathes very slightly while nothing else moves (never with Reduce Motion)
//
// It is drawn by one shader (shaders/room.frag) that dithers what it writes by under one 8-bit step: the room is a
// gradient between dark tones a few steps apart, and undithered that shows as bands. The dither is fixed to the
// pixels, so a still room is never redrawn for it. After changing room.frag, build it again:
//   pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/room.frag.qsb shaders/room.frag
// A software renderer has no shaders: there the same room is drawn with plain gradients (and may band).
Item {
    id: room
    property bool wall: true
    property real poolX: 0.5
    property real poolY: 0.3
    property real poolW: 900
    property real poolH: 460
    property real poolK: Theme.dark ? 0.13 : 1
    property bool breathe: false
    property real vignetteK: 1
    readonly property bool plain: GraphicsInfo.api === GraphicsInfo.Software
    // breathing is stepped, not animated: a still window then redraws five times in two seconds instead of sixty
    // times a second. A step moves the pool's opacity by 3 % of itself at most, under one level of an 8-bit
    // channel in both themes (the pool adds some twenty levels at its brightest), so the steps cannot be seen
    property real phase: 0
    readonly property real poolOpacity: 0.91 + 0.09 * Math.cos(phase)
    Timer { interval: 400; repeat: true; running: room.breathe && room.visible && !Theme.reduced; onTriggered: room.phase += 0.3308 }

    ShaderEffect {
        anchors.fill: parent; visible: !room.plain; blending: !room.wall
        fragmentShader: "shaders/room.frag.qsb"
        property real wall: room.wall ? 1 : 0
        property real poolA: room.poolW > 0 ? Math.max(0, room.poolK) * room.poolOpacity : 0
        property real vigA: Math.max(0, Theme.vignette.a * room.vignetteK)
        property size size: Qt.size(width, height)
        property point poolC: Qt.point(width * room.poolX, height * room.poolY)
        property point poolR: Qt.point(room.poolW / 2, room.poolH / 2)
        property point vigC: Qt.point(width * 0.46, height * 0.5)
        property real vigR: Math.max(width, height) * 0.82
        property real grain: 1
        property color room0: Theme.room[0]; property color room1: Theme.room[1]
        property color room2: Theme.room[2]; property color room3: Theme.room[3]
        property color key: Theme.key
        property color vig: Qt.rgba(Theme.vignette.r, Theme.vignette.g, Theme.vignette.b, 1)
    }

    Rectangle { anchors.fill: parent; visible: room.wall && room.plain
        gradient: Gradient { orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.room[0] } GradientStop { position: 0.4; color: Theme.room[1] }
            GradientStop { position: 0.72; color: Theme.room[2] } GradientStop { position: 1; color: Theme.room[3] } } }

    // the pool: an ellipse of key light, strongest in its middle
    Shape {
        id: pool; visible: room.plain && room.poolK > 0 && room.poolW > 0
        x: room.width * room.poolX - width / 2; y: room.height * room.poolY - height / 2
        width: room.poolW; height: room.poolH
        opacity: room.poolOpacity
        transform: Scale { yScale: pool.height / Math.max(1, pool.width) }
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: pool.width / 2; centerY: pool.width / 2; centerRadius: pool.width / 2; focalX: centerX; focalY: centerY
                GradientStop { position: 0; color: Theme.alpha(Theme.key, room.poolK) }
                GradientStop { position: 0.55; color: Theme.alpha(Theme.key, room.poolK * 0.32) }
                GradientStop { position: 1; color: Theme.alpha(Theme.key, 0) } }
            startX: 0; startY: 0
            PathLine { x: pool.width; y: 0 } PathLine { x: pool.width; y: pool.width } PathLine { x: 0; y: pool.width } PathLine { x: 0; y: 0 }
        }
    }
    // the vignette: clear in the middle, the corners fall away
    Shape {
        id: vig; anchors.fill: parent; visible: room.plain && room.vignetteK > 0
        readonly property real r: Math.max(width, height) * 0.82
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: vig.width * 0.46; centerY: vig.height * 0.5; centerRadius: vig.r; focalX: centerX; focalY: centerY
                GradientStop { position: 0; color: Theme.alpha(Theme.vignette, 0) }
                GradientStop { position: 0.38; color: Theme.alpha(Theme.vignette, 0) }
                GradientStop { position: 1; color: Theme.alpha(Theme.vignette, Theme.vignette.a * room.vignetteK) } }
            startX: 0; startY: 0
            PathLine { x: vig.width; y: 0 } PathLine { x: vig.width; y: vig.height } PathLine { x: 0; y: vig.height } PathLine { x: 0; y: 0 }
        }
    }
}
