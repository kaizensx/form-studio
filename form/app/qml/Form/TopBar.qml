import QtQuick
import FormNative
import "F.js" as F

// The window's own title bar: where you are, which revision, whether it is released, and what it will print on.
Rectangle {
    id: bar
    property real inset: 0                    // room for the macOS window buttons
    height: 44; color: Theme.plate1
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    readonly property var ap: Store.data ? Store.data.approval : null
    Row { x: bar.inset + 14; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        Item { width: mark.implicitWidth + 12; height: 28; anchors.verticalCenter: parent.verticalCenter
            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: hm.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent" }
            Txt { id: mark; anchors.centerIn: parent; text: "FORM"; font.weight: 700; font.letterSpacing: 2.2; font.pixelSize: 13 }
            MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.home() }
            Tip { show: hm.containsMouse; text: "All designs" } }
        Icon { visible: !!Store.project; name: "chevron_right"; size: 12; color: Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
        Txt { visible: !!Store.project; text: Store.project ? Store.project.name : ""; font.weight: 600; anchors.verticalCenter: parent.verticalCenter }
        Txt { visible: !!Store.recipe && Store.recipe.title !== Store.project.name; kind: "fine"; text: Store.recipe ? Store.recipe.title : ""; anchors.verticalCenter: parent.verticalCenter }
        Rectangle { visible: !!Store.project; width: rv.implicitWidth + 12; height: 20; radius: 4; color: Theme.plate3; anchors.verticalCenter: parent.verticalCenter
            Txt { id: rv; anchors.centerIn: parent; mono: true; font.pixelSize: 11; text: Store.project ? F.pad(Store.project.head) : "" } }
        Tag { visible: !!Store.project; anchors.verticalCenter: parent.verticalCenter
            kind: Store.hasDraft ? "draft" : bar.ap && bar.ap.state === "approved" ? "PASS" : bar.ap && bar.ap.state === "superseded" ? "WARN" : ""
            text: !Store.project || !bar.ap ? "" : Store.hasDraft ? "uncommitted draft" : bar.ap.state === "approved" ? "released " + F.pad(Store.project.head)
                : bar.ap.state === "superseded" ? F.pad(bar.ap.rev) + " released · " + F.pad(Store.project.head) + " is not" : "unreleased" }
    }
    Row { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 10
        StatusChips { anchors.verticalCenter: parent.verticalCenter }      // setup / update notices
        Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter; visible: !!Store.studio && bar.width > 1180
            Rectangle { width: 6; height: 6; radius: 3; color: Store.slicer.available ? Theme.pass : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink2
                text: Store.slicer.available ? Store.slicer.presets.machine.name : "Slicer unavailable" }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; visible: Store.slicer.available && bar.width > 1380
                text: Store.slicer.available ? "/  " + Store.slicer.presets.filament.name + "  /  " + Store.slicer.presets.process.name : "" } }
        Rectangle { width: 214; height: 26; radius: Theme.rSm; color: sm.containsMouse ? Theme.plate3 : Theme.well; border.color: Theme.rule2; anchors.verticalCenter: parent.verticalCenter
            Icon { x: 8; name: "search"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
            Txt { x: 28; text: "Search and commands"; tone: 3; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            Txt { anchors.right: parent.right; anchors.rightMargin: 8; mono: true; font.pixelSize: 11; tone: 4; text: Bridge.platform === "darwin" ? "⌘K" : "Ctrl K"; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.paletteOpen = true } }
        Btn { kind: "quiet"; icon: "message_square"; active: Store.talkOpen; tip: "Claude"; visible: Store.screen === "work"; onClicked: Store.talkOpen = !Store.talkOpen }
    }
}
