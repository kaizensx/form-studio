import QtQuick

// A shortcut hint. keys: "Ctrl+K", "Ctrl+Shift+O", "Esc", "?" — written the Qt way, shown the platform's way (⌘K on macOS).
// Each key is a small cap of glass with its glyph in mono.
Row {
    id: k
    property string keys: ""
    property bool quiet: false               // no key caps, just the glyphs (inside tooltips, menu rows)
    spacing: quiet ? 2 : 3
    Repeater {
        model: k.keys ? Theme.keyCaps(k.keys) : []
        Rectangle {
            required property string modelData
            width: Math.max(k.quiet ? 0 : 20, kt.implicitWidth + (k.quiet ? 0 : 10)); height: 20; radius: Theme.rXs
            color: k.quiet ? "transparent" : Theme.glass2; border.width: k.quiet || Theme.dark ? 0 : 1; border.color: Theme.rule
            Rectangle { visible: !k.quiet && Theme.dark; x: parent.radius; y: 0; width: parent.width - 2 * parent.radius; height: 1; color: Theme.gleam }
            Text { id: kt; anchors.centerIn: parent; text: parent.modelData; color: k.quiet ? Theme.ink3 : Theme.ink2; renderType: Text.NativeRendering
                font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium }
        }
    }
}
