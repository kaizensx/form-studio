import QtQuick
import FormNative

// What Form Studio is set up for (form/capabilities.py): one card per capability, two columns, 3D printing last
// (in Settings: tiles in three columns, each with its switch).
// The launcher's first step and Settings › General › Set up for show the same cards. A card names what it installs
// and how much it downloads; "Parametric CAD" is always on. Ticking a card only reports it (toggled): the launcher
// keeps a local pick until Continue, Settings turns it on or off at once (Store.setCap). Off never uninstalls.
Grid {
    id: cc
    property var pick: []                   // capability ids that are on
    property bool settings: false           // Settings: the card says what turning it off does
    signal toggled(string id, bool on)
    readonly property var caps: Store.caps ? Store.caps.capabilities : []
    columns: settings ? (width > 760 ? 3 : width > 500 ? 2 : 1) : width > 560 ? 2 : 1      // tileFx: Settings' tiles
    columnSpacing: 10; rowSpacing: 10
    // Settings: the size as the mockup's mono word after the sentence ("always on", "138 MB", "needs Blender")
    // every tile is as tall as the tallest one needs
    property real tileH: 92
    function fitTiles() { var h = 92; for (var i = 0; i < children.length; i++) if (children[i].need) h = Math.max(h, children[i].need); tileH = h }
    function tileSize(c) {
        if (c.id === "core" || c.level === "required") return "always on"
        if (!c.software.length) return "in the app"
        if (c.ready) return "ready"
        return c.size_mb > 0 ? (c.size_mb >= 1000 ? (c.size_mb / 1000).toFixed(1) + " GB" : c.size_mb + " MB") : "download page"
    }
    function sizeText(c) {
        if (c.id === "core") return "Included"
        if (!c.software.length) return "Included"
        if (c.ready) return "Ready"
        return c.size_mb > 0 ? (c.size_mb >= 1000 ? "about " + (c.size_mb / 1000).toFixed(1) + " GB" : "about " + c.size_mb + " MB") : "Download page"
    }
    Repeater {
        model: cc.caps
        Rectangle {
            id: card
            required property var modelData
            readonly property var c: modelData
            readonly property bool on: cc.pick.indexOf(c.id) >= 0
            readonly property bool locked: c.level === "required"
            objectName: "capCard_" + c.id
            width: Math.floor((cc.width - (cc.columns - 1) * cc.columnSpacing) / cc.columns)
            height: cc.settings ? cc.tileH : Math.max(118, cb.implicitHeight + 28); radius: cc.settings ? 16 : Theme.rMd + 2
            color: cc.settings ? (on ? Theme.glass2 : ma.containsMouse && !locked ? Theme.glass : (Theme.dark ? Qt.rgba(1, 1, 1, 0.04) : Qt.rgba(1, 1, 1, 0.42)))
                 : on ? Theme.alpha(Theme.datum, Theme.dark ? 0.1 : 0.07) : ma.containsMouse && !locked ? Theme.glass2 : Theme.glass
            border.color: cc.settings ? (on ? Theme.alpha(Theme.datum, 0.45) : Theme.rule) : on ? Theme.datum : Theme.dark ? Theme.glassEdge : Theme.rule
            border.width: cc.settings ? 1 : on ? 1.5 : 1
            Behavior on color { Tint {} }
            // Settings: a tile. Its name and its switch, then one sentence and, in mono, what it takes.
            readonly property real need: cc.settings ? tb.implicitHeight + 27 : 0
            onNeedChanged: cc.fitTiles()
            Column { id: tb; visible: cc.settings; x: 14; y: 13; width: parent.width - 28; spacing: 9
                Item { width: parent.width; height: 20
                    Txt { text: card.c.title; font.weight: Theme.wSemi; lineHeight: 1.0; height: 20; verticalAlignment: Text.AlignVCenter
                        width: parent.width - 40; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Toggle { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; checked: card.on
                        enabled: !card.locked && !Store.installing; opacity: card.locked ? 0.6 : enabled ? 1 : 0.4
                        onToggled: function (on) { cc.toggled(card.c.id, on) } } }
                Txt { width: parent.width; font.pixelSize: 12; lineHeight: 1.35; tone: 2; textFormat: Text.StyledText
                    text: String(card.c.sub).replace(/&/g, "&amp;").replace(/</g, "&lt;") + " <font face=\"" + Theme.mono + "\" color=\"" + Theme.ink3 + "\">" + cc.tileSize(card.c) + "</font>" } }
            Column { id: cb; visible: !cc.settings; x: 16; y: 14; width: parent.width - 32; spacing: 5
                Row { spacing: 8; width: parent.width
                    Icon { name: card.c.icon; size: 16; color: card.on ? Theme.datum : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: card.c.title + (card.c.id === "print" ? " (optional)" : ""); font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
                        wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, parent.width - 24 - 34) } }
                Txt { kind: "fine"; tone: 2; width: parent.width; text: card.c.sub }
                Item { width: 1; height: installs.height } }      // the room of the last line, which stands on the card's foot
            // what it installs, and at the other end of the same line what that downloads
            Txt { id: installs; visible: !cc.settings; kind: "fine"; x: 16; anchors.bottom: parent.bottom; anchors.bottomMargin: 12
                width: parent.width - 32 - capSize.width - 12; elide: Text.ElideRight; wrapMode: Text.NoWrap
                text: card.locked ? "Always on · " + card.c.installs
                    : cc.settings && card.on ? card.c.installs + " · off uninstalls nothing"
                    : card.c.installs }
            // on/off, and what it downloads
            Rectangle { visible: !cc.settings; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; width: 18; height: 18; radius: 5
                color: card.on ? Theme.datum : "transparent"; border.width: card.on ? 0 : 1.5; border.color: Theme.rule2; opacity: card.locked ? 0.55 : 1
                Icon { visible: card.on; anchors.centerIn: parent; name: "check"; size: 12; color: Theme.datumInk } }
            Txt { id: capSize; objectName: "capSize"; visible: !cc.settings; anchors.right: parent.right; anchors.rightMargin: 16; anchors.baseline: installs.baseline; kind: "fine"; mono: true
                text: cc.sizeText(card.c); color: card.c.ready || card.c.id === "core" ? Theme.ink3 : card.on ? Theme.datum : Theme.ink3 }
            MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; enabled: !card.locked && !Store.installing
                cursorShape: card.locked ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: cc.toggled(card.c.id, !card.on) }
        }
    }
}
