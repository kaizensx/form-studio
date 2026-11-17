import QtQuick
import "F.js" as F

// Stage 02 — Shape. Pick a feature on the model or here; its parameters and what follows from them.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var f: Store.featureById(Store.feature)
    readonly property var params: Store.recipe ? Store.recipe.params : []
    function paramsOf(id) { return params.filter(function (p) { return p.feature === id }) }

    // a design written in OpenSCAD is a mesh: say what that rules out (CAD bridges)
    Note { visible: !!Store.recipe && !!Store.recipe.mesh; kind: "amber"; width: parent.width
        title: "Mesh design · OpenSCAD"
        text: Store.recipe && Store.recipe.mesh ? Store.recipe.notes.join("\n")
              + (Store.recipe.fixed_in_source.length ? "\nFixed in the source (no range comment): " + Store.recipe.fixed_in_source.join(", ") + "." : "") : "" }
    Item { width: 1; height: 8; visible: !!Store.recipe && !!Store.recipe.mesh }

    // all features
    Column {
        visible: !root.f; width: parent.width
        Sec { title: "Features"; note: "build order"
            Repeater {
                model: Store.recipe ? Store.recipe.features : []
                Rectangle {
                    id: fr
                    required property var modelData
                    objectName: "feature-" + modelData.id
                    readonly property bool touched: root.paramsOf(modelData.id).some(function (p) { return Store.draftValues[p.key] !== undefined })
                    width: parent.width; height: 46; radius: Theme.rMd
                    color: fm.pressed ? Theme.washPress : fm.containsMouse ? Theme.washHover : "transparent"
                    Behavior on color { Tint {} }
                    Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 3; height: 22; radius: 1.5; color: Theme.evidence(fr.modelData.role); opacity: 0.8 }
                    Column { x: 20; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 20 - tg.width - 30; spacing: 1
                        Txt { text: fr.modelData.label + (fr.touched ? "  ●" : ""); font.weight: 550; color: fr.touched ? Theme.blueprint : Theme.ink; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; visible: text !== ""; text: fr.modelData.doc || ""; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                    Tag { id: tg; text: fr.modelData.role; anchors.right: chev.left; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter }
                    Icon { id: chev; name: "chevron_right"; size: 13; color: Theme.ink4; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true
                        onClicked: Store.select(fr.modelData.id); onEntered: Store.hover(fr.modelData.id); onExited: Store.hover("") }
                }
            }
        }
        Sec { title: "General"
            visible: gen.count > 0
            Item { width: parent.width; height: 1 }
            Column { width: parent.width; x: 0
                Repeater { id: gen
                    model: root.params.filter(function (p) { return p.group !== "brief" && !Store.featureById(p.feature) })
                    ParamRow { required property var modelData; p: modelData } } } }
        Sec { title: "Explore"
            Txt { tone: 2; width: parent.width; text: "Build a grid of real candidates and rank them against objectives you weight." }
            Row { spacing: 6
                Btn { text: "Compare alternatives"; icon: "boxes"; enabled: !Store.hasDraft; onClicked: Store.openSheet("alternatives") }
                Btn { kind: "quiet"; text: "Variants"; icon: "layout_grid"; onClicked: Store.openSheet("variants") } } }
    }

    // one feature
    Column {
        visible: !!root.f; width: parent.width
        Item { width: parent.width; height: 34
            Btn { kind: "quiet"; small: true; icon: "arrow_left"; text: "All features"; x: -8; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.select("") } }
        Row { spacing: 8
            Txt { kind: "h2"; text: root.f ? root.f.label : "" }
            Tag { text: root.f ? root.f.role : ""; anchors.verticalCenter: parent.verticalCenter } }
        Txt { tone: 2; width: parent.width; topPadding: 4; text: root.f ? (root.f.doc || "") : "" }
        Sec { title: "Drives this feature"; note: root.f ? F.plural(root.paramsOf(root.f.id).length, "parameter") : ""
            Txt { kind: "fine"; width: parent.width; visible: !!root.f && root.paramsOf(root.f.id).length === 0
                text: "This feature has no parameters of its own; it follows the features around it." }
            Column { width: parent.width
                Repeater { model: root.f ? root.paramsOf(root.f.id) : []
                    ParamRow { required property var modelData; p: modelData; prov: modelData.group === "brief" } } } }
        // design tools: the text a Label parameter puts on the part (project setting; empty = the project name)
        Sec { title: "Label text"; note: "used when Label is 1 or 2"
            visible: !!root.f && root.f.id === "mark" && root.paramsOf("mark").some(function (p) { return p.key === "label" })
            Field { id: markText; width: parent.width; placeholder: Store.project ? Store.project.name : ""
                text: Store.project && Store.project.mark_text ? Store.project.mark_text : ""
                onAccepted: function (t) {
                    if (!Store.project || t === (Store.project.mark_text || "")) return
                    Store.settings({ mark_text: t }).then(function () { Store.refresh(true); if (Store.hasDraft) Store.runPreview() }) } }
            Txt { kind: "fine"; width: parent.width
                text: "Press Enter to apply. Lettering uses FORM’s bundled font; the checks measure its stroke width against the nozzle. The revision stamp reads like “r04 a3f1”: revision, then a short hash of its values." } }
        Sec { title: "Follows from them"; note: "not editable"
            readonly property var rows: root.f && Store.shown ? Store.shown.derived.filter(function (x) { return x.feature === root.f.id }) : []
            visible: rows.length > 0
            Column { width: parent.width
                Repeater { model: parent.parent.rows
                    KV { required property var modelData; required property int index; first: index === 0
                        k: modelData.label; sub: modelData.formula || ""; value: F.fmt(modelData.value) + " " + modelData.unit; tag: modelData.interface ? "interface" : "" } } } }
    }
}
