import QtQuick
import QtQuick3D
import FormNative

// The part as it would lie on the plate in one candidate orientation: the head geometry, rotated by the
// engine's quaternion and dropped onto the plate. A picture of the candidate, nothing more.
Item {
    id: ot
    property var mesh: []                // Store.view.mesh
    property var cand: null              // { quaternion: [w, x, y, z], drop: [x, y, z], footprint_mm, height_mm }
    readonly property real r: cand ? Math.max(12, Math.hypot(cand.footprint_mm[0], cand.footprint_mm[1], cand.height_mm) / 2) : 40
    readonly property real dist: r / Math.sin(13 * Math.PI / 180) * 0.86
    View3D {
        anchors.fill: parent
        camera: cam
        environment: SceneEnvironment { clearColor: Theme.well; backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA; antialiasingQuality: SceneEnvironment.High; tonemapMode: SceneEnvironment.TonemapModeFilmic }
        PerspectiveCamera {
            id: cam
            fieldOfView: 26; clipNear: 2; clipFar: 6000
            readonly property real ra: -34 * Math.PI / 180
            readonly property real re: 26 * Math.PI / 180
            readonly property vector3d tgt: Qt.vector3d(0, 0, ot.cand ? ot.cand.height_mm / 2 : 0)
            readonly property vector3d zpos: Qt.vector3d(tgt.x + ot.dist * Math.sin(ra) * Math.cos(re), tgt.y - ot.dist * Math.cos(ra) * Math.cos(re), tgt.z + ot.dist * Math.sin(re))
            position: Qt.vector3d(zpos.x, zpos.z, -zpos.y)
            rotation: Quaternion.lookAt(Qt.vector3d(zpos.x, zpos.z, -zpos.y), Qt.vector3d(tgt.x, tgt.z, -tgt.y))
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-52, -32, 0); brightness: 1.5 }
        DirectionalLight { eulerRotation: Qt.vector3d(-18, 118, 0); brightness: 0.5 }
        DirectionalLight { eulerRotation: Qt.vector3d(40, -150, 0); brightness: 0.25 }
        Node {
            eulerRotation.x: -90                           // Z-up millimetres below
            Model { source: "#Rectangle"; scale: Qt.vector3d(ot.r * 0.026, ot.r * 0.026, 1); z: -0.05; pickable: false
                materials: PrincipledMaterial { baseColor: Theme.plate3; roughness: 1; specularAmount: 0 } }
            Node {
                position: ot.cand ? Qt.vector3d(ot.cand.drop[0], ot.cand.drop[1], ot.cand.drop[2]) : Qt.vector3d(0, 0, 0)
                Node {
                    rotation: ot.cand ? Qt.quaternion(ot.cand.quaternion[0], ot.cand.quaternion[1], ot.cand.quaternion[2], ot.cand.quaternion[3]) : Qt.quaternion(1, 0, 0, 0)
                    Repeater3D {
                        model: ot.mesh
                        Model { required property var modelData; pickable: false
                            geometry: MeshGeometry { positions: modelData.positions; indices: modelData.indices }
                            materials: PrincipledMaterial { baseColor: Theme.clay; roughness: 0.84; cullMode: Material.NoCulling } }
                    }
                }
            }
        }
    }
}
