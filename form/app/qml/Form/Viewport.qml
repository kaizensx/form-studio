import QtQuick
import QtQuick3D
import FormNative
import "F.js" as F

// The part on its build plate. Millimetres, Z up. Everything the engine returns is drawn as-is:
// one mesh per feature, the kernel's own edges, and overall dimensions as drawing-style dimension lines.
Item {
    id: vp
    // ── public state ─────────────────────────────────────────
    property var model: null                 // engine view: { mesh[], edges, bbox, companions }
    property var ghost: null                 // another revision drawn as blueprint edges
    property string selected: ""
    property string hovered: ""
    property var flagged: []
    property bool showCompanions: true
    property bool showDims: true
    property bool interactive: true
    property bool spin: false                // slow turntable (home screen)
    property real plateSize: 180
    property var bounds: ({ lo: Qt.vector3d(-40, -40, 0), hi: Qt.vector3d(40, 40, 40) })   // on the plate
    property vector3d shift: Qt.vector3d(0, 0, 0)
    property var marker: null                // { at:[x,y,z], to:[x,y,z] } in design coordinates
    property string sectionAxis: ""
    property real sectionT: 0.5
    signal picked(string feature)
    signal hoveredFeature(string feature, real x, real y)

    // ── camera (orbit around target; angles in degrees) ─────
    property vector3d target: Qt.vector3d(0, 0, 20)
    property real az: -34
    property real el: 28.4
    property real dist: 420
    property bool tween: false
    Behavior on az { enabled: vp.tween; NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    Behavior on el { enabled: vp.tween; NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    Behavior on dist { enabled: vp.tween; NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    Behavior on target { enabled: vp.tween; Vector3dAnimation { duration: 420; easing.type: Easing.OutCubic } }

    readonly property var views: ({ iso: [-34, 28.4], front: [0, 3.4], side: [90, 3.4], back: [153.4, 26], top: [0, 89], under: [-35.5, -41] })
    function scene(p) { return Qt.vector3d(p.x, p.z, -p.y) }           // Z-up millimetres → Qt Quick 3D's Y-up
    function center(b) { return Qt.vector3d((b.lo.x + b.hi.x) / 2, (b.lo.y + b.hi.y) / 2, (b.lo.z + b.hi.z) / 2) }
    function radius(b) { return Math.max(Math.hypot(b.hi.x - b.lo.x, b.hi.y - b.lo.y, b.hi.z - b.lo.z) / 2, 12) }
    function frame(b, slack) { return radius(b) / Math.sin(13 * Math.PI / 180) * slack }
    function setView(name, animate, box) {
        var v = views[name] || views.iso, b = box || bounds
        tween = animate !== false
        // take the short way round
        var a = v[0]; while (a - az > 180) a -= 360; while (a - az < -180) a += 360
        az = a; el = v[1]; target = center(b); dist = frame(b, box ? 1.25 : 1.5)
    }
    function featureBox(id) {
        for (var i = 0; i < parts.count; i++) {
            var m = parts.objectAt(i)
            if (m && m.feature === id) return { lo: m.geometry.lo.plus(shift), hi: m.geometry.hi.plus(shift) }
        }
        return null
    }
    function focusFeature(id) {
        var b = featureBox(id); if (!b) return
        tween = true; target = center(b); dist = Math.max(14, radius(b)) / Math.sin(13 * Math.PI / 180) * 1.9
    }
    function setModel(v) {
        model = v
        if (!v) return
        var b = v.bbox
        shift = Qt.vector3d(-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2])
        bounds = { lo: Qt.vector3d(b[0][0], b[0][1], b[0][2]).plus(shift), hi: Qt.vector3d(b[1][0], b[1][1], b[1][2]).plus(shift) }
    }
    function setGhost(v) { ghost = v }
    function setSection(axis, t) { sectionAxis = axis || ""; sectionT = t === undefined ? 0.5 : t }
    function setMarker(m) {
        marker = m
        if (!m) return
        var a = Qt.vector3d(m.at[0], m.at[1], m.at[2]).plus(shift), c = Qt.vector3d(m.to[0], m.to[1], m.to[2]).plus(shift), p = 18
        setView(Store.viewName, true, { lo: Qt.vector3d(Math.min(a.x, c.x) - p, Math.min(a.y, c.y) - p, Math.min(a.z, c.z) - p),
                                        hi: Qt.vector3d(Math.max(a.x, c.x) + p, Math.max(a.y, c.y) + p, Math.max(a.z, c.z) + p) })
    }

    // section plane, in scene coordinates (the shader keeps what is on the near side)
    readonly property bool clipOn: sectionAxis !== ""
    readonly property real clipAt: {
        var i = sectionAxis
        if (!i) return 0
        var lo = bounds.lo[i], hi = bounds.hi[i]
        return lo + (hi - lo) * sectionT
    }
    // x: remove x > at ; y: remove the front (y < at) ; z: remove above
    readonly property vector3d clipN: sectionAxis === "x" ? Qt.vector3d(1, 0, 0) : sectionAxis === "y" ? Qt.vector3d(0, 0, 1) : Qt.vector3d(0, 1, 0)
    readonly property real clipD: sectionAxis === "y" ? -clipAt : clipAt

    function partColor(id) {
        return id === selected ? "#b9e8d7" : flagged.indexOf(id) >= 0 ? "#a9bff5" : id === hovered ? "#f1eee6" : "#d8d3c8"
    }

    FrameAnimation { running: vp.spin && vp.visible; onTriggered: { vp.tween = false; vp.az += frameTime * 9 } }

    View3D {
        id: view
        anchors.fill: parent
        camera: cam
        environment: SceneEnvironment {
            clearColor: Theme.plate; backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA; antialiasingQuality: SceneEnvironment.VeryHigh
            aoEnabled: true; aoStrength: 55; aoDistance: 6; aoSoftness: 30; aoSampleRate: 3
            tonemapMode: SceneEnvironment.TonemapModeFilmic
        }
        PerspectiveCamera {
            id: cam
            fieldOfView: 26; clipNear: 2; clipFar: 6000
            readonly property real ra: vp.az * Math.PI / 180
            readonly property real re: Math.max(-89, Math.min(89, vp.el)) * Math.PI / 180
            readonly property vector3d zpos: Qt.vector3d(vp.target.x + vp.dist * Math.sin(ra) * Math.cos(re),
                                                         vp.target.y - vp.dist * Math.cos(ra) * Math.cos(re),
                                                         vp.target.z + vp.dist * Math.sin(re))
            position: vp.scene(zpos)
            rotation: Quaternion.lookAt(vp.scene(zpos), vp.scene(vp.target))
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-52, -32, 0); brightness: 2.1; color: "#ffffff"
            castsShadow: true; shadowFactor: 85; shadowMapQuality: Light.ShadowMapQualityVeryHigh; softShadowQuality: Light.PCF32; pcfFactor: 5; shadowMapFar: 1400; csmNumSplits: 1 }
        DirectionalLight { eulerRotation: Qt.vector3d(-18, 118, 0); brightness: 0.7; color: "#fff1e0" }
        DirectionalLight { eulerRotation: Qt.vector3d(40, -150, 0); brightness: 0.35; color: "#cfe0ff" }
        DirectionalLight { eulerRotation: Qt.vector3d(-90, 0, 0); brightness: 0.25 }

        Node {
            id: zup
            eulerRotation.x: -90                       // everything below is in Z-up millimetres

            // build plate: ground that catches the shadow, a 10 mm grid, a firm outline
            Model { source: "#Rectangle"; scale: Qt.vector3d(14, 14, 1); z: -0.06; receivesShadows: true; castsShadows: false; pickable: false
                materials: PrincipledMaterial { baseColor: "#232a2f"; roughness: 1; specularAmount: 0 } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: {
                    var p = [], h = vp.plateSize / 2
                    for (var x = -h; x <= h + 1e-6; x += 10) { p.push(x, -h, 0, x, h, 0); p.push(-h, x, 0, h, x, 0) }
                    return p } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: "#2e363b"; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: { var h = vp.plateSize / 2; return [-h, -h, 0, h, -h, 0, h, -h, 0, h, h, 0, h, h, 0, -h, h, 0, -h, h, 0, -h, -h, 0] } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: "#55616a"; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

            Node {
                id: design
                position: vp.shift
                Repeater3D {
                    id: parts
                    model: vp.model ? vp.model.mesh : []
                    Model {
                        required property var modelData
                        readonly property string feature: modelData.feature || ""
                        pickable: true
                        geometry: MeshGeometry { positions: modelData.positions; indices: modelData.indices }
                        materials: CustomMaterial {
                            shadingMode: CustomMaterial.Shaded; cullMode: Material.NoCulling; fragmentShader: "shaders/clay.frag"
                            property color uColor: vp.partColor(feature)
                            property color uGlow: feature === vp.selected ? "#0a2019" : "#000000"
                            property vector3d uClipN: vp.clipN
                            property real uClipD: vp.clipD
                            property real uClip: vp.clipOn ? 1 : 0
                            Behavior on uColor { ColorAnimation { duration: 140 } }
                        }
                    }
                }
                Model { visible: !!(vp.model && vp.model.edges); pickable: false; castsShadows: false; depthBias: -2
                    geometry: LineGeometry { segments: vp.model && vp.model.edges ? vp.model.edges : "" }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                        property color uColor: "#2b2925"; property vector3d uClipN: vp.clipN; property real uClipD: vp.clipD; property real uClip: vp.clipOn ? 1 : 0 } }
                Model { visible: !!(vp.ghost && vp.ghost.edges); pickable: false; castsShadows: false
                    geometry: LineGeometry { segments: vp.ghost && vp.ghost.edges ? vp.ghost.edges : "" }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"; depthDrawMode: Material.NeverDepthDraw
                        property color uColor: Theme.blueprint; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

                // the thing the part holds, as a blueprint volume
                Repeater3D {
                    model: vp.showCompanions && vp.model && vp.model.companions ? vp.model.companions : []
                    Node {
                        id: comp
                        required property var modelData
                        readonly property bool isMesh: !!modelData.mesh      // an imported part (STEP/STL), in design coordinates
                        position: isMesh ? Qt.vector3d(0, 0, 0) : Qt.vector3d(modelData.origin[0], modelData.origin[1], modelData.origin[2])
                        eulerRotation.x: isMesh ? 0 : (modelData.rot_x_deg || 0)
                        Model { visible: comp.isMesh; pickable: false; castsShadows: false
                            geometry: MeshGeometry { positions: comp.isMesh ? comp.modelData.mesh.positions : ""; indices: comp.isMesh ? comp.modelData.mesh.indices : "" }
                            materials: PrincipledMaterial { baseColor: Theme.blueprint; opacity: 0.14; alphaMode: PrincipledMaterial.Blend; lighting: PrincipledMaterial.NoLighting
                                cullMode: Material.NoCulling; depthDrawMode: Material.NeverDepthDraw } }
                        Model { visible: comp.isMesh && !!comp.modelData.edges; pickable: false; castsShadows: false
                            geometry: LineGeometry { segments: comp.isMesh ? (comp.modelData.edges || "") : "" }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                                property color uColor: Theme.alpha(Theme.blueprint, 0.75); property vector3d uClipN; property real uClipD; property real uClip: 0 } }
                        Model { visible: !comp.isMesh; source: "#Cube"; pickable: false; castsShadows: false
                            scale: Qt.vector3d(modelData.size[0] / 100, modelData.size[1] / 100, modelData.size[2] / 100); z: modelData.size[2] / 2
                            materials: PrincipledMaterial { baseColor: Theme.blueprint; opacity: 0.1; alphaMode: PrincipledMaterial.Blend; lighting: PrincipledMaterial.NoLighting; depthDrawMode: Material.NeverDepthDraw } }
                        Model { visible: !comp.isMesh; pickable: false; castsShadows: false
                            geometry: LineGeometry { points: {
                                if (comp.isMesh) return []
                                var w = modelData.size[0] / 2, t = modelData.size[1] / 2, l = modelData.size[2], p = []
                                var c = [[-w, -t], [w, -t], [w, t], [-w, t]]
                                for (var i = 0; i < 4; i++) { var a = c[i], b = c[(i + 1) % 4]
                                    p.push(a[0], a[1], 0, b[0], b[1], 0, a[0], a[1], l, b[0], b[1], l, a[0], a[1], 0, a[0], a[1], l) }
                                return p } }
                            materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                                property color uColor: Theme.blueprint; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
                    }
                }

                // a check pointing at a place: thin signal line between two points
                Node {
                    visible: !!vp.marker
                    Model { pickable: false; castsShadows: false
                        geometry: LineGeometry { points: vp.marker ? [vp.marker.at[0], vp.marker.at[1], vp.marker.at[2], vp.marker.to[0], vp.marker.to[1], vp.marker.to[2]] : [] }
                        materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"; depthDrawMode: Material.NeverDepthDraw
                            property color uColor: Theme.signal; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
                    Repeater3D {
                        model: vp.marker ? [vp.marker.at, vp.marker.to] : []
                        Model { required property var modelData; source: "#Sphere"; scale: Qt.vector3d(0.018, 0.018, 0.018); pickable: false; castsShadows: false
                            position: Qt.vector3d(modelData[0], modelData[1], modelData[2])
                            materials: PrincipledMaterial { baseColor: Theme.signal; lighting: PrincipledMaterial.NoLighting } }
                    }
                }
            }

            // overall dimensions, drawn like a drawing: extension lines, a dimension line, the number
            Model { visible: vp.showDims && !!vp.model; pickable: false; castsShadows: false
                geometry: LineGeometry { points: {
                    var b = vp.bounds, o = 7, t = 2.2, p = []
                    var x0 = b.lo.x, x1 = b.hi.x, y0 = b.lo.y, y1 = b.hi.y, z1 = b.hi.z
                    var g = 0.12
                    p.push(x0, y0 - o, g, x1, y0 - o, g, x0, y0 - o - t, g, x0, y0 - 1, g, x1, y0 - o - t, g, x1, y0 - 1, g)
                    p.push(x1 + o, y0, g, x1 + o, y1, g, x1 + 1, y0, g, x1 + o + t, y0, g, x1 + 1, y1, g, x1 + o + t, y1, g)
                    p.push(x1 + o, y1, 0, x1 + o, y1, z1, x1 + 1, y1, z1, x1 + o + t, y1, z1)
                    return p } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: "#8fb5a7"; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
        }
    }

    // dimension numbers, placed where the 3D dimension lines are
    Repeater {
        model: vp.showDims && vp.model ? 3 : 0
        Rectangle {
            id: dl
            required property int index
            property point at: Qt.point(-999, -999)
            readonly property var b: vp.bounds
            readonly property real mm: index === 0 ? b.hi.x - b.lo.x : index === 1 ? b.hi.y - b.lo.y : b.hi.z
            x: at.x - width / 2; y: at.y - height / 2
            width: t.implicitWidth + 12; height: 18; radius: 3; color: Theme.alpha(Theme.plate, 0.82); border.color: Theme.alpha(Theme.datum, 0.35)
            visible: at.x > 0 && at.y > 0
            Text { id: t; anchors.centerIn: parent; text: F.fmt(dl.mm, 1); color: Theme.datum; font.family: Theme.mono; font.pixelSize: 11; renderType: Text.NativeRendering }
            FrameAnimation {
                running: dl.visible || vp.visible
                onTriggered: {
                    var o = 7, b = dl.b
                    var p = dl.index === 0 ? Qt.vector3d((b.lo.x + b.hi.x) / 2, b.lo.y - o, 0)
                          : dl.index === 1 ? Qt.vector3d(b.hi.x + o, (b.lo.y + b.hi.y) / 2, 0)
                          : Qt.vector3d(b.hi.x + o, b.hi.y, b.hi.z / 2)
                    var s = view.mapFrom3DScene(vp.scene(p))
                    dl.at = s.z > 0 ? Qt.point(s.x, s.y) : Qt.point(-999, -999)
                }
            }
        }
    }

    // ── input: drag to orbit, right-drag or shift to pan, wheel or pinch to zoom, click to select ──
    MouseArea {
        id: ma
        anchors.fill: parent; enabled: vp.interactive
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton; hoverEnabled: true
        property point last
        property point down
        property bool moved: false
        cursorShape: vp.hovered ? Qt.PointingHandCursor : pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        function hit(x, y) { var r = view.pick(x, y); return r.objectHit && r.objectHit.feature !== undefined ? r.objectHit.feature : "" }
        onPressed: function (e) { last = Qt.point(e.x, e.y); down = last; moved = false; vp.tween = false }
        onPositionChanged: function (e) {
            if (!pressed) {
                var f = hit(e.x, e.y)
                if (f !== vp.hovered) vp.hovered = f
                vp.hoveredFeature(f, e.x, e.y)
                return
            }
            var dx = e.x - last.x, dy = e.y - last.y
            if (Math.hypot(e.x - down.x, e.y - down.y) > 4) moved = true
            last = Qt.point(e.x, e.y)
            if ((e.buttons & Qt.LeftButton) && !(e.modifiers & Qt.ShiftModifier)) {
                vp.az -= dx * 0.4; vp.el = Math.max(-89, Math.min(89, vp.el + dy * 0.4))
            } else {
                var k = vp.dist * 2 * Math.tan(13 * Math.PI / 180) / height
                var ra = vp.az * Math.PI / 180, re = vp.el * Math.PI / 180
                var right = Qt.vector3d(Math.cos(ra), Math.sin(ra), 0)
                var up = Qt.vector3d(-Math.sin(ra) * Math.sin(re), Math.cos(ra) * Math.sin(re), Math.cos(re))
                vp.target = vp.target.minus(right.times(dx * k)).plus(up.times(dy * k))
            }
        }
        onReleased: function (e) { if (!moved && e.button === Qt.LeftButton) vp.picked(hit(e.x, e.y)) }
        onExited: { if (vp.hovered) vp.hovered = ""; vp.hoveredFeature("", 0, 0) }
        onWheel: function (w) {
            vp.tween = false
            var d = w.pixelDelta.y !== 0 ? w.pixelDelta.y * 0.0035 : w.angleDelta.y / 120 * 0.12
            vp.dist = Math.max(30, Math.min(3000, vp.dist * Math.exp(-d)))
        }
    }
    PinchHandler {
        enabled: vp.interactive; target: null
        property real d0: 0
        onActiveChanged: if (active) { d0 = vp.dist; vp.tween = false }
        onScaleChanged: (delta) => { vp.dist = Math.max(30, Math.min(3000, vp.dist / delta)) }
    }
}
