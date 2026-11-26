import QtQuick
import FormNative

// The opening screen while the engine starts, about a second.
//
// One idea: the mark is a coordinate frame, so the app opens on its origin. Two construction lines come in from the
// window's edges and meet at the origin, the mark is built on them the way a part is (origin, then the X arm and the Y stem, then the middle arm)
// and the name sets beside it as the brand lockup, all within half a second. The lockup is centred in the window and
// the one status line sits centred under it; that line says what the engine is really doing.
//
// The hand-off is the point: when the app is ready the lockup travels to where the top bar's logo sits and lands on it
// at the same size, while the plate fades to show Home behind. There is no cut, no flash, and the logo you watched
// being drawn is the one that stays. `landOn` is that logo (see Main.qml).
// Reduced motion: the finished lockup, then a plain fade.
Item {
    id: sp
    objectName: "splash"
    property bool done: false
    property string status: ""                        // what is really happening (Store.bootStatus); empty shows no words
    property Item landOn: null                        // the top bar's Logo; without one it lands top left
    property point landing: Qt.point(24, 15)
    property int landingSize: 14
    readonly property int s: 72                       // the mark's height here: a multiple of 12, so every edge is on a pixel
    readonly property real u: s / 48
    readonly property bool calm: Theme.reduced
    readonly property real homeX: Math.round((width - lock.width) / 2)
    readonly property real homeY: Math.round(height * 0.46 - s / 2)
    // 0 while it waits in the middle, 1 once it has landed on the top bar
    property real go: 0
    readonly property bool showing: plate.opacity > 0.001 || lock.opacity > 0.001      // false once it has handed over
    visible: showing
    readonly property bool carrying: showing && go < 1      // the lockup is still on its way: the top bar holds its own logo back until it lands

    onDoneChanged: if (done) {
        if (landOn) { landing = landOn.mapToItem(sp, 0, 0); landingSize = landOn.size }
        if (calm) { go = 1; lock.opacity = 0 }          // no travel: the real logo is already there under the fade
        leave.start()
    }
    SequentialAnimation { id: leave
        ParallelAnimation {
            NumberAnimation { target: quiet; property: "opacity"; to: 0; duration: Theme.exit }
            NumberAnimation { target: sp; property: "go"; to: 1; duration: Theme.move(Theme.screen + 80); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMove }
            SequentialAnimation { PauseAnimation { duration: Theme.move(60) }
                NumberAnimation { target: plate; property: "opacity"; to: 0; duration: Theme.screen; easing.type: Easing.OutCubic } } }
        // it has landed on the real logo: let go of it
        NumberAnimation { target: lock; property: "opacity"; to: 0; duration: Theme.exit } }

    // the room the app opens in: the key light falls on the mark. It fades to show Home, which stands in the same room.
    Item { id: plate; anchors.fill: parent
        Rectangle { anchors.fill: parent; color: Theme.plate }
        Room { anchors.fill: parent; poolX: 0.5; poolY: 0.46; poolW: 820; poolH: 440; poolK: Theme.dark ? 0.16 : 1 }
        MouseArea { anchors.fill: parent; enabled: !sp.done; hoverEnabled: true; onWheel: function (w) { w.accepted = true } } }

    // everything that belongs to the splash only and leaves first: the construction lines and the status
    Item { id: quiet; anchors.fill: parent
        readonly property real ox: sp.homeX + 6 * sp.u          // the origin's centre
        readonly property real oy: sp.homeY + 6 * sp.u
        property real reach: sp.calm ? 1 : 0                    // how far the lines have been drawn, 0..1
        NumberAnimation on reach { running: !sp.calm; to: 1; duration: 420; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
        // X comes in from the left edge and Y from the top, and they meet at the origin: the mark's top arm and stem
        // carry them on. They are drawn outward from the origin and are faintest far from it.
        Rectangle { y: Math.round(quiet.oy); height: 1; width: Math.round(quiet.ox * quiet.reach); x: Math.round(quiet.ox - width)
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0.04) } GradientStop { position: 1; color: Theme.alpha(Theme.datum, 0.42) } } }
        Rectangle { x: Math.round(quiet.ox); width: 1; height: Math.round(quiet.oy * quiet.reach); y: Math.round(quiet.oy - height)
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0.04) } GradientStop { position: 1; color: Theme.alpha(Theme.datum, 0.42) } } }
        // ticks every 12 units along both, the grid the mark is drawn on
        Repeater { model: 10
            Rectangle { required property int index; readonly property int n: index + 2
                x: Math.round(quiet.ox - n * 12 * sp.u); y: Math.round(quiet.oy) - 3; width: 1; height: 7; color: Theme.datum
                opacity: quiet.reach * Math.max(0, 0.5 - n * 0.042) } }
        Repeater { model: 10
            Rectangle { required property int index; readonly property int n: index + 2
                y: Math.round(quiet.oy - n * 12 * sp.u); x: Math.round(quiet.ox) - 3; height: 1; width: 7; color: Theme.datum
                opacity: quiet.reach * Math.max(0, 0.5 - n * 0.042) } }

        Column { anchors.horizontalCenter: parent.horizontalCenter; y: Math.round(sp.homeY + sp.s + 56); spacing: 12
            opacity: sp.calm ? 1 : 0
            // the status arrives with the name, so it is never read under half a lockup
            SequentialAnimation on opacity { running: !sp.calm; PauseAnimation { duration: 150 } NumberAnimation { to: 1; duration: 220; easing.type: Easing.OutCubic } }
            // Indeterminate, always: how long the kernel takes is not known and nothing feeds this a real fraction, so it
            // never pretends to be one. It says "working", the line under it says on what.
            Rectangle { id: rail; width: 120; height: 2; radius: 1; color: Theme.rule2; clip: true; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { id: seg; width: 40; height: 2; radius: 1; color: Theme.datum; x: sp.calm ? 40 : -width
                    SequentialAnimation on x { loops: Animation.Infinite; running: sp.visible && !sp.calm && !sp.done
                        NumberAnimation { from: -seg.width; to: rail.width; duration: 1100; easing.type: Easing.InOutCubic } PauseAnimation { duration: 120 } } } }
            Txt { objectName: "splashStatus"; kind: "fine"; tone: 3; text: sp.status; anchors.horizontalCenter: parent.horizontalCenter
                height: Theme.tFine + 4 } }          // the row keeps its height when there are no words
        Txt { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 28; mono: true; font.pixelSize: Theme.tFine; tone: 4
            text: Bridge.version }
    }

    // the lockup: drawn at 72, it lands on the top bar at `landingSize` (the same drawing, scaled about its corner)
    Item {
        id: lock
        width: word.x + word.width; height: sp.s
        transformOrigin: Item.TopLeft
        x: sp.homeX + (sp.landing.x - sp.homeX) * sp.go
        y: sp.homeY + (sp.landing.y - sp.homeY) * sp.go
        scale: 1 + (sp.landingSize / sp.s - 1) * sp.go
        // the mark, built on the lines: origin, X arm and Y stem, middle arm
        Rectangle { id: org; width: 12 * sp.u; height: width; color: Theme.markOrigin; opacity: sp.calm ? 1 : 0; scale: sp.calm ? 1 : 0.6 }
        Rectangle { id: xa; x: 14 * sp.u; height: 12 * sp.u; color: Theme.markPart; width: sp.calm ? 26 * sp.u : 0 }
        Rectangle { id: ya; y: 14 * sp.u; width: 12 * sp.u; color: Theme.markPart; height: sp.calm ? 34 * sp.u : 0 }
        Rectangle { id: ma; x: 12 * sp.u; y: 20 * sp.u; height: 12 * sp.u; color: Theme.markPart; width: sp.calm ? 20 * sp.u : 0 }
        Logo { id: word; mark: false; size: sp.s; x: Math.round(40 * sp.u + 0.42 * sp.s)
            opacity: sp.calm ? 1 : 0
            transform: Translate { id: wordTr; x: sp.calm ? 0 : -10 } }
        // Built in 0.45 s, everything overlapping: the origin, the arms from 70 ms, the middle arm and the name from
        // 150 ms. The whole lockup is on screen, centred, well before the status under it is read.
        ParallelAnimation {
            running: !sp.calm
            NumberAnimation { target: org; property: "opacity"; to: 1; duration: 110 }
            NumberAnimation { target: org; property: "scale"; to: 1; duration: 160; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
            SequentialAnimation { PauseAnimation { duration: 70 }
                ParallelAnimation {
                    NumberAnimation { target: xa; property: "width"; to: 26 * sp.u; duration: 240; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                    NumberAnimation { target: ya; property: "height"; to: 34 * sp.u; duration: 260; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
            SequentialAnimation { PauseAnimation { duration: 150 }
                ParallelAnimation {
                    NumberAnimation { target: ma; property: "width"; to: 20 * sp.u; duration: 200; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                    NumberAnimation { target: word; property: "opacity"; to: 1; duration: 220; easing.type: Easing.OutCubic }
                    NumberAnimation { target: wordTr; property: "x"; to: 0; duration: 300; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
        }
    }
}
