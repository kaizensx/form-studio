import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
import FormNative
import "F.js" as F

// Stage 04 — Prove. What has been established about this revision, and by what kind of evidence.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var d: Store.data
    readonly property var ch: d ? d.checks : null
    readonly property var sl: d ? d.slice : null
    readonly property var st: d ? d.status : null
    readonly property var cn: st ? st.checks : null          // checks node of the pipeline
    readonly property var sn: st ? st.slice : null           // slice node of the pipeline
    readonly property string head: d ? F.pad(d.project.head) : ""
    readonly property bool busy: Store.job !== ""
    readonly property bool sliceFailed: !!sn && sn.state === "failed"
    readonly property var colw: [54, 70, 78, 70]            // orientation table: numeric column widths
    function uniq(a) { return a.filter(function (x, i) { return a.indexOf(x) === i }) }

    // ── checks: not current ──────────────────────────────────
    Sec { title: "Checks"; visible: !root.ch
        Note { kind: "amber"
            text: !root.cn ? "Checks have not been produced for this revision."
                : root.cn.state === "failed" ? (root.cn.error ? root.cn.error.message : "The checks failed.")
                : root.cn.state === "stale" ? "The last checks were made for " + F.pad(root.cn.last_rev) + " and do not describe " + root.head + "."
                : "Checks have not been produced for this revision." }
        Btn { kind: "primary"; icon: "play"; text: root.busy ? "Working…" : "Run pipeline"; enabled: !root.busy; onClicked: Store.run() }
    }

    // ── checks ───────────────────────────────────────────────
    Sec { visible: !!root.ch
        title: root.ch ? "Checks for " + F.pad(root.ch.rev) : ""
        note: root.ch ? root.ch.rollup.PASS + " pass · " + root.ch.rollup.WARN + " review · " + root.ch.rollup.FAIL + " fail" : ""
        Column { x: -8; width: parent.width + 16
            Repeater {
                model: root.ch ? root.ch.checks : []
                Rectangle {
                    id: cr
                    required property var modelData
                    required property int index
                    readonly property bool link: !!(modelData.at || modelData.feature)
                    width: parent.width; height: cc.implicitHeight + 18; radius: Theme.rMd
                    color: link && cm.containsMouse ? Qt.rgba(1, 1, 1, 0.045) : "transparent"
                    Rectangle { visible: cr.index > 0; x: 8; width: parent.width - 16; height: 1; color: Theme.rule }
                    Column { id: cc; x: 8; y: 9; width: parent.width - 16; spacing: 5
                        Item { width: parent.width; height: Math.max(lab.implicitHeight, 17)
                            Tag { text: cr.modelData.status; y: 1 }
                            Txt { id: lab; x: 50; width: parent.width - 50 - val.width - 10; text: cr.modelData.label; font.weight: 550 }
                            Txt { id: val; mono: true; anchors.right: parent.right; text: String(cr.modelData.value === undefined || cr.modelData.value === null ? "" : cr.modelData.value)
                                wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, 170); horizontalAlignment: Text.AlignRight } }
                        Tag { x: 50; text: cr.modelData.evidence || ""; visible: text !== "" }
                        Txt { kind: "fine"; x: 50; width: parent.width - 50; text: cr.modelData.detail || ""; visible: text !== "" }
                    }
                    MouseArea { id: cm; anchors.fill: parent; enabled: cr.link; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: Store.marker(cr.modelData) }
                }
            }
        }
    }

    // ── orientation ──────────────────────────────────────────
    Sec { title: "Print orientation"; tag: "computed"; visible: !!root.ch
        Column { x: -8; width: parent.width + 16
            Item { width: parent.width; height: 22
                Txt { kind: "cap"; x: 8; text: "Lay it"; anchors.verticalCenter: parent.verticalCenter }
                Row { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: ["Height", "On plate", "Overhang", "Ceilings"]
                        Txt { required property string modelData; required property int index; kind: "cap"; text: modelData; width: root.colw[index]; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap } } } }
            Repeater {
                model: root.ch ? root.ch.orientation_table : []
                Rectangle {
                    id: orow
                    required property var modelData
                    readonly property bool on: !!root.d && modelData.id === root.d.project.orientation
                    readonly property color ink: on ? Theme.datum : Theme.ink2
                    width: parent.width; height: 30; radius: Theme.rSm
                    color: on ? Theme.alpha(Theme.datum, 0.07) : om.containsMouse ? Qt.rgba(1, 1, 1, 0.045) : "transparent"
                    Rectangle { visible: !orow.on; x: 8; width: parent.width - 16; height: 1; color: Theme.rule }
                    Txt { x: 8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 16 - nums.width - 6
                        text: orow.modelData.label; color: orow.on ? Theme.datum : Theme.ink; font.weight: orow.on ? 600 : 420; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Row { id: nums; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                        Repeater { model: [orow.modelData.height_mm, orow.modelData.contact_mm2, orow.modelData.steep_mm2, orow.modelData.ceiling_mm2]
                            Txt { required property var modelData; required property int index; mono: true; text: F.fmt(modelData, 0); color: orow.ink; width: root.colw[index]; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap } } }
                    MouseArea { id: om; anchors.fill: parent; hoverEnabled: true; cursorShape: orow.on ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: if (!orow.on && !root.busy) Store.settings({ orientation: orow.modelData.id }) }
                    Tip { show: om.containsMouse && !orow.on; text: "Use this orientation (re-exports the STL and re-slices)" }
                }
            }
        }
        OrientFinder {}
        Txt { kind: "fine"; width: parent.width
            text: "Areas in mm², computed from the solid. Overhang is surface steeper than 45°; ceilings are flat faces that must bridge or be supported. Changing orientation makes the exports, checks and slice stale." }
    }

    // ── slice ────────────────────────────────────────────────
    Sec { visible: !!root.sl
        title: root.sl ? "Slice of " + F.pad(root.sl.rev) : ""; tag: "simulated"
        Row { width: parent.width; topPadding: 4; bottomPadding: 2
            Repeater {
                model: root.sl ? [
                    { big: F.dur(root.sl.time_s), small: "estimated print time" },
                    { big: F.fmt(root.sl.filament_g, 1) + " g", small: F.fmt(root.sl.filament_mm / 1000, 1) + " m filament" },
                    { big: String(root.sl.layers), small: "layers to " + F.fmt(root.sl.max_z_mm, 1) + " mm" }] : []
                Column { required property var modelData; width: parent.width / 3; spacing: 3
                    Txt { mono: true; font.pixelSize: 16; font.weight: 600; text: modelData.big; width: parent.width - 8; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Txt { kind: "fine"; text: modelData.small; width: parent.width - 8 } }
            }
        }
        Column { width: parent.width
            KV { k: "Supports generated"; value: root.sl ? (root.sl.support_used ? "yes" : "none") : "" }
            KV { k: "Presets"
                Column { spacing: 2; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: root.sl ? F.vals(root.sl.presets) : []
                        Txt { required property var modelData; kind: "fine"; tone: 2; text: modelData.name; width: 250; horizontalAlignment: Text.AlignRight
                            wrapMode: Text.NoWrap; elide: Text.ElideLeft } } } }
            KV { k: "Slicer"; value: root.sl ? (root.sl.slicer_name || "Bambu Studio") + " " + root.sl.slicer_version + " · " + root.sl.seconds + "s" : "" }
        }
        Txt { kind: "fine"; width: parent.width
            visible: !!root.sl && (root.sl.plate_warnings || []).length > 0
            text: root.sl ? "Slicer notes: " + root.uniq(root.sl.plate_warnings || []).join(", ") : "" }
        Item { id: plate
            visible: !!root.sl && (root.sl.images || []).indexOf("plate_1.png") >= 0
            width: parent.width
            height: visible ? (img.status === Image.Ready ? Math.round(width * img.sourceSize.height / img.sourceSize.width) : Math.round(width * 0.75)) : 0
            Rectangle { id: mask; anchors.fill: parent; radius: Theme.rMd; visible: false; layer.enabled: true }
            Rectangle { anchors.fill: parent; radius: Theme.rMd; color: Theme.well }
            Image { id: img; anchors.fill: parent; asynchronous: true; fillMode: Image.PreserveAspectFit; mipmap: true
                source: plate.visible && root.sn ? Store.file("slice/current/plate_1.png") + "?k=" + root.sn.key : ""
                layer.enabled: true
                layer.effect: MultiEffect { maskEnabled: true; maskSource: mask } }
            Rectangle { anchors.fill: parent; radius: Theme.rMd; color: "transparent"; border.width: 1; border.color: Theme.rule2 }
        }
        Txt { kind: "fine"; visible: plate.visible; text: "Plate preview rendered by " + ((root.sl && root.sl.slicer_name) || "Bambu Studio") + "." }
        Row { spacing: 8; topPadding: 2
            Btn { icon: Store.layers ? "arrow_left" : "layers"; text: Store.layers ? "Back to 3D" : "Inspect layers"; onClicked: Store.showLayers(!Store.layers) }
            Btn { kind: "quiet"; icon: "download"; text: "Save sliced 3MF…"; visible: !!root.sl && !!root.sl.threemf
                onClicked: { save.selectedFile = Bridge.downloads() + "/" + root.sl.threemf; save.open() } } }
        Txt { kind: "fine"; width: parent.width
            text: "A slice shows the toolpaths " + ((root.sl && root.sl.slicer_name) || "Bambu Studio") + " would send with these presets. It is not a print: adhesion, warping and fit are only known after printing." }
    }

    // ── slice: not current ───────────────────────────────────
    Sec { title: "Slice"; visible: !root.sl
        Note { kind: "red"; visible: !!root.sn && !!root.sn.unavailable; title: "Blocked"; text: root.sn && root.sn.unavailable ? String(root.sn.unavailable) : "" }
        Note { kind: "amber"; visible: !(root.sn && root.sn.unavailable)
            title: root.sliceFailed && root.sn.error ? root.sn.error.message : ""
            text: !root.sn ? "Not sliced yet."
                : root.sliceFailed ? (root.sn.error && root.sn.error.hint || "")
                : root.sn.state === "stale" ? "The last slice was of " + F.pad(root.sn.last_rev) + "; it does not describe " + root.head + "."
                : "Not sliced yet." }
        Btn { icon: "layers"; text: root.busy ? "Working…" : root.sliceFailed ? "Try again" : "Slice now"
            enabled: !root.busy && !(root.sn && root.sn.unavailable)
            onClicked: Store.run(["geometry", "exports", "checks", "slice"], root.sliceFailed) }
    }

    FileDialog {
        id: save
        title: "Save sliced 3MF"; fileMode: FileDialog.SaveFile; nameFilters: ["3MF (*.3mf)"]; defaultSuffix: "3mf"
        currentFolder: Bridge.downloads()
        onAccepted: {
            if (Bridge.save("/projects/" + Store.pid + "/file/slice/current/" + root.sl.threemf, selectedFile)) Bridge.reveal(selectedFile)
            else Store.toast("The sliced 3MF could not be saved.", "Check that the folder is writable and try again.", true)
        }
    }
}
