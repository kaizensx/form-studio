import QtQuick
import QtQuick.Controls

// Tooltip: appears after a short rest, never steals focus. Once one tooltip has shown, its neighbours open at once.
// `keys` adds a shortcut hint ("Ctrl+K").
Item {
    id: t
    property string text: ""
    property string keys: ""
    property bool show: false
    anchors.fill: parent
    readonly property bool want: show && text !== ""
    onWantChanged: {
        if (want) { tt.warm = Date.now() - Theme.tipSeen < 600; tt.delay = tt.warm ? 0 : 450; tt.visible = true }
        else { if (tt.opened) Theme.tipSeen = Date.now(); tt.visible = false }
    }
    ToolTip {
        id: tt
        property bool warm: false
        timeout: 8000; padding: 0; margins: 6
        y: -implicitHeight - 6; x: Math.round((t.width - implicitWidth) / 2)
        transformOrigin: Popup.Bottom
        contentItem: Row { padding: 7; leftPadding: 9; rightPadding: 9; spacing: 8
            Text { text: t.text; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap; width: Math.min(implicitWidth, 280); renderType: Text.NativeRendering; lineHeight: 1.2 }
            Kbd { visible: t.keys !== ""; keys: t.keys; quiet: true; anchors.verticalCenter: parent.verticalCenter } }
        background: Rectangle { color: Theme.plate4; radius: Theme.rSm; border.color: Theme.rule2; Shadow { radius: parent.radius; spread: 10; drop: 4; strength: 0.7 } }
        enter: Transition { enabled: !tt.warm
            Glide { property: "opacity"; from: 0; to: 1; duration: Theme.pop }
            Glide { property: "scale"; from: Theme.from(0.96); to: 1; duration: Theme.pop } }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: tt.warm ? 0 : Theme.exit } }
    }
}
