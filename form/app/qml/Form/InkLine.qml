import QtQuick
import QtQuick3D
import FormNative

// Lines that lie in the part's own depth (the profile of a sketch on a face): a flat list of xyz pairs in the part's
// frame. Unlike OverLine they are depth-tested: what stands in front of a line hides it. They sit a hair nearer the
// eye than the face they lie on (shaders/ink.vert), and are drawn after the part, so a ghosted part does not veil
// the lines on its own face. A GPU line is one pixel wide, so the segments are drawn several times, each a fraction
// of a pixel aside, which reads as a line `weight` pixels wide at any zoom.
Node {
    id: il
    property var points: []
    property color color: "#ffffff"
    property real weight: 2              // pixels
    property var port: null              // the viewport (its size gives a pixel in clip units)
    property real bias: 1                // how many hairs nearer: orders lines that share a place
    readonly property real cx: port ? 2 / Math.max(1, port.width) : 0.001
    readonly property real cy: port ? 2 / Math.max(1, port.height) : 0.001
    readonly property var offs: weight <= 1.2 ? [[0, 0]] : weight <= 2.2 ? [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]]
        : [[-1, -1], [0, -1], [1, -1], [-1, 0], [0, 0], [1, 0], [-1, 1], [0, 1], [1, 1]]
    LineGeometry { id: geo; points: il.points }
    Repeater3D { model: il.visible && il.points.length ? il.offs : []
        Model { required property var modelData; pickable: false; castsShadows: false; geometry: geo; depthBias: -1e5
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/ink.vert"; depthDrawMode: Material.NeverDepthDraw
                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                property vector3d uOff: Qt.vector3d(modelData[0] * il.cx * il.weight / 3, modelData[1] * il.cy * il.weight / 3, il.bias)
                property color uColor: Theme.alpha(il.color, il.color.a * (il.offs.length > 4 ? 0.5 : il.offs.length > 1 ? 0.7 : 1))
                property vector3d uClipN; property real uClipD; property real uClip: 0 } } }
}
