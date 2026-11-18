import QtQuick
import FormNative
import "F.js" as F

// A standard feature on a face (form/feature_helpers.py): a screw boss or a snap-fit hook at the point and normal picked
// in Annotate. "Add to design" writes it into the design's source as a feature and builds a new revision in the kernel.
// The checks below are computed as you type: the boss wall against the nozzle, the hook's strain (1.5·t·y/L²).
Column {
    id: fs
    objectName: "featureSheet"
    property string title: "Feature on this face"
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
    property string kind: "boss"
    property string size: "M3"
    property string hole: "tapped"
    property var check: null
    property string checkErr: ""
    property bool checking: false
    property bool adding: false
    readonly property var nums: kind === "boss" ? [{ k: "height", t: "Height", v: "8" }, { k: "outer_d", t: "Outer Ø", v: "" }]
                                                : [{ k: "length", t: "Length", v: "12" }, { k: "thickness", t: "Thickness", v: "1.6" },
                                                   { k: "width", t: "Width", v: "6" }, { k: "lip", t: "Lip (undercut)", v: "1" }]
    property var values: ({})
    readonly property bool ready: !!at && !!normal && !!check && checkErr === "" && !adding
    spacing: 14

    function options() {
        var o = {}
        if (kind === "boss") { o.size = size; o.hole = hole }
        for (var i = 0; i < nums.length; i++) { var v = values[nums[i].k]; if (v !== undefined && String(v).trim() !== "") o[nums[i].k] = Number(v) }
        return o
    }
    function recheck() { checkTimer.restart() }
    onKindChanged: { values = ({}); recheck() }
    onSizeChanged: recheck()
    onHoleChanged: recheck()
    Component.onCompleted: recheck()
    Timer { id: checkTimer; interval: 200
        onTriggered: {
            fs.checking = true
            var o = fs.options(), q = "kind=" + fs.kind
            for (var k in o) q += "&" + k + "=" + encodeURIComponent(o[k])
            Store.pget("/features/check?" + q).then(function (r) { fs.check = r; fs.checkErr = ""; fs.checking = false },
                                                   function (e) { fs.check = null; fs.checkErr = e.message || "Not a valid feature."; fs.checking = false })
        } }

    function accept() {
        if (!ready) return
        adding = true
        Store.addFeature({ kind: kind, at: at, normal: normal, options: options() }).then(function (ok) {
            fs.adding = false
            if (ok) Store.openSheet(null)
        })
    }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { objectName: "featureAdd"; kind: "primary"; icon: "wrench"; text: "Add to design"; busy: fs.adding; busyText: "Building…"
            enabled: fs.ready; onClicked: fs.accept() } }

    Seg { objectName: "featureKind"; model: [{ value: "boss", text: "Screw boss" }, { value: "snap_hook", text: "Snap-fit hook" }]
        value: fs.kind; onPicked: function (v) { fs.kind = v } }
    Column { width: parent.width; spacing: 8; visible: fs.kind === "boss"
        Seg { model: ["M2", "M2.5", "M3", "M4", "M5"]; value: fs.size; onPicked: function (v) { fs.size = v } }
        Seg { model: [{ value: "tapped", text: "Screw cuts its thread" }, { value: "insert", text: "Heat-set insert" }, { value: "clearance", text: "Screw passes" }]
            value: fs.hole; onPicked: function (v) { fs.hole = v } } }
    Grid { width: parent.width; columns: 2; columnSpacing: 12; rowSpacing: 8
        Repeater { model: fs.nums
            Column { required property var modelData; width: (fs.width - 12) / 2; spacing: 4
                Txt { kind: "fine"; text: modelData.t }
                Field { objectName: "feature_" + modelData.k; width: parent.width; numeric: true; unit: "mm"; text: modelData.v
                    placeholder: modelData.v === "" ? "auto" : ""
                    onEdited: { var o = Object.assign({}, fs.values); o[modelData.k] = text; fs.values = o; fs.recheck() } } } } }

    Rectangle { width: parent.width; height: pc.implicitHeight + 24; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
        Column { id: pc; x: 14; y: 12; width: parent.width - 28; spacing: 6
            Item { width: parent.width; height: 17
                Txt { kind: "cap"; text: fs.kind === "boss" ? "Boss" : "Hook"; anchors.verticalCenter: parent.verticalCenter }
                Spinner { size: 12; visible: fs.checking; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter } }
            Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!fs.check && fs.kind === "boss"
                text: fs.check && fs.check.spec.kind === "boss" ? "Hole Ø " + F.fmt(fs.check.spec.hole_d, 2) + " mm (" + fs.check.hole_source + "), boss Ø "
                      + F.fmt(fs.check.spec.outer_d, 1) + " × " + F.fmt(fs.check.spec.height, 1) + " mm" : "" }
            Repeater { model: fs.check ? fs.check.checks : []
                Row { required property var modelData; width: pc.width; spacing: 8
                    Tag { text: modelData.status; kind: modelData.status }
                    Txt { width: parent.width - 60; kind: "fine"; tone: 2; text: modelData.label + ": " + modelData.value } } }
            Txt { kind: "fine"; width: parent.width; color: Theme.amber; visible: fs.checkErr !== ""; text: fs.checkErr } } }

    Txt { kind: "fine"; width: parent.width
        text: "The feature becomes code in the design and a new revision, built in the kernel. One that does not sit on the part is refused with the reason." }
}
