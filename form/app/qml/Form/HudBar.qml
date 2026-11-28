import QtQuick

// The options of one viewport tool: a row of controls beside the rail that appears while that tool is active.
// It wraps onto more lines when the viewport is narrow. Arrives quickly, leaves quicker.
Item {
    id: h
    property bool shown: false
    property real maxWidth: 600
    property bool cut: false                 // in the tool capsule: there and gone at once, no fade and no slide
    default property alias content: flow.data
    width: flow.childrenRect.width; height: flow.childrenRect.height
    opacity: shown ? 1 : 0; visible: opacity > 0.01; enabled: shown
    Behavior on opacity { NumberAnimation { duration: h.cut ? 0 : h.shown ? Theme.ui : Theme.exit; easing.type: Easing.OutCubic } }
    transform: Translate { x: h.shown || h.cut ? 0 : -Motion.shift(6)
        Behavior on x { NumberAnimation { duration: Motion.move(Motion.ui); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
    Flow { id: flow; width: h.maxWidth; spacing: 6 }
}
