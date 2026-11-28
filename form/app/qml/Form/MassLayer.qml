import QtQuick
import QtQuick3D
import FormNative

// The centre of mass and the principal axes of inertia, drawn in the scene (form/massprops.py). Lives inside the
// Viewport's design node, in the frame the engine computed them in: the design as built, or assembled at the pose.
// The centre is a datum dot with a ring of casing; each principal axis is a line through it, the axis of the smallest
// moment (the one the part turns about most easily) the longest, the largest moment's the shortest.
Node {
    id: ml
    property var total: null             // Store.mass.total: { com_mm, principal: { axes, moments_g_mm2 } }
    property real reach: 20              // half-length of the longest axis, mm
    property real dot: 0.017
    property vector2d px: Qt.vector2d(0.002, 0.002)
    readonly property var com: total ? total.com_mm : null
    readonly property var axes: total ? total.principal.axes : []
    readonly property var lens: [1.0, 0.78, 0.58]

    function axisLine(k) {
        if (!com || !axes[k]) return []
        var a = axes[k], L = reach * lens[k]
        return [com[0] - a[0] * L, com[1] - a[1] * L, com[2] - a[2] * L, com[0] + a[0] * L, com[1] + a[1] * L, com[2] + a[2] * L]
    }
    visible: !!com

    readonly property var ring: [[1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7]]
    Repeater3D {
        model: ml.com ? [0, 1, 2] : []
        Node {
            id: ax
            required property int modelData
            readonly property var pts: ml.axisLine(modelData)
            // a dark casing a pixel around, then the line: it reads on the clay and on the floor
            Repeater3D {
                model: ml.ring
                Model { required property var modelData; pickable: false; castsShadows: false
                    geometry: LineGeometry { points: ax.pts }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                        property vector3d uOff: Qt.vector3d(modelData[0] * ml.px.x * 2.2, modelData[1] * ml.px.y * 2.2, 0.0002)
                        property color uColor: Theme.plate; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            }
            Repeater3D {
                model: [[0, 0], [1, 0], [0, 1]]
                Model { required property var modelData; pickable: false; castsShadows: false
                    geometry: LineGeometry { points: ax.pts }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                        property vector3d uOff: Qt.vector3d(modelData[0] * ml.px.x * 0.8, modelData[1] * ml.px.y * 0.8, 0.0001)
                        property color uColor: Theme.datum; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            }
        }
    }
    // the centre: a casing sphere behind a datum one, drawn at the front of the depth range (it is inside the solid)
    Repeater3D {
        model: ml.com ? [[1.9, Theme.plate, 0.00005], [1.2, Theme.datum, 0.0]] : []
        Model { required property var modelData; source: "#Sphere"; pickable: false; castsShadows: false
            readonly property real k: ml.dot * modelData[0]
            scale: Qt.vector3d(k, k, k)
            position: Qt.vector3d(ml.com[0], ml.com[1], ml.com[2])
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                property vector3d uOff: Qt.vector3d(0, 0, modelData[2])
                property color uColor: modelData[1]; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
    }
}
