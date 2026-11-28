import QtQuick
import QtQuick.Controls
import FormNative

// The agent and model that design the next request, on Home under the composer, at the right end of the "Make it
// for" line. The same picker as the conversation's composer (TalkModelPicker); what is picked here is what the
// request is sent with. Without an agent it says so and opens Settings › Agents & models.
// `room` is the width it may take: its words shorten first, and under 110 only the icon and the chevron stay.
Item {
    id: mchip
    objectName: "startModel"
    property real room: 320
    readonly property bool bare: room < 110
    readonly property alias popOpen: mpop.opened
    function pick() { if (Store.chatReady && !mpop.opened) mpop.open() }      // opened from elsewhere (Store.modelPickWanted)
    function act() { if (!Store.chatReady) Store.openSettings("agents"); else if (mpop.opened) mpop.close(); else mpop.open() }
    width: (bare ? 0 : ml.width + 9) + 49; height: 34
    visible: !!Store.studio && room >= 48
    activeFocusOnTab: true
    Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; mchip.act() } }
    Rectangle { anchors.fill: parent; radius: 12; color: mcm.pressed ? Theme.washPress : mcm.containsMouse || mpop.opened ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
    Icon { x: 10; name: "sparkles"; size: 15; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
    Txt { id: ml; objectName: "startModelLabel"; visible: !mchip.bare; x: 34; tone: 2; wrapMode: Text.NoWrap; lineHeight: 1.0
        height: parent.height; verticalAlignment: Text.AlignVCenter
        width: Math.min(Math.ceil(implicitWidth), Math.max(0, mchip.room - 58)); elide: Text.ElideRight
        text: !Store.chatReady ? "Connect an agent"
            : Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) + (Store.chatEffort ? " · " + Store.chatEffort : "") }
    Icon { x: mchip.width - 10 - 12; name: Store.chatReady ? "chevron_down" : "chevron_right"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
    FocusRing { on: mchip.activeFocus; radius: 14 }
    MouseArea { id: mcm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: mchip.act() }
    Tip { show: mcm.containsMouse && !mpop.opened
        text: Store.chatReady ? "The agent and model that design it. Click to change them." : "No agent is connected: add one in Settings › Agents & models" }
    Pop {
        id: mpop; objectName: "startModelPop"; width: 380; padding: 6
        // under the chip, its right edge on the chip's; above it when there is more room there
        property bool up: false
        x: Math.round(parent.width - width); y: up ? -height - 6 : parent.height + 6
        origin: up ? Popup.BottomRight : Popup.TopRight
        height: Math.min(mp.implicitHeight + 12, (mchip.Window.height || 800) * 0.6)
        onAboutToShow: { var at = mchip.mapToItem(null, 0, 0).y, h = mchip.Window.height || 800
            up = h - (at + mchip.height + 6) - 8 < height && at - 6 - 8 > h - (at + mchip.height + 6) - 8
            mp.reset() }
        onOpened: mp.opened()
        onClosed: Qt.callLater(function () {
            Store.retryAfterPick = false
            if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
        Flickable { anchors.fill: parent; clip: true; contentHeight: mp.implicitHeight; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            TalkModelPicker { id: mp; width: parent.width; onDone: mpop.close() } } }
}
