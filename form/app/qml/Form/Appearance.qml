import QtQuick
import "F.js" as F

// Colour and material: for the whole design, and for each part of a design that prints several. A row shows the
// colour, the name and the material; opened, it offers the swatches and the materials. The viewport draws the
// colour; the material adds its notes to the checks and gives the solid-mass estimate (form/materials.py).
Sec {
    id: ap
    objectName: "appearance"
    title: "Colour and material"
    note: Store.assembly ? F.plural(Store.assembly.parts.length, "part") : ""
    property string open: "-"                 // the row being edited: "" is the design, else a part id; "-" none
    readonly property var parts: Store.assembly ? Store.assembly.parts : []
    readonly property var rows: [{ id: "", label: parts.length ? "Whole design" : "Design", volume: Store.shown ? Store.shown.volume_mm3 : 0 }]
        .concat(parts.map(function (x) { return { id: x.id, label: x.label, volume: x.volume_mm3 } }))
    readonly property var matModel: [{ value: "", text: "Not chosen" }].concat((Store.materialCat ? Store.materialCat.materials : []).map(function (m) { return { value: m.id, text: m.label } }))
    Component.onCompleted: Store.loadMaterials()

    Column {
        width: parent.width; spacing: 2
        Repeater {
            model: ap.rows
            Column {
                id: row
                required property var modelData
                required property int index
                readonly property var lk: { var a = Store.appearance, c = Store.materialCat; return Store.look(modelData.id) }
                readonly property var mat: Store.material(lk.material)
                readonly property bool editing: ap.open === modelData.id
                readonly property bool inherits: modelData.id !== "" && !lk.own
                objectName: "look-" + (modelData.id || "design")
                width: parent.width
                Rectangle {
                    width: parent.width; height: 44; radius: Theme.rMd
                    color: rm.pressed ? Theme.washPress : row.editing ? Theme.plate3 : rm.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} }
                    Rectangle { id: dot; x: 10; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 10
                        color: row.lk.color || "#d8d3c8"; border.width: 1; border.color: Theme.alpha("#ffffff", 0.18)
                        Behavior on color { Tint {} }
                        Rectangle { anchors.centerIn: parent; width: 26; height: 26; radius: 13; color: "transparent"; border.width: 1
                            border.color: row.editing ? Theme.datum : "transparent" } }
                    Column { x: 42; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 42 - 30; spacing: 1
                        Txt { text: row.modelData.label; font.weight: 550; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: (row.mat ? row.mat.label : "No material chosen")
                                + (row.inherits ? " · as the design" : "")
                                + (row.mat && row.modelData.volume ? " · " + F.fmt(row.modelData.volume / 1000 * row.mat.density_g_cm3, 1) + " g if solid" : "") } }
                    Icon { name: "chevron_down"; size: 12; color: Theme.ink4; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                        rotation: row.editing ? 0 : -90
                        Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } }
                    MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: ap.open = row.editing ? "-" : row.modelData.id }
                }
                // the editor: swatches, then the material
                Column {
                    id: ed
                    visible: row.editing; width: parent.width; spacing: 10; topPadding: 8; bottomPadding: 12; leftPadding: 10; rightPadding: 10
                    opacity: row.editing ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
                    Flow {
                        width: parent.width - 20; spacing: 8
                        Repeater {
                            model: Store.materialCat ? Store.materialCat.swatches : []
                            Rectangle {
                                required property var modelData
                                objectName: "swatch-" + modelData
                                readonly property bool on: (row.lk.color || "").toLowerCase() === modelData && (row.lk.own || row.modelData.id === "")
                                width: 26; height: 26; radius: 13; color: modelData; border.width: 1; border.color: Theme.alpha("#ffffff", 0.16)
                                scale: sm.pressed ? 0.92 : sm.containsMouse ? 1.08 : 1
                                Behavior on scale { NumberAnimation { duration: Motion.quick; easing.type: Easing.OutCubic } }
                                Rectangle { anchors.centerIn: parent; width: 32; height: 32; radius: 16; color: "transparent"; border.width: 1.5
                                    border.color: parent.on ? Theme.datum : "transparent" }
                                MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: Store.setLook(row.modelData.id, modelData, undefined) }
                                Tip { show: sm.containsMouse; text: modelData }
                            }
                        }
                        Btn { small: true; kind: "quiet"; height: 26; text: row.modelData.id ? "Same as design" : "Material colour"
                            visible: row.modelData.id ? row.lk.own : !!Store.appearance.color
                            tip: row.modelData.id ? "Use the design’s colour and material for this part." : "Show the design in its material’s usual colour."
                            onClicked: row.modelData.id ? Store.setLook(row.modelData.id, null, null) : Store.setLook("", null, undefined) }
                    }
                    Row {
                        spacing: 10
                        Txt { kind: "fine"; text: "Material"; anchors.verticalCenter: parent.verticalCenter; width: 58 }
                        Pick { objectName: "materialPick"; width: Math.min(220, ed.width - 88); height: 28; model: ap.matModel
                            value: (row.modelData.id && !row.lk.own ? "" : row.lk.material) || ""
                            onPicked: function (v) { Store.setLook(row.modelData.id, undefined, v || null) } }
                    }
                    Txt { kind: "fine"; tone: 2; width: parent.width - 20; visible: !!row.mat
                        text: row.mat ? row.mat.note + " Softens from about " + row.mat.heat_c + " °C" + (row.mat.nozzle_c ? "; nozzle " + row.mat.nozzle_c[0] + "–" + row.mat.nozzle_c[1] + " °C." : ".") : "" }
                }
            }
        }
    }
    Txt { kind: "fine"; width: parent.width
        text: "The colour is drawn here and written into the 3MF. A material adds its notes to the checks (heat, sunlight, warping, flexible, resin); typical datasheet values, brands differ." }
    Btn { objectName: "save3mf"; small: true; icon: "download"; text: "Save 3MF with colours…"; enabled: !Store.hasDraft
        tip: Store.hasDraft ? "Commit or discard the draft first." : "The current revision as printed, one object per part, each in its colour."
        onClicked: Store.exportRequested("colour3mf", Store.pid, "3mf") }
}
