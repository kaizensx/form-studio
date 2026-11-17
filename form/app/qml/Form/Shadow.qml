import QtQuick

// A soft drop shadow for floating layers (popovers, sheets, toasts). Place it as the first child of the surface:
//   Rectangle { radius: Theme.rLg; Shadow { radius: parent.radius } ... }
// It is drawn as a few translucent rings, so it needs no offscreen layer.
Item {
    id: s
    property real radius: Theme.rMd
    property int spread: 22
    property real strength: 1
    property int drop: 8
    anchors.fill: parent; z: -1
    Repeater {
        model: 7
        Rectangle {
            required property int index
            readonly property real g: (index + 1) * s.spread / 7
            x: -g; y: -g + s.drop * (index + 1) / 7; width: s.width + 2 * g; height: s.height + 2 * g
            radius: s.radius + g; color: "transparent"
            border.width: s.spread / 7 + 1
            border.color: Qt.rgba(0, 0, 0, 0.17 * s.strength * Math.pow(1 - index / 7, 2))
        }
    }
}
