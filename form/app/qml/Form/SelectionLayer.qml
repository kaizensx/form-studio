import QtQuick
import QtQuick3D
import FormNative

// What is selected, drawn on the part: a face or a painted region as a tint on the surface, an edge as a bright line,
// a point as a dot. Geometry comes from the engine in each part's print frame; every item is placed where its part
// is shown now (vp.shownXf), so a selection rides along into the assembled and exploded views.
// Lives inside the Viewport's design node.
Node {
    id: sl
    property Item vp: null
    property var items: []               // engine analysis items (form/selection.py): kind, part, on, mesh, edge.segments
    property color tint: Theme.annotate
    property real dot: 0.017
    property vector2d px: Qt.vector2d(0.002, 0.002)
    property real strength: 1            // 0.55 for a kept annotation being looked at, 1 for the live selection

    Repeater3D {
        model: sl.items
        Node {
            id: it
            required property var modelData
            readonly property var xf: sl.vp ? (sl.vp.frameTag, sl.vp.shownXf(modelData.part || "")) : null
            position: xf ? xf.pos : Qt.vector3d(0, 0, 0)
            rotation: xf ? xf.rot : Qt.quaternion(1, 0, 0, 0)
            readonly property bool area: !!modelData.mesh

            // a face or a region: the surface itself, tinted
            Model { visible: it.area; pickable: false; castsShadows: false; receivesShadows: false
                geometry: MeshGeometry { positions: it.area ? it.modelData.mesh.positions : ""; indices: it.area ? it.modelData.mesh.indices : "" }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/companion.frag"; vertexShader: "shaders/line.vert"
                    cullMode: Material.NoCulling; depthDrawMode: Material.NeverDepthDraw
                    sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                    property color uColor: Theme.alpha(sl.tint, 0.42 * sl.strength); property real uFade0: 1e9; property real uFade1: 2e9 } }
            // an edge: a line two pixels wide, over everything
            Repeater3D {
                model: it.modelData.edge && it.modelData.edge.segments ? [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]] : []
                Model { required property var modelData; pickable: false; castsShadows: false
                    geometry: LineGeometry { segments: it.modelData.edge.segments }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                        property vector3d uOff: Qt.vector3d(modelData[0] * sl.px.x * 1.1, modelData[1] * sl.px.y * 1.1, 0.0001)
                        property color uColor: Theme.alpha(sl.tint, sl.strength); property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            }
            // a point (and where a face or edge was picked): a dot
            Model { visible: !!it.modelData.on && it.modelData.kind !== "region"; source: "#Sphere"; pickable: false; castsShadows: false
                scale: Qt.vector3d(sl.dot, sl.dot, sl.dot)
                position: it.modelData.on ? Qt.vector3d(it.modelData.on[0], it.modelData.on[1], it.modelData.on[2]) : Qt.vector3d(0, 0, 0)
                materials: PrincipledMaterial { baseColor: sl.tint; lighting: PrincipledMaterial.NoLighting } }
        }
    }
}
