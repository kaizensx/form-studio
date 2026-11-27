import QtQuick

// A picture that falls away to nothing all round: the effect of a layer whose edge must not show (a part on its
// floor, standing in the room).
//
//   Item { layer.enabled: true; layer.effect: Veil { full: 0.55 } }
//
// The picture is whole out to `full` of an ellipse's radius and gone at its edge. By default the ellipse touches
// the item's edges; `centre` and `radii` (px) place another. It is worked out per pixel by a shader
// (shaders/veil.frag) and dithered by one 8-bit step: a dark floor fading into a dark room is otherwise drawn as
// rings. After changing veil.frag, build it again:
//   pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/veil.frag.qsb shaders/veil.frag
// A software renderer has no shaders: use a MultiEffect mask there (see DesignCard.qml).
ShaderEffect {
    property var source
    property real full: 0.5
    property real grain: 1
    property size size: Qt.size(width, height)
    property point centre: Qt.point(width / 2, height / 2)
    property point radii: Qt.point(width / 2, height / 2)
    fragmentShader: "shaders/veil.frag.qsb"
}
