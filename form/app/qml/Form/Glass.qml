import QtQuick
import QtQuick.Effects

// A pane of glass over the room: every control of a workspace sits on one. It blurs what is behind it (`source`, the
// room: the 3D view or Home's backdrop), lays a thin tint over that, and draws a 1 px edge of light, a faint highlight
// along the top and a soft shadow.
//
//   Glass { source: room; radius: height / 2; ... }      a capsule
//   Glass { source: room; arrive: 2; ... }               fades in and rises 8 px, third in its screen's cascade
//
// The blur is a quarter-size copy of the part of `source` under the pane, so it costs little, and Qt only redraws it
// when `source` itself changes: with a still 3D view nothing is blurred again. `source` must not contain the pane.
// Without a source, with "Reduce transparency", in Low Power Mode or on a software renderer (Theme.blur false) the
// pane is solid (Theme.glassSolid) and nothing is blurred at all.
Item {
    id: g
    property Item source: null
    property real radius: Theme.rPane
    // where the pane is in `source`'s coordinates. Worked out from the scene; it follows the pane's own x, y and size
    // and the window's size. A pane moved by something else (a parent that slides) calls place() when it has landed.
    property int _tick: 0
    readonly property point _at: { g.x; g.y; g.width; g.height; g._tick; return source && g.parent ? g.mapToItem(source, 0, 0) : Qt.point(0, 0) }
    property real sx: _at.x
    property real sy: _at.y
    function place() { _tick++ }
    property bool bare: false                // nothing drawn at all: only what is inside (the lockup on Home)
    property bool flat: false                // no blur and no shadow: a thin tinted pane inside something that scrolls
    property bool shadow: true
    property real strength: 1                // 0..1: how much of the tint (a slim bar over the part may ask for less)
    property int arrive: -1                  // >= 0: the pane arrives with its screen, this many beats after it
    property bool edge: true
    readonly property bool blurred: Theme.blur && !flat && !bare && !!source && visible && width > 0 && height > 0
    default property alias content: inner.data

    Shadow { visible: g.shadow && !g.flat && !g.bare; radius: g.radius; spread: Theme.dark ? 30 : 22; drop: Theme.dark ? 14 : 8; strength: Theme.dark ? 0.85 : 0.45 }

    Loader {
        anchors.fill: parent; active: g.blurred
        sourceComponent: Item {
            ShaderEffectSource {
                id: grab; visible: false; width: g.width; height: g.height
                sourceItem: g.source; sourceRect: Qt.rect(g.sx, g.sy, g.width, g.height)
                textureSize: Qt.size(Math.max(8, Math.ceil(g.width / 4)), Math.max(8, Math.ceil(g.height / 4)))
                live: true; smooth: true; recursive: false
            }
            Rectangle { id: shape; anchors.fill: parent; radius: g.radius; visible: false; layer.enabled: true; antialiasing: true }
            MultiEffect {
                anchors.fill: parent; source: grab
                blurEnabled: true; blur: 1; blurMax: 32; blurMultiplier: 1.0; autoPaddingEnabled: false
                saturation: 0.3
                maskEnabled: true; maskSource: shape; maskThresholdMin: 0.5; maskSpreadAtMin: 1
            }
        }
    }
    // the tint: thin over a blur, nearly opaque without one
    Rectangle { anchors.fill: parent; radius: g.radius; antialiasing: true; visible: !g.bare
        color: g.flat ? "transparent" : g.blurred ? Theme.alpha(Theme.glassTint, Theme.glassTint.a * g.strength) : Theme.glassSolid }
    Rectangle { anchors.fill: parent; radius: g.radius; antialiasing: true; visible: (g.blurred || g.flat) && !g.bare; color: Theme.glass }
    // the edge of light, and the highlight just inside the top edge
    Rectangle { anchors.fill: parent; radius: g.radius; antialiasing: true; color: "transparent"; visible: g.edge && !g.bare
        border.width: 1; border.color: Theme.dark ? Theme.glassEdge : Theme.alpha(Theme.lineBase, 0.07) }
    Rectangle { visible: g.edge && !g.bare; x: g.radius * 0.7; width: Math.max(0, g.width - g.radius * 1.4); y: 1; height: 1
        gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 0.2; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.1 : 0.9) }
            GradientStop { position: 0.8; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.1 : 0.9) }
            GradientStop { position: 1; color: "transparent" } } }
    Item { id: inner; anchors.fill: parent }

    // arriving with the screen: a fade and an 8 px rise, `stagger` after the pane before it. Reduce Motion: the fade.
    transform: Translate { id: rise }
    SequentialAnimation { id: come
        PropertyAction { target: g; property: "opacity"; value: 0 }
        PropertyAction { target: rise; property: "y"; value: Theme.shift(Theme.rise) }
        PauseAnimation { duration: 60 + Math.max(0, g.arrive) * Theme.stagger }
        ParallelAnimation {
            NumberAnimation { target: g; property: "opacity"; to: 1; duration: Theme.base; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
            NumberAnimation { target: rise; property: "y"; to: 0; duration: Theme.move(Theme.panel); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
    function replay() { if (arrive >= 0) come.restart() }
    Component.onCompleted: { replay(); settle.start() }
    Timer { id: settle; interval: 350; onTriggered: g.place() }          // once the screen that brought it has arrived
    onVisibleChanged: if (visible) place()
    onSourceChanged: place()
    Connections { target: g.source; ignoreUnknownSignals: true
        function onWidthChanged() { g.place() } function onHeightChanged() { g.place() } }
}
