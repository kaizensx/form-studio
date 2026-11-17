import QtQuick
import FormNative
import "F.js" as F

// The window's own title bar, one calm line. Left: the agent column's toggle, where you are, which revision and whether
// it is released. Right: notices, what it will print on, search, settings. It gives up detail, never function, as the
// window narrows: the slicer chip drops the filament, then the name; search becomes its icon; notices become dots.
Rectangle {
    id: bar
    objectName: "topBar"
    property real inset: 0                    // room for the macOS window buttons
    height: 44; color: Theme.plate1
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    readonly property var ap: Store.data ? Store.data.approval : null
    readonly property bool work: Store.screen === "work"
    readonly property bool roomy: width >= 1500
    readonly property bool tight: width < 1260

    Row { id: left; x: bar.inset + (bar.inset ? 4 : 10); anchors.verticalCenter: parent.verticalCenter; spacing: 4
        // elsewhere than macOS there is no menu bar at the top of the screen: the same actions live here
        Btn { id: menuBtn; visible: !Theme.mac; kind: "quiet"; icon: "menu"; tip: "Menu"; active: appMenu.opened; onClicked: appMenu.opened ? appMenu.close() : appMenu.open()
            PopMenu { id: appMenu; y: parent.height + 6; width: 264
                model: [
                    { icon: "plus", text: "New design…", keys: "Ctrl+N", run: function () { Store.openSheet("new") } },
                    { icon: "file_text", text: "New design from a brief…", run: function () { Store.openSheet("new", { tab: "brief" }) } },
                    { icon: "message_square_plus", text: "New conversation", keys: "Ctrl+Shift+O", run: function () { Store.newChat(); Store.talkOpen = true } },
                    { sep: true },
                    { icon: "home", text: "All designs", keys: "Ctrl+Shift+H", run: function () { Store.home() } },
                    { icon: "folder_open", text: "Open the projects folder", run: function () { Bridge.openDataFolder() } },
                    { sep: true },
                    { icon: "search", text: "Search and commands…", keys: "Ctrl+K", run: function () { Store.paletteOpen = true } },
                    { icon: "keyboard", text: "Keyboard shortcuts", run: function () { Store.openSheet("shortcuts") } },
                    { icon: "wrench", text: "Software: install or check…", run: function () { Store.openSetup() } },
                    { icon: "settings", text: "Settings…", keys: "Ctrl+,", run: function () { Store.openSettings("general") } },
                    { sep: true },
                    { icon: "info", text: "About Form Studio", run: function () { Store.openSheet("about") } }
                ] } }
        Btn { visible: bar.work; kind: "quiet"; icon: Store.talkOpen ? "panel_left_close" : "panel_left_open"; keys: "Ctrl+J"
            tip: Store.talkOpen ? "Hide the conversation" : "Show the conversation"; onClicked: Store.talkOpen = !Store.talkOpen }
        Item { width: mark.implicitWidth + 16; height: 28; anchors.verticalCenter: parent.verticalCenter
            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: hm.pressed ? Theme.washPress : hm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
            Logo { id: mark; anchors.centerIn: parent; size: 18; ink: bar.work ? Theme.ink2 : Theme.ink; ink2: bar.work ? Theme.ink3 : Theme.ink2 }
            MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.home() }
            Tip { show: hm.containsMouse && bar.work; text: "All designs"; keys: "Ctrl+Shift+H" } }
        Txt { visible: !!Store.project; text: "/"; tone: 4; anchors.verticalCenter: parent.verticalCenter; rightPadding: 6 }
        Txt { id: pname; visible: !!Store.project; text: Store.project ? Store.project.name : ""; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, Math.max(120, bar.width - left.x - right.width - 420)); elide: Text.ElideRight; wrapMode: Text.NoWrap
            HoverHandler { id: ph }
            Tip { show: ph.hovered && !!Store.recipe; text: Store.recipe && Store.project ? (String(Store.project.recipe).indexOf("src:") === 0 ? "Designed by an agent" : "Recipe: " + Store.recipe.title) : "" } }
        Item { width: 6; height: 1 }
        Txt { visible: !!Store.project; mono: true; font.pixelSize: 12; tone: 2; text: Store.project ? F.pad(Store.project.head) : ""; anchors.verticalCenter: parent.verticalCenter }
        Item { width: 6; height: 1 }
        Tag { visible: !!Store.project && text !== ""; anchors.verticalCenter: parent.verticalCenter
            kind: Store.hasDraft ? "draft" : bar.ap && bar.ap.state === "approved" ? "PASS" : bar.ap && bar.ap.state === "superseded" ? "WARN" : ""
            text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "draft" : bar.ap.state === "approved" ? "released"
                : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " released" : "unreleased"
            HoverHandler { id: th }
            Tip { show: th.hovered
                text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "There is an uncommitted draft on top of " + F.pad(Store.project.head)
                    : bar.ap.state === "approved" ? F.pad(Store.project.head) + " is released"
                    : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " is released. " + F.pad(Store.project.head) + " is not."
                    : F.pad(Store.project.head) + " has not been approved for release" } }
    }
    Row { id: right; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 6
        StatusChips { anchors.verticalCenter: parent.verticalCenter; compact: bar.work ? !bar.roomy : bar.tight }      // setup / update notices
        // what it will print on; opens the slicer picker
        Item { width: chip.implicitWidth + 16; height: 26; anchors.verticalCenter: parent.verticalCenter; visible: !!Store.studio
            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
            Row { id: chip; x: 8; spacing: 7; anchors.verticalCenter: parent.verticalCenter
                Icon { name: "printer"; size: 13; anchors.verticalCenter: parent.verticalCenter; color: Store.slicer.available ? Theme.ink3 : Theme.amber }
                Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink2; visible: !bar.tight || !bar.work
                    width: Math.min(implicitWidth, 190); elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: Store.slicer.available ? Store.slicer.presets.machine.name : "No slicer" }
                Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; visible: Store.slicer.available && bar.roomy
                    width: Math.min(implicitWidth, 150); elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: Store.slicer.available ? Store.slicer.presets.filament.name : "" } }
            MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSheet("slicer") }
            Tip { show: cm.containsMouse
                text: Store.slicer.available ? (Store.slicer.label || "Slicer") + (Store.slicer.version ? " " + Store.slicer.version : "") + " · " + Store.slicer.presets.machine.name + " · " + Store.slicer.presets.filament.name + " · " + Store.slicer.presets.process.name + ". Click to choose the slicer."
                    : "No slicer was found. Click to see which Form Studio can use." } }
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
