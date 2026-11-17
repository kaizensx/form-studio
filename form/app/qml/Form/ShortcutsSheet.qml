import QtQuick
import FormNative

// Keyboard shortcuts, in one place. Opened with "?".
// Keys are written the Qt way ("Ctrl+K"); Kbd shows them the platform's way (⌘K on macOS).
Column {
    id: sh
    property string title: "Keyboard shortcuts"
    property string note: "Model keys work while the 3D view has the keyboard"
    property int sheetWidth: Theme.sheetL
    spacing: 16
    readonly property int gap: 40
    readonly property var groups: [
        { title: "Model", rows: [
            ["F", "Frame the selected feature, or the whole part"],
            ["1", "Iso view"], ["2", "Front view"], ["3", "Side view"], ["4", "Top view"], ["5", "Underside view"],
            [".", "Reset the view"],
            ["X", "Section cut on or off"],
            ["H", "Hide or show the selected feature"],
            ["Shift+H", "Show all features"],
            ["Right-click", "Quick actions for a feature"],
            ["Esc", "Clear the selection"]] },
        { title: "Design", rows: [
            ["Ctrl+K", "Command palette"],
            ["Ctrl+1", "Brief"], ["Ctrl+2", "Shape"], ["Ctrl+3", "Fit"], ["Ctrl+4", "Prove"], ["Ctrl+5", "Release"],
            ["Ctrl+Return", "Commit the draft"],
            ["Ctrl+J", "Show or hide the conversation"],
            ["Ctrl+N", "New design"],
            ["?", "This sheet"]] }]

    Row { width: parent.width; spacing: sh.gap
        Repeater { model: sh.groups
            Column { id: g; required property var modelData; width: (sh.width - sh.gap) / 2; spacing: 0
                Txt { kind: "cap"; text: g.modelData.title; height: 24 }
                Repeater { model: g.modelData.rows
                    Item { id: r; required property var modelData; required property int index
                        width: g.width; height: 32
                        Rectangle { width: parent.width; height: 1; color: Theme.rule }
                        Txt { text: r.modelData[1]; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: parent.width - kr.width - 16; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Kbd { id: kr; keys: r.modelData[0]; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } } } } } }

    Txt { kind: "fine"; width: parent.width
        text: "Model keys work while the 3D view has the keyboard: not while you type in a field or the conversation. Hiding a feature is visual only; the solid, checks and exports do not change." }
}
