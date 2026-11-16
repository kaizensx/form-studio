import QtQuick

// A live 3D card of one project: the real head geometry, turning slowly while hovered.
Item {
    id: mv
    property string projectId: ""
    property bool turning: false
    property bool loaded: false
    onProjectIdChanged: load()
    Component.onCompleted: load()
    function load() {
        if (!projectId) return
        loaded = false
        Store.get("/projects/" + projectId + "/view").then(function (v) {
            v.companions = []
            vp.setModel(v); vp.setView("iso", false); vp.dist *= 0.82; mv.loaded = true
        }, function () {})
    }
    Viewport { id: vp; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; spin: mv.turning
        opacity: mv.loaded ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 400 } } }
}
