import QtQuick
import QtQuick.Window
import FormNative
import "F.js" as F

// The window's own title bar, one calm line. Left: the agent column's toggle, where you are, which revision and whether
// it is released. Right: another conversation at work (outside the workspace, which says it over the view), the
// printer of a design made for printing, notices, search, settings. A 3D model shows no printer and no purpose: not
// printing is the normal case and needs no label. It gives up detail, never function, as the window narrows: search
// becomes its icon; notices become dots.
Rectangle {
    id: bar
    objectName: "topBar"
    property real inset: 0                    // room for the macOS window buttons
    height: 44; color: Theme.plate1
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    // the bar is the window's title bar: drag it to move the window, double-click it to zoom (macOS) or maximise.
    // Buttons and chips on it take their own clicks first.
    DragHandler { target: null; grabPermissions: PointerHandler.CanTakeOverFromAnything
        onActiveChanged: if (active && bar.Window.window) bar.Window.window.startSystemMove() }
    TapHandler { acceptedButtons: Qt.LeftButton; gesturePolicy: TapHandler.DragThreshold
        onDoubleTapped: { var w = bar.Window.window; if (!w) return
            w.visibility = w.visibility === Window.Maximized ? Window.Windowed : Window.Maximized } }
    readonly property var ap: Store.data ? Store.data.approval : null
    readonly property bool work: Store.screen === "work"
    readonly property bool roomy: width >= 1500
    readonly property bool tight: width < 1260
    readonly property Item logo: mark         // where the opening screen's lockup lands (Splash.qml)
    property bool logoHeld: false             // while that lockup travels here, so there are never two logos on screen
    // the empty middle of the bar, where the engine's work is named (ActivityBar.qml)
    readonly property real freeX: left.x + left.width + 16
    readonly property real freeW: Math.max(0, right.x - freeX - 16)

    Row { id: left; x: bar.inset + (bar.inset ? 4 : 10); anchors.verticalCenter: parent.verticalCenter; spacing: 4
        // elsewhere than macOS there is no menu bar at the top of the screen: the same actions live here
        Btn { id: menuBtn; visible: !Theme.mac; kind: "quiet"; icon: "menu"; tip: "Menu"; active: appMenu.opened; onClicked: appMenu.opened ? appMenu.close() : appMenu.open()
            PopMenu { id: appMenu; y: parent.height + 6; width: 264
                model: [
                    { icon: "plus", text: "New design", keys: "Ctrl+N", run: function () { Store.startNew() } },
                    { icon: "message_square_plus", text: "New conversation", keys: "Ctrl+Shift+O", run: function () { Store.newChat(); Store.talkOpen = true } },
                    { icon: "import", text: "Import…", run: function () { Store.askImport() } },
                    { icon: "archive", text: "Export this design…", enabled: !!Store.project, run: function () { Store.exportProject(Store.pid) } },
                    { sep: true },
                    { icon: "home", text: "All designs", keys: "Ctrl+Shift+H", run: function () { Store.home() } },
                    { icon: "folder_open", text: "Open the projects folder", run: function () { Bridge.openDataFolder() } },
                    { sep: true },
                    { icon: "search", text: "Search and commands…", keys: "Ctrl+K", run: function () { Store.paletteOpen = true } },
                    { icon: "keyboard", text: "Keyboard shortcuts", run: function () { Store.openSheet("shortcuts") } },
                    { icon: "wrench", text: "Software: install or check…", run: function () { Store.openSetup() } },
                    { icon: "settings", text: "Settings…", keys: "Ctrl+,", run: function () { Store.openSettings("general") } },
                    { sep: true },
                    { icon: "sparkle", text: "What’s new", run: function () { Store.showWhatsNew() } },
                    { icon: "info", text: "About Form Studio", run: function () { Store.openSheet("about") } }
                ] } }
        Btn { visible: bar.work; kind: "quiet"; icon: Store.talkOpen ? "panel_left_close" : "panel_left_open"; keys: "Ctrl+J"
            tip: Store.talkOpen ? "Hide the conversation" : "Show the conversation"; onClicked: Store.talkOpen = !Store.talkOpen }
        Item { id: logoBox; objectName: "homeButton"; width: mark.implicitWidth + 16; height: 28; anchors.verticalCenter: parent.verticalCenter
            baselineOffset: mark.y + mark.baselineOffset          // the name, revision and tag sit on the wordmark's baseline
            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
            Logo { id: mark; anchors.centerIn: parent; size: 14; opacity: bar.logoHeld ? 0 : 1; ink: bar.work ? Theme.ink2 : Theme.ink; ink2: bar.work ? Theme.ink3 : Theme.ink2 }
            MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.home() }
            Tip { show: hm.containsMouse && bar.work; text: "All designs"; keys: "Ctrl+Shift+H" } }
        Txt { visible: !!Store.project; text: "/"; tone: 4; anchors.baseline: logoBox.baseline; leftPadding: 2; rightPadding: 6 }
        Txt { id: pname; visible: !!Store.project; text: Store.project ? Store.project.name : ""; font.weight: Theme.wSemi; anchors.baseline: logoBox.baseline
            width: Math.min(implicitWidth, Math.max(120, bar.width - left.x - right.width - 420)); elide: Text.ElideRight; wrapMode: Text.NoWrap
            HoverHandler { id: ph }
            Tip { show: ph.hovered && !!Store.recipe; text: Store.recipe && Store.project ? (String(Store.project.recipe).indexOf("src:") === 0 ? "Designed by an agent" : "Started from: " + Store.recipe.title) : "" } }
        Item { width: 6; height: 1 }
        // the revision. A commit lands here: the number takes the settled colour for a moment and comes to rest,
        // so saving a revision is seen where the revision is named (not when another design opens).
        Txt { id: revTxt; objectName: "topRevision"; visible: !!Store.project; mono: true; font.pixelSize: 12; text: Store.project ? F.pad(Store.project.head) : ""; anchors.baseline: logoBox.baseline
            property real lit: 0
            property string forPid: ""
            property int was: 0
            color: Qt.tint(Theme.ink2, Theme.alpha(Theme.pass, lit))
            transformOrigin: Item.Left; scale: 1 + 0.12 * lit * (Theme.reduced ? 0 : 1)
            readonly property int head: Store.project ? Store.project.head : 0
            onHeadChanged: { var same = Store.pid === forPid && was > 0 && head > was; forPid = Store.pid; was = head; if (same) landed.restart() }
            SequentialAnimation { id: landed
                NumberAnimation { target: revTxt; property: "lit"; to: 1; duration: Theme.fast; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
                PauseAnimation { duration: 500 }
                NumberAnimation { target: revTxt; property: "lit"; to: 0; duration: 700; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } }
        Item { width: 6; height: 1 }
        Tag { visible: !!Store.project && text !== ""; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 1
            kind: Store.hasDraft ? "draft" : bar.ap && bar.ap.state === "approved" ? "PASS" : bar.ap && bar.ap.state === "superseded" ? "WARN" : ""
            text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "draft" : bar.ap.state === "approved" ? "released"
                : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " released" : "unreleased"
            HoverHandler { id: th }
            Tip { show: th.hovered
                text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "There is an uncommitted draft on top of " + F.pad(Store.project.head)
                    : bar.ap.state === "approved" ? F.pad(Store.project.head) + " is released"
                    : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " is released. " + F.pad(Store.project.head) + " is not."
                    : F.pad(Store.project.head) + " has not been approved for release" } }
        // a partial build (features left out, a feature that hung, parts still to come): saved and shown, not released
        Item { visible: !!Store.partial; width: 6; height: 1 }
        Tag { objectName: "partialBadge"; visible: !!Store.project && !!Store.partial; kind: "partial"; text: "partial"
            anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: 1
            HoverHandler { id: pth }
            Tip { show: pth.hovered; text: Store.project ? F.pad(Store.project.head) + " is a partial build. " + Store.partialLine : "" } }
    }
    Row { id: right; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 6
        // another conversation is working while Home or a design being made is in front: named, one click opens it
        Rectangle { id: away; objectName: "agentElsewhereBar"; visible: !bar.work && !!Store.agentElsewhere && Store.screen !== "boot"
            anchors.verticalCenter: parent.verticalCenter; height: 26; radius: 13
            width: awt.width + 35
            color: awm.pressed ? Theme.washPress : awm.containsMouse ? Theme.plate3 : Theme.plate2; border.color: Theme.rule2
            Behavior on color { Tint {} }
            Row { id: awr; x: 11; spacing: 7; anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity { running: away.visible && !Theme.reduced; loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                Txt { id: awt; kind: "fine"; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                    width: Math.min(implicitWidth, Math.max(130, bar.width * 0.3 - 35)); elide: Text.ElideRight
                    text: Store.agentElsewhere ? Store.agentElsewhere.by + " is working on " + Store.agentElsewhere.name : "" } }
            MouseArea { id: awm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.showElsewhere() }
            Tip { show: awm.containsMouse; text: Store.agentElsewhere && Store.agentElsewhere.title ? "In “" + Store.agentElsewhere.title + "”. Click to open that conversation." : "Click to open it." } }
        // the printer a design made for printing prints on, in every stage (a 3D model has none)
        PrinterChip { anchors.verticalCenter: parent.verticalCenter; visible: Store.printUi && bar.work; roomy: bar.roomy }
        StatusChips { anchors.verticalCenter: parent.verticalCenter; compact: bar.work ? !bar.roomy : bar.tight }      // setup / update notices
        Rectangle { visible: !bar.tight; width: bar.roomy ? 220 : 170; height: 26; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
            color: sm.pressed ? Theme.plate : sm.containsMouse ? Theme.plate2 : Theme.well; border.color: sm.containsMouse ? Theme.rule2 : Theme.rule
            Behavior on color { Tint {} }
            Icon { x: 9; name: "search"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
            Txt { x: 29; text: bar.roomy ? "Search and commands" : "Search"; tone: 3; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            Kbd { keys: "Ctrl+K"; quiet: true; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.paletteOpen = true } }
        Btn { visible: bar.tight; kind: "quiet"; icon: "search"; tip: "Search and commands"; keys: "Ctrl+K"; onClicked: Store.paletteOpen = true }
        Btn { kind: "quiet"; icon: "settings"; tip: "Settings"; keys: "Ctrl+,"; active: !!Store.sheet && Store.sheet.kind === "settings"; onClicked: Store.openSettings("general") }   // setup workstream
    }
}
