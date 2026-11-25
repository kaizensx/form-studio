import QtQuick
import QtQuick3D
import FormNative

// One feature's own edges while a build-up runs (Viewport: the build-up). They are the edges of the faces the kernel
// made for this feature, taken from its triangles (LineGeometry.meshPositions): drawn in datum the moment its step
// comes, before its solid, and settled to the ordinary edge colour as the solid lands. Once the build-up is over the
// model's whole edge set is drawn again and these go.
Model {
    id: fe
    property Item host: null
    property var mesh: null                  // { feature, positions, indices }
    property string partId: ""
    property bool last: true                 // a streamed stage: false for the stage under the one growing in
    readonly property string feature: mesh ? (mesh.feature || "") : ""
    readonly property bool held: !!host && host._hold.indexOf(feature) >= 0
    // e: how much of the line is there. s: 0 datum, 1 the edge colour. Neither animates when the model is made.
    property real e: held ? 0 : last ? 1 : (host && host._hold.length > 0 ? 1 : 0)
    property real s: held ? 0 : 1
    Behavior on e { NumberAnimation { duration: fe.host ? fe.host.edgeMs : 0 } }
    Behavior on s { SequentialAnimation {
        PauseAnimation { duration: fe.host ? fe.host.edgeMs + Math.max(0, fe.host.revealMs - Theme.cross) : 0 }
        NumberAnimation { duration: Theme.cross; easing.type: Easing.OutCubic } } }
    pickable: false; castsShadows: false; depthBias: -2
    visible: e > 0.001 && !!host && !host.mapShown && host.hiddenFeatures.indexOf(feature) < 0
    geometry: LineGeometry { meshPositions: fe.mesh ? fe.mesh.positions : ""; meshIndices: fe.mesh ? fe.mesh.indices : "" }
    materials: CustomMaterial {
        shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
        // blended only while it fades: at rest it is an opaque line like every other edge
        sourceBlend: fe.e < 0.999 ? CustomMaterial.One : CustomMaterial.NoBlend
        destinationBlend: fe.e < 0.999 ? CustomMaterial.OneMinusSrcAlpha : CustomMaterial.NoBlend
        property color uColor: {
            var a = Theme.datum, b = fe.host ? Qt.darker(fe.host.edgeColor(fe.partId), 1.0) : a, t = fe.s
            return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, fe.e)
        }
        property vector3d uClipN: fe.host ? fe.host.clipN : Qt.vector3d(0, 0, 1)
        property real uClipD: fe.host ? fe.host.clipD : 0
        property real uClip: fe.host && fe.host.clipOn ? 1 : 0
    }
}
