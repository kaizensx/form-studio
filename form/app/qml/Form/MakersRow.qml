import QtQuick
import QtQuick.Dialogs

// Home's quick starts: the makers' generators (form/makers, GET /api/makers). One click makes a print-ready design
// that stays editable (sliders, the full code, the checks); a name tag asks for its text first and a lithophane for a
// picture, which is read on this computer and never sent anywhere.
Column {
    id: mk
    objectName: "makersRow"
    spacing: Theme.s2
    property var generators: []
    property string asking: ""                // the generator waiting for its text
    property bool busy: false
    Component.onCompleted: Store.get("/makers").then(function (r) { mk.generators = r.generators || [] }, function () {})

    function run(g, extra) {
        if (mk.busy) return
        mk.busy = true
        var body = { preset: g["default"], purpose: Store.newPurposeEffective === "print" ? "print" : "" }
        for (var k in (extra || {})) body[k] = extra[k]
        Store.post("/makers/" + g.id, body).then(function (r) {
            mk.busy = false; mk.asking = ""; Store.refresh(); Store.open(r.project)
        }, function (e) { mk.busy = false; Store.fail(e) })
    }
    function start(g) {
        if (g.inputs.indexOf("text") >= 0) { mk.asking = g.id; textField.text = ""; textField.input.forceActiveFocus(); return }
        if (g.inputs.indexOf("image") >= 0) { picDlg.gen = g; Store.ask(picDlg); return }
        run(g)
    }

    FileDialog { id: picDlg; property var gen: null; title: "A picture for the lithophane"
        nameFilters: ["Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"]
        onAccepted: mk.run(picDlg.gen, { image: decodeURIComponent(String(selectedFile).replace(/^file:\/\/\/([A-Za-z]:)/, "$1").replace(/^file:\/\//, "")) }) }

    Txt { kind: "cap"; tone: 3; text: "Or make one now · print-ready and editable" ; visible: mk.generators.length > 0 }
    Flow { width: parent.width; spacing: Theme.s2; visible: mk.generators.length > 0
        Repeater { model: mk.generators
            Btn { required property var modelData; objectName: "make_" + modelData.id; small: true; kind: "quiet"
                text: modelData.title; tip: modelData.summary; enabled: !mk.busy
                onClicked: mk.start(modelData) } }
        // a generated mesh (TRELLIS.2 here, or Meshy or Tripo on your key), rebuilt as CAD: opt-in, told what is sent
        Btn { objectName: "makeGenerated"; small: true; kind: "quiet"; icon: "sparkles"; text: "Generate from words or a picture…"
            tip: "A mesh generator you set up makes a mesh; Form Studio splits it into parts and rebuilds it as editable CAD."
            onClicked: Store.openSheet("generate") } }
    Row { visible: mk.asking !== ""; spacing: Theme.s2
        Field { id: textField; width: 260; placeholder: "The text, e.g. MAYA"
            onAccepted: function (t) { if (t.trim()) mk.run(mk.generators.filter(function (g) { return g.id === mk.asking })[0], { text: t }) } }
        Btn { small: true; text: mk.busy ? "Making…" : "Make it"; enabled: !mk.busy && textField.text.trim() !== ""
            onClicked: mk.run(mk.generators.filter(function (g) { return g.id === mk.asking })[0], { text: textField.text }) }
        Btn { small: true; kind: "quiet"; icon: "x"; tip: "Cancel"; onClicked: mk.asking = "" } }
}
