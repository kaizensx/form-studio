import QtQuick
import QtQuick.Dialogs
import FormNative

// Home's quick starts: the makers' generators (form/makers, GET /api/makers). One click makes a print-ready design
// that stays editable (sliders, the full code, the checks); a name tag asks for its text first and a lithophane for a
// picture, which is read on this computer and never sent anywhere.
// One quiet line under "Make it for": the generators that fit, then "More" with the rest and the mesh generator
// (Generate from words or a picture). Every generator keeps its name ("make_<id>") whether it stands in the line or
// in the menu: start(g) is the one way in.
Item {
    id: mk
    objectName: "makersRow"
    property var generators: []
    property string asking: ""                // the generator waiting for its text
    property bool busy: false
    readonly property int h: 34
    implicitHeight: generators.length > 0 ? h : 0
    height: implicitHeight
    Component.onCompleted: Store.get("/makers").then(function (r) { mk.generators = r.generators || [] }, function () {})

    function gen(id) { for (var i = 0; i < generators.length; i++) if (generators[i].id === id) return generators[i]; return null }
    function run(g, extra) {
        if (mk.busy || !g) return
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

    // how many generators stand in the line: as many as fit before "More"
    FontMetrics { id: fm; font.family: Theme.sans; font.pixelSize: 13; font.letterSpacing: -0.1 }
    readonly property var widths: generators.map(function (g) { return Math.ceil(fm.advanceWidth(g.title)) + 22 })
    readonly property int shown: {
        var room = width - lbl.width - 12 - more.width - 4, n = 0, x = 0
        for (var i = 0; i < widths.length; i++) { if (x + widths[i] > room) break; x += widths[i] + 2; n++ }
        return n
    }

    // one generator in the line: its name, quiet until the pointer is on it
    component Chip: Item {
        id: chip
        property string text: ""
        property string tip: ""
        property string icon: ""
        property bool chevron: false
        property bool lit: false
        signal clicked()
        width: (icon ? 22 : 0) + Math.ceil(fm.advanceWidth(text)) + 22 + (chevron ? 16 : 0); height: 30
        opacity: enabled ? 1 : 0.5
        activeFocusOnTab: true
        Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; chip.clicked() } }
        Rectangle { anchors.fill: parent; radius: 10
            color: cm.pressed ? Theme.washPress : cm.containsMouse || chip.lit ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
        Icon { visible: chip.icon !== ""; x: 10; name: chip.icon; size: 14; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
        Text { x: chip.icon ? 32 : 11; height: parent.height; verticalAlignment: Text.AlignVCenter; text: chip.text; renderType: Theme.textRender
            font.family: Theme.sans; font.pixelSize: 13; font.letterSpacing: -0.1
            color: cm.containsMouse || chip.lit ? Theme.ink : Theme.ink2; Behavior on color { Tint {} } }
        Icon { visible: chip.chevron; x: chip.width - 10 - 12; name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
        FocusRing { on: chip.activeFocus; radius: 12 }
        MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
        Tip { show: cm.containsMouse && chip.tip !== "" && !cm.pressed; text: chip.tip }
    }

    Txt { id: lbl; visible: mk.generators.length > 0; tone: 2; text: mk.asking ? (mk.gen(mk.asking) ? mk.gen(mk.asking).title : "") : "Or make"
        height: mk.h; lineHeight: 1.0; verticalAlignment: Text.AlignVCenter; wrapMode: Text.NoWrap }
    Row { id: line; visible: mk.generators.length > 0 && mk.asking === ""; x: lbl.width + 12 - 11; y: 2; spacing: 2
        Repeater { model: mk.generators.slice(0, mk.shown)
            Chip { required property var modelData; objectName: "make_" + modelData.id
                text: modelData.title; tip: modelData.summary + " Print-ready, and editable like any design."; enabled: !mk.busy
                onClicked: mk.start(modelData) } }
        Chip { id: more; objectName: "makersMore"; text: "More"; chevron: true; lit: menu.opened; enabled: !mk.busy
            tip: "Every generator, and a mesh generator's result rebuilt as CAD"
            onClicked: menu.openAt(more, 0, more.height + 6) } }
    PopMenu { id: menu; objectName: "makersMenu"
        model: mk.generators.slice(mk.shown).map(function (g) { return { icon: "box", text: g.title, run: function () { mk.start(g) } } })
            .concat(mk.shown < mk.generators.length ? [{ sep: true }] : [])
            .concat([{ icon: "sparkles", text: "Generate from words or a picture…", run: function () { Store.openSheet("generate") } }]) }
    // the name tag's text: typed here, in the line
    Row { visible: mk.asking !== ""; x: lbl.width + 12; height: mk.h; spacing: Theme.s2
        Field { id: textField; objectName: "makersText"; width: 240; anchors.verticalCenter: parent.verticalCenter; placeholder: "The text, e.g. MAYA"
            onAccepted: function (t) { if (t.trim()) mk.run(mk.gen(mk.asking), { text: t }) }
            Keys.onEscapePressed: mk.asking = "" }
        Btn { small: true; kind: "primary"; anchors.verticalCenter: parent.verticalCenter; text: mk.busy ? "Making…" : "Make it"; enabled: !mk.busy && textField.text.trim() !== ""
            onClicked: mk.run(mk.gen(mk.asking), { text: textField.text }) }
        Btn { small: true; kind: "quiet"; icon: "x"; tip: "Cancel"; anchors.verticalCenter: parent.verticalCenter; onClicked: mk.asking = "" } }
}
