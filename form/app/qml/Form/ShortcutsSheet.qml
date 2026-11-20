import QtQuick
import FormNative

// Keyboard shortcuts, in one place. Opened with "?".
// Keys are written the Qt way ("Ctrl+K"); Kbd shows them the platform's way (⌘K on macOS).
// Every row here is pressed by tests/journeys/shell.py, which fails if a key does not do what its row says.
Column {
    id: sh
    objectName: "shortcutsSheet"
    property string title: "Keyboard shortcuts"
    property string note: "Single keys work while a design is open and you are not typing"
    property int sheetWidth: Theme.sheetXl
    spacing: 16
    readonly property int gap: 36
    // three columns; each holds one or more titled groups
    readonly property var columns: [
        [{ title: "Viewport tools", rows: [
            ["V", "Select: click a feature, drag to orbit"],
            ["M", "Measure distances, faces and diameters"],
            ["N", "Annotate: pick, paint or lasso, keep, ask the agent"],
            ["X", "Section cut on or off"],
            ["A", "Analyze: thickness, overhang and other maps"],
            ["E", "Assembly views and joints"],
            ["T", "History: the revision timeline"],
            ["Esc", "Leave the tool or clear the selection"]] },
         { title: "Conversation", rows: [
            ["Return", "Send the message"],
            ["Shift+Return", "A new line in the message"],
            ["Up", "Bring back your last message"]] }],
        [{ title: "View and features", rows: [
            ["F", "Frame the selected feature, or the whole part"],
            ["1", "Iso view"], ["2", "Front view"], ["3", "Side view"], ["4", "Top view"], ["5", "Underside view"],
            [".", "Reset the view"],
            ["H", "Hide or show the selected feature"],
            ["Shift+H", "Show all features"],
            ["Right-click", "Quick actions for a feature"]] },
         { title: "Inside Measure and Annotate", rows: [
            ["D", "Measure: distance"], ["G", "Measure or Annotate: face"], ["O", "Measure: diameter"],
            ["R", "Annotate: edge"], ["P", "Annotate: point"], ["B", "Annotate: brush"], ["L", "Annotate: lasso"],
            ["[", "Brush smaller"], ["]", "Brush larger"],
            ["Shift+Click", "Add to the selection"], ["Alt+Drag", "Orbit while painting"]] }],
        [{ title: "Everywhere", rows: [
            ["Ctrl+K", "Search and commands"],
            ["Ctrl+N", "New design"],
            ["Ctrl+Shift+O", "New conversation"],
            ["Ctrl+J", "Show or hide the conversation"],
            ["Ctrl+Shift+H", "All designs"],
            ["Ctrl+,", "Settings"],
            ["Ctrl+1", "Describe"], ["Ctrl+2", "Design"], ["Ctrl+3", "Fit"], ["Ctrl+4", "Review"], ["Ctrl+5", "Make"],
            ["Ctrl+Return", "Commit the draft"],
            ["?", "This sheet"]] }]]
    // flat list, for the tests and anything else that wants every row
    readonly property var all: { var o = []; columns.forEach(function (c) { c.forEach(function (g) { g.rows.forEach(function (r) { o.push(r) }) }) }); return o }

    Row { width: parent.width; spacing: sh.gap
        Repeater { model: sh.columns
            Column { id: colm; required property var modelData; width: (sh.width - sh.gap * 2) / 3; spacing: 18
                Repeater { model: colm.modelData
                    Column { id: g; required property var modelData; width: colm.width; spacing: 0
                        Txt { kind: "cap"; text: g.modelData.title; height: 24 }
                        Repeater { model: g.modelData.rows
                            Item { id: r; required property var modelData; required property int index
                                width: g.width; height: 32
                                Rectangle { width: parent.width; height: 1; color: Theme.rule }
                                Txt { text: r.modelData[1]; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: parent.width - kr.width - 16; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                Kbd { id: kr; keys: r.modelData[0]; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } } } } } } } }

    Txt { kind: "fine"; width: parent.width
        text: "Single keys work while a design is open, not while you type in a field or the conversation. E needs a design with several parts; Esc also closes whatever is open; ↑ works while the message box is empty. Hiding a feature is visual only; the solid, checks and exports do not change." }
}
