import QtQuick
import "F.js" as F

// The tree's other rows (the reference's FeatureManager, in our row grammar), kept out of Shape.qml's listing:
//   part "head": Equations (the design's values: opens the Values view), Material, Purchased parts (from the parts
//                list, GET /bom), and the Origin with its three planes: a plane's row starts a sketch on it
//   part "pmi":  what the drawing declares (GET /pmi): datums, toleranced dimensions (fits, with their ISO 286 limits
//                once a drawing is made), GD&T, surface texture and notes, each with who declared it
// Each row is the tree's: an icon in the mark's column, a name, its value on the right. Nothing here is computed.
Column {
    id: tx
    property string part: "head"
    readonly property int head: Store.project ? Store.project.head : 0
    property var bom: null
    property var pmi: null
    readonly property bool hasAny: part === "pmi" ? !!pmi && pmi.count > 0 : true
    readonly property var general: Store.recipe ? Store.recipe.params.filter(function (p) { return p.group !== "brief" }) : []
    readonly property var mat: { var a = Store.appearance, c = Store.materialCat; return Store.material(Store.look("").material) }
    readonly property bool originOpen: Ws.isOpen("tree.origin", false)
    readonly property bool pmiOpen: Ws.isOpen("tree.pmi", true)
    function load() {
        if (!Store.pid) return
        var at = Store.pid
        if (part === "head") Store.pget("/bom?made=0").then(function (r) { if (Store.pid === at) tx.bom = r }, function () { tx.bom = null })
        else Store.pget("/pmi").then(function (r) { if (Store.pid === at) tx.pmi = r }, function () { tx.pmi = null })
    }
    onHeadChanged: load()
    Component.onCompleted: { load(); if (part === "head") Store.loadMaterials() }
    Connections { target: Store; function onPidChanged() { tx.bom = null; tx.pmi = null; tx.load() } }

    component Row_: Item {
        id: rw
        property string icon: ""
        property string name: ""
        property string value: ""
        property string tip: ""
        property int indent: 0
        property bool chevron: false
        property bool open: false
        property bool dim: false
        signal clicked()
        width: tx.width; height: 30
        Rectangle { anchors.fill: parent; radius: 10; color: rm.pressed ? Theme.washPress : rm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
        Icon { visible: rw.chevron; x: 10; anchors.verticalCenter: parent.verticalCenter; name: rw.open ? "chevron_down" : "chevron_right"; size: 12; color: Theme.ink3 }
        Icon { x: 41 + rw.indent; anchors.verticalCenter: parent.verticalCenter; name: rw.icon; size: 13; color: rw.dim ? Theme.ink3 : Theme.ink2 }
        Txt { id: rn; x: 64 + rw.indent; anchors.verticalCenter: parent.verticalCenter; width: parent.width - x - rv.width - 22; elide: Text.ElideRight; wrapMode: Text.NoWrap
            font.pixelSize: 13; font.letterSpacing: -0.05; font.weight: Theme.wMedium; color: rw.dim ? Theme.ink3 : Theme.ink; text: rw.name }
        Txt { id: rv; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
            width: Math.min(implicitWidth, parent.width * 0.48); elide: Text.ElideRight; text: rw.value }
        MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rw.clicked() }
        Tip { show: rm.containsMouse && rw.tip !== ""; text: rw.tip }
    }

    // ── head ──
    Row_ { visible: tx.part === "head"; objectName: "treeEquations"; icon: "hash"; name: "Equations"; value: F.plural(tx.general.length, "value")
        tip: "The design's parameters: every size is a value you can change. Opens the Values view."
        onClicked: { Store.treeLower = "values"; Store.select("") } }
    Row_ { visible: tx.part === "head"; objectName: "treeMaterial"; icon: "library"; name: "Material"; dim: !tx.mat
        value: tx.mat ? tx.mat.label : "not chosen"
        tip: tx.mat ? "Colour and material: " + tx.mat.label + ". Its density gives the mass." : "No material chosen: the mass stays unknown. Choose one under Colour and material."
        onClicked: { Store.treeLower = "values"; Store.select("") } }
    Row_ { visible: tx.part === "head"; objectName: "treeParts"; icon: "wrench"; name: "Purchased parts"
        readonly property int n: tx.bom && tx.bom.purchased ? tx.bom.purchased.reduce(function (s, x) { return s + (x.quantity || 1) }, 0) : 0
        dim: n === 0; value: tx.bom ? (n ? F.plural(n, "part") : "none") : ""
        tip: "Screws, inserts, bearings and other bought parts placed on the design, from the parts list. Opens the parts list in the Bench."
        onClicked: { Store.benchOpen = true; Store.benchSheetSel = "doc.bom" } }
    Row_ { visible: tx.part === "head"; objectName: "treeOrigin"; icon: "crosshair"; name: "Origin"; chevron: true; open: tx.originOpen; value: "XY · XZ · YZ"
        tip: "The three planes through the origin: open to sketch on one"
        onClicked: Ws.setOpen("tree.origin", !tx.originOpen) }
    Repeater { model: tx.part === "head" && tx.originOpen ? [["XY", "the floor plane, normal +z"], ["XZ", "the front plane, normal −y"], ["YZ", "the side plane, normal +x"]] : []
        Row_ { required property var modelData; objectName: "treePlane-" + modelData[0]; indent: 14; icon: "square_dashed"; name: modelData[0] + " plane"; value: "sketch"
            tip: "Sketch on " + modelData[1] + ", then extrude, cut or revolve it"
            onClicked: Store.openSheet("handsketch", { mode: "add", plane: { datum: modelData[0], offset: 0 }, kind: "extrude" }) } }
    Item { visible: tx.part === "head"; width: 1; height: 4 }
    Rectangle { visible: tx.part === "head"; x: 12; width: parent.width - 24; height: 1; color: Theme.rule }
    Item { visible: tx.part === "head"; width: 1; height: 4 }

    // ── PMI ──
    Item { visible: tx.part === "pmi"; width: 1; height: 6 }
    Row_ { visible: tx.part === "pmi"; objectName: "treePmi"; icon: "pencil_ruler"; name: "PMI"; chevron: true; open: tx.pmiOpen
        value: tx.pmi ? F.plural(tx.pmi.count, "annotation") : ""
        tip: "What the drawing declares: datums, toleranced dimensions and notes. " + (tx.pmi ? tx.pmi.evidence : "")
        onClicked: Ws.setOpen("tree.pmi", !tx.pmiOpen) }
    Repeater {
        model: tx.part !== "pmi" || !tx.pmi || !tx.pmiOpen ? [] : [].concat(
            tx.pmi.datums.map(function (d) { return { k: "datum", icon: "flag", n: "Datum " + (d.letter || "?"), v: d.by === "you" ? "by you" : "by the design" } }),
            tx.pmi.fits.map(function (f) { var sp = Store.recipe ? Store.recipe.params.filter(function (p) { return p.key === f.param })[0] : null
                return { k: "fit", icon: "diameter", n: (sp ? sp.label : (f.param || "a size")) + " " + (f["class"] || ""),
                         v: f.limits ? F.trim(f.limits.min, 3) + " – " + F.trim(f.limits.max, 3) + " mm" : "limits when drawn" } }),
            tx.pmi.gdt.map(function (g) { return { k: "gdt", icon: "target", n: String(g.type || "tolerance").replace(/_/g, " "), v: g.tol !== undefined ? F.trim(g.tol, 3) + " mm" + (g.datums && g.datums.length ? " | " + g.datums.join(" | ") : "") : "" } }),
            tx.pmi.surface.map(function (s) { return { k: "surface", icon: "scan_line", n: "Surface", v: s.ra !== undefined ? "Ra " + F.trim(s.ra, 2) : (s.text || "") } }),
            tx.pmi.notes.map(function (n) { return { k: "note", icon: "message_square_text", n: n.text || "", v: n.by === "you" ? "by you" : "note" } }))
        Row_ { required property var modelData; required property int index; objectName: "treePmi-" + modelData.k + "-" + index; indent: 14; icon: modelData.icon === "flag" ? "map_pin" : modelData.icon
            name: modelData.n; value: modelData.v; tip: "Opens the drawing in Document"
            onClicked: Store.setStage("document") } }
}
