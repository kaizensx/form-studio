import QtQuick
import FormNative

// What Form Studio is set up for (form/capabilities.py): one card per capability, two columns, 3D printing last.
// The launcher's first step and Settings › General › Set up for show the same cards. A card names what it installs
// and how much it downloads; "Parametric CAD" is always on. Ticking a card only reports it (toggled): the launcher
// keeps a local pick until Continue, Settings turns it on or off at once (Store.setCap). Off never uninstalls.
Grid {
    id: cc
    property var pick: []                   // capability ids that are on
    property bool settings: false           // Settings: the card says what turning it off does
    signal toggled(string id, bool on)
    readonly property var caps: Store.caps ? Store.caps.capabilities : []
    columns: width > 560 ? 2 : 1
    columnSpacing: 10; rowSpacing: 10
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
            width: cc.columns === 2 ? (cc.width - cc.columnSpacing) / 2 : cc.width
            height: Math.max(118, cb.implicitHeight + 28); radius: Theme.rMd
            color: on ? Theme.alpha(Theme.datum, 0.07) : ma.containsMouse && !locked ? Theme.washHover : Theme.plate1
            border.color: on ? Theme.datum : Theme.rule; border.width: on ? 1.5 : 1
            Behavior on color { Tint {} }
            Column { id: cb; x: 16; y: 14; width: parent.width - 32; spacing: 5
                Row { spacing: 8; width: parent.width
                    Icon { name: card.c.icon; size: 16; color: card.on ? Theme.datum : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: card.c.title + (card.c.id === "print" ? " (optional)" : ""); font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
                        wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, parent.width - 24 - 34) } }
                Txt { kind: "fine"; tone: 2; width: parent.width; text: card.c.sub }
                Txt { kind: "fine"; width: parent.width - 64; elide: Text.ElideRight; wrapMode: Text.NoWrap   // room for the size
                    text: card.locked ? "Always on · " + card.c.installs
                        : cc.settings && card.on ? card.c.installs + " · off uninstalls nothing"
                        : card.c.installs } }
            // on/off, and what it downloads
            Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; width: 18; height: 18; radius: 5
                color: card.on ? Theme.datum : "transparent"; border.width: card.on ? 0 : 1.5; border.color: Theme.rule2; opacity: card.locked ? 0.55 : 1
                Icon { visible: card.on; anchors.centerIn: parent; name: "check"; size: 12; color: Theme.datumInk } }
            Txt { objectName: "capSize"; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12; kind: "fine"; mono: true
                text: cc.sizeText(card.c); color: card.c.ready || card.c.id === "core" ? Theme.ink3 : card.on ? Theme.datum : Theme.ink3 }
            MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; enabled: !card.locked && !Store.installing
                cursorShape: card.locked ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: cc.toggled(card.c.id, !card.on) }
        }
    }
}
