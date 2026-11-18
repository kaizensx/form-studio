import QtQuick
import QtQuick.Window
import QtCore
import Form
import FormNative

// FORM — the window. Home is where a design starts; the agent on the left, the work in the middle.
Window {
    id: win
    property string startProject: ""
    property string startStage: ""
    property bool headless: false
    readonly property bool mac: Bridge.platform === "darwin"
    readonly property bool full: visibility === Window.FullScreen
    visible: true; color: Theme.plate
    // macOS draws the window title over our own top bar (the title bar is see-through), so it stays empty there;
    // the Dock, the app menu and Mission Control still say Form Studio. Windows and Linux show it in their frame.
    title: mac ? "" : Store.project ? Store.project.name + (Store.hasDraft ? " (draft)" : "") + " — Form Studio" : "Form Studio"
    minimumWidth: 1120; minimumHeight: 700
    // on macOS the content runs under a transparent title bar, so the window buttons sit in our own bar
    flags: mac ? Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint : Qt.Window

    // ── remembered between runs: window place and size, the agent column, recent commands ──
    Settings { id: mem; category: "window"
        property real x: -1; property real y: -1; property real w: 0; property real h: 0
        property real talkWidth: 340; property bool talkOpen: true; property string recent: "[]" }
    property bool restored: false
    function restore() {
        if (!headless) {
            if (mem.w >= minimumWidth && mem.h >= minimumHeight) { width = Math.min(mem.w, Screen.desktopAvailableWidth); height = Math.min(mem.h, Screen.desktopAvailableHeight) }
            // only where it is still on a screen
            if (mem.x >= 0 && mem.y >= 0 && mem.x < Screen.virtualX + Screen.desktopAvailableWidth - 120 && mem.y < Screen.virtualY + Screen.desktopAvailableHeight - 120) { x = mem.x; y = mem.y }
            Store.talkWidth = Math.max(talk.minW, Math.min(talk.maxW, mem.talkWidth)); Store.talkOpen = mem.talkOpen
            try { Store.paletteRecent = JSON.parse(mem.recent) } catch (e) { Store.paletteRecent = [] }
        }
        restored = true
    }
    function remember() {
        if (!restored || headless) return
        if (visibility === Window.Windowed) { mem.x = x; mem.y = y; mem.w = width; mem.h = height }
        mem.talkWidth = Store.talkWidth; mem.talkOpen = Store.talkOpen; mem.recent = JSON.stringify(Store.paletteRecent)
    }
    Timer { id: later; interval: 600; onTriggered: win.remember() }
    onXChanged: later.restart(); onYChanged: later.restart(); onWidthChanged: later.restart(); onHeightChanged: later.restart()
    onClosing: remember()
    Connections { target: Store
        function onTalkWidthChanged() { later.restart() }
        function onTalkOpenChanged() { later.restart() }
        function onPaletteRecentChanged() { later.restart() } }
    Component.onCompleted: { restore(); Store.boot(startProject, startStage); Store.bootSetup(headless); Store.checkWhatsNew(headless) }

    // the native menu bar (macOS). Elsewhere the same actions are in the top bar's menu button and the palette.
    Loader { active: win.mac; sourceComponent: MacMenu { onFullScreen: win.visibility = win.full ? Window.Windowed : Window.FullScreen } }

    TopBar { id: top; width: parent.width; inset: win.mac && !win.full ? 78 : 0; z: 10 }

    // collapsed: a slim rail keeps the agent's state in sight
    Rectangle {
        id: rail
        visible: Store.screen === "work"
        anchors.top: top.bottom; anchors.bottom: parent.bottom; width: 44; color: Theme.plate1
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.rule }
        Column { y: 10; width: parent.width; spacing: 4
            Item { width: 28; height: 28; anchors.horizontalCenter: parent.horizontalCenter
                Rectangle { anchors.fill: parent; radius: Theme.rSm; color: rm.pressed ? Theme.washPress : rm.containsMouse ? Theme.washHover : "transparent" }
                Rectangle { anchors.centerIn: parent; width: 8; height: 8; radius: 4
                    color: Store.chatBusy ? Theme.datum : Store.chatReady ? Theme.pass : Theme.ink4
                    SequentialAnimation on opacity { running: Store.chatBusy && rail.visible; loops: Animation.Infinite; alwaysRunToEnd: true
                        NumberAnimation { to: 0.3; duration: 600 } NumberAnimation { to: 1; duration: 600 } } }
                MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.talkOpen = true }
                Tip { show: rm.containsMouse; keys: "Ctrl+J"
                    text: Store.chatBusy ? Store.chatAgentLabel + " is working. Show the conversation" : Store.chatReady ? "Show the conversation" : "No agent is connected. Show the conversation" } }
            Btn { kind: "quiet"; icon: "message_square_plus"; tip: "New conversation"; keys: "Ctrl+Shift+O"; anchors.horizontalCenter: parent.horizontalCenter
                onClicked: { Store.newChat(); Store.talkOpen = true } }
            Btn { kind: "quiet"; icon: "history"; tip: "Conversations"; anchors.horizontalCenter: parent.horizontalCenter
                onClicked: { Store.talkOpen = true; talk.showList() } } }
    }
    Talk {
        id: talk
        readonly property int minW: 300
        readonly property int maxW: Math.max(minW, Math.min(560, win.width - 760))
        property bool dragging: false
        anchors.top: top.bottom; anchors.bottom: parent.bottom
        // Home is the start: the column appears there once a conversation is under way. While a design is being made
        // it is always there; in the workspace it can be folded away.
        readonly property bool shown: Store.screen === "designing" ? true
                                    : Store.screen === "home" ? Store.talkOpen && (Store.chatItems.length > 0 || Store.chatBusy)
                                    : Store.screen === "work" && Store.talkOpen
        width: Math.max(minW, Math.min(maxW, Store.talkWidth))
        x: shown ? 0 : -width
        Behavior on x { NumberAnimation { duration: Theme.move(260); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeDrawer } }
        Behavior on width { enabled: !talk.dragging && win.restored; NumberAnimation { duration: Theme.move(260); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeDrawer } }
        // drag the edge to resize; double-click puts it back
        MouseArea {
            visible: talk.shown; z: 9
            anchors.right: parent.right; anchors.rightMargin: -4; width: 9; height: parent.height
            hoverEnabled: true; cursorShape: Qt.SplitHCursor; preventStealing: true
            property real x0: 0; property real w0: 0
            onPressed: function (e) { talk.dragging = true; x0 = mapToItem(null, e.x, 0).x; w0 = talk.width }
            onPositionChanged: function (e) { if (pressed) Store.talkWidth = Math.max(talk.minW, Math.min(talk.maxW, w0 + mapToItem(null, e.x, 0).x - x0)) }
            onReleased: talk.dragging = false
            onDoubleClicked: Store.talkWidth = 340
            Rectangle { anchors.right: parent.right; anchors.rightMargin: 4; width: parent.pressed ? 2 : 1; height: parent.height
                color: Theme.datum; opacity: parent.pressed ? 0.9 : parent.containsMouse ? 0.5 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
        }
    }
    Item {
        id: stage
        anchors.top: top.bottom; anchors.bottom: parent.bottom
        x: Math.max(rail.visible ? rail.width : 0, talk.x + talk.width); width: parent.width - x
        Loader { id: homeLd; anchors.fill: parent; active: Store.screen === "home"; sourceComponent: Home {} }
        Loader { anchors.fill: parent; active: Store.screen === "work"; sourceComponent: Workspace {} }
        Loader { anchors.fill: parent; active: Store.screen === "designing"; sourceComponent: Designing {} }
        Column { anchors.centerIn: parent; visible: Store.screen === "boot"; spacing: 12
            Logo { size: 36; anchors.horizontalCenter: parent.horizontalCenter }
            Item { width: 1; height: 8 }
            Row { spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
                Spinner { size: 12; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; text: "Starting the CAD kernel…" } } }
    }
    Loader { anchors.top: top.bottom; anchors.bottom: parent.bottom; width: parent.width; z: 30; active: Store.welcome; sourceComponent: Welcome {} }
    Toasts { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 18; z: 80 }
    ActivityBar { anchors.top: top.bottom; width: parent.width; z: 70 }          // named engine work over 300 ms, with progress
    SheetHost {}
    Exports {}
    Palette { id: palette }
    Lightbox {}

    // Shortcuts. The native menu claims the same keys on macOS; Qt then reports them as ambiguous and hands the press to
    // one of the two, so each handler answers both signals and exactly one runs.
    function esc() {
        if (Store.lightbox) Store.lightbox = null
        else if (Store.paletteOpen) Store.paletteOpen = false
        else if (Store.ctxMenu) Store.ctxMenu = null
        else if (Store.sheet) Store.openSheet(null)
        else if (Store.measuring) Store.setMeasuring(false)
        else if (Store.selecting && Store.selItems.length) Store.selClear()
        else if (Store.selecting) Store.setSelecting(false)
        else if (Store.annFocus) Store.focusAnnotation(null)
        else if (Store.layers) Store.showLayers(false)
        else if (Store.feature) Store.select("")
    }
    function stageKey(id) { if (Store.data) Store.setStage(id) }
    function commitKey() { if (Store.hasDraft && !Store.draftError) Store.commit() }
    Shortcut { sequences: ["Ctrl+K"]; onActivated: Store.paletteOpen = !Store.paletteOpen; onActivatedAmbiguously: Store.paletteOpen = !Store.paletteOpen }
    Shortcut { sequence: "Escape"; onActivated: win.esc() }
    Shortcut { sequence: "Ctrl+1"; onActivated: win.stageKey("brief"); onActivatedAmbiguously: win.stageKey("brief") }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.stageKey("shape"); onActivatedAmbiguously: win.stageKey("shape") }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.stageKey("fit"); onActivatedAmbiguously: win.stageKey("fit") }
    Shortcut { sequence: "Ctrl+4"; onActivated: win.stageKey("prove"); onActivatedAmbiguously: win.stageKey("prove") }
    Shortcut { sequence: "Ctrl+5"; onActivated: win.stageKey("release"); onActivatedAmbiguously: win.stageKey("release") }
    Shortcut { sequence: "Ctrl+Return"; onActivated: win.commitKey(); onActivatedAmbiguously: win.commitKey() }
    function newDesign() { Store.openSheet(null); if (Store.screen !== "home") Store.home(); Store.startFocus++ }
    Shortcut { sequences: [StandardKey.New]; onActivated: win.newDesign(); onActivatedAmbiguously: win.newDesign() }
    Shortcut { sequence: "Ctrl+J"; onActivated: Store.talkOpen = !Store.talkOpen; onActivatedAmbiguously: Store.talkOpen = !Store.talkOpen }
    Shortcut { sequences: ["Ctrl+,"]; onActivated: Store.openSettings("general"); onActivatedAmbiguously: Store.openSettings("general") }      // Settings (⌘, on macOS)
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: { Store.newChat(); Store.talkOpen = true } onActivatedAmbiguously: { Store.newChat(); Store.talkOpen = true } }
    Shortcut { sequence: "Ctrl+Shift+H"; onActivated: Store.home(); onActivatedAmbiguously: Store.home() }
}
