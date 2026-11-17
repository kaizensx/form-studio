import QtQuick

// A shortcut hint. keys: "Ctrl+K", "Ctrl+Shift+O", "Esc", "?" — written the Qt way, shown the platform's way (⌘K on macOS).
Row {
    id: k
    property string keys: ""
    property bool quiet: false               // no key caps, just the glyphs (inside tooltips, menu rows)
    spacing: quiet ? 2 : 3
    Repeater {
        model: k.keys ? Theme.keyCaps(k.keys) : []
        Rectangle {
            required property string modelData
            width: Math.max(k.quiet ? 0 : 18, kt.implicitWidth + (k.quiet ? 0 : 8)); height: 18; radius: Theme.rXs
            color: k.quiet ? "transparent" : Theme.alpha(Theme.ink, 0.06); border.width: k.quiet ? 0 : 1; border.color: Theme.rule
            Text { id: kt; anchors.centerIn: parent; text: parent.modelData; color: Theme.ink3; renderType: Text.NativeRendering
                font.family: parent.modelData.length > 1 ? Theme.sans : Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium }
        }
    }
}
