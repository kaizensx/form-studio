import QtQuick

// A built-in recipe at its default values, built by the kernel and drawn live. Turning while hovered, like MiniView.
// Only built-in recipes are drawn: an installed recipe is code someone else wrote, and it is never run just to
// draw a picture of it.
Item {
    id: rv
    property string recipeId: ""
    property bool turning: false
    property bool loaded: false
    property bool failed: false
    property bool active: true                 // a card scrolled out of a GridView is destroyed; this one waits until shown
    onRecipeIdChanged: load()
    onActiveChanged: if (active && !loaded) load()
    Component.onCompleted: load()
    function load() {
        if (!recipeId || !active) return
        loaded = false; failed = false
        var want = recipeId
        Store.get("/recipes/builtin/" + recipeId + "/view").then(function (v) {
            if (want !== rv.recipeId) return
            vp.setModel(v); vp.setView("iso", false); vp.dist *= 0.86; rv.loaded = true
        }, function () { rv.failed = true })
    }
    Icon { anchors.centerIn: parent; name: rv.failed ? "circle_alert" : "cuboid"; size: 24; color: Theme.ink4; visible: !rv.loaded
        SequentialAnimation on opacity { running: !rv.loaded && !rv.failed; loops: Animation.Infinite
            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine } } }
    Viewport { id: vp; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; spin: rv.turning
        opacity: rv.loaded ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } } }
}
