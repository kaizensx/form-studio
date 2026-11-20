import QtQuick
import FormNative
import "F.js" as F

// One design on Home: the live part on its plate, its name, where it stands. Home shows one card per design family
// (a design with its copies, variants and picked concepts); that card carries the family's count and opens the family.
// `member` is the same card inside an opened family: smaller, with how it came to be instead of the count.
// Rename and move-to-trash happen in place; the state for both lives on Home (`host`), because a list refresh rebuilds
// the cards and must not wipe a half-typed name.
Item {
    id: card
    objectName: "projectCard"            // an opened family names its members "familyMember" (Home.qml)
    property Item host: null                 // Home
    property var p: ({})                     // the design (a row of /studio projects)
    property int index: 0
    property bool member: false
    property int count: 1                    // designs in this family (the family's face only)
    property bool opened: false              // the family is open under this row
    property var photo: null
    signal toggled()

    readonly property string title: p.name || ""
    readonly property bool hot: cm.containsMouse || more.hovered || fam.hovered || (host && host.menuOpenFor(p))
    readonly property bool editing: !!host && host.renaming === p.id
    readonly property bool asking: !!host && host.confirming === p.id
    readonly property int foot: member ? 54 : 62
    readonly property string via: p.lineage && p.lineage.via ? ({ duplicate: "copy", variant: "variant", concept: "concept" })[p.lineage.via] || "" : ""
    readonly property bool root: !p.lineage || !p.lineage.parent
    height: Math.round(width * (member ? 0.66 : 0.74)) + foot

    opacity: 0
    Component.onCompleted: { if (!host || host.entered || member) opacity = 1; else appear.start() }
    SequentialAnimation { id: appear; PauseAnimation { duration: 260 + Math.min(card.index, 9) * Theme.stagger }
        ParallelAnimation { Glide { target: card; property: "opacity"; to: 1; duration: Theme.slow }
            Glide { target: rise; property: "y"; from: Theme.shift(14); to: 0; duration: Theme.slow } } }
    transform: Translate { id: rise; y: 0 }

    // a family is a stack: two sheets show behind the face, so the count is seen before it is read
    Repeater { model: card.member ? 0 : Math.min(2, card.count - 1)
        Rectangle { required property int index
            x: 8 * (index + 1); width: parent.width - 16 * (index + 1); y: face.y + face.height - 6; height: 6 + 5 * (index + 1)
            radius: Theme.rLg; z: -1 - index
            color: Theme.alpha(Theme.plate1, 0.9 - index * 0.3); border.color: Theme.rule
            Behavior on y { Glide { duration: Theme.base } } } }

    Rectangle {
        id: face
        width: parent.width; height: parent.height; radius: card.member ? Theme.rLg : Theme.rLg + 2
        y: card.hot && !cm.pressed ? Theme.shift(card.member ? -2 : -4) : 0
        scale: cm.pressed ? Theme.from(0.985) : 1
        color: Theme.plate1
        border.color: card.asking ? Theme.alpha(Theme.signal, 0.5) : card.opened ? Theme.alpha(Theme.datum, 0.45) : card.hot ? Theme.rule3 : Theme.rule
        Behavior on y { Glide { duration: Theme.base } }
        Behavior on scale { Glide { duration: Theme.press } }
        Behavior on border.color { Tint {} }
        Shadow { radius: parent.radius; spread: 30; drop: 16; opacity: card.hot ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
        // the part on its plate, turning while you look at it
        Rectangle { id: stagePv; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; clip: true
            color: Theme.plate; topLeftRadius: face.radius - 1; topRightRadius: face.radius - 1
            MiniView { anchors.fill: parent; projectId: card.p.id || ""; turning: card.hot && !card.asking } }
        Rectangle { visible: !!card.photo && pim.status === Image.Ready; anchors.right: stagePv.right; anchors.bottom: stagePv.bottom; anchors.margins: 10
            width: 58; height: 44; radius: Theme.rSm; color: Theme.plate; border.color: phm.containsMouse ? Theme.rule3 : Theme.rule2; clip: true; z: 2
            scale: phm.containsMouse ? 1.06 : 1; Behavior on scale { Glide { duration: Theme.fast } }
            Image { id: pim; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                source: card.photo ? Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.photo.key + ".png" : "" }
            MouseArea { id: phm; anchors.fill: parent; hoverEnabled: true
                onClicked: Store.showImage(Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.photo.key + ".png", card.p.name, "Blender render · an illustration, not evidence") }
            Tip { show: phm.containsMouse; text: "Blender render of this revision · illustration" } }
        Rectangle { y: parent.height - card.foot; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
        Column { visible: !card.editing && !card.asking; x: 16; y: parent.height - card.foot + (card.member ? 10 : 12); width: parent.width - 32 - side.width - 10; spacing: 3
            Txt { text: card.p.name || ""; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
            Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                text: (card.member ? (card.root ? "the first design" : card.via ? "a " + card.via : "design")
                                   : card.p.purpose === "model" ? "3D model" : card.host ? card.host.recipeTitle(card.p.recipe) : "") + "  ·  " + F.ago(card.p.updated) } }
        Column { id: side; visible: !card.editing && !card.asking; anchors.right: parent.right; anchors.rightMargin: 16; y: parent.height - card.foot + (card.member ? 10 : 12); spacing: 5
            Txt { mono: true; font.pixelSize: 12; text: F.pad(card.p.head); anchors.right: parent.right; tone: 2 }
            Tag { anchors.right: parent.right; visible: !!card.p.approved_rev
                text: card.p.approved_rev === card.p.head ? "released" : card.p.approved_rev ? F.pad(card.p.approved_rev) + " released" : ""
                kind: card.p.approved_rev === card.p.head ? "PASS" : card.p.approved_rev ? "WARN" : "" } }
        MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; enabled: !card.editing && !card.asking
            onClicked: function (e) {
                if (e.button === Qt.RightButton) card.host.openMenu(card.p, card, e.x, e.y)
                else Store.open(card.p.id) } }
        // the family: how many designs share this one's origin; a click opens them under the row
        Item { id: fam; objectName: "familyToggle"; visible: !card.member && card.count > 1; x: 10; y: 10; z: 3
            width: famRow.implicitWidth + 16; height: 24
            property alias hovered: fm.containsMouse
            Rectangle { anchors.fill: parent; radius: 12
                color: fm.pressed ? Theme.plate4 : card.opened ? Theme.datum : Theme.plate3
                border.color: card.opened ? "transparent" : fm.containsMouse ? Theme.rule3 : Theme.rule2
                Behavior on color { Tint {} } }
            Row { id: famRow; anchors.centerIn: parent; spacing: 5
                Icon { name: "layers"; size: 12; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink2 }
                Txt { mono: true; font.pixelSize: 11; text: card.count; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink; font.weight: Theme.wMedium }
                Icon { name: card.opened ? "chevron_up" : "chevron_down"; size: 11; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink3 } }
            MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true; onClicked: card.toggled() }
            Tip { show: fm.containsMouse; text: card.opened ? "Close the family" : card.count + " designs share this origin: copies, variants and picked concepts. Click to see them." } }
        Btn { id: more; objectName: "cardMore"; kind: "quiet"; icon: "ellipsis"; tip: "Rename, duplicate, export, delete"; x: parent.width - width - 8; y: 8; z: 3
            opacity: card.hot && !card.asking && !card.editing ? 1 : 0; visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            onClicked: card.host.openMenu(card.p, card, more.x, more.y + more.height + 4) }
        // rename in place
        Field { id: rf; visible: card.editing; x: 12; y: parent.height - card.foot + (card.member ? 13 : 17); width: parent.width - 24
            // The card menu gives focus back to whatever had it when it closes, a moment after this
            // field appears. Take it, take it again once the menu is gone, and only then treat losing
            // it as a cancel.
            property bool armed: false
            function grab() { input.forceActiveFocus(); if (text === card.p.name) input.selectAll(); else input.cursorPosition = text.length }
            function begin() { text = card.host.renameDraft; grab(); arm.restart() }
            Component.onCompleted: if (visible) begin()      // the card was rebuilt in the middle of a rename
            onEdited: function (t) { card.host.renameDraft = t }
            Timer { id: arm; interval: 140; onTriggered: { if (!rf.input.activeFocus) rf.grab(); rf.armed = true } }
            onVisibleChanged: { armed = false; if (visible) begin(); else arm.stop() }
            onAccepted: function (t) { if (!card.editing) return; card.host.renaming = ""; if (t.trim() && t.trim() !== card.p.name) Store.renameProject(card.p.id, t.trim()) }
            Keys.onEscapePressed: card.host.renaming = ""
            Connections { target: rf.input; function onActiveFocusChanged() {
                if (rf.armed && !rf.input.activeFocus && card.editing && rf.Window.window && rf.Window.window.active) card.host.renaming = "" } }
            Connections { target: rf.Window.window; enabled: card.editing
                function onActiveChanged() { if (rf.Window.window.active && card.editing && !rf.input.activeFocus) rf.input.forceActiveFocus() } } }
        // move to trash?
        Rectangle { visible: card.asking; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; radius: face.radius - 1; color: Theme.alpha(Theme.plate, 0.72) }
        Item { visible: card.asking; x: 16; y: parent.height - card.foot; width: parent.width - 32; height: card.foot
            Column { anchors.verticalCenter: parent.verticalCenter; width: parent.width - tacts.width - 10; spacing: 2
                Txt { text: "Move to the trash?"; font.weight: Theme.wMedium; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                Txt { kind: "fine"; text: card.p.name + " · kept in .trash"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
            Row { id: tacts; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Btn { small: true; kind: "quiet"; text: "Keep"; onClicked: card.host.confirming = "" }
                Btn { small: true; kind: "danger"; text: "Move to trash"; onClicked: { card.host.confirming = ""; Store.deleteProject(card.p.id) } } } }
    }
}
