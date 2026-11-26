import QtQuick
import QtQuick.Controls

// Tooltip: appears after a short rest, never steals focus. Once one tooltip has shown, its neighbours open at once.
// `keys` adds a shortcut hint ("Ctrl+K"). A small pane of glass, made only while it shows.
Item {
    id: t
    property string text: ""
    property string keys: ""
    property bool show: false
    property bool below: false           // under the control instead of over it (controls right under the top bar)
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
        y: t.below ? t.height + 6 : -implicitHeight - 6; x: Math.round((t.width - implicitWidth) / 2)
        transformOrigin: t.below ? Popup.Top : Popup.Bottom
        contentItem: Row { padding: 7; leftPadding: 10; rightPadding: 10; spacing: 8
            Text { text: t.text; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap; width: Math.min(implicitWidth, 280); renderType: Theme.textRender; lineHeight: 1.2 }
            Kbd { visible: t.keys !== ""; keys: t.keys; quiet: true; anchors.verticalCenter: parent.verticalCenter } }
        background: Item {
            Loader { anchors.fill: parent; active: tt.visible
                sourceComponent: Glass { source: Store.backdrop; radius: 10; shadow: false
                    Shadow { radius: 10; spread: 10; drop: 4; strength: 0.7 }
                    Rectangle { anchors.fill: parent; radius: 10; color: Theme.alpha(Theme.plate4, blurred ? 0.62 : 0.85) } } } }
        enter: Transition { enabled: !tt.warm
            Glide { property: "opacity"; from: 0; to: 1; duration: Theme.pop }
            Glide { property: "scale"; from: Theme.from(0.96); to: 1; duration: Theme.pop } }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: tt.warm ? 0 : Theme.exit } }
    }
}
