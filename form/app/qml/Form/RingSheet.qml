import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// The pocket ring test piece, after it has been cut and sliced: what it is, what the slicer says, the files.
Column {
    id: rs
    property string title: "Pocket ring"
    property string note: "A test piece: print it, then measure it"
    property int sheetWidth: Theme.sheetS
    readonly property var r: Store.sheet && Store.sheet.props && Store.sheet.props.result ? Store.sheet.props.result : null
    readonly property var piece: r && r.piece ? r.piece : null
    readonly property bool has3mf: !!r && !!r.threemf
    spacing: 14

    function saveAs(name, title) { dlg.name = name; dlg.title = title; dlg.currentFolder = Bridge.downloads(); dlg.selectedFile = Bridge.downloads() + "/" + name; Store.ask(dlg) }
    function saveStl() { if (r && r.stl) saveAs(r.stl, "Save the ring STL") }
    function save3mf() { if (has3mf) saveAs(r.threemf, "Save the sliced 3MF") }
    function accept() { if (has3mf) save3mf(); else saveStl() }

    property Component footer: Row { spacing: 8
        Btn { text: "Save STL…"; icon: "download"; kind: rs.has3mf ? "default" : "primary"; enabled: !!rs.r && !!rs.r.stl; onClicked: rs.saveStl() }
        Btn { text: "Save sliced 3MF…"; icon: "download"; kind: "primary"; visible: rs.has3mf; onClicked: rs.save3mf() } }

    Txt { tone: 2; width: parent.width; visible: text !== ""; text: rs.piece ? (rs.piece.doc || "") : "" }

    // nothing was handed over: say so instead of showing dashes
    Note { visible: !rs.r; kind: "amber"; title: "No ring to show"
        text: "Cut the pocket ring under Fit first. This sheet opens by itself when the ring has been cut and sliced." }

    // what the slicer says: the one thing to read on this sheet
    Rectangle { visible: !!rs.r; width: parent.width; height: est.implicitHeight + 28; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
        Column { id: est; x: 16; y: 14; width: parent.width - 32; spacing: 12
            Item { width: parent.width; height: 17
                Txt { kind: "cap"; text: "Slicer estimate"; anchors.verticalCenter: parent.verticalCenter }
                Tag { text: "simulated"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
            Row { width: parent.width
                Repeater {
                    model: rs.r ? [[F.dur(rs.r.time_s), "print time"], [F.fmt(rs.r.filament_g, 1) + " g", "filament"], [String(rs.r.layers), "layers"]] : []
                    Column { required property var modelData; width: est.width / 3; spacing: 2
                        Txt { mono: true; kind: "h3"; font.weight: Theme.wMedium; text: modelData[0] }
                        Txt { kind: "fine"; text: modelData[1] } } } }
            Txt { kind: "fine"; width: parent.width; text: "With the presets shown in the header." } } }

    Column { visible: !!rs.r; width: parent.width
        KV { first: true; k: "Size"; tag: "computed"
            value: rs.piece && rs.piece.bbox ? rs.piece.bbox.map(function (x) { return F.fmt(x, 1) }).join(" × ") + " mm" : "—" } }

    Txt { kind: "fine"; width: parent.width
        text: "FORM does not send anything to the printer. Open the 3MF in " + (Store.slicer.label || "Bambu Studio") + " to print it, then record the measured width under Fit." }

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
