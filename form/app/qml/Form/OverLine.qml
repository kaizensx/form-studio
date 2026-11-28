import QtQuick
import QtQuick3D
import FormNative

// Lines drawn over the part (an arrow, a bend line, a traced path): a flat list of xyz pairs in the part's frame.
// A GPU line is one pixel wide, so the same segments are drawn `passes` times, each a fraction of a pixel aside
// (overlay.vert's uOff), which reads as a line `weight` pixels wide at any zoom.
Node {
    id: ol
    property var points: []
    property color color: "#ffffff"
    property real weight: 2              // pixels
    property var port: null              // the viewport (its size gives a pixel in clip units)
    property real depth: 0               // orders overlays among themselves (larger = further back)
    readonly property real cx: port ? 2 / Math.max(1, port.width) : 0.001
    readonly property real cy: port ? 2 / Math.max(1, port.height) : 0.001
    readonly property var offs: weight <= 1.2 ? [[0, 0]] : weight <= 2.2 ? [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]]
        : [[-1, -1], [0, -1], [1, -1], [-1, 0], [0, 0], [1, 0], [-1, 1], [0, 1], [1, 1]]
    LineGeometry { id: geo; points: ol.points }
    Repeater3D { model: ol.visible ? ol.offs : []
        Model { required property var modelData; pickable: false; castsShadows: false; geometry: geo
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"; depthDrawMode: Material.NeverDepthDraw
                sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                property vector3d uOff: Qt.vector3d(modelData[0] * ol.cx * ol.weight / 3, modelData[1] * ol.cy * ol.weight / 3, ol.depth)
                property color uColor: Theme.alpha(ol.color, ol.color.a * (ol.offs.length > 4 ? 0.5 : ol.offs.length > 1 ? 0.7 : 1))
                property vector3d uClipN; property real uClipD; property real uClip: 0 } } }
}
