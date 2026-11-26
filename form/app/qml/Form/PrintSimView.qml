import QtQuick
import QtQuick3D
import FormNative

// The sliced toolpaths on the build plate, in plate millimetres, Z up. One vertex buffer for the whole print
// (ToolpathGeometry); scrubbing only changes a shader value. Three ways to look at it:
//   3d    – orbit camera, everything printed so far, the nozzle, optionally a ghost of what is still to come
//   2d    – straight down, orthographic, the current layer only (the per-layer inspector)
//   plate – copies of the print laid out on the bed (a computed arrangement, see form/packing.py)
Item {
    id: v
    property string url: ""
    property var colors: ({})                 // line type → colour
    property real now: 0                      // layer + fraction of the layer
    property real total: 1                    // number of layers
    property string mode: "3d"
    property bool ghost: false
    property var shown: []                    // 16 numbers, 1 = draw that line type index
    property var nozzle: ({})                 // { x, y, z } where the nozzle is
    property bool nozzleOn: true
    property var bed: [180, 180]              // width, depth
    property var box: null                    // toolpath bounding box [[x0,y0,0],[x1,y1,z1]]
    property var layout: null                 // plate mode: packing result { placed: [{x,y,w,h,rotated}], fits }
    property real footer: 0                   // screen pixels at the bottom covered by controls
    // The free stage (LayerView): the print is framed in this rectangle, clear of the panes, the line types and the
    // transport. The scene still fills the whole view; it is drawn around the rectangle's middle, so the plate runs
    // on under the glass. Changes glide (the conversation opening, the transport folding).
    property real freeX: 0
    property real freeY: 0
    property real freeW: width
    property real freeH: height
    readonly property bool freeSet: freeW < width - 1 || freeH < height - 1
    property bool freeGlide: false
    Timer { interval: 500; running: true; onTriggered: v.freeGlide = true }
    Behavior on freeX { enabled: v.freeGlide; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on freeY { enabled: v.freeGlide; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on freeW { enabled: v.freeGlide; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on freeH { enabled: v.freeGlide; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    readonly property real offX: freeSet ? freeX + freeW / 2 - width / 2 : 0
    readonly property real offY: freeSet ? freeY + freeH / 2 - height / 2 : 0
    // pull back when the rectangle is much smaller than the view (as the design viewport does)
    readonly property real fitK: !freeSet ? 1 : Math.min(4, Math.max(1, 0.86 * view.height / Math.max(60, freeH), 0.95 * view.height / Math.max(60, freeW)))
    readonly property alias geometry: geo
    signal loaded(var summary)
    signal failed(string message)

    readonly property bool flat: mode === "2d"
    readonly property bool finished: now >= total - 0.001
    readonly property vector3d origin: Qt.vector3d(-bed[0] / 2, -bed[1] / 2, 0)        // plate centre at the scene origin
    readonly property matrix4x4 showM: {
        var s = shown.length === 16 ? shown : [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        return Qt.matrix4x4(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10], s[11], s[12], s[13], s[14], s[15])
    }

    // ── cameras ──────────────────────────────────────────────
    property vector3d target: Qt.vector3d(0, 0, 15)
    property real az: -34
    property real el: 30
    property real dist: 420
    property bool tween: false
    property bool framed: false               // the first frame is ours; after that the camera is the user's
    property point pan2: Qt.point(0, 0)       // 2D: plate point at the centre of the view
    property real zoom2: 4                    // 2D: pixels per millimetre
    Behavior on az { enabled: v.tween; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on el { enabled: v.tween; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on dist { enabled: v.tween; NumberAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    Behavior on target { enabled: v.tween; Vector3dAnimation { duration: Theme.move(Theme.camera); easing.type: Easing.OutCubic } }
    function scene(p) { return Qt.vector3d(p.x, p.z, -p.y) }
    function frame(animate) {
        if (!box) return
        tween = !!animate
        var lo = Qt.vector3d(box[0][0], box[0][1], 0).plus(origin), hi = Qt.vector3d(box[1][0], box[1][1], box[1][2]).plus(origin)
        if (mode === "plate") { lo = Qt.vector3d(-bed[0] / 2, -bed[1] / 2, 0); hi = Qt.vector3d(bed[0] / 2, bed[1] / 2, box[1][2]) }
        var r = Math.max(Math.hypot(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) / 2, 12)
        // keep the print clear of the controls: aim a little below it
        var lift = !freeSet && footer > 0 && height > 0 ? r * 1.1 * footer / height : 0
        target = Qt.vector3d((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2 - lift)
        dist = r / Math.sin(13 * Math.PI / 180) * (mode === "plate" ? 1.18 : 1.42)
        if (mode === "plate") { az = -24; el = 52 }
        pan2 = Qt.point((box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2)
        var availH = freeSet ? Math.max(80, freeH - 24) : Math.max(120, height - footer - 70)
        var availW = freeSet ? Math.max(120, freeW - 24) : Math.max(160, width - 230 - 48)          // clear of the line-type list on the left
        zoom2 = Math.max(0.5, Math.min(availW / Math.max(1, box[1][0] - box[0][0] + 6), availH / Math.max(1, box[1][1] - box[0][1] + 6)))
        framed = true
    }
    onBoxChanged: if (!framed) frame(false)
    onModeChanged: if (mode === "plate" || !framed) frame(true)
    onHeightChanged: if (!framed) frame(false)

    ToolpathGeometry {
        id: geo
        url: v.url
        colors: v.colors
        onLoaded: function (summary) { v.loaded(summary) }
        onFailed: function (message) { v.failed(message) }
    }

    View3D {
        id: view
        // centred on the free stage, and large enough to still cover the whole view
        x: v.offX - Math.abs(v.offX); y: v.offY - Math.abs(v.offY); width: v.width + 2 * Math.abs(v.offX); height: v.height + 2 * Math.abs(v.offY)
        camera: v.flat ? ortho : persp
        environment: SceneEnvironment {
            clearColor: Theme.plate; backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA; antialiasingQuality: SceneEnvironment.VeryHigh
        }
        PerspectiveCamera {
            id: persp
            fieldOfView: 26; clipNear: 2; clipFar: 6000
            readonly property real ra: v.az * Math.PI / 180
            readonly property real re: Math.max(-89, Math.min(89, v.el)) * Math.PI / 180
            readonly property real far: v.dist * v.fitK
            readonly property vector3d zpos: Qt.vector3d(v.target.x + far * Math.sin(ra) * Math.cos(re),
                                                         v.target.y - far * Math.cos(ra) * Math.cos(re),
                                                         v.target.z + far * Math.sin(re))
            position: v.scene(zpos)
            rotation: Quaternion.lookAt(v.scene(zpos), v.scene(v.target))
        }
        OrthographicCamera {
            id: ortho
            clipNear: 1; clipFar: 4000
            horizontalMagnification: v.zoom2; verticalMagnification: v.zoom2
            // straight down; the controls at the bottom push the layer up a little
            position: v.freeSet ? Qt.vector3d(v.pan2.x + v.origin.x, 1500, -(v.pan2.y + v.origin.y))
                                 : Qt.vector3d(v.pan2.x + v.origin.x - 115 / v.zoom2, 1500, -(v.pan2.y + v.origin.y - v.footer / 2 / v.zoom2 + 20 / v.zoom2))
            eulerRotation.x: -90
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-52, -32, 0); brightness: 1.6 }

        Node {
            eulerRotation.x: -90                       // everything below is in Z-up millimetres, plate centre at 0,0

            // the bed: ground, 10 mm grid, outline
            Model { source: "#Rectangle"; scale: Qt.vector3d(v.bed[0] / 100, v.bed[1] / 100, 1); z: -0.08; pickable: false; castsShadows: false
                materials: PrincipledMaterial { baseColor: Theme.plate1; lighting: PrincipledMaterial.NoLighting } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: {
                    var p = [], w = v.bed[0] / 2, d = v.bed[1] / 2, g
                    for (g = -w + 10; g < w - 1e-6; g += 10) p.push(g, -d, 0, g, d, 0)
                    for (g = -d + 10; g < d - 1e-6; g += 10) p.push(-w, g, 0, w, g, 0)
                    return p } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: Theme.plate3; property vector3d uClipN; property real uClipD; property real uClip: 0 } }
            Model { pickable: false; castsShadows: false
                geometry: LineGeometry { points: { var w = v.bed[0] / 2, d = v.bed[1] / 2; return [-w, -d, 0, w, -d, 0, w, -d, 0, w, d, 0, w, d, 0, -w, d, 0, -w, d, 0, -w, -d, 0] } }
                materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                    property color uColor: Theme.ink4; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

            Node {
                position: v.origin
                // the print so far (or, on the plate, every copy of it)
                Repeater3D {
                    model: v.mode === "plate" ? (v.layout ? v.layout.placed : []) : [null]
                    Node {
                        id: inst
                        required property var modelData
                        // a copy: move the print's own footprint to where the packer put it (turned 90° about Z if it says so)
                        readonly property bool turned: !!modelData && modelData.rotated
                        position: !modelData || !v.box ? Qt.vector3d(0, 0, 0)
                                : turned ? Qt.vector3d(modelData.x + v.box[1][1], modelData.y - v.box[0][0], 0)
                                         : Qt.vector3d(modelData.x - v.box[0][0], modelData.y - v.box[0][1], 0)
                        eulerRotation.z: turned ? 90 : 0
                        Model {
                            pickable: false; castsShadows: false
                            geometry: geo
                            materials: CustomMaterial {
                                shadingMode: CustomMaterial.Unshaded; cullMode: Material.NoCulling
                                vertexShader: "shaders/toolpath.vert"; fragmentShader: "shaders/toolpath.frag"
                                property real uNow: inst.modelData ? 1e6 : v.now
                                property real uGhost: 0
                                property real uOnly: v.flat ? 1 : 0
                                property real uShade: v.flat ? 0.35 : 1
                                property real uDim: inst.modelData || v.finished ? 1 : 0.6
                                property matrix4x4 uShow: v.showM
                                property color uPlate: Theme.plate
                                property color uGhostColor: Theme.ink3
                            }
                        }
                    }
                }
                // what is still to come, faintly
                Model {
                    visible: v.ghost && v.mode === "3d" && !v.finished
                    pickable: false; castsShadows: false
                    geometry: geo
                    materials: CustomMaterial {
                        shadingMode: CustomMaterial.Unshaded; cullMode: Material.NoCulling
                        vertexShader: "shaders/toolpath.vert"; fragmentShader: "shaders/toolpath.frag"
                        sourceBlend: CustomMaterial.One; destinationBlend: CustomMaterial.OneMinusSrcAlpha
                        depthDrawMode: Material.NeverDepthDraw
                        property real uNow: v.now
                        property real uGhost: 1
                        property real uOnly: 0
                        property real uShade: 0
                        property real uDim: 1
                        property matrix4x4 uShow: v.showM
                        property color uPlate: Theme.plate
                        property color uGhostColor: Theme.alpha(Theme.datum, 0.032)
                    }
                }
                // plate mode: each footprint the packer placed
                Model {
                    visible: v.mode === "plate" && !!v.layout; pickable: false; castsShadows: false
                    geometry: LineGeometry { points: {
                        var p = [], a = v.mode === "plate" && v.layout ? v.layout.placed : []
                        for (var i = 0; i < a.length; i++) {
                            var x0 = a[i].x, y0 = a[i].y, x1 = x0 + a[i].w, y1 = y0 + a[i].h
                            p.push(x0, y0, 0.05, x1, y0, 0.05, x1, y0, 0.05, x1, y1, 0.05, x1, y1, 0.05, x0, y1, 0.05, x0, y1, 0.05, x0, y0, 0.05)
                        }
                        return p } }
                    materials: CustomMaterial { shadingMode: CustomMaterial.Unshaded; fragmentShader: "shaders/line.frag"; vertexShader: "shaders/line.vert"
                        property color uColor: v.layout && v.layout.fits ? Theme.datum : Theme.signal; property vector3d uClipN; property real uClipD; property real uClip: 0 } }

                // the nozzle: a small bright point where material is being laid, with a soft glow
                Node {
                    id: noz
                    visible: v.nozzleOn && v.mode !== "plate" && !v.finished && v.nozzle.x !== undefined
                    position: Qt.vector3d(v.nozzle.x || 0, v.nozzle.y || 0, (v.nozzle.z || 0) + 0.1)
                    readonly property real k: v.flat ? 1.6 / v.zoom2 : v.dist / 420
                    Model { source: "#Sphere"; scale: Qt.vector3d(0.016, 0.016, 0.016).times(noz.k); pickable: false; castsShadows: false
                        materials: PrincipledMaterial { baseColor: Qt.lighter(Theme.datum, 1.2); lighting: PrincipledMaterial.NoLighting } }
                    Model { source: "#Sphere"; scale: Qt.vector3d(0.034, 0.034, 0.034).times(noz.k); pickable: false; castsShadows: false
                        materials: PrincipledMaterial { baseColor: Theme.datum; opacity: 0.34; alphaMode: PrincipledMaterial.Blend; lighting: PrincipledMaterial.NoLighting; depthDrawMode: Material.NeverDepthDraw } }
                    Model { source: "#Sphere"; scale: Qt.vector3d(0.07, 0.07, 0.07).times(noz.k); pickable: false; castsShadows: false
                        materials: PrincipledMaterial { baseColor: Theme.datum; opacity: 0.13; alphaMode: PrincipledMaterial.Blend; lighting: PrincipledMaterial.NoLighting; depthDrawMode: Material.NeverDepthDraw } }
                    // the nozzle itself, as a faint cone above the point
                    Model { visible: !v.flat; source: "#Cone"; pickable: false; castsShadows: false
                        eulerRotation.x: -90; z: 6.2 * noz.k; scale: Qt.vector3d(0.045, 0.06, 0.045).times(noz.k)
                        materials: PrincipledMaterial { baseColor: Theme.ink; opacity: 0.16; alphaMode: PrincipledMaterial.Blend; lighting: PrincipledMaterial.NoLighting; depthDrawMode: Material.NeverDepthDraw } }
                }
            }
        }
    }

    // ── input: drag to orbit (pan in 2D), right-drag or shift to pan, wheel or pinch to zoom ──
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        property point last
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        onPressed: function (e) { last = Qt.point(e.x, e.y); v.tween = false }
        onPositionChanged: function (e) {
            var dx = e.x - last.x, dy = e.y - last.y
            last = Qt.point(e.x, e.y)
            if (v.flat) { v.pan2 = Qt.point(v.pan2.x - dx / v.zoom2, v.pan2.y + dy / v.zoom2); return }
            if ((e.buttons & Qt.LeftButton) && !(e.modifiers & Qt.ShiftModifier)) {
                v.az -= dx * 0.4; v.el = Math.max(2, Math.min(89, v.el + dy * 0.4))
            } else {
                var k = v.dist * 2 * Math.tan(13 * Math.PI / 180) / height
                var ra = v.az * Math.PI / 180, re = v.el * Math.PI / 180
                var right = Qt.vector3d(Math.cos(ra), Math.sin(ra), 0)
                var up = Qt.vector3d(-Math.sin(ra) * Math.sin(re), Math.cos(ra) * Math.sin(re), Math.cos(re))
                v.target = v.target.minus(right.times(dx * k)).plus(up.times(dy * k))
            }
        }
        onWheel: function (w) {
            v.tween = false
            var d = w.pixelDelta.y !== 0 ? w.pixelDelta.y * 0.0035 : w.angleDelta.y / 120 * 0.12
            if (v.flat) v.zoom2 = Math.max(0.4, Math.min(80, v.zoom2 * Math.exp(d)))
            else v.dist = Math.max(20, Math.min(3000, v.dist * Math.exp(-d)))
        }
    }
    PinchHandler {
        target: null
        onActiveChanged: if (active) v.tween = false
        onScaleChanged: (delta) => {
            if (v.flat) v.zoom2 = Math.max(0.4, Math.min(80, v.zoom2 * delta))
            else v.dist = Math.max(20, Math.min(3000, v.dist / delta))
        }
    }
}
