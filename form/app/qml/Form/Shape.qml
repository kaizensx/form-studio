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

    // ── the program: the features in build order, as a listing that runs ──
    // Each line has its place in the order, its name and its role. While a build plays (the stages an agent streams,
    // or the build-up of a new revision) the listing runs: the gutter lights down to the line being built, the lines
    // above it are ticked, the ones below wait. All of it follows the real build (Store.building, Store.revealing,
    // Store.builtIds, Store.stageLog); the listing counts nothing itself.
    readonly property real paneHeight: root.f ? -1 : program.listingHeight
    readonly property bool streaming: !!Store.building && Store.building.project === Store.pid
    readonly property bool running: streaming || Store.revealing.length > 0
    readonly property int stepAt: streaming ? Store.building.at : Store.buildAt
    readonly property int stepOf: streaming ? Store.building.of : Store.buildOf
    readonly property var builtNow: {
        if (!running) return []
        if (!streaming) return Store.builtIds
        var out = [], d = Store.building.draft
        for (var i = 0; i < Store.stageLog.length; i++) if (Store.stageLog[i].draft === d && Store.stageLog[i].feature !== Store.building.feature) out.push(Store.stageLog[i].feature)
        return out
    }
    Column {
        id: program; objectName: "program"
        readonly property real listingHeight: 40 + listing.height + 6      // the pane is this tall; what follows is a scroll away
        visible: !root.f; width: parent.width
        Item { width: parent.width; height: 40
            Txt { id: pt; x: 12; anchors.verticalCenter: parent.verticalCenter; text: "Program"; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15 }
            Txt { anchors.left: pt.right; anchors.leftMargin: 8; anchors.baseline: pt.baseline; mono: true; font.pixelSize: 11; tone: 3; text: Store.recipe ? String(Store.recipe.features.length) : "" }
            Txt { visible: !root.running; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3; text: "build order" }
            Row { objectName: "programRun"; visible: root.running; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 9
                Item { width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(Theme.datum, 0.22) }
                    Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.datum } }
                Txt { anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.5; font.capitalization: Font.AllUppercase; color: Theme.datum; wrapMode: Text.NoWrap
                    text: root.stepOf > 1 ? root.stepAt + " of " + root.stepOf : "building" } } }
        Item {
            id: listing; width: parent.width; height: lines.implicitHeight
            // the gutter: the one drawn line of the pane, 39 px in: between the numbers and the marks, which stand
            // beside it and are never crossed by it. Lit from the top down to the middle of the line being built.
            Rectangle { x: 39; y: 4; width: 1; height: parent.height - 8; color: Theme.rule }
            // the line being built is raised: one pane of glass that glides from line to line
            Rectangle { id: nowBar; objectName: "programNow"; width: parent.width; height: 32; radius: 10; color: Theme.glass2
                y: pc.at ? pc.at.y : 0; opacity: root.running && pc.at ? 1 : 0; visible: opacity > 0.01
                Behavior on y { enabled: nowBar.opacity > 0.5; NumberAnimation { duration: Theme.move(220); easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                Rectangle { x: parent.radius; width: parent.width - 2 * parent.radius; height: 1; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.1 : 0) } }
            Rectangle { id: pc; objectName: "programGutter"; x: 38.5; y: 0; width: 2; radius: 1
                property Item at: null                    // the row being built
                property real reach: root.running && at ? at.y + 16 : 0
                height: reach; visible: height > 0.5
                opacity: root.running ? 1 : 0
                Behavior on reach { NumberAnimation { duration: Theme.reduced ? 0 : 220; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: Theme.cross } }
                gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0.25) } GradientStop { position: 0.7; color: Theme.datum } }
                Glow { blur: 10; strength: 0.55 } }
            Column {
                id: lines; width: parent.width
                Repeater {
                    model: Store.recipe ? Store.recipe.features : []
                    Item {
                        id: fr
                        required property var modelData
                        required property int index
                        objectName: "feature-" + modelData.id
                        readonly property bool touched: root.paramsOf(modelData.id).some(function (p) { return Store.draftValues[p.key] !== undefined })
                        readonly property var out: Store.leftOut(modelData.id)       // left out of a partial build
                        // its step of a build is running in the viewport (Store.revealing, or the stage the agent streams)
                        readonly property bool arriving: Store.revealing.indexOf(modelData.id) >= 0 || (root.streaming && Store.building.feature === modelData.id)
                        readonly property bool built: root.running && !arriving && root.builtNow.indexOf(modelData.id) >= 0
                        readonly property bool todo: root.running && !arriving && !built
                        onArrivingChanged: if (arriving) pc.at = fr
                        onBuiltChanged: if (built && root.running) landed.restart()
                        width: lines.width; height: Math.max(32, why.visible ? why.implicitHeight + 30 : 0)
                        Rectangle { anchors.fill: parent; radius: 10
                            color: fm.pressed ? Theme.washPress : fm.containsMouse && !fr.arriving ? Theme.washHover : "transparent"
                            Behavior on color { Tint {} } }
                        Item { objectName: "featureArriving"; width: 1; height: 1; opacity: fr.arriving ? 1 : 0 }       // what the tree and tests read
                        // its number in the build order
                        Txt { x: 0; y: (32 - height) / 2; width: 30; horizontalAlignment: Text.AlignRight; mono: true; font.pixelSize: 11; wrapMode: Text.NoWrap
                            text: (fr.index < 9 ? "0" : "") + (fr.index + 1); color: fr.arriving ? Theme.datum : fr.out ? Theme.amber : Theme.ink3; opacity: fr.todo ? 0.7 : 1
                            Behavior on color { Tint {} } }
                        // the mark, right of the gutter: ticked when built (the tick lands on a small spring and its
                        // light flares once), a pointer on the line being built
                        Item { x: 34; y: 0; width: 30; height: 32
                            Rectangle { id: flare; anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.pass; opacity: 0
                                Glow { color: Theme.pass; blur: 9; strength: 0.9; on: flare.opacity > 0.01 } }
                            Icon { id: tick; anchors.centerIn: parent; name: "check"; size: 13; color: Theme.pass
                                opacity: fr.built ? 1 : 0; scale: fr.built ? 1 : Theme.from(0.3)
                                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                                Behavior on scale { SpringAnimation { spring: 5.5; damping: 0.36; epsilon: 0.01 } } }
                            Icon { anchors.centerIn: parent; name: "play"; size: 10; color: Theme.datum
                                opacity: fr.arriving ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
                            SequentialAnimation { id: landed
                                NumberAnimation { target: flare; property: "opacity"; from: 0; to: Theme.reduced ? 0 : 0.9; duration: 90 }
                                NumberAnimation { target: flare; property: "opacity"; to: 0; duration: 360; easing.type: Easing.OutCubic } } }
                        Txt { id: nameTxt; x: 64; y: (32 - height) / 2; width: parent.width - 64 - kw.width - 22; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13; font.letterSpacing: -0.05
                            text: fr.modelData.label + (fr.touched ? "  ●" : ""); font.weight: fr.arriving ? Theme.wSemi : Theme.wMedium
                            color: fr.touched ? Theme.datum : fr.out || fr.todo ? Theme.ink3 : fr.built ? Theme.ink2 : Theme.ink
                            Behavior on color { Tint {} } }
                        Txt { id: why; objectName: "leftOutReason"; kind: "fine"; visible: !!fr.out; tone: 2; x: 64; y: 28; width: parent.width - 78; wrapMode: Text.WordWrap
                            text: fr.out ? Store.leftOutReason(fr.out) : "" }
                        // its role, lettered in neutral mono; "building" on the line that runs
                        Txt { id: kw; objectName: "featureRole"; anchors.right: parent.right; anchors.rightMargin: 12; y: (32 - height) / 2; mono: true; font.pixelSize: 10; font.weight: Theme.wMedium; font.letterSpacing: 1.0
                            font.capitalization: Font.AllUppercase; wrapMode: Text.NoWrap
                            text: fr.arriving ? "building" : fr.out ? "left out" : fr.modelData.role
                            color: fr.arriving ? Theme.datum : fr.out ? Theme.amber : Theme.ink3; opacity: fr.built ? 0.6 : fr.todo ? 0.5 : 1 }
                        MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true
                            onClicked: Store.select(fr.modelData.id); onEntered: Store.hover(fr.modelData.id); onExited: Store.hover("") }
                        Tip { show: fm.containsMouse && !!fr.modelData.doc && !fr.out; text: fr.modelData.doc || "" }
                    }
                }
            }
        }
        Item { width: 1; height: 6 }
    }
    Column {
        visible: !root.f; x: 10; width: parent.width - 20
        Sec { title: "General"
            visible: gen.count > 0
            Item { width: parent.width; height: 1 }
            Column { width: parent.width; x: 0
                Repeater { id: gen
                    model: root.params.filter(function (p) { return p.group !== "brief" && !Store.featureById(p.feature) })
                    ParamRow { required property var modelData; p: modelData } } } }
        Appearance { }                                  // colours and materials (form/materials.py)
        Sec { title: "Explore"
            Txt { tone: 2; width: parent.width; text: "Build a grid of real candidates and rank them against objectives you weight." }
            Row { spacing: 6
                Btn { text: "Compare alternatives"; icon: "boxes"; enabled: !Store.hasDraft; onClicked: Store.openSheet("alternatives") }
                Btn { kind: "quiet"; text: "Variants"; icon: "layout_grid"; onClicked: Store.openSheet("variants") } } }
    }

    // one feature
    Column {
        visible: !!root.f; x: 10; width: parent.width - 20
        Item { width: parent.width; height: 34
            Btn { kind: "quiet"; small: true; icon: "arrow_left"; text: "All features"; x: -8; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.select("") } }
        Row { spacing: 8
            Txt { kind: "h2"; text: root.f ? root.f.label : "" }
            Tag { text: root.f ? root.f.role : ""; anchors.verticalCenter: parent.verticalCenter } }
        Txt { tone: 2; width: parent.width; topPadding: 4 + lead; visible: text !== ""; text: root.f ? (root.f.doc || "") : "" }
        // its own parameters; a feature without any says what shapes it instead: values that follow from standards
        // (below), the design's general parameters and the features built before it (each one click away)
        Sec { id: drives; objectName: "featureDrives"
            readonly property int n: root.f ? root.paramsOf(root.f.id).length : 0
            readonly property var before: {
                var fs = Store.recipe ? Store.recipe.features : [], out = []
                for (var i = 0; root.f && i < fs.length && fs[i].id !== root.f.id; i++) out.push(fs[i])
                return out }
            readonly property int general: root.params.filter(function (p) { return p.group !== "brief" && !Store.featureById(p.feature) }).length
            readonly property int derived: root.f && Store.shown && Store.shown.derived ? Store.shown.derived.filter(function (x) { return x.feature === root.f.id }).length : 0
            title: n > 0 ? "Parameters" : "What shapes it"; note: n > 1 ? String(n) : ""
            Txt { objectName: "featureNoParams"; tone: 2; width: parent.width; visible: !!root.f && drives.n === 0
                text: {
                    var from = []
                    if (drives.derived) from.push("the values below")
                    if (drives.general) from.push("the design's general parameters")
                    if (drives.before.length) from.push("the features built before it")
                    return from.length ? "No settings of its own. Its size and place come from " + from.slice(0, -1).join(", ") + (from.length > 1 ? " and " : "") + from[from.length - 1] + "."
                                       : "No settings of its own. To change it, describe what you want in the conversation." } }
            Flow { width: parent.width; spacing: Theme.s1; visible: !!root.f && drives.n === 0 && (drives.before.length > 0 || drives.general > 0)
                Repeater { model: drives.n === 0 ? drives.before.slice(-3) : []
                    Btn { required property var modelData; small: true; kind: "quiet"; icon: "box"; text: modelData.label
                        tip: "Open " + modelData.label; onClicked: Store.select(modelData.id) } }
                Btn { visible: drives.general > 0; small: true; kind: "quiet"; icon: "sliders_horizontal"; text: "General parameters"
                    tip: "All features, with the design's general parameters"; onClicked: Store.select("") } }
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
                text: "Press Enter to apply. Lettering uses Form Studio’s bundled font; the checks measure its stroke width against the nozzle. The revision stamp reads like “r04 a3f1”: revision, then a short hash of its values." } }
        Sec { title: drives.n > 0 ? "Follows from them" : "Values it uses"; note: "not editable"
            readonly property var rows: root.f && Store.shown ? Store.shown.derived.filter(function (x) { return x.feature === root.f.id }) : []
            visible: rows.length > 0
            Column { width: parent.width
                Repeater { model: parent.parent.rows
                    KV { required property var modelData; required property int index; first: index === 0
                        k: modelData.label; sub: modelData.formula || ""; value: F.fmt(modelData.value) + " " + modelData.unit; tag: modelData.interface ? "interface" : "" } } } }
    }
}
