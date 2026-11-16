import QtQuick
import FormNative

// Keyboard shortcuts, in one place. Opened with "?".
Column {
    id: sh
    property string title: "Keyboard shortcuts"
    property int sheetWidth: 720
    spacing: 6; bottomPadding: 22
    readonly property string mod: Bridge.platform === "darwin" ? "⌘" : "Ctrl"
    readonly property var groups: [
        { title: "Model", rows: [
            [["F"], "Frame the selected feature, or the whole part"],
            [["1"], "Iso view"], [["2"], "Front view"], [["3"], "Side view"], [["4"], "Top view"], [["5"], "Underside view"],
            [["."], "Reset the view"],
            [["X"], "Section cut on or off"],
            [["H"], "Hide or show the selected feature"],
            [["⇧", "H"], "Show all features"],
            [["Right-click"], "Quick actions for a feature"],
            [["Esc"], "Clear the selection"]] },
        { title: "Design", rows: [
            [[mod, "K"], "Command palette"],
            [[mod, "1"], "Brief"], [[mod, "2"], "Shape"], [[mod, "3"], "Fit"], [[mod, "4"], "Prove"], [[mod, "5"], "Release"],
            [[mod, "↵"], "Commit the draft"],
            [[mod, "J"], "Show or hide the conversation"],
            [[mod, "N"], "New design"],
            [["?"], "This sheet"]] }]
    Row { width: parent.width; spacing: 36
        Repeater { model: sh.groups
            Column { id: g; required property var modelData; width: (sh.width - 36) / 2; spacing: 0
                Cap { text: g.modelData.title; width: parent.width }
                Item { width: 1; height: 8 }
                Repeater { model: g.modelData.rows
                    Item { id: r; required property var modelData; required property int index
                        width: g.width; height: 30
                        Rectangle { visible: r.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Txt { text: r.modelData[1]; tone: 2; anchors.verticalCenter: parent.verticalCenter; width: parent.width - kr.width - 12; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Row { id: kr; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                            Repeater { model: r.modelData[0]
                                Rectangle { required property var modelData
                                    width: Math.max(22, kt.implicitWidth + 12); height: 20; radius: Theme.rXs; color: Theme.plate3; border.color: Theme.rule2
                                    Txt { id: kt; anchors.centerIn: parent; text: parent.modelData; mono: true; font.pixelSize: 11 } } } } } } } } }
    Item { width: 1; height: 8 }
    Txt { kind: "fine"; width: parent.width
        text: "Model keys work while the 3D view has the keyboard: not while you type in a field or the conversation. Hiding a feature is visual only; the solid, checks and exports do not change." }
}
