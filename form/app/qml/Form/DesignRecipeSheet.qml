import QtQuick
import QtQuick.Controls
import FormNative
import "F.js" as F

// Turn a design into a recipe: the design's code, with every parameter defaulting to the design's value. Each range
// starts as the code's own and can be narrowed, so whoever uses the recipe stays where this design was tested.
// "Build and review" rewrites the code, builds it once and compares it with the design; the review sheet then shows
// the code, its SHA-256 and that comparison before anything is installed.
//   Store.openSheet("designRecipe", { project: "hallway-phone-dock" })
Column {
    id: dr
    objectName: "designRecipeSheet"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property string pid: props.project || Store.pid
    property string title: "Turn this design into a recipe"
    property string note: info ? "“" + info.name + "” at " + F.pad(info.rev) + " · " + F.plural(info.params.length, "parameter") : ""
    property int sheetWidth: Theme.sheetL
    property var info: null            // GET /recipes/derive/<pid>
    property var ranges: ({})          // key → [min, max] the person typed
    property string error: ""
    spacing: 14
    Component.onCompleted: Store.get("/recipes/derive/" + pid).then(function (r) { dr.info = r; titleF.text = r.name; sumF.text = "" }, Store.fail)

    function setRange(key, i, txt) {
        var o = Object.assign({}, ranges), v = parseFloat(txt), row = info.params.filter(function (p) { return p.key === key })[0]
        var cur = o[key] ? o[key].slice() : [row.min, row.max]
        if (!isNaN(v)) cur[i] = v
        o[key] = cur; ranges = o
    }
    function build() {
        error = ""
        var p = Store.post("/recipes/derive", { project: pid, title: titleF.text, summary: sumF.text, ranges: ranges })
        p.then(function (r) { Store.openSheet("recipe", { mode: "derived", info: r }) }, function (e) { dr.error = e.message + (e.hint ? " " + e.hint : "") })
        return p
    }
    function num(v) { return String(Math.round(Number(v) * 1000) / 1000) }
    function accept() { if (info && info.ok) build() }

    property Component footerLeft: Txt { kind: "fine"; verticalAlignment: Text.AlignVCenter; text: "Your design is not changed." }
    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { id: buildBtn; objectName: "deriveBuild"; kind: "primary"; icon: "wand"; text: "Build and review"; busyText: "Building…"; keys: "Return"
            enabled: !!dr.info && dr.info.ok; onClicked: run(dr.build) } }

    Note { visible: !!dr.info && !dr.info.ok; kind: "amber"; title: "This design cannot become a recipe"; text: dr.info ? dr.info.why : "" }
    Note { visible: dr.error !== ""; kind: "red"; title: "Not built"; text: dr.error }
    Row { width: parent.width; spacing: 12
        Column { width: 260; spacing: 4
            Txt { kind: "cap"; text: "Recipe title" }
            Field { id: titleF; objectName: "deriveTitle"; width: parent.width } }
        Column { width: parent.width - 272; spacing: 4
            Txt { kind: "cap"; text: "Summary" }
            Field { id: sumF; width: parent.width; placeholder: dr.info ? dr.info.summary : "What it is and what makes it fit" } } }

    Column { width: parent.width; spacing: 0
        Row { width: parent.width; height: 26
            Txt { kind: "cap"; text: "Parameter"; width: parent.width - 330; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "cap"; text: "Default"; width: 110; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "cap"; text: "Range people can set"; width: 220; anchors.verticalCenter: parent.verticalCenter } }
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Rectangle { width: parent.width; height: Math.min(330, list.contentHeight + 2); color: "transparent"; clip: true
            ListView { id: list; anchors.fill: parent; model: dr.info ? dr.info.params : []; boundsBehavior: Flickable.StopAtBounds; clip: true
                ScrollBar.vertical: ScrollBar { width: 6 }
                delegate: Item { id: row; required property var modelData; required property int index
                    width: list.width; height: 40
                    Rectangle { visible: row.index > 0; width: parent.width; height: 1; color: Theme.rule }
                    Column { width: parent.width - 330; anchors.verticalCenter: parent.verticalCenter; spacing: 0
                        Txt { text: row.modelData.label; width: parent.width - 8; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; tone: 4; text: row.modelData.group + (row.modelData.provenance !== "assumed" ? " · " + row.modelData.provenance : "") } }
                    Txt { x: parent.width - 330; width: 110; mono: true; anchors.verticalCenter: parent.verticalCenter
                        text: dr.num(row.modelData.value) + " " + row.modelData.unit }
                    Row { x: parent.width - 220; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                        Field { width: 82; numeric: true; text: dr.num(row.modelData.min); onEdited: function (t) { dr.setRange(row.modelData.key, 0, t) } }
                        Txt { kind: "fine"; text: "to"; anchors.verticalCenter: parent.verticalCenter }
                        Field { width: 82; numeric: true; text: dr.num(row.modelData.max); onEdited: function (t) { dr.setRange(row.modelData.key, 1, t) } } } } } } }
    Txt { kind: "fine"; width: parent.width
        text: "A range can be narrowed, not widened: the code was written for its own. The new recipe is built once at these defaults and compared with the design before you review its code." }
}
