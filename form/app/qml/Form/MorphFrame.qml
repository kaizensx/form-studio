import QtQuick

// The composer becomes the workspace: when a design opens from Home, an outline with the composer's corners grows
// from where you typed to the frame of the viewport, then fades. Only a frame moves; nothing is drawn twice.
Item {
    id: mf
    property rect to: Qt.rect(0, 0, 0, 0)               // where it lands (window coordinates)
    function play(from) {
        if (Theme.reduced || !from || from.width <= 0) return
        box.x = from.x; box.y = from.y; box.width = from.width; box.height = from.height
        box.radius = 22; box.opacity = 1; glowFill.opacity = 0.10
        run.restart()
    }
    Rectangle {
        id: box; opacity: 0; color: "transparent"; border.width: 1.5; border.color: Theme.datum
        Rectangle { id: glowFill; anchors.fill: parent; radius: parent.radius; color: Theme.datum; opacity: 0 }
    }
    ParallelAnimation {
        id: run
        NumberAnimation { target: box; property: "x"; to: mf.to.x; duration: Theme.move(520); easing.type: Easing.InOutCubic }
        NumberAnimation { target: box; property: "y"; to: mf.to.y; duration: Theme.move(520); easing.type: Easing.InOutCubic }
        NumberAnimation { target: box; property: "width"; to: mf.to.width; duration: Theme.move(520); easing.type: Easing.InOutCubic }
        NumberAnimation { target: box; property: "height"; to: mf.to.height; duration: Theme.move(520); easing.type: Easing.InOutCubic }
        NumberAnimation { target: box; property: "radius"; to: 10; duration: Theme.move(520); easing.type: Easing.InOutCubic }
        NumberAnimation { target: glowFill; property: "opacity"; to: 0; duration: Theme.move(420) }
        SequentialAnimation { PauseAnimation { duration: Theme.move(380) }
            NumberAnimation { target: box; property: "opacity"; to: 0; duration: Theme.move(320); easing.type: Easing.OutCubic } }
    }
}
