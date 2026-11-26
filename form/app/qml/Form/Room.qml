import QtQuick
import QtQuick.Shapes

// The room: the studio every screen stands in. A wall that falls to a lit floor, a pool of warm key light, and a
// vignette that lets the corners fall away. Home and the first-run screen use the whole of it (`wall: true`); a
// workspace lays only the vignette over its 3D view, whose own floor carries the pool (`wall: false`).
//
//   poolX, poolY   where the key light falls, as fractions of the room
//   poolW, poolH   its size in px
//   breathe        the pool breathes very slightly while nothing else moves (never with Reduce Motion)
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

    Rectangle { anchors.fill: parent; visible: room.wall
        gradient: Gradient { orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.room[0] } GradientStop { position: 0.4; color: Theme.room[1] }
            GradientStop { position: 0.72; color: Theme.room[2] } GradientStop { position: 1; color: Theme.room[3] } } }

    // the pool: an ellipse of key light, strongest in its middle
    Shape {
        id: pool; visible: room.poolK > 0 && room.poolW > 0
        x: room.width * room.poolX - width / 2; y: room.height * room.poolY - height / 2
        width: room.poolW; height: room.poolH
        opacity: 1
        SequentialAnimation on opacity { running: room.breathe && room.visible && !Theme.reduced; loops: Animation.Infinite
            NumberAnimation { to: 0.82; duration: 3800; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1; duration: 3800; easing.type: Easing.InOutSine } }
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
        id: vig; anchors.fill: parent; visible: room.vignetteK > 0
        readonly property real r: Math.max(width, height) * 0.82
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: vig.width * 0.46; centerY: vig.height * 0.5; centerRadius: vig.r; focalX: centerX; focalY: centerY
                GradientStop { position: 0; color: Theme.alpha(Theme.vignette, 0) }
                GradientStop { position: 0.5; color: Theme.alpha(Theme.vignette, 0) }
                GradientStop { position: 1; color: Theme.alpha(Theme.vignette, Theme.vignette.a * room.vignetteK) } }
            startX: 0; startY: 0
            PathLine { x: vig.width; y: 0 } PathLine { x: vig.width; y: vig.height } PathLine { x: 0; y: vig.height } PathLine { x: 0; y: 0 }
        }
    }
}
