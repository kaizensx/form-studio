import QtQuick

// A live 3D card of one project: the real head geometry, turning slowly while hovered.
Item {
    id: mv
    property string projectId: ""
    property bool turning: false
    property bool loaded: false
    property bool failed: false
    onProjectIdChanged: load()
    Component.onCompleted: load()
    function load() {
        if (!projectId) return
        loaded = false; failed = false
        Store.get("/projects/" + projectId + "/view").then(function (v) {
            v.companions = []
            vp.setModel(v); vp.setView("iso", false); vp.dist *= 0.82; mv.loaded = true
        }, function () { mv.failed = true })
    }
    // while the kernel builds it: the outline of a part on the plate, breathing
    Icon { anchors.centerIn: parent; name: mv.failed ? "circle_alert" : "cuboid"; size: 28; color: Theme.ink4; visible: !mv.loaded
        SequentialAnimation on opacity { running: !mv.loaded && !mv.failed; loops: Animation.Infinite
            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine } } }
    Viewport { id: vp; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; spin: mv.turning
        opacity: mv.loaded ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } } }
}
