import QtQuick
import QtQuick.Controls
import "F.js" as F

// A project: the part in the middle, the question being asked of it on the right.
Item {
    id: ws
    readonly property var d: Store.data
    function stageNote(id) {
        if (!d) return ["", ""]
        var roll = d.checks ? d.checks.rollup : null
        if (id === "brief") {
            var k = d.recipe.params.filter(function (p) { return p.group === "brief" })
            var m = k.filter(function (p) { var pv = Store.head.provenance[p.key]; return pv && pv.source === "measured" }).length
            return k.length ? [m + "/" + k.length + " measured", m === k.length ? "ok" : ""] : ["", ""]
        }
        if (id === "shape") return [Store.hasDraft ? "Draft open" : F.plural(d.recipe.features.length, "feature"), Store.hasDraft ? "draft" : ""]
        if (id === "fit") return d.fit ? [Math.round(d.fit.yield * 100) + "% modelled", d.fit.yield >= 0.95 ? "ok" : "warn"] : ["Calibration", ""]
        if (id === "prove") return !roll ? ["Not current", "warn"] : roll.FAIL ? [roll.FAIL + " failed", "fail"] : roll.WARN ? [roll.WARN + " to review", "warn"] : ["All pass", "ok"]
        if (id === "release") return d.approval.state === "approved" ? ["Released", "ok"] : d.gate.ready ? ["Ready to approve", ""] : ["Not ready", ""]
        return ["", ""]
    }
    function noteColor(c) { return c === "ok" ? Theme.pass : c === "warn" ? Theme.amber : c === "fail" ? Theme.signal : c === "draft" ? Theme.blueprint : Theme.ink3 }

    // ── centre: the part ─────────────────────────────────────
    Item {
        id: centre
        anchors.left: parent.left; anchors.right: insp.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        Viewport {
            id: vp
            anchors.fill: parent
            visible: !Store.layers
            Component.onCompleted: { Store.viewer = vp; if (Store.view) { Store.showHead(); vp.setView("iso", false) } }
            Component.onDestruction: if (Store.viewer === vp) Store.viewer = null
            onPicked: function (f) { Store.pick(f) }
            onHoveredFeature: function (f, x, y) { chip.feat = Store.featureById(f); chip.x = x + 14; chip.y = y + 14 }
        }
        Loader { anchors.fill: parent; active: !!Store.layers; source: "LayerView.qml" }
        // soft vignette so the plate falls away at the edges
        Rectangle { anchors.fill: parent; visible: !Store.layers
            gradient: Gradient { orientation: Gradient.Vertical
                GradientStop { position: 0; color: Theme.alpha(Theme.plate, 0.55) } GradientStop { position: 0.18; color: "transparent" }
                GradientStop { position: 0.8; color: "transparent" } GradientStop { position: 1; color: Theme.alpha(Theme.plate, 0.7) } } }

        Rectangle { id: chip; property var feat: null; visible: !!feat && !Store.layers; z: 5
            width: ct.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.plate3; border.color: Theme.rule2
            Row { id: ct; anchors.centerIn: parent; spacing: 6
                Txt { text: chip.feat ? chip.feat.label : ""; font.pixelSize: 12; font.weight: 550 }
                Txt { text: chip.feat ? chip.feat.role : ""; kind: "fine" } } }

        // HUD — top left: state banners
        Column { x: 16; y: 14; spacing: 6; visible: !Store.layers
            Rectangle { visible: Store.hasDraft && !!Store.preview; width: b1.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b1; anchors.centerIn: parent; font.pixelSize: 12; color: "#cdd9ff"
                    text: "Draft, not committed · blue lines are " + (Store.project ? F.pad(Store.project.head) : "") } }
            Rectangle { visible: !!Store.compare; width: b2.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b2; anchors.centerIn: parent; font.pixelSize: 12; color: "#cdd9ff"
                    text: Store.compare ? "Comparing · solid is " + F.pad(Store.project.head) + " (head), blue lines are " + F.pad(Store.compare.rev) : "" } } }
        // HUD — top right: views and section
        Row { anchors.right: parent.right; anchors.rightMargin: 16; y: 14; spacing: 8; visible: !Store.layers
            Rectangle { visible: !!Store.sectionNow(); width: 150; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                Beam { anchors.centerIn: parent; width: parent.width - 20; from: 0.02; to: 0.98; step: 0.01
                    value: Store.section && Store.section.axis ? Store.section.t : (Store.sectionNow() ? Store.sectionNow().t : 0.5)
                    onMoved: function (v) { var s = Store.sectionNow(); Store.setSection(s ? s.axis : "y", v) } } }
            Seg { model: [{ value: "x", text: "Cut X" }, { value: "y", text: "Cut Y" }, { value: "z", text: "Cut Z" }]
                value: Store.sectionNow() ? Store.sectionNow().axis : ""
                onPicked: function (v) { var s = Store.sectionNow(); Store.setSection(s && s.axis === v ? "" : v, 0.5) } }
            Seg { model: ["iso", "front", "side", "top", "under"]; value: Store.viewName; onPicked: function (v) { Store.setView(v) } } }
        // HUD — bottom left: what you are looking at
        Row { x: 16; anchors.bottom: pipe.top; anchors.bottomMargin: 12; spacing: 8; visible: !Store.layers && !!Store.shown
            Rectangle { width: ro.implicitWidth + 20; height: 26; radius: Theme.rSm; color: Theme.alpha(Theme.plate1, 0.86); border.color: Theme.rule
                Row { id: ro; anchors.centerIn: parent; spacing: 8
                    Txt { mono: true; font.pixelSize: 12
                        text: Store.shown ? F.fmt(Store.shown.bbox[1][0] - Store.shown.bbox[0][0], 1) + " × " + F.fmt(Store.shown.bbox[1][1] - Store.shown.bbox[0][1], 1) + " × " + F.fmt(Store.shown.bbox[1][2] - Store.shown.bbox[0][2], 1) + " mm" : "" }
                    Txt { text: "·"; tone: 4 }
                    Txt { mono: true; font.pixelSize: 12; text: Store.shown ? F.fmt(Store.shown.volume_mm3 / 1000, 1) + " cm³" : "" }
                    Txt { text: "·"; tone: 4 }
                    Txt { font.pixelSize: 12; tone: 3; text: "plate 180 × 180" } } }
            Btn { small: true; kind: "quiet"; active: Store.dims; icon: "ruler"; tip: "Overall dimensions"; onClicked: Store.toggleDims() }
            Btn { small: true; kind: "quiet"; active: Store.companions; icon: "box"; tip: "Show what the part holds"
                visible: !!(Store.shown && Store.shown.companions && Store.shown.companions.length); onClicked: Store.toggleCompanions() } }

        Pipeline { id: pipe; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 12 }
    }

    // ── right: the stage inspector ───────────────────────────
    Rectangle {
        id: insp
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 400
        color: Theme.plate1
        Rectangle { width: 1; height: parent.height; color: Theme.rule }
        // stage tabs
        Row { id: tabs; x: 8; y: 6; width: parent.width - 16; height: 52
            Repeater {
                model: Store.stages
                Item {
                    id: tab
                    required property var modelData
                    required property int index
                    readonly property bool on: Store.stage === modelData.id
                    readonly property var note: ws.stageNote(modelData.id)
                    width: tabs.width / 5; height: tabs.height
                    Rectangle { anchors.fill: parent; anchors.margins: 2; radius: Theme.rMd; color: tab.on ? Theme.plate3 : tm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.fast } } }
                    Column { anchors.centerIn: parent; spacing: 2
                        Row { spacing: 5; anchors.horizontalCenter: parent.horizontalCenter
                            Txt { mono: true; font.pixelSize: 10; tone: 4; text: "0" + (tab.index + 1); anchors.baseline: tl.baseline }
                            Txt { id: tl; text: tab.modelData.title; font.weight: 600; font.pixelSize: 13; tone: tab.on ? 1 : 2 } }
                        Txt { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: 10; text: tab.note[0]; color: ws.noteColor(tab.note[1]); wrapMode: Text.NoWrap } }
                    MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.setStage(tab.modelData.id) }
                    Tip { show: tm.containsMouse; text: tab.modelData.hint }
                }
            }
        }
        Rectangle { anchors.top: tabs.bottom; anchors.topMargin: 5; width: parent.width; height: 1; color: Theme.rule }
        Flickable {
            id: scroll
            anchors.top: tabs.bottom; anchors.topMargin: 6; anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
            contentHeight: body.implicitHeight + 40; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            Column {
                id: body; x: 20; y: 6; width: parent.width - 40; spacing: 14
                Loader { id: panel; width: parent.width; active: !!Store.data
                    source: ({ brief: "Brief.qml", shape: "Shape.qml", fit: "Fit.qml", prove: "Prove.qml", release: "Release.qml" })[Store.stage]
                    onLoaded: { scroll.contentY = 0; fadeIn.restart() }
                    NumberAnimation { id: fadeIn; target: panel; property: "opacity"; from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic } }
                DraftCard { width: parent.width }
            }
        }
    }
}
