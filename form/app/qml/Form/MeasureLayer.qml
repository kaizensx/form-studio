import QtQuick
import QtQuick3D
import FormNative

// Measurements drawn in the scene, in design millimetres: a dimension line with its dX/dY/dZ legs,
// a fitted or exact circle with its diameter, a face's normal. Lives inside the Viewport's design node.
Node {
    id: ml
    property var measures: []            // Store.measures
    property var from: null              // first point of a distance being taken: { at: [x, y, z] }
    property real dot: 0.017             // sphere scale: about 1.7 mm across at the default zoom
    property vector2d px: Qt.vector2d(0.002, 0.002)   // one screen pixel in clip units

    function v(a) { return Qt.vector3d(a[0], a[1], a[2]) }
    function mainLines() {
        var p = [], i, k
        for (i = 0; i < measures.length; i++) {
            var m = measures[i]
            if (m.kind === "distance") p.push(m.a[0], m.a[1], m.a[2], m.b[0], m.b[1], m.b[2])
            else if (m.kind === "diameter" && m.circle.center && m.circle.axis) {
                var c = v(m.circle.center), ax = v(m.circle.axis).normalized(), r = m.circle.radius_mm
                var u = ax.crossProduct(Math.abs(ax.z) < 0.9 ? Qt.vector3d(0, 0, 1) : Qt.vector3d(1, 0, 0)).normalized(), w = ax.crossProduct(u)
                var at = v(m.at), rad = at.minus(c), along = rad.dotProduct(ax)
                var cc = c.plus(ax.times(along))                      // the circle at the height that was clicked
                rad = at.minus(cc)
                if (rad.length() > 1e-6) { u = rad.normalized(); w = ax.crossProduct(u) }
                for (k = 0; k < 64; k++) {
                    var a0 = k / 64 * 2 * Math.PI, a1 = (k + 1) / 64 * 2 * Math.PI
                    var p0 = cc.plus(u.times(r * Math.cos(a0))).plus(w.times(r * Math.sin(a0)))
                    var p1 = cc.plus(u.times(r * Math.cos(a1))).plus(w.times(r * Math.sin(a1)))
                    p.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
                }
                var d0 = cc.minus(u.times(r)), d1 = cc.plus(u.times(r))
                p.push(d0.x, d0.y, d0.z, d1.x, d1.y, d1.z)
            } else if (m.kind === "face") {
                var n = v(m.face.normal), q = v(m.at), e = q.plus(n.times(7))
                p.push(q.x, q.y, q.z, e.x, e.y, e.z)
            }
        }
        return p
    }
    function legLines() {                // a distance resolved along the design axes: X, then Y, then Z
        var p = []
        for (var i = 0; i < measures.length; i++) {
            var m = measures[i]
            if (m.kind !== "distance") continue
            var a = m.a, b = m.b, n = (Math.abs(b[0] - a[0]) > 0.005) + (Math.abs(b[1] - a[1]) > 0.005) + (Math.abs(b[2] - a[2]) > 0.005)
            if (n < 2) continue                                       // already along one axis: the legs are the line itself
            p.push(a[0], a[1], a[2], b[0], a[1], a[2], b[0], a[1], a[2], b[0], b[1], a[2], b[0], b[1], a[2], b[0], b[1], b[2])
        }
        return p
    }
    function dots() {
        var d = []
        for (var i = 0; i < measures.length; i++) {
            var m = measures[i]
            if (m.kind === "distance") d.push(m.a, m.b)
            else d.push(m.at)
        }
        if (from) d.push(from.at)
        return d
    }

    // Lines are one pixel wide, so each is drawn several times a pixel apart: a dark casing first, the datum line over it.
    readonly property var ring: [[1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7]]
    Repeater3D {
        model: ml.ring
        Model { required property var modelData; pickable: false; castsShadows: false
            geometry: LineGeometry { points: ml.mainLines() }
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                property vector3d uOff: Qt.vector3d(modelData[0] * ml.px.x * 2.4, modelData[1] * ml.px.y * 2.4, 0.0002)
                property color uColor: Theme.plate; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
    }
    Repeater3D {
        model: [[0, 0]].concat(ml.ring)
        Model { required property var modelData; pickable: false; castsShadows: false
            geometry: LineGeometry { points: ml.mainLines() }
            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"
                property vector3d uOff: Qt.vector3d(modelData[0] * ml.px.x * 0.9, modelData[1] * ml.px.y * 0.9, 0)
                property color uColor: Theme.datum; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
    }
    Model { pickable: false; castsShadows: false
        geometry: LineGeometry { points: ml.legLines() }
        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/overlay.vert"; depthDrawMode: Material.NeverDepthDraw
            property vector3d uOff: Qt.vector3d(0, 0, 0.0001)
            property color uColor: Theme.alpha(Theme.datum, 0.6); property vector3d uClipN; property real uClipD; property real uClip: 0 } }
    Repeater3D {
        model: ml.dots()
        Model { required property var modelData; source: "#Sphere"; scale: Qt.vector3d(ml.dot, ml.dot, ml.dot); pickable: false; castsShadows: false
            position: Qt.vector3d(modelData[0], modelData[1], modelData[2])
            materials: PrincipledMaterial { baseColor: Theme.datum; lighting: PrincipledMaterial.NoLighting } }
    }
}
