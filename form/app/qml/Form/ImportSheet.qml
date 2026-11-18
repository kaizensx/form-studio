import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Import: a .formstudio / .formproj archive, a conversation, or an example that ships with Form Studio.
// (A design starts on Home; this sheet only brings in work made elsewhere.)
//   Store.openSheet("import")   Store.openSheet("import", { examples: true })
Column {
    id: ns
    objectName: "importSheet"
    property string title: "Import"
    property string note: "Work made elsewhere: a project with its history and conversations, a conversation, or an example."
    property int sheetWidth: Theme.sheetL
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    spacing: 14
    Component.onCompleted: loadExamples()

    // ════ Import ═══════════════════════════════════════════════════════════════════════
    property var examples: []
    function loadExamples() { Store.get("/examples").then(function (r) { ns.examples = r.examples }, Store.fail) }
    Column { width: parent.width; spacing: 16
        Row { width: parent.width; spacing: 12
            ImportTile { objectName: "importProject"; icon: "archive"; title: "A project"; onPicked: Store.ask(projDlg)
                text: "A .formstudio file: the design, its history, its conversations and the code it was built from. Older .formproj files work too." }
            ImportTile { objectName: "importConversation"; icon: "message_square"; title: "A conversation"; onPicked: Store.ask(convDlg)
                text: "A conversation exported as JSON from Form Studio. It is added to your conversations; its design link is kept when that design is here." } }
        Txt { kind: "fine"; width: parent.width; text: "Files are checked before anything is written: a damaged or unsafe archive is refused whole. A design or conversation whose id already exists here gets a new one; nothing is overwritten." }
        Column { width: parent.width; spacing: 6
            Txt { kind: "cap"; text: "Examples that ship with Form Studio" }
            Txt { kind: "fine"; width: parent.width; text: "Opening one copies its design history into your projects; its outputs are rebuilt on your computer." }
            Repeater { model: ns.examples
                Rectangle { id: ex; required property var modelData
                    width: ns.width; height: 40; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Icon { x: 12; name: "box"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { x: 34; text: ex.modelData.name; font.weight: 600; anchors.verticalCenter: parent.verticalCenter }
                    Btn { objectName: "exampleAdd"; small: true; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                        text: ex.modelData.present ? "Open" : "Add and open"
                        onClicked: { if (ex.modelData.present) { Store.openSheet(null); Store.open(ex.modelData.id) } else Store.addExample(ex.modelData.id) } } } } }
    }

    component ImportTile: Rectangle {
        id: ic
        property string icon: ""; property string title: ""; property string text: ""
        signal picked()
        width: (ns.width - 12) / 2; height: 150; radius: Theme.rLg
        color: im.pressed ? Theme.plate1 : im.containsMouse ? Theme.plate3 : Theme.plate2; border.color: im.containsMouse ? Theme.rule3 : Theme.rule
        Behavior on color { Tint {} }
        Rectangle { x: 18; y: 18; width: 40; height: 40; radius: Theme.rMd; color: Theme.alpha(Theme.datum, 0.1)
            Icon { anchors.centerIn: parent; name: ic.icon; size: 18; color: Theme.datum } }
        Column { x: 74; y: 18; width: parent.width - 92; spacing: 4
            Txt { kind: "lead"; font.weight: Theme.wSemi; text: ic.title }
            Txt { tone: 2; width: parent.width; text: ic.text } }
        Txt { x: 74; anchors.bottom: parent.bottom; anchors.bottomMargin: 16; kind: "fine"; color: im.containsMouse ? Theme.datum : Theme.ink3; text: "Choose a file…" }
        MouseArea { id: im; anchors.fill: parent; hoverEnabled: true; onClicked: ic.picked() } }
    FileDialog { id: projDlg; title: "Import a Form Studio project"; nameFilters: ["Form Studio projects (*.formstudio *.formproj *.zip)"]; onAccepted: Store.importFile(selectedFile) }
    FileDialog { id: convDlg; title: "Import a conversation"; nameFilters: ["Form Studio conversations (*.json)"]; onAccepted: Store.importFile(selectedFile) }
}
