import QtQuick
import QtQuick.Window
import FormNative
import "F.js" as F

// The top of the window: three glass capsules floating over the room, and nothing between them.
//   left    the mark (home), the design's name, its revision and whether it is released
//   centre  the four modes of the design, each with its one line (StageTabs), in a workspace
//   right   notices, search, settings; the printer only in Make, of a design made for printing
// The name in the left capsule opens the Overview of the design (what Describe was).
// On Home the left capsule is just the lockup, without glass. A 3D model shows no printer and no purpose: not printing
// is the normal case and needs no label. As the window narrows the name is cut first, then the stages draw closer;
// nothing loses its function. The strip is still the window's title bar: drag it to move the window.
Item {
    id: bar
    objectName: "topBar"
    property real inset: 0                    // room for the macOS window buttons
    readonly property int capY: 16            // where the capsules sit, and how tall they are
    readonly property int capH: 44
    // macOS: where the close button starts. The three buttons (54 px) stand on the capsules' centre line, 24 px in
    // from the side, and the title capsule begins 14 px after them: one row, evenly spaced.
    readonly property int buttonsX: 24
    height: 44                                // what Home starts under; the capsules reach a little below it
    Item { id: grip; width: parent.width; height: bar.work ? bar.capY + bar.capH + 8 : bar.height      // on Home the column's header starts right under the bar
        // drag to move the window, double-click to zoom (macOS) or maximise. Buttons and chips take their own clicks first.
        DragHandler { target: null; grabPermissions: PointerHandler.CanTakeOverFromAnything
            onActiveChanged: if (active && bar.Window.window) bar.Window.window.startSystemMove() }
        TapHandler { acceptedButtons: Qt.LeftButton; gesturePolicy: TapHandler.DragThreshold
            onDoubleTapped: { var w = bar.Window.window; if (!w) return
                w.visibility = w.visibility === Window.Maximized ? Window.Windowed : Window.Maximized } } }
    readonly property var ap: Store.data ? Store.data.approval : null
    readonly property bool work: Store.screen === "work"
    readonly property bool roomy: width >= 1500
    readonly property bool tight: width < 1260
    readonly property Item logo: mark         // where the opening screen's lockup lands (Splash.qml)
    property bool logoHeld: false             // while that lockup travels here, so there are never two logos on screen
    // the free strip between the capsules, where the engine's work is named (ActivityBar.qml)
    readonly property real freeX: (stages.visible ? stages.x + stages.width : left.x + left.width) + 12
    readonly property real freeW: Math.max(0, right.x - freeX - 12)

    // ── left: where you are ──
    Glass {
        id: left
        objectName: "titleCapsule"
        source: Store.backdrop; arrive: 0
        // on Home it is the lockup alone: no pane
        bare: !bar.work
        x: Math.max(Theme.edge, bar.inset + 6); y: bar.capY; height: bar.capH; radius: height / 2
        visible: !Store.welcome               // the first run brings its own lockup
        width: lrow.implicitWidth + (bar.work ? 22 : 12)
        Row { id: lrow; x: bar.work ? 8 : 6; anchors.verticalCenter: parent.verticalCenter; spacing: 4
            // the way back to all designs: in a design the mark carries a ‹, and the two are one button
            Item { id: logoBox; objectName: "homeButton"; width: mark.implicitWidth + 16 + (bar.work ? 16 : 0); height: 30; anchors.verticalCenter: parent.verticalCenter
                baselineOffset: mark.y + mark.baselineOffset
                Rectangle { anchors.fill: parent; radius: height / 2; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                // the mark alone beside a design's name; the whole lockup on Home
                Icon { objectName: "backChevron"; visible: bar.work; x: 5; anchors.verticalCenter: parent.verticalCenter; name: "chevron_left"; size: 14
                    color: hm.containsMouse ? Theme.ink : Theme.ink3; Behavior on color { Tint {} }
                    transform: Translate { x: hm.containsMouse && !hm.pressed ? -Theme.shift(2) : 0; Behavior on x { Glide { duration: Theme.fast } } } }
                Logo { id: mark; anchors.verticalCenter: parent.verticalCenter; x: parent.width - width - 8; size: 18; word: !bar.work; opacity: bar.logoHeld ? 0 : 1 }
                MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.home() }
                Tip { show: hm.containsMouse && bar.work; below: true; text: "Back to all designs"; keys: "Ctrl+[" } }
            Txt { id: pname; visible: bar.work && !!Store.project; text: Store.project ? Store.project.name : ""; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, Math.max(90, (bar.width - stages.natural) / 2 - left.x - (stateTag.visible ? 210 : 104) - (partial.visible ? 60 : 0))); elide: Text.ElideRight; wrapMode: Text.NoWrap
                HoverHandler { id: ph }
                MouseArea { objectName: "designCapsule"; anchors.fill: parent; anchors.margins: -7; cursorShape: Qt.PointingHandCursor; onClicked: Store.toggleOverview() }
                Tip { show: ph.hovered && !!Store.recipe; below: true; keys: "Ctrl+I"; text: Store.overview ? "Close the Overview" : "Overview: the brief, what is known, the revisions" } }
            Item { width: 5; height: 1; visible: pname.visible }
            // the revision. A commit lands here: the number takes the pass colour for a moment and comes to rest,
            // so saving a revision is seen where the revision is named.
            Txt { id: revTxt; objectName: "topRevision"; visible: bar.work && !!Store.project; mono: true; font.pixelSize: 12; text: Store.project ? F.pad(Store.project.head) : ""
                anchors.verticalCenter: parent.verticalCenter
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
            Item { width: 5; height: 1; visible: stateTag.visible }
            // "unreleased" is how every design starts: it is said where there is room (1400 px and wider); a draft,
            // a release and a superseded release are always said
            Tag { id: stateTag; visible: bar.work && !!Store.project && text !== "" && (text !== "unreleased" || (bar.width >= 1400 && !Frame.tabs.length)); anchors.verticalCenter: parent.verticalCenter
                kind: Store.hasDraft ? "draft" : bar.ap && bar.ap.state === "approved" ? "PASS" : bar.ap && bar.ap.state === "superseded" ? "WARN" : ""
                text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "draft" : bar.ap.state === "approved" ? "released"
                    : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " released" : "unreleased"
                HoverHandler { id: th }
                Tip { show: th.hovered; below: true
                    text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "There is an uncommitted draft on top of " + F.pad(Store.project.head)
                        : bar.ap.state === "approved" ? F.pad(Store.project.head) + " is released"
                        : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " is released. " + F.pad(Store.project.head) + " is not."
                        : F.pad(Store.project.head) + " has not been approved for release" } }
            // a partial build (features left out, a feature that hung, parts still to come): saved and shown, not released
            Item { visible: partial.visible; width: 2; height: 1 }
            Tag { id: partial; objectName: "partialBadge"; visible: bar.work && !!Store.project && !!Store.partial; kind: "partial"; text: "partial"
                anchors.verticalCenter: parent.verticalCenter
                HoverHandler { id: pth }
                Tip { show: pth.hovered; below: true; text: Store.project ? F.pad(Store.project.head) + " is a partial build. " + Store.partialLine : "" } }
            // the design's menu (and, where there is no menu bar at the top of the screen, the app's)
            Btn { id: menuBtn; objectName: "titleMenu"; visible: bar.work || !Theme.mac; kind: "quiet"; small: true; icon: bar.work ? "chevron_down" : "menu"; tip: "Menu"
                anchors.verticalCenter: parent.verticalCenter; active: appMenu.opened; onClicked: appMenu.opened ? appMenu.close() : appMenu.open()
                PopMenu { id: appMenu; y: parent.height + 12; width: 264
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
        }
    }

    // ── left, after the design: its open things as tabs (Frame.qml). They take the room left of the modes; the
    //    modes leave the centre line only when the tabs need more than that, and fold to a count before the modes shrink ──
    DocTabStrip {
        id: docTabs
        source: Store.backdrop; arrive: 0
        x: left.x + left.width + 8; y: bar.capY
        readonly property real spare: right.x - 24 - x - stages.natural
        room: bar.work && !!Store.data ? Math.max(0, spare >= 140 ? spare : right.x - 24 - x - 330) : 0
        visible: bar.work && !!Store.data && on && room >= 120
    }
    readonly property real leftEnd: docTabs.visible ? docTabs.x + docTabs.width : left.x + left.width

    // ── centre: the stages ──
    StageTabs {
        id: stages
        source: Store.backdrop; arrive: 1
        visible: bar.work && !!Store.data
        y: bar.capY - 4
        // on the window's centre line whenever its words fit there between the two capsules; only when they do not
        // does it take all the room between them, off the centre
        readonly property real onLine: 2 * Math.min(bar.width / 2 - (bar.leftEnd + 12), right.x - 12 - bar.width / 2)
        readonly property bool centred: onLine >= natural
        room: centred ? onLine : Math.max(330, right.x - bar.leftEnd - 24)
        x: Math.round(centred ? (bar.width - width) / 2 : Math.max(bar.leftEnd + 12, Math.min((bar.width - width) / 2, right.x - 12 - width)))
        Behavior on x { enabled: stages.visible && Store.screen === "work"; NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
    }

    // ── right: the printer, notices, search, settings ──
    Glass {
        id: right
        objectName: "toolsCapsule"
        source: Store.backdrop; arrive: 2
        anchors.right: parent.right; anchors.rightMargin: Theme.edge; y: bar.capY; height: bar.capH; radius: height / 2
        width: rrow.implicitWidth + 14
        visible: !Store.welcome
        onXChanged: place()
        Row { id: rrow; x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 2
            // another conversation is working while Home or a design being made is in front: named, one click opens it
            Rectangle { id: away; objectName: "agentElsewhereBar"; visible: !bar.work && !!Store.agentElsewhere && Store.screen !== "boot"
                anchors.verticalCenter: parent.verticalCenter; height: 30; radius: 15
                width: awt.width + 35
                color: awm.pressed ? Theme.washPress : awm.containsMouse ? Theme.washHover : "transparent"
                Behavior on color { Tint {} }
                Row { id: awr; x: 11; spacing: 7; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity { running: away.visible && !Theme.reduced; loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                    Txt { id: awt; kind: "fine"; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                        width: Math.min(implicitWidth, Math.max(130, bar.width * 0.3 - 35)); elide: Text.ElideRight
                        text: Store.agentElsewhere ? Store.agentElsewhere.by + " is working on " + Store.agentElsewhere.name : "" } }
                MouseArea { id: awm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.showElsewhere() }
                Tip { show: awm.containsMouse; below: true; text: Store.agentElsewhere && Store.agentElsewhere.title ? "In “" + Store.agentElsewhere.title + "”. Click to open that conversation." : "Click to open it." } }
            // the printer a design made for printing prints on: a property of the print route, so only in Make
            PrinterChip { id: printer; anchors.verticalCenter: parent.verticalCenter; visible: Store.printUi && bar.work && Store.mode === "release"; roomy: bar.roomy; iconOnly: bar.width < 1400 }      // under 1400 px its name would push the stages off the window's centre line
            Item { visible: printer.visible || away.visible; width: 13; height: 18; anchors.verticalCenter: parent.verticalCenter
                Rectangle { x: 6; width: 1; height: parent.height; color: Theme.rule } }
            StatusChips { anchors.verticalCenter: parent.verticalCenter; compact: bar.work ? !bar.roomy : bar.tight }      // setup / update notices
            Item { id: search; objectName: "searchButton"; width: srow.implicitWidth + 18; height: 32; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.fill: parent; radius: 16; color: sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                Row { id: srow; anchors.centerIn: parent; spacing: 8
                    Icon { name: "search"; size: 16; color: sm.containsMouse ? Theme.ink : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                    Txt { mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 3; text: Theme.keyText("Ctrl+K"); anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } }
                MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.paletteOpen = true }
                Tip { show: sm.containsMouse; below: true; text: "Search and commands"; keys: "Ctrl+K" } }
            // the Bench, open: every study, route and document on one sheet
            Item { id: benchBtn; objectName: "benchButton"; visible: bar.work && !!Store.data; width: brow.implicitWidth + 18; height: 32; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.fill: parent; radius: 16; color: bbm.pressed ? Theme.washPress : bbm.containsMouse || Store.benchOpen ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                Row { id: brow; anchors.centerIn: parent; spacing: 8
                    Icon { name: "list_checks"; size: 16; color: bbm.containsMouse || Store.benchOpen ? Theme.ink : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                    Txt { mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 3; text: Theme.keyText("Ctrl+B"); anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } }
                MouseArea { id: bbm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.toggleBench() }
                Tip { show: bbm.containsMouse; below: true; text: Store.benchOpen ? "Close the Bench" : "The Bench: every study, route and document"; keys: "Ctrl+B" } }
            Item { width: 34; height: 32; anchors.verticalCenter: parent.verticalCenter
                readonly property bool on: !!Store.sheet && Store.sheet.kind === "settings"
                Rectangle { anchors.fill: parent; radius: 16; color: gm.pressed ? Theme.washPress : gm.containsMouse || parent.on ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                Icon { anchors.centerIn: parent; name: "sliders_horizontal"; size: 16; color: gm.containsMouse || parent.on ? Theme.ink : Theme.ink2 }
                MouseArea { id: gm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSettings("general") }
                Tip { show: gm.containsMouse; below: true; text: "Settings"; keys: "Ctrl+," } }
        }
    }
}
