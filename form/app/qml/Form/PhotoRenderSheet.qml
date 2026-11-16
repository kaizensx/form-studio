import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Render: the current revision's STL in Blender, headless, under a studio preset with a filament material.
// An illustration, never evidence. Cached per geometry and settings; a new revision makes old renders stale.
Column {
    id: rs
    property string title: "Render"
    property int sheetWidth: 1120
    property var st: null                  // engine: blender, presets, finishes, swatches, layer, latest, current
    property string preset: "studio"
    property string finish: "matte"
    property string color: "#eeece6"
    property bool layerLines: true
    property bool fast: false
    property var shown: null               // the render on screen
    property string jobId: ""
    property real progress: 0
    property string progressText: ""
    property var error: null
    readonly property bool busy: jobId !== ""
    readonly property bool ready: !!st && st.blender.available
    readonly property var current: st ? st.current : []
    spacing: 14; bottomPadding: 20

    function url(key) { return Bridge.baseUrl + "/api/projects/" + Store.pid + "/photo/" + key + ".png" }
    function load(first) {
        return Store.pget("/photo").then(function (s) {
            st = s
            if (first && s.latest) {
                shown = s.latest; preset = s.latest.preset; finish = s.latest.finish; color = s.latest.color
                layerLines = !!(s.latest.layer && s.latest.layer.mm) || !s.layer.mm; fast = s.latest.engine === "BLENDER_EEVEE"
            } else if (first) color = s.default_color
        }, Store.fail)
    }
    // props (optional): { preset, finish, color, fast, start: true } — open with settings chosen, and render at once
    Component.onCompleted: load(true).then(function () {
        var o = Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
        if (o.preset) preset = o.preset
        if (o.finish) finish = o.finish
        if (o.color) color = o.color
        if (o.fast !== undefined) fast = !!o.fast
        if (o.start && ready) go()
    })
    function go() {
        error = null; progress = 0; progressText = "Starting Blender"
        Store.ppost("/render_photo", { preset: preset, finish: finish, color: color, fast: fast, layer_lines: layerLines }).then(function (r) {
            if (r.render) { shown = r.render; load(false); return }
            jobId = r.job; poll.restart()
        }, function (e) { error = e })
    }
    Timer {
        id: poll; interval: 350; repeat: true
        onTriggered: Store.pget("/job/" + rs.jobId).then(function (j) {
            rs.progress = j.progress || 0; rs.progressText = j.text || ""
            if (j.state === "running") return
            poll.stop(); rs.jobId = ""
            if (j.state === "done") { rs.shown = j.result; rs.load(false) }
            else rs.error = j.error || { message: "The render failed." }
        }, function (e) { poll.stop(); rs.jobId = ""; rs.error = e })
    }

    Note { visible: !!rs.st && !rs.ready; kind: "amber"; title: "Blender is not available"
        text: rs.st ? rs.st.blender.reason + " Everything else in FORM works without it." : "" }

    Row {
        width: parent.width; spacing: 22
        // ── left: what to render ──────────────────────────
        Column {
            id: ctl; width: 290; spacing: 0
            Sec { title: "Scene"; topPadding: 0
              Column { width: ctl.width; spacing: 6
                Repeater {
                    model: rs.st ? rs.st.presets : []
                    Rectangle {
                        id: pc
                        required property var modelData
                        readonly property bool on: rs.preset === modelData.id
                        width: ctl.width; height: 48; radius: Theme.rMd
                        color: on ? Theme.plate3 : pm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
                        border.color: on ? Theme.alpha(Theme.datum, 0.45) : Theme.rule
                        // a small picture of the light: backdrop tone and where the key light sits
                        Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 40; height: 32; radius: Theme.rSm; clip: true
                            gradient: Gradient {
                                GradientStop { position: 0; color: pc.modelData.id === "dark" ? "#2a3136" : pc.modelData.id === "desk" ? "#a07a55" : "#d9d8d4" }
                                GradientStop { position: 1; color: pc.modelData.id === "dark" ? "#0f1215" : pc.modelData.id === "desk" ? "#6b4a2c" : "#a9a9a6" } }
                            Rectangle { x: 13; y: 11; width: 14; height: 12; radius: 3; color: rs.color; border.color: Qt.rgba(0, 0, 0, 0.25) } }
                        Column { x: 58; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 66; spacing: 1
                            Txt { text: pc.modelData.label; font.weight: 600; tone: pc.on ? 1 : 2 }
                            Txt { kind: "fine"; text: pc.modelData.note; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                        MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; enabled: !rs.busy; cursorShape: Qt.PointingHandCursor
                            onClicked: rs.preset = pc.modelData.id }
                    }
                }
              }
            }
            Sec { title: "Filament"; note: "invented, for the picture"
                Seg { model: rs.st ? rs.st.finishes.map(function (f) { return { value: f.id, text: f.label } }) : []
                    value: rs.finish; onPicked: function (v) { if (!rs.busy) rs.finish = v } }
                Flow { width: ctl.width; spacing: 5
                    Repeater {
                        model: rs.st ? rs.st.swatches : []
                        Rectangle {
                            id: sw
                            required property var modelData
                            readonly property bool on: rs.color === modelData.hex
                            width: 22; height: 22; radius: 11; color: modelData.hex
                            border.width: on ? 2 : 1; border.color: on ? Theme.datum : Qt.rgba(1, 1, 1, 0.16)
                            MouseArea { id: sm; anchors.fill: parent; anchors.margins: -2; hoverEnabled: true; enabled: !rs.busy
                                cursorShape: Qt.PointingHandCursor; onClicked: rs.color = sw.modelData.hex }
                            Tip { show: sm.containsMouse; text: sw.modelData.name }
                        }
                    }
                }
            }
            Sec { title: "Options"
                Row { spacing: 10; width: ctl.width
                    Check { checked: rs.layerLines; enabled: !!rs.st && !!rs.st.layer.mm; anchors.verticalCenter: parent.verticalCenter
                        onToggled: function (c) { rs.layerLines = c } }
                    Column { width: parent.width - 26; spacing: 1
                        Row { spacing: 6
                            Txt { text: "Layer lines"; tone: rs.st && rs.st.layer.mm ? 1 : 3 }
                            Txt { visible: !!rs.st && !!rs.st.layer.mm; mono: true; text: rs.st && rs.st.layer.mm ? F.fmt(rs.st.layer.mm, 2) + " mm" : "" }
                            Tag { visible: !!rs.st && !!rs.st.layer.mm; text: "specified"; anchors.verticalCenter: parent.verticalCenter } }
                        Txt { kind: "fine"; width: parent.width; text: rs.st ? (rs.st.layer.mm ? "From the " + rs.st.layer.note : "Off: " + rs.st.layer.note) : "" } } }
                Row { spacing: 10; width: ctl.width
                    Check { checked: rs.fast; anchors.verticalCenter: parent.verticalCenter; onToggled: function (c) { rs.fast = c } }
                    Column { width: parent.width - 26; spacing: 1
                        Txt { text: "Fast preview" }
                        Txt { kind: "fine"; width: parent.width; text: "EEVEE instead of Cycles: seconds, softer shadows." } } }
            }
            Item { width: 1; height: 18 }
            Btn { text: rs.busy ? "Rendering…" : "Render"; kind: "primary"; icon: "camera"; enabled: rs.ready && !rs.busy; onClicked: rs.go() }
            Item { width: 1; height: 10 }
            Column { visible: rs.busy; width: ctl.width; spacing: 6
                Rectangle { width: parent.width; height: 4; radius: 2; color: Theme.well
                    Rectangle { width: Math.max(4, parent.width * rs.progress); height: parent.height; radius: 2; color: Theme.datum
                        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } } } }
                Txt { kind: "fine"; text: rs.progressText; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
            Note { visible: !!rs.error; kind: "red"; width: ctl.width; title: rs.error ? rs.error.message : ""; text: rs.error ? (rs.error.hint || "") : ""
                Txt { visible: !!(rs.error && rs.error.log); width: parent.width; mono: true; font.pixelSize: 10; tone: 3; maximumLineCount: 8; elide: Text.ElideLeft
                    text: rs.error && rs.error.log ? rs.error.log.split("\n").slice(-8).join("\n") : "" } }
        }

        // ── right: the picture ────────────────────────────
        Column {
            width: parent.width - ctl.width - parent.spacing; spacing: 10
            Rectangle {
                width: parent.width; height: Math.round(width * 3 / 4); radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
                Image { id: img; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true; asynchronous: true
                    source: rs.shown ? rs.url(rs.shown.key) : ""; opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } } }
                Column { anchors.centerIn: parent; spacing: 8; visible: !rs.shown
                    Icon { name: "camera"; size: 26; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
                    Txt { tone: 3; text: rs.ready ? "Pick a scene and a filament, then Render." : "No render yet."; anchors.horizontalCenter: parent.horizontalCenter } }
                Rectangle { visible: rs.busy && !!rs.shown; anchors.fill: parent; color: Theme.alpha(Theme.plate, 0.45) }
                // the label travels with the picture
                Rectangle { visible: !!rs.shown && img.status === Image.Ready; anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 10
                    width: lb.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.alpha(Theme.plate, 0.78)
                    Txt { id: lb; anchors.centerIn: parent; font.pixelSize: 11; tone: 2; text: rs.st ? rs.st.label : "" } }
            }
            Item { width: parent.width; height: 28; visible: !!rs.shown
                Column { anchors.verticalCenter: parent.verticalCenter; width: parent.width - saveBtn.width - 12; spacing: 1
                    Txt { width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.weight: 550
                        text: rs.shown ? F.pad(rs.shown.rev) + " · " + rs.shown.preset_label + " · " + rs.shown.finish_label + " " + rs.shown.color.toUpperCase() : "" }
                    Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                        text: rs.shown ? (rs.shown.engine === "CYCLES" ? "Cycles" : "EEVEE") + " on " + rs.shown.device + " · " + rs.shown.samples + " samples · Blender " + rs.shown.blender
                                         + (rs.shown.seconds ? " · " + F.fmt(rs.shown.seconds, 0) + " s" : "") + (rs.shown.layer && rs.shown.layer.mm ? " · layer lines " + F.fmt(rs.shown.layer.mm, 2) + " mm" : "") : "" } }
                Btn { id: saveBtn; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "Save PNG…"; icon: "download"
                    onClicked: { dlg.currentFolder = Bridge.downloads(); dlg.selectedFile = Bridge.downloads() + "/" + Store.pid + "_" + F.pad(rs.shown.rev) + "_" + rs.shown.preset + ".png"; dlg.open() } } }
            // other renders of this revision
            Row { spacing: 8; visible: rs.current.length > 1
                Repeater {
                    model: rs.current.slice(0, 8)
                    Rectangle {
                        id: th
                        required property var modelData
                        width: 72; height: 54; radius: Theme.rSm; color: Theme.well; clip: true
                        border.width: rs.shown && rs.shown.key === modelData.key ? 2 : 1
                        border.color: rs.shown && rs.shown.key === modelData.key ? Theme.datum : Theme.rule
                        Image { anchors.fill: parent; anchors.margins: 2; source: rs.url(th.modelData.key); fillMode: Image.PreserveAspectCrop; sourceSize.width: 160; asynchronous: true }
                        MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rs.shown = th.modelData }
                        Tip { show: tm.containsMouse; text: th.modelData.preset_label + " · " + th.modelData.finish_label }
                    }
                }
            }
            Txt { kind: "fine"; width: parent.width; visible: !!rs.st && rs.st.stale > 0
                text: F.plural(rs.st ? rs.st.stale : 0, "older render") + " of earlier geometry kept on disk; they no longer show this design." }
        }
    }

    FileDialog {
        id: dlg
        title: "Save the render"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PNG image (*.png)"]
        onAccepted: {
            if (Bridge.save("/projects/" + Store.pid + "/photo/" + rs.shown.key + ".png", selectedFile)) Bridge.reveal(selectedFile)
            else Store.toast("Could not save the render", "Check the folder is writable and try again.", true)
        }
    }
}
