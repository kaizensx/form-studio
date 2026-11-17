import QtQuick
import QtQuick.Controls

// The sheet system. One modal sheet at a time, centred over a scrim.
//
// A sheet is a `Column` in its own file, registered in `files` below. The host draws everything around it, so every
// sheet has the same header, padding, scrolling and action bar. What a sheet may declare:
//   property string title              the header (required)
//   property int sheetWidth            Theme.sheetS | sheetM | sheetL | sheetXl
//   property string note               one quiet line under the title
//   property var tabs; property string tab     [{ value, text, badge? }] — the host shows them under the header and sets `tab`
//   property Component footer          the actions, a Row: primary button LAST (it sits at the right edge)
//   property Component footerLeft      secondary things at the left of the action bar (a Row: quiet buttons, a status line)
//   property int sheetHeight           a fixed body height, for sheets whose tabs would otherwise make the card jump
//   function accept()                  run by Enter when no field has taken it (and by nothing else)
// Esc closes. Tab and Shift+Tab stay inside the sheet. The body scrolls under soft edges when it is longer than the window.
// Motion: scale 0.97 → 1 and fade in 180 ms; it leaves in 110 ms; none of it when the system asks for reduced motion.
Item {
    id: host
    anchors.fill: parent; z: 40
    readonly property var files: ({ "new": "NewSheet.qml", alternatives: "Alternatives.qml", photo: "PhotoSheet.qml", ring: "RingSheet.qml", setup: "SetupSheet.qml", settings: "SettingsSheet.qml", update: "UpdateSheet.qml", slicer: "SlicerSheet.qml", render: "PhotoRenderSheet.qml", variants: "VariantsSheet.qml", share: "ShareSheet.qml", shortcuts: "ShortcutsSheet.qml", about: "AboutSheet.qml" })
    readonly property bool open: !!Store.sheet
    readonly property Item sheet: ld.item
    property string file: ""                 // stays set while the sheet fades out
    visible: scrim.opacity > 0.001
    onOpenChanged: { if (open) { file = files[Store.sheet.kind] || ""; Qt.callLater(card.grab) } else unload.restart() }
    Connections { target: Store; function onSheetChanged() { if (Store.sheet) { host.file = host.files[Store.sheet.kind] || ""; flick.contentY = 0; Qt.callLater(card.grab) } } }
    Timer { id: unload; interval: Theme.exit + 40; onTriggered: if (!host.open) host.file = "" }

    Rectangle { id: scrim; anchors.fill: parent; color: Theme.scrim; opacity: host.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: host.open ? Theme.base : Theme.exit } }
        MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: Store.openSheet(null); onWheel: function (w) { w.accepted = true } } }

    FocusScope {
        id: card
        objectName: "sheetCard"
        readonly property int pad: 24
        readonly property int headH: host.sheet && host.sheet.note ? 68 : 58       // a title with a line under it needs the same air above as beside
        readonly property int tabsH: tabs.visible ? 34 : 0
        readonly property int footH: foot.visible ? 60 : 0
        readonly property real bodyH: host.sheet ? (host.sheet.sheetHeight ? host.sheet.sheetHeight : host.sheet.implicitHeight) : 160
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.max(40, Math.round((parent.height - height) / 2 - parent.height * 0.02))
        width: Math.min(parent.width - 64, host.sheet && host.sheet.sheetWidth ? host.sheet.sheetWidth : Theme.sheetM)
        height: Math.min(parent.height - 88, headH + tabsH + bodyH + pad + (foot.visible ? 0 : 4) + footH)
        opacity: host.open ? 1 : 0
        scale: host.open ? 1 : Theme.from(0.97)
        Behavior on opacity { NumberAnimation { duration: host.open ? Theme.base : Theme.exit; easing.type: Easing.OutCubic } }
        Behavior on scale { Glide { duration: host.open ? Theme.base : Theme.exit } }

        // A focused control moves Tab along the window's whole chain by itself, so the card never sees the key.
        // Two guards, first and last in the card, catch the keyboard on its way out and send it round.
        Item { id: guardStart; width: 1; height: 1; activeFocusOnTab: true
            onActiveFocusChanged: if (activeFocus) card.wrap(false) }
        function wrap(forward) {
            var n = (forward ? guardStart : guardEnd).nextItemInFocusChain(forward), guard = 0
            while (n && (n === guardStart || n === guardEnd) && guard++ < 4) n = n.nextItemInFocusChain(forward)
            if (n && inside(n) && n !== guardStart && n !== guardEnd) n.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
            else sink.forceActiveFocus()          // a sheet with nothing to tab to: the keyboard rests on the card
        }
        Item { id: sink }
        function inside(it) { while (it) { if (it === card) return true; it = it.parent } return false }
        function grab() { if (!host.open) return; card.forceActiveFocus(); if (host.sheet && host.sheet.firstFocus) host.sheet.firstFocus.forceActiveFocus() }
        // keep Tab inside the sheet
        function step(forward) {
            var w = card.Window.window, cur = w ? w.activeFocusItem : null
            var start = cur && inside(cur) ? cur : card
            var n = start.nextItemInFocusChain(forward), guard = 0
            while (n && (!inside(n) || n === guardStart || n === guardEnd) && guard++ < 400) n = n.nextItemInFocusChain(forward)
            if (n && inside(n) && n !== card) n.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
        }
        Keys.onTabPressed: step(true)
        Keys.onBacktabPressed: step(false)
        Keys.onReturnPressed: function (e) { if (host.sheet && host.sheet.accept) host.sheet.accept(); else e.accepted = false }
        Keys.onEnterPressed: function (e) { if (host.sheet && host.sheet.accept) host.sheet.accept(); else e.accepted = false }
        Keys.onEscapePressed: Store.openSheet(null)

        Rectangle { anchors.fill: parent; radius: Theme.rXl; color: Theme.plate2; border.color: Theme.rule2
            Shadow { radius: parent.radius; spread: 44; drop: 18; strength: 1.25 }
            // light catches the top edge
            Rectangle { x: parent.radius; y: 1; width: parent.width - 2 * parent.radius; height: 1; color: Qt.rgba(1, 1, 1, 0.05) } }
        MouseArea { anchors.fill: parent; onWheel: function (w) { w.accepted = true } }

        // header
        Column { x: card.pad; width: parent.width - card.pad * 2 - 36; anchors.verticalCenter: head.verticalCenter; spacing: 1
            Txt { kind: "lead"; font.weight: Theme.wSemi; font.letterSpacing: -0.1; text: host.sheet && host.sheet.title ? host.sheet.title : ""; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
            Txt { kind: "fine"; visible: text !== ""; text: host.sheet && host.sheet.note ? host.sheet.note : ""; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
        Item { id: head; width: parent.width; height: card.headH }
        Btn { kind: "quiet"; icon: "x"; tip: "Close"; keys: "Esc"; anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: head.verticalCenter; activeFocusOnTab: false
            onClicked: Store.openSheet(null) }
        Tabs { id: tabs; visible: !!host.sheet && !!host.sheet.tabs && host.sheet.tabs.length > 0
            x: card.pad; y: card.headH - 4; width: parent.width - card.pad * 2
            model: visible ? host.sheet.tabs : []; value: visible ? host.sheet.tab : null
            onPicked: function (v) { host.sheet.tab = v; flick.contentY = 0 } }
        Rectangle { visible: !tabs.visible; y: card.headH - 1; width: parent.width; height: 1; color: flick.atYBeginning ? "transparent" : Theme.rule }

        // body
        Flickable {
            id: flick
            objectName: "sheetScroll"
            x: 0; y: card.headH + card.tabsH; width: parent.width; height: parent.height - y - card.footH - (foot.visible ? 0 : 4)
            clip: true; contentHeight: (host.sheet ? host.sheet.implicitHeight : 0) + card.pad + (tabs.visible ? 18 : 2); boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6; policy: flick.contentHeight > flick.height + 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
            Loader { id: ld; x: card.pad; y: tabs.visible ? 18 : 2; width: flick.width - card.pad * 2; source: host.file }
        }
        // scroll shadows: the body slides under the header and the action bar
        Rectangle { x: 1; y: flick.y; width: parent.width - 2; height: 18; opacity: flick.atYBeginning ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.26) } GradientStop { position: 1; color: "transparent" } } }
        Rectangle { x: 1; y: flick.y + flick.height - 18; width: parent.width - 2; height: 18; opacity: flick.atYEnd || flick.contentHeight <= flick.height ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.3) } } }

        // action bar: secondary left, primary right
        Item {
            id: foot
            visible: !!host.sheet && (!!host.sheet.footer || !!host.sheet.footerLeft)
            anchors.bottom: parent.bottom; width: parent.width; height: 60
            Rectangle { width: parent.width; height: 1; color: Theme.rule }
            Rectangle { x: 1; y: 1; width: parent.width - 2; height: parent.height - 2; color: Theme.alpha(Theme.plate1, 0.55)
                radius: Theme.rXl - 1; Rectangle { width: parent.width; height: parent.radius; color: parent.color } }
            Loader { id: fl; x: card.pad; anchors.verticalCenter: parent.verticalCenter; width: Math.max(0, parent.width - card.pad * 2 - fr.width - 16); clip: true
                sourceComponent: host.sheet && host.sheet.footerLeft ? host.sheet.footerLeft : null }
            Loader { id: fr; anchors.right: parent.right; anchors.rightMargin: card.pad; anchors.verticalCenter: parent.verticalCenter
                sourceComponent: host.sheet && host.sheet.footer ? host.sheet.footer : null }
        }
        Item { id: guardEnd; width: 1; height: 1; activeFocusOnTab: true
            onActiveFocusChanged: if (activeFocus) card.wrap(true) }
    }
}
