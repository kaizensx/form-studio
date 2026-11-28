import QtQuick
import FormNative
import "F.js" as F

// Standard parts (form/catalog.py, form/placement.py): search the tables, pick a part, and place it on the point
// picked in Annotate (a hole's wall or a flat face). Placing is one action: it snaps to the hole or face, cuts the
// mating hole, counterbore, insert pocket or seat into the design as a feature, records the part as purchased with
// its standard designation, and checks the fit on the B-rep. Below: the parts already placed, with their fit.
Column {
    id: ps
    objectName: "partsSheet"
    property string title: "Standard parts"
    property string note: at ? "Place at " + at.map(function (x) { return F.fmt(x, 1) }).join(", ") + " mm (snaps to the hole or face)"
                             : "Search the tables. To place one, pick a hole or a face in Annotate first."
    property int sheetWidth: Theme.sheetS
    readonly property var item: Store.sheet && Store.sheet.props ? Store.sheet.props.item : null
    readonly property var at: item && item.on ? item.on : null
    readonly property var normal: item && item.normal ? item.normal : null
    property var results: []
    property var picked: null
    property var placed: []
    property var fitRows: ({})
    property bool busy: false
    property string err: ""
    spacing: 14

    function search(t) {
        Store.pget("/parts/search?q=" + encodeURIComponent(t)).then(function (r) { ps.results = r.results; ps.err = "" },
                                                                    function (e) { ps.results = []; ps.err = e.message || String(e) })
    }
    function load() {
        Store.pget("/parts").then(function (r) { ps.placed = r.placements }, function () {})
        Store.pget("/parts/fit").then(function (r) { var m = {}; for (var i = 0; i < r.rows.length; i++) m[r.rows[i].id] = r.rows[i]; ps.fitRows = m },
                                      function () {})
    }
    Component.onCompleted: load()
    Timer { id: typing; interval: 220; onTriggered: ps.search(query.text) }

    function accept() {
        if (!picked || !at || busy || picked.error) return
        busy = true
        Store.ppost("/part_place", { spec: picked.spec, at: at, normal: normal, expect_head: Store.project ? Store.project.head : null })
            .then(function (r) {
                ps.busy = false
                var f = r.fit && r.fit.rows.length ? r.fit.rows[0] : null
                Store.toast("Placed as " + F.pad(r.head), r.designation + (f ? " · fit " + f.status : ""))
                if (r.job) Store.track(r.job)
                Store.refresh(true)
                Store.openSheet(null)
            }, function (e) { ps.busy = false; Store.fail(e) })
    }
    function remove(id) {
        Store.ppost("/part_remove", { id: id, expect_head: Store.project ? Store.project.head : null })
            .then(function (r) { if (r.job) Store.track(r.job); Store.refresh(true); ps.load() }, function (e) { Store.fail(e) })
    }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { objectName: "partPlace"; kind: "primary"; icon: "wrench"; text: "Place on the picked point"; busy: ps.busy; busyText: "Cutting and checking…"
            enabled: !!ps.picked && !!ps.at && !ps.picked.error; onClicked: ps.accept() } }

    Field { id: query; objectName: "partSearch"; width: parent.width; placeholder: "M5 socket 12, 608, LM8UU, NEMA 17, O-ring 010…"
        onEdited: typing.restart(); onAccepted: ps.search(text) }

    Column { width: parent.width; spacing: 2; visible: ps.results.length > 0
        Repeater { model: ps.results
            Rectangle { required property var modelData; width: ps.width; height: rc.implicitHeight + 14; radius: 10
                color: ps.picked === modelData ? Theme.alpha(Theme.datum, 0.16) : (ma.containsMouse ? Theme.glass : "transparent")
                Column { id: rc; x: 10; y: 7; width: parent.width - 20; spacing: 2
                    Txt { width: parent.width; text: modelData.designation || (modelData.label + " " + modelData.spec.size); elide: Text.ElideRight }
                    Txt { width: parent.width; kind: "fine"; tone: 2; elide: Text.ElideRight
                        text: modelData.error ? modelData.error : modelData.source } }
                MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: ps.picked = modelData } } } }
    Txt { kind: "fine"; width: parent.width; color: Theme.amber; visible: ps.err !== ""; text: ps.err }

    Column { width: parent.width; spacing: 6; visible: ps.placed.length > 0
        Txt { kind: "cap"; text: "On this design" }
        Repeater { model: ps.placed
            Row { required property var modelData; width: ps.width; spacing: 8
                readonly property var fit: ps.fitRows[modelData.id]
                Tag { text: fit ? fit.status : "…"; kind: fit ? fit.status : "" }
                Txt { width: parent.width - 150; kind: "fine"; elide: Text.ElideRight
                    text: modelData.id + " · " + (fit ? fit.designation : modelData.spec.family + " " + modelData.spec.size) }
                Btn { small: true; kind: "quiet"; text: "Remove"; onClicked: ps.remove(modelData.id) } } } }

    Txt { kind: "fine"; width: parent.width
        text: "Every dimension comes from a cited table; threads are cosmetic. The parts list (Bench › Parts list) groups what to buy by designation." }
}
