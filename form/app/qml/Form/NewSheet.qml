import QtQuick
import QtQuick.Dialogs
import FormNative

// Start a design from a built-in recipe, or restore a saved .formproj.
Column {
    id: ns
    property string title: "New design"
    property int sheetWidth: 720
    property string pickId: Store.studio && Store.studio.recipes.length ? Store.studio.recipes[0].id : ""
    spacing: 12; bottomPadding: 20
    function chosen() { var r = Store.studio.recipes; for (var i = 0; i < r.length; i++) if (r[i].id === pickId) return r[i]; return null }
    Txt { tone: 2; width: parent.width; text: "Recipes are parametric designs with real engineering checks. For anything else, describe it to Claude and it writes the design as code." }
    Grid { width: parent.width; columns: 2; spacing: 8
        Repeater { model: Store.studio ? Store.studio.recipes : []
            Rectangle { id: rc; required property var modelData
                width: (ns.width - 8) / 2; height: 62; radius: Theme.rMd
                color: ns.pickId === modelData.id ? Theme.alpha(Theme.datum, 0.08) : rm.containsMouse ? Theme.plate3 : Theme.plate1
                border.color: ns.pickId === modelData.id ? Theme.alpha(Theme.datum, 0.6) : Theme.rule
                Column { x: 12; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 24; spacing: 2
                    Txt { text: rc.modelData.title; font.weight: 600 }
                    Txt { kind: "fine"; text: rc.modelData.summary || ""; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: ns.pickId = rc.modelData.id } } } }
    Field { id: name; width: parent.width; placeholder: "Name, e.g. “Hallway phone dock”" }
    Area { id: brief; width: parent.width; minLines: 2; placeholder: "What is it for? (optional; you can write this later)" }
    Row { spacing: 8
        Btn { kind: "primary"; text: "Create"; icon: "plus"; enabled: ns.pickId !== ""
            onClicked: Store.create(name.text.trim() || (ns.chosen() ? ns.chosen().title : "Design"), ns.pickId, brief.text) }
        Btn { kind: "quiet"; text: "Restore a .formproj…"; icon: "upload"; onClicked: dlg.open() } }
    Txt { kind: "fine"; width: parent.width; text: "FORM works from a written brief, dimensions you measure, and reference photos with a marked scale. It does not reconstruct geometry from photos or scans." }
    FileDialog { id: dlg; title: "Restore a FORM project"; nameFilters: ["FORM projects (*.formproj *.zip)"]; onAccepted: Store.importArchive(selectedFile) }
}
