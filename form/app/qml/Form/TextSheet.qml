import QtQuick
import FormNative
import "F.js" as F

// Text on a face (form/engrave.py): the point and normal picked in Annotate, the words, raised or sunk, cap height and
// depth. "Add to design" writes it into the design's source as a feature and builds a new revision in the kernel.
// Printability (stroke width against the nozzle, cap height) is computed on the glyphs as you type.
Column {
    id: ts
    objectName: "textSheet"
    property string title: "Text on this face"
    property string note: at ? "At " + at.map(function (x) { return F.fmt(x, 1) }).join(", ") + " mm, facing " + facing : "Pick a flat face in Annotate first"
    property int sheetWidth: Theme.sheetS
    readonly property var item: Store.sheet && Store.sheet.props ? Store.sheet.props.item : null
    readonly property var at: item && item.on ? item.on : null
    readonly property var normal: item && item.normal ? item.normal : null
    readonly property string facing: {
        if (!normal) return ""
        var n = normal, k = Math.abs(n[0]) >= Math.abs(n[1]) && Math.abs(n[0]) >= Math.abs(n[2]) ? 0 : Math.abs(n[1]) >= Math.abs(n[2]) ? 1 : 2
        return (n[k] < 0 ? "−" : "+") + ["X", "Y", "Z"][k]
    }
    property bool sunk: false
    property var check: null
    property bool checking: false
    property bool adding: false
    property var firstFocus: words.input
    readonly property real h: Number(hField.text)
    readonly property real d: Number(dField.text)
    readonly property string hErr: isFinite(h) && h >= 1 && h <= 200 ? "" : "1 to 200 mm"
    readonly property string dErr: isFinite(d) && d >= 0.1 && d <= 20 ? "" : "0.1 to 20 mm"
    readonly property bool ready: !!at && !!normal && words.text.trim() !== "" && hErr === "" && dErr === "" && !adding
    spacing: 14

    function recheck() { if (words.text.trim() !== "" && hErr === "" && dErr === "") checkTimer.restart(); else check = null }
    Timer { id: checkTimer; interval: 220
        onTriggered: {
            ts.checking = true
            Store.pget("/text/check?text=" + encodeURIComponent(words.text) + "&height=" + ts.h + "&depth=" + ts.d + "&sunk=" + (ts.sunk ? 1 : 0))
                .then(function (r) { ts.check = r; ts.checking = false }, function () { ts.check = null; ts.checking = false })
        } }
    onSunkChanged: recheck()

    function accept() {
        if (!ready) return
        adding = true
        Store.addText({ text: words.text, at: at, normal: normal, height: h, depth: d, sunk: sunk }).then(function (ok) {
            ts.adding = false
            if (ok) Store.openSheet(null)
        })
    }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { objectName: "textAdd"; kind: "primary"; icon: "type"; text: "Add to design"; busy: ts.adding; busyText: "Building…"
            enabled: ts.ready; onClicked: ts.accept() } }

    Field { id: words; objectName: "textWords"; width: parent.width; placeholder: "Text, e.g. DESK 01"; onEdited: ts.recheck() }
    Seg { model: [{ value: false, text: "Raised" }, { value: true, text: "Sunk" }]; value: ts.sunk; onPicked: function (v) { ts.sunk = v } }
    Row { width: parent.width; spacing: 12
        Column { width: (parent.width - 12) / 2; spacing: 4
            Txt { kind: "fine"; text: "Cap height" }
            Field { id: hField; width: parent.width; numeric: true; unit: "mm"; text: "6"; error: ts.hErr; onEdited: ts.recheck() } }
        Column { width: (parent.width - 12) / 2; spacing: 4
            Txt { kind: "fine"; text: ts.sunk ? "Depth" : "Height above the face" }
            Field { id: dField; width: parent.width; numeric: true; unit: "mm"; text: "0.6"; error: ts.dErr; onEdited: ts.recheck() } } }

    // printability, computed on the glyphs of the bundled font
    Rectangle { width: parent.width; height: pc.implicitHeight + 24; radius: 14; color: Theme.glass
        visible: ts.check !== null || ts.checking
        Column { id: pc; x: 14; y: 12; width: parent.width - 28; spacing: 6
            Item { width: parent.width; height: 17
                Txt { kind: "cap"; text: "Printability"; anchors.verticalCenter: parent.verticalCenter }
                Spinner { size: 12; visible: ts.checking; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
            Repeater { model: ts.check ? ts.check.checks : []
                Row { required property var modelData; width: pc.width; spacing: 8
                    Tag { text: modelData.status; kind: modelData.status }
                    Txt { width: parent.width - 60; kind: "fine"; tone: 2; text: modelData.label.replace(/^Label: /, "") + ": " + modelData.value } } }
            Txt { kind: "fine"; width: parent.width; visible: !!ts.check
                text: ts.check ? "Text " + F.fmt(ts.check.width_mm, 1) + " mm wide. Computed on the glyphs." : "" } } }

    Txt { kind: "fine"; width: parent.width
        text: "The text becomes a feature in the design's code and a new revision, built in the kernel. A face that is not flat, or text that runs off the part, is refused with the reason." }
}
