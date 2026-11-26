import QtQuick
import QtQuick.Window
import QtCore
import Form
import FormNative

// Form Studio — the window (Lightdesk). One room: Home is where a design starts; a workspace is the 3D view edge to
// edge with every control a pane of glass over it, and the conversation one bar under the part.
Window {
    id: win
    property string startProject: ""
    property string startStage: ""
    property bool headless: false
    readonly property bool mac: Bridge.platform === "darwin"
    readonly property bool full: visibility === Window.FullScreen
    // a workspace fills the window with its 3D view; Home and the first run stand in the window's own room
    readonly property bool plates: Store.screen === "work" || Store.screen === "designing"
    visible: true; color: Theme.frame
    // macOS draws the window title over our own top bar (the title bar is see-through), so it stays empty there;
    // the Dock, the app menu and Mission Control still say Form Studio. Windows and Linux show it in their frame.
    title: mac ? "" : Store.project ? Store.project.name + (Store.hasDraft ? " (draft)" : "") + " — Form Studio" : "Form Studio"
    minimumWidth: 1100; minimumHeight: 700
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
            Store.talkWidth = Math.max(talk.minW, Math.min(talk.maxW, mem.talkWidth)); Store.talkOpen = mem.talkOpen && width >= 1200      // a narrow window starts with the conversation folded: the part and its panes first
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
    onXChanged: later.restart(); onYChanged: later.restart()
    onWidthChanged: { later.restart(); buttons.restart() } onHeightChanged: { later.restart(); buttons.restart() }
    // macOS: the window buttons sit on the top row's centre line, as far in from the side as the row's capsules begin
    // below the top (TopBar.buttonsX); AppKit puts them back after a resize or full screen, so they are moved again then
    function centerButtons() { if (mac && !full && !headless) Bridge.centerWindowButtons(win, top.capY * 2 + top.capH, top.buttonsX) }
    Timer { id: buttons; interval: 0; onTriggered: win.centerButtons() }
    onVisibilityChanged: buttons.restart()
    onActiveChanged: buttons.restart()
    onClosing: remember()
    Connections { target: Store
        function onTalkWidthChanged() { later.restart() }
        function onTalkOpenChanged() { later.restart() }
        function onPaletteRecentChanged() { later.restart() } }
    Component.onCompleted: { setBackdrop(); restore(); buttons.restart(); Store.boot(startProject, startStage); Store.bootSetup(headless); Store.checkWhatsNew(headless) }

    // the native menu bar (macOS). Elsewhere the same actions are in the top bar's menu button and the palette.
    Loader { active: win.mac; sourceComponent: MacMenu { onFullScreen: win.visibility = win.full ? Window.Windowed : Window.FullScreen } }

    // the room behind Home, the first run and the opening screen: what their glass blurs. A workspace brings its own
    // (the 3D view) and puts it in Store.backdrop while it is in front.
    Room { id: room; anchors.fill: parent; visible: !win.plates; poolX: 0.5; poolY: 0.27; poolW: Math.min(width * 1.1, 1500); poolH: 760; poolK: Theme.dark ? 0.1 : 0.9
        breathe: Store.screen === "home" && !Store.sheet && win.active }
    function setBackdrop() { if (!win.plates) Store.backdrop = room }
    Connections { target: Store; function onScreenChanged() { win.setBackdrop() } }

    TopBar { id: top; width: parent.width; inset: win.mac && !win.full ? top.buttonsX + 54 + 8 : 0; z: 10; logoHeld: splash.visible && splash.carrying }

    // The conversation. In a workspace: one bar under the part, clear of the view buttons on its left and the panes on
    // its right; it opens upward into the transcript sheet with a spring and folds back while a build plays. On Home:
    // a glass column on the left once a conversation is under way.
    Talk {
        id: talk
        z: 6
        // In a workspace the conversation, once something was said, is a glass column on the left: under the top row,
        // down to the foot of the window, with the gutters of the panes on the right. The stage is what is left
        // between the two. Folded (Ctrl+J, the column's own button) it is the bar under the part, as it is before
        // anything was said. (A window under 1200 px has room for the column or the panes, not both: Workspace.panesOff.)
        readonly property bool col: Store.screen === "work" && Store.talkOpen && !empty && !Store.talkCalm && !Store.focusView
        // 340 px wide unless its edge was dragged (300 to 480, remembered with the window)
        readonly property int colW: Math.round(Math.max(300, Math.min(480, win.width - 700, Store.talkWidth)))
        bar: win.plates && !col
        docked: col
        drawer: Store.screen !== "work"
        onScreen: shown
        readonly property int minW: 300
        readonly property int maxW: Math.max(minW, Math.min(560, win.width - 760))
        property bool dragging: false
        readonly property bool shown: Store.screen === "designing" || Store.screen === "work" ? true
                                    : Store.screen === "home" ? Store.talkOpen && (Store.chatItems.length > 0 || Store.chatBusy) : false
        // the bar: where it may be, and how tall
        readonly property bool tight: win.width < 1300                         // the view buttons fold to one
        readonly property real leftLimit: tight ? 140 : 328
        readonly property real rightLimit: win.width - Theme.edge - Theme.paneW - Theme.gap
        // One rule for where the bar stands: on the window's centre line, as wide as fits there between the view
        // buttons and the panes (600 at most). Only in a window so narrow that this would leave it under 440 px does
        // it stand in the middle of the free strip between them instead.
        readonly property real axisRoom: 2 * Math.min(win.width / 2 - leftLimit, rightLimit - win.width / 2)
        readonly property bool centred: axisRoom >= 440
        readonly property real barW: Math.round(centred ? Math.min(600, axisRoom) : Math.max(360, Math.min(600, rightLimit - leftLimit)))
        readonly property real barX: Math.round(centred ? (win.width - barW) / 2 : leftLimit + (rightLimit - leftLimit - barW) / 2)
        // open, it is a drawer as tall as what was said and never more than 40 % of the window: the stage keeps the rest
        readonly property real sheetMax: Math.round(Math.max(barHeight + 150, win.height * 0.4))
        readonly property real sheetH: Math.round(Math.max(barHeight + 150, Math.min(sheetMax, barHeight + bodyWant)))
        // k: 0 folded .. 1 open; a spring carries it (Reduce Motion: it is there at once and only the words fade)
        property real k: expanded ? 1 : 0
        Behavior on k { enabled: win.restored && !Theme.reduced; SpringAnimation { spring: Theme.springK; damping: Theme.springDamp; mass: 0.9; epsilon: 0.001 } }
        roomAbove: win.height - 110
        width: bar ? barW : col ? colW : Math.max(minW, Math.min(maxW, Store.talkWidth))
        height: bar ? Math.round(barHeight + (sheetH - barHeight) * Math.max(0, k)) : col ? win.height - Theme.paneTop - Theme.edge : win.height - top.height - Theme.gap
        x: bar ? barX : col ? Theme.edge : shown ? Theme.gap : -width - Theme.gap - 40
        y: bar ? win.height - Theme.edge - height : col ? Theme.paneTop : top.height
        // the column and the bar are two places: one fades in where it stands, it does not fly across the part
        onColChanged: if (win.restored && Store.screen === "work") swap.restart()
        NumberAnimation { id: swap; target: talk; property: "opacity"; from: 0; to: 1; duration: Theme.base; easing.type: Easing.OutCubic }
        // where the column ends, for the workspace: its tools and its stage begin right of it
        Binding { target: Store; property: "talkCol"; value: talk.col ? Theme.edge + talk.colW : 0 }
        Behavior on x { enabled: !talk.bar && !talk.col; NumberAnimation { duration: Theme.move(260); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeDrawer } }
        Behavior on width { enabled: !talk.bar && !talk.col && !talk.dragging && win.restored; NumberAnimation { duration: Theme.move(260); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeDrawer } }
        // where the bar is, for the screen in front: the camera keeps the part clear of it, the cue sits above it
        onYChanged: if (bar) Store.barY = y
        onBarChanged: Store.barY = bar ? y : win.height
        Binding { target: Store; property: "barRestY"; value: talk.bar ? win.height - Theme.edge - talk.restHeight : win.height }
        onXChanged: if (bar) Store.barX = x
        onWidthChanged: if (bar) Store.barW = width
        Component.onCompleted: { Store.barY = bar ? y : win.height; Store.barX = x; Store.barW = width }
        // the column on Home: drag the edge to resize; double-click puts it back
        MouseArea {
            visible: talk.shown && !talk.bar; z: 9
            anchors.right: parent.right; anchors.rightMargin: -4; width: 9; height: parent.height
            hoverEnabled: true; cursorShape: Qt.SplitHCursor; preventStealing: true
            property real x0: 0; property real w0: 0
            onPressed: function (e) { talk.dragging = true; Store.talkDragging = true; x0 = mapToItem(null, e.x, 0).x; w0 = talk.width }
            onPositionChanged: function (e) { if (pressed) Store.talkWidth = Math.max(talk.minW, Math.min(talk.col ? 480 : talk.maxW, w0 + mapToItem(null, e.x, 0).x - x0)) }
            onReleased: { talk.dragging = false; Store.talkDragging = false }
            onDoubleClicked: Store.talkWidth = 340
        }
    }
    Item {
        id: stage
        // a workspace runs under the top bar's capsules, edge to edge; Home starts below them
        y: win.plates ? 0 : top.height; height: parent.height - y
        x: win.plates ? 0 : Math.max(0, talk.x + talk.width); width: parent.width - x
        // One screen hands over to the next along one axis, depth: going deeper (Home -> designing -> the workspace)
        // the new screen pushes in from slightly small; coming back it settles from slightly large. Its panels then
        // arrive a beat apart (each screen staggers its own). Reduced motion: a plain fade.
        readonly property var order: ({ boot: -1, home: 0, designing: 1, work: 2 })
        property string was: "boot"
        function enter(it) {
            var prev = stage.was; stage.was = Store.screen
            if (!it || prev === "boot") return
            // the saved design taking over from the stages drawn while it built: the part stays where it is
            if (Store.calmArrive) { Store.calmArrive = false; arrive.stop(); it.opacity = 1; it.scale = 1; return }
            var deeper = (stage.order[Store.screen] || 0) >= (stage.order[prev] || 0)
            arrive.target = it
            arriveScale.from = Theme.from(deeper ? 0.975 : 1.025)
            arrive.restart()
        }
        ParallelAnimation { id: arrive; property Item target: null
            NumberAnimation { target: arrive.target; property: "opacity"; from: 0; to: 1; duration: Theme.screen * 0.7; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
            NumberAnimation { id: arriveScale; target: arrive.target; property: "scale"; to: 1; duration: Theme.move(Theme.screen); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        Loader { id: homeLd; anchors.fill: parent; active: Store.screen === "home"; onLoaded: stage.enter(item); sourceComponent: Home {} }
        Loader { anchors.fill: parent; active: Store.screen === "work"; onLoaded: stage.enter(item); sourceComponent: Workspace {} }
        Loader { anchors.fill: parent
            active: Store.screen === "designing"; onLoaded: stage.enter(item); sourceComponent: Designing {} }
    }
    Loader { anchors.top: top.bottom; anchors.bottom: parent.bottom; width: parent.width; z: 30; active: Store.welcome; sourceComponent: Welcome {} }
    // the opening screen: the mark is drawn on its origin while the engine starts, then travels to the top bar's logo.
    // It stays until the mark is drawn (under a second), never longer than the engine needs.
    Splash { id: splash; anchors.fill: parent; z: 90; visible: !win.headless && !Bridge.underTest && showing; landOn: top.logo
        status: Store.bootStatus
        done: Store.screen !== "boot" && splashMin.ran
        Timer { id: splashMin; property bool ran: win.headless; interval: Theme.reduced ? 300 : 800; running: true; onTriggered: ran = true } }
    MorphFrame { id: morph; anchors.fill: parent; z: 85
        to: { var p = stage.mapToItem(null, 0, 0); return Qt.rect(p.x, p.y, stage.width, stage.height) } }
    Connections { target: Store; function onMorphFrom(r) { morph.play(r) } }
    Toasts { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 18; z: 80 }
    ActivityBar { y: 0; width: parent.width; z: 70; barH: top.capY * 2 + top.capH; slotX: top.freeX; slotW: top.freeW
        dropX: win.plates ? talk.barX + talk.barW / 2 : -1 }          // named engine work over 300 ms, with progress
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
        else if (Store.compare) Store.endCompare()
        else if (Store.measuring) Store.setMeasuring(false)
        else if (Store.selecting && Store.selItems.length) Store.selClear()
        else if (Store.selecting) Store.setSelecting(false)
        else if (Store.annFocus) Store.focusAnnotation(null)
        else if (Store.layers) Store.showLayers(false)
        else if (Store.feature) Store.select("")
        else if (Store.focusView) Store.focusView = false
        else if (talk.col) Store.talkCalm = true           // nothing else to leave: the conversation steps back, the part has the room
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
    function newDesign() { Store.startNew() }
    Shortcut { sequences: [StandardKey.New]; onActivated: win.newDesign(); onActivatedAmbiguously: win.newDesign() }
    Shortcut { sequence: "Ctrl+J"; onActivated: Store.toggleTalk(); onActivatedAmbiguously: Store.toggleTalk() }
    // Focus: both side columns step away and the part has the window; again to bring them back
    function focusKey() { if (Store.screen === "work" && !Store.sheet) Store.focusView = !Store.focusView }
    Shortcut { sequence: "Ctrl+."; onActivated: win.focusKey(); onActivatedAmbiguously: win.focusKey() }
    Shortcut { sequences: ["Ctrl+,"]; onActivated: Store.openSettings("general"); onActivatedAmbiguously: Store.openSettings("general") }      // Settings (⌘, on macOS)
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: { Store.newChat(); Store.talkOpen = true } onActivatedAmbiguously: { Store.newChat(); Store.talkOpen = true } }
    Shortcut { sequence: "Ctrl+Shift+H"; onActivated: Store.home(); onActivatedAmbiguously: Store.home() }
    // back: out of a design to all designs, as in a browser or the Finder (the title capsule's ‹ does the same)
    function back() { if (Store.sheet || Store.paletteOpen) return; if (Store.screen === "work" || Store.screen === "designing") Store.home() }
    Shortcut { sequence: "Ctrl+["; onActivated: win.back(); onActivatedAmbiguously: win.back() }
}
