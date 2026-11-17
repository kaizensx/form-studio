import QtQuick

// One learned starter on Home: a prompt the person can send to the agent, pin, edit or remove (form/starters.py).
// A click puts the words in the composer, so they can be adjusted before they are sent.
Rectangle {
    id: sc
    objectName: "starterCard"
    property var item: ({})
    property int index: 0
    property bool editing: false
    property bool entered: true                // false: rise in once, a beat after the card before it
    readonly property string text: item.text || ""
    readonly property bool hot: ma.containsMouse || acts.hovered
    signal editRequested()
    signal editDone(string text)
    signal editCancelled()
    readonly property color tint: item.pinned ? Theme.datum : item.source === "mine" ? Theme.datum : item.source === "learned" ? Theme.blueprint : Theme.ink3
    readonly property string label: item.pinned ? "Pinned" : item.source === "mine" ? "Yours" : item.source === "learned" ? "From your designs" : "Suggested"
    readonly property string glyph: item.pinned ? "pin" : item.source === "mine" ? "pencil" : item.source === "learned" ? "sparkle" : "lightbulb"
    implicitHeight: 118
    radius: Theme.rLg
    color: ma.pressed ? Theme.plate1 : hot ? Theme.plate3 : Theme.plate2
    border.color: editing ? Theme.alpha(Theme.datum, 0.6) : hot ? Theme.rule3 : Theme.rule
    Behavior on color { Tint {} }
    Behavior on border.color { Tint {} }
    y: hot && !ma.pressed && !editing ? Theme.shift(-2) : 0
    Behavior on y { Glide { duration: Theme.base } }
    scale: ma.pressed ? Theme.from(0.985) : 1
    Behavior on scale { Glide { duration: Theme.press } }
    opacity: entered ? 1 : 0
    Component.onCompleted: if (!entered) rise.start()
    SequentialAnimation { id: rise; PauseAnimation { duration: 80 + Math.min(sc.index, 8) * Theme.stagger }
        ParallelAnimation { Glide { target: sc; property: "opacity"; to: 1; duration: Theme.slow }
            Glide { target: tr; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } } }
    transform: Translate { id: tr }
    Shadow { radius: parent.radius; spread: 22; drop: 10; opacity: sc.hot && !sc.editing ? 0.8 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }

    // where it comes from
    Row { x: 16; y: 14; spacing: 6
        Icon { name: sc.glyph; size: 12; color: sc.tint; anchors.verticalCenter: parent.verticalCenter }
        Txt { kind: "cap"; text: sc.label; color: sc.tint; anchors.verticalCenter: parent.verticalCenter } }
    // the words
    Txt { visible: !sc.editing; x: 16; y: 36; width: parent.width - 32; text: sc.text; font.pixelSize: Theme.tLead - 1; lineHeight: 1.3
        maximumLineCount: 3; elide: Text.ElideRight; tone: sc.hot ? 1 : 1 }
    Txt { visible: !sc.editing && !!sc.item.why && sc.item.source === "learned"; x: 16; anchors.bottom: parent.bottom; anchors.bottomMargin: 12
        width: parent.width - 32 - go.width; kind: "fine"; tone: 3; text: sc.item.why || ""; elide: Text.ElideRight; wrapMode: Text.NoWrap }
    Icon { id: go; visible: !sc.editing; name: "arrow_right"; size: 14; color: sc.hot ? Theme.datum : Theme.ink4
        anchors.right: parent.right; anchors.rightMargin: sc.hot ? 12 : 16; anchors.bottom: parent.bottom; anchors.bottomMargin: 13
        Behavior on anchors.rightMargin { Glide { duration: Theme.fast } } }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; enabled: !sc.editing; acceptedButtons: Qt.LeftButton
        onClicked: Store.useStarter(sc.item) }
    Tip { show: ma.containsMouse && !acts.hovered; text: "Put it in the composer" }

    // pin, edit, remove: shown on hover
    Row {
        id: acts
        readonly property bool hovered: pinB.hovered || edB.hovered || rmB.hovered
        visible: opacity > 0; opacity: (sc.hot || sc.item.pinned) && !sc.editing ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        anchors.right: parent.right; anchors.rightMargin: 8; y: 8; spacing: 0
        Btn { id: pinB; objectName: "starterPin"; small: true; kind: "quiet"; icon: sc.item.pinned ? "pin_off" : "pin"; tip: sc.item.pinned ? "Unpin" : "Pin to the front"
            opacity: sc.hot ? 1 : 0.7; onClicked: Store.pinStarter(sc.item.id, !sc.item.pinned) }
        Btn { id: edB; objectName: "starterEdit"; visible: sc.hot; small: true; kind: "quiet"; icon: "pencil"; tip: "Edit the words"; onClicked: sc.editRequested() }
        Btn { id: rmB; objectName: "starterRemove"; visible: sc.hot; small: true; kind: "quiet"; icon: "x"
            tip: sc.item.source === "mine" ? "Delete" : "Hide this suggestion"; onClicked: Store.removeStarter(sc.item.id) } }

    // edit in place
    Area { id: ed; visible: sc.editing; x: 10; y: 32; width: parent.width - 20; minLines: 2; submitOnEnter: true
        onSubmit: function (t) { sc.editDone(t) }
        Keys.onEscapePressed: sc.editCancelled() }
    onEditingChanged: if (editing) { ed.text = text; ed.area.forceActiveFocus(); ed.area.cursorPosition = ed.text.length }
    Row { visible: sc.editing; anchors.right: parent.right; anchors.rightMargin: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 8; spacing: 4
        Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: sc.editCancelled() }
        Btn { small: true; kind: "primary"; text: "Save"; onClicked: sc.editDone(ed.text) } }
}
