import QtQuick

// kind: default | primary | quiet | danger.   States: hover, pressed, keyboard focus, disabled, busy.
// `keys` shows a shortcut in the tooltip.
//
// Busy: the icon turns into a spinner, the label can change (busyText, e.g. "Creating…"), presses are ignored and the
// pointer shows it is working. It appears after a short delay and then stays for a minimum time, so a quick answer
// never flickers. A button is busy while any of these hold:
//   busy: true                       bound by the caller (a job, a flag)
//   busyWhile: somePromise           until that promise settles
//   onClicked: run(function () { return Store.post(...) })      the same, for the promise the function returns
//   autoBusy (default on)            any engine action the click starts (Store.post/upload) keeps it busy until
//                                    the engine answers; the request is also named in the activity bar (Store.activity)
Item {
    id: b
    property string text: ""
    property string icon: ""
    property string kind: "default"
    property bool small: false
    property int iconSize: 0             // 0: the size that goes with the button's (13 small, 14 otherwise)
    property bool large: false
    property bool active: false
    property bool busy: false
    property string busyText: ""
    property var busyWhile: null
    property bool autoBusy: true
    property string tip: ""
    property string keys: ""
    property alias hovered: ma.containsMouse
    property bool kdown: false
    property int busyDelay: 90           // ms before the spinner shows: an instant answer shows nothing
    property int busyMin: 450            // ms it then stays, so it never flashes
    property int _pending: 0
    property bool _shown: false
    property real _since: 0
    readonly property bool working: busy || _pending > 0
    readonly property bool showsBusy: _shown           // what is on screen (after the delay, for the minimum time)
    readonly property string shownText: _shown && busyText !== "" ? busyText : text
    readonly property bool down: (ma.pressed || kdown) && enabled && !working
    signal clicked()
    function track(p) {
        if (!p || typeof p.then !== "function") return p
        _pending++
        var done = function () { try { if (b._pending > 0) b._pending-- } catch (e) {} }
        p.then(done, done)
        return p
    }
    function run(fn) { return track(fn()) }
    function _press() {
        if (!enabled || working) return
        Store._clickOwner = autoBusy ? b : null
        try { b.clicked() } finally { Store._clickOwner = null }
    }
    onBusyWhileChanged: track(busyWhile)
    onWorkingChanged: {
        if (working) { hideT.stop(); if (!_shown) showT.restart() }
        else { showT.stop(); if (_shown) { hideT.interval = Math.max(0, b.busyMin - (Date.now() - _since)); hideT.restart() } }
    }
    Component.onCompleted: if (working) { _shown = true; _since = Date.now() }
    Component.onDestruction: if (Store._clickOwner === b) Store._clickOwner = null     // its click replaced the screen it was on
    Timer { id: showT; interval: b.busyDelay; onTriggered: { b._shown = true; b._since = Date.now() } }
    Timer { id: hideT; onTriggered: if (!b.working) b._shown = false }

    // the label never makes the button jump: it is as wide as the wider of its two texts
    TextMetrics { id: tmA; font: lbl.font; text: b.text }
    TextMetrics { id: tmB; font: lbl.font; text: b.busyText }
    readonly property real _textW: b.text === "" ? 0 : Math.ceil(Math.max(tmA.advanceWidth, b.busyText !== "" ? tmB.advanceWidth : 0)) + 1
    // the words on its face are as wide as they are, so they stay in the middle; the room for the longer text is the button's
    readonly property real _nowW: b.text === "" ? 0 : Math.ceil(b.shownText === b.text ? tmA.advanceWidth : tmB.advanceWidth) + 1
    implicitHeight: small ? Theme.hSm : large ? Theme.hLg : Theme.hMd
    implicitWidth: Math.max(implicitHeight, row.implicitWidth + (_textW - _nowW) + (text ? (small ? 20 : large ? 34 : 26) : (small ? 10 : 14)))
    opacity: enabled ? 1 : 0.4
    scale: down ? Theme.from(0.97) : 1
    activeFocusOnTab: true          // Qt skips hidden and disabled items by itself
    Behavior on scale { Glide { duration: Theme.press } }
    Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; if (!e.isAutoRepeat) kdown = true } }
    Keys.onReleased: function (e) { if (kdown && (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter)) { e.accepted = true; kdown = false; b._press() } }
    onActiveFocusChanged: if (!activeFocus) kdown = false
    Rectangle {
        id: face
        anchors.fill: parent; radius: height / 2          // Lightdesk: buttons are capsules
        readonly property bool hot: ma.containsMouse && b.enabled && !b.working
        color: b.kind === "primary" ? (b.down ? Qt.darker(Theme.send, 1.08) : hot ? Theme.sendHi : Theme.send)
             : b.kind === "quiet" ? (b.down ? Theme.washPress : b.active ? Theme.washOn : hot ? Theme.washHover : "transparent")
             : b.kind === "danger" ? (b.down ? Theme.alpha(Theme.signal, 0.24) : hot ? Theme.alpha(Theme.signal, 0.17) : Theme.alpha(Theme.signal, 0.1))
             : (b.down ? Theme.washPress : hot || b.active ? Theme.alpha(Theme.lineBase, Theme.dark ? 0.16 : 0.1) : Theme.alpha(Theme.lineBase, Theme.dark ? 0.1 : 0.055))
        border.width: b.kind === "default" ? 1 : 0; border.color: hot ? Theme.rule2 : Theme.rule
        Behavior on color { Tint {} }
        // a hairline of light on the top edge of raised buttons
        Rectangle { visible: b.kind === "default" || b.kind === "primary"; x: parent.radius; width: parent.width - 2 * parent.radius; y: 1; height: 1
            color: b.kind === "primary" ? Qt.rgba(1, 1, 1, Theme.dark ? 0.5 : 0.16) : Theme.gleam }
        // while busy, a soft sheen runs across the face: the button is visibly alive, not stuck
        Item { anchors.fill: parent; clip: true; visible: b._shown && !Theme.reduced
            Rectangle { id: sheen; width: parent.width * 0.5; height: parent.height; y: 0
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.5; color: b.kind === "primary" ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.06) }
                    GradientStop { position: 1; color: "transparent" } }
                NumberAnimation on x { running: b._shown && !Theme.reduced; from: -sheen.width; to: face.width; duration: 1100; loops: Animation.Infinite } } }
    }
    FocusRing { on: b.activeFocus; radius: face.radius + 3 }
    Row {
        id: row; anchors.centerIn: parent; spacing: b.small ? 5 : 6
        Item { visible: b.icon !== "" || b._shown; width: b.iconSize > 0 ? b.iconSize : b.small ? 13 : 14; height: width; anchors.verticalCenter: parent.verticalCenter
            Icon { anchors.centerIn: parent; visible: !b._shown; name: b.icon; size: parent.width
                color: b.kind === "primary" ? Theme.sendInk : b.kind === "danger" ? Theme.signal : (b.active || ma.containsMouse) ? Theme.ink : Theme.ink2 }
            Spinner { objectName: "btnSpinner"; anchors.centerIn: parent; visible: b._shown; size: parent.width; color: b.kind === "primary" ? Theme.sendInk : Theme.ink2 } }
        Text { id: lbl; visible: b.text !== ""; text: b.shownText; anchors.verticalCenter: parent.verticalCenter
            width: b._nowW; elide: Text.ElideRight
            font.family: Theme.sans; font.pixelSize: b.small ? 12 : b.large ? 14 : 13; font.letterSpacing: -0.1; font.weight: b.kind === "primary" ? Theme.wSemi : Theme.wMedium; renderType: Theme.textRender
            color: b.kind === "primary" ? Theme.sendInk : b.kind === "danger" ? Theme.signal : (b.kind === "quiet" && !b.active && !ma.containsMouse) ? Theme.ink2 : Theme.ink }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: b._shown ? Qt.BusyCursor : Qt.ArrowCursor; onClicked: b._press() }
    Tip { text: b._shown && b.busyText ? b.busyText : b.tip; keys: b._shown ? "" : b.keys; show: ma.containsMouse && (b.tip !== "" || (b._shown && b.busyText !== "")) && !ma.pressed && !b.active }     // not over the menu it has just opened
}
