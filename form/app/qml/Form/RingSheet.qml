import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// The pocket ring test piece, after it has been cut and sliced: what it is, what the slicer says, the files.
Column {
    id: rs
    property string title: "Pocket ring"
    property int sheetWidth: 620
    readonly property var r: Store.sheet && Store.sheet.props && Store.sheet.props.result ? Store.sheet.props.result : null
    readonly property var piece: r && r.piece ? r.piece : null
    spacing: 12; bottomPadding: 20

    function saveAs(name, title) { dlg.name = name; dlg.title = title; dlg.currentFolder = Bridge.downloads(); dlg.selectedFile = Bridge.downloads() + "/" + name; dlg.open() }

    Txt { tone: 2; width: parent.width; text: rs.piece ? (rs.piece.doc || "") : "" }
    Column { width: parent.width
        KV { first: true; k: "Size"
            value: rs.piece && rs.piece.bbox ? rs.piece.bbox.map(function (x) { return F.fmt(x, 1) }).join(" × ") + " mm" : "—" }
        KV { k: "Slicer estimate"; sub: "with the presets shown in the header"; tag: "simulated"
            value: rs.r ? F.dur(rs.r.time_s) + " · " + F.fmt(rs.r.filament_g, 1) + " g · " + rs.r.layers + " layers" : "—" } }
    Row { spacing: 8
        Btn { text: "Save STL…"; icon: "download"; enabled: !!rs.r && !!rs.r.stl; onClicked: rs.saveAs(rs.r.stl, "Save the ring STL") }
        Btn { text: "Save sliced 3MF…"; icon: "download"; visible: !!rs.r && !!rs.r.threemf; onClicked: rs.saveAs(rs.r.threemf, "Save the sliced 3MF") } }
    Txt { kind: "fine"; width: parent.width
        text: "FORM does not send anything to the printer. Open the 3MF in Bambu Studio to print it, then record the measured width under Fit." }

    FileDialog {
        id: dlg
        property string name: ""
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (Bridge.save("/projects/" + Store.pid + "/file/side/" + rs.r.key + "/" + name, selectedFile)) Bridge.reveal(selectedFile)
            else Store.toast("Could not save " + name, "Check the folder is writable and try again.", true)
        }
    }
}
