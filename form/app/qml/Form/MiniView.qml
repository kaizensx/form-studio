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
    // while the kernel answers: a band of light crosses the empty frame, then the part cross-fades in over it.
    // A design that cannot be read says so with a mark instead.
    Item { id: wait; anchors.fill: parent; clip: true
        opacity: mv.loaded ? 0 : 1; visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        Fade { id: band; visible: !mv.failed; width: parent.width * 0.6; height: parent.height * 2.2; y: -parent.height * 0.6; rotation: 18
            across: true; stops: 3
            c0: Theme.alpha(Theme.lineBase, 0); c1: Theme.alpha(Theme.lineBase, Theme.dark ? 0.045 : 0.06); p1: 0.5
            c2: Theme.alpha(Theme.lineBase, 0); p2: 1
            x: Theme.reduced ? parent.width * 0.2 : -width
            SequentialAnimation on x { running: wait.visible && !mv.failed && !Theme.reduced; loops: Animation.Infinite
                NumberAnimation { from: -band.width; to: wait.width; duration: 1300; easing.type: Easing.InOutSine }
                PauseAnimation { duration: 260 } } }
        Icon { anchors.centerIn: parent; name: "circle_alert"; size: 22; color: Theme.ink4; visible: mv.failed } }
    Viewport { id: vp; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; spin: mv.turning
        opacity: mv.loaded ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.cross; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
}
