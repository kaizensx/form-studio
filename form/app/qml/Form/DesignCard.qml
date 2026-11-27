import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import FormNative
import "F.js" as F

// One design on Home: the live part standing in its own pool of key light, with its number, name and revision under
// it. No box: the part is the card. Home shows one per design family (a design with its copies, variants and picked
// concepts); that one carries the family's count and opens the family.
// `member` is the same thing inside an opened family: smaller, with how it came to be instead of the count.
// Rename and move-to-trash happen in place; the state for both lives on Home (`host`), because a list refresh rebuilds
// the cards and must not wipe a half-typed name.
Item {
    id: card
    objectName: "projectCard"            // an opened family names its members "familyMember" (Home.qml)
    property Item host: null                 // Home
    property var p: ({})                     // the design (a row of /studio projects)
    property int order: 0                    // its place on Home, for the stagger as cards arrive (not `index`: a Repeater sets that)
    property bool member: false
    property int count: 1                    // designs in this family (the family's face only)
    property bool opened: false              // the family is open under this row
    property var photo: null
    signal toggled()

    readonly property string title: p.name || ""
    readonly property bool hot: cm.containsMouse || more.hovered || fam.hovered || (host && host.menuOpenFor(p))
    readonly property bool editing: !!host && host.renaming === p.id
    readonly property bool asking: !!host && host.confirming === p.id
    readonly property int plinth: member ? 150 : 200       // the part and its light
    readonly property int foot: 64                         // the caption under it
    readonly property string via: p.lineage && p.lineage.via ? ({ duplicate: "copy", variant: "variant", concept: "concept" })[p.lineage.via] || "" : ""
    readonly property bool root: !p.lineage || !p.lineage.parent
    height: plinth + foot

    opacity: 0
    Component.onCompleted: { if (!host || host.entered || member) opacity = 1; else appear.start() }
    SequentialAnimation { id: appear; PauseAnimation { duration: 220 + Math.min(card.order, 9) * Theme.stagger }
        ParallelAnimation { Glide { target: card; property: "opacity"; to: 1; duration: Theme.slow }
            Glide { target: rise; property: "y"; from: Theme.shift(14); to: 0; duration: Theme.slow } } }
    transform: Translate { id: rise; y: 0 }

    // the pool of key light the part stands in: an ellipse on the floor that brightens under the pointer
    Fade {
        id: pool; x: Math.round(card.width * 0.08); width: card.width - 2 * x; height: 110; y: card.plinth - 6 - height
        opacity: card.asking ? 0.4 : card.hot ? 1 : 0.62
        Behavior on opacity { NumberAnimation { duration: Theme.base } }
        radial: true; c0: Theme.alpha(Theme.key, Theme.dark ? 0.3 : 0.9); c1: Theme.alpha(Theme.key, 0)
    }

    // the part on the studio floor, turning while you look at it. Its frame has no edge: the floor fades into the
    // room all round (Veil: dithered, so the fall shows no rings; a software renderer masks it with a drawn ellipse).
    Item {
        id: stagePv; width: parent.width; height: card.plinth
        scale: cm.pressed ? Theme.from(0.985) : 1
        Behavior on scale { Glide { duration: Theme.press } }
        transform: Translate { y: card.hot && !cm.pressed ? -Theme.shift(4) : 0; Behavior on y { Glide { duration: Theme.base } } }
        readonly property bool plain: GraphicsInfo.api === GraphicsInfo.Software
        Component { id: veilFx; Veil { full: 0.55 } }
        Component { id: maskFx; MultiEffect { maskEnabled: true; maskSource: fade; maskThresholdMin: 0.5; maskSpreadAtMin: 1 } }
        Item { id: fade; anchors.fill: parent; anchors.topMargin: card.member ? -10 : -22; anchors.bottomMargin: card.member ? -8 : -16; visible: false; layer.enabled: stagePv.plain
            Shape { id: fs; width: parent.width; height: parent.width
                transform: Scale { yScale: fade.height / Math.max(1, fade.width) }
                ShapePath {
                    strokeWidth: -1
                    fillGradient: RadialGradient {
                        centerX: fs.width / 2; centerY: fs.width / 2; centerRadius: fs.width / 2; focalX: centerX; focalY: centerY
                        GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 1) }
                        GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 1) }
                        GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0) } }
                    startX: 0; startY: 0
                    PathLine { x: fs.width; y: 0 } PathLine { x: fs.width; y: fs.width } PathLine { x: 0; y: fs.width } PathLine { x: 0; y: 0 }
                } } }
        MiniView { anchors.fill: parent; anchors.topMargin: card.member ? -10 : -22; anchors.bottomMargin: card.member ? -8 : -16; projectId: card.p.id || ""; turning: card.hot && !card.asking
            opacity: card.asking ? 0.35 : 1; Behavior on opacity { NumberAnimation { duration: Theme.base } }
            layer.enabled: true
            layer.effect: stagePv.plain ? maskFx : veilFx }
    }
    Rectangle { visible: !!card.photo && pim.status === Image.Ready; anchors.right: stagePv.right; anchors.bottom: stagePv.bottom; anchors.margins: 10
        width: 58; height: 44; radius: Theme.rSm; color: Theme.plate; border.color: phm.containsMouse ? Theme.rule3 : Theme.rule2; clip: true; z: 2
        scale: phm.containsMouse ? Theme.from(1.06) : 1; Behavior on scale { Glide { duration: Theme.fast } }
        Image { id: pim; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
            source: card.photo ? Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.photo.key + ".png" : "" }
        MouseArea { id: phm; anchors.fill: parent; hoverEnabled: true
            onClicked: Store.showImage(Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.photo.key + ".png", card.p.name, "Blender render · an illustration, not evidence") }
        Tip { show: phm.containsMouse; text: "Blender render of this revision · illustration" } }

    // the caption: its number on Home, the name, the revision, released or not; then what it is and when it changed
    Column { id: cap; visible: !card.editing && !card.asking; y: card.plinth + 6; width: parent.width; spacing: 5
        Row { id: line; anchors.horizontalCenter: parent.horizontalCenter; spacing: 9; height: 20
            Txt { id: no; visible: !card.member; mono: true; font.pixelSize: 11; tone: 3; text: card.order < 9 ? "0" + (card.order + 1) : card.order + 1; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: card.p.name || ""; font.pixelSize: 15; font.weight: Theme.wSemi; font.letterSpacing: -0.15; lineHeight: 1.0; anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, Math.max(40, cap.width - 12 - (no.visible ? no.width + 9 : 0) - rev.width - 9 - (rel.visible ? rel.width + 9 : 0)))
                elide: Text.ElideRight; wrapMode: Text.NoWrap }
            Txt { id: rev; mono: true; font.pixelSize: 11; tone: 3; text: F.pad(card.p.head); anchors.verticalCenter: parent.verticalCenter }
            Tag { id: rel; visible: !!card.p.approved_rev; anchors.verticalCenter: parent.verticalCenter
                text: card.p.approved_rev === card.p.head ? "released" : card.p.approved_rev ? F.pad(card.p.approved_rev) + " released" : ""
                kind: card.p.approved_rev === card.p.head ? "PASS" : card.p.approved_rev ? "WARN" : "" } }
        Txt { width: parent.width - 12; x: 6; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 12; tone: 3; lineHeight: 1.0
            text: (card.member ? (card.root ? "the first design" : card.via ? "a " + card.via : "design")
                               : card.p.purpose === "print" && Store.printOn ? "For 3D printing" : card.host ? card.host.recipeTitle(card.p.recipe) : "") + " · " + F.ago(card.p.updated) } }      // a model is the normal case: no label
    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; enabled: !card.editing && !card.asking
        cursorShape: Qt.PointingHandCursor
        onClicked: function (e) {
            if (e.button === Qt.RightButton) card.host.openMenu(card.p, card, e.x, e.y)
            else Store.open(card.p.id) } }
    // the family: how many designs share this one's origin; a click opens them under the row
    Item { id: fam; objectName: "familyToggle"; visible: !card.member && card.count > 1; x: 8; y: 8; z: 3
        width: famRow.implicitWidth + 18; height: 26
        property alias hovered: fm.containsMouse
        Rectangle { anchors.fill: parent; radius: height / 2
            color: fm.pressed ? Theme.washPress : card.opened ? Theme.datum : fm.containsMouse ? Theme.glass2 : Theme.glass
            border.width: card.opened ? 0 : 1; border.color: fm.containsMouse ? Theme.rule3 : Theme.rule2
            Behavior on color { Tint {} } }
        Row { id: famRow; anchors.centerIn: parent; spacing: 5
            Icon { name: "layers"; size: 12; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink2 }
            Txt { mono: true; font.pixelSize: 11; text: card.count; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink; font.weight: Theme.wMedium }
            Icon { name: card.opened ? "chevron_up" : "chevron_down"; size: 11; anchors.verticalCenter: parent.verticalCenter; color: card.opened ? Theme.datumInk : Theme.ink3 } }
        MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: card.toggled() }
        Tip { show: fm.containsMouse; text: card.opened ? "Close the family" : card.count + " designs share this origin: made by one request, or copies, variants and picked concepts. Click to see them." } }
    Btn { id: more; objectName: "cardMore"; kind: "quiet"; icon: "ellipsis"; tip: "Rename, duplicate, export, delete"; x: parent.width - width - 6; y: 6; z: 3
        opacity: card.hot && !card.asking && !card.editing ? 1 : 0; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        onClicked: card.host.openMenu(card.p, card, more.x, more.y + more.height + 4) }
    // rename in place
    Field { id: rf; visible: card.editing; x: 12; y: card.plinth + 8; width: parent.width - 24
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
    Column { visible: card.asking; y: card.plinth - 12; width: parent.width; spacing: 6
        Txt { text: "Move to the trash?"; font.weight: Theme.wSemi; font.pixelSize: 15; width: parent.width - 12; x: 6; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Txt { kind: "fine"; text: card.p.name + " · kept in .trash"; width: parent.width - 12; x: 6; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap }
        Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 6
            Btn { small: true; kind: "quiet"; text: "Keep"; onClicked: card.host.confirming = "" }
            Btn { small: true; kind: "danger"; text: "Move to trash"; onClicked: { card.host.confirming = ""; Store.deleteProject(card.p.id) } } } }
}
