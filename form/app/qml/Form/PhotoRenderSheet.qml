import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Render: the current revision's STL in Blender, headless, under a studio preset with a filament material.
// An illustration, never evidence. Cached per geometry and settings; a new revision makes old renders stale.
Column {
    id: rs
    objectName: "renderSheet"
    property string title: "Render"
    property string note: "An illustration of the current revision, never evidence"
    property int sheetWidth: Theme.sheetXl
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
    property bool starting: false          // between pressing Render and the engine's answer
    readonly property bool busy: jobId !== "" || starting
    readonly property bool ready: !!st && st.blender.available
    readonly property var current: st ? st.current : []
    // the picture is 4:3 and gives way to a short window, so Render never scrolls out of reach
    readonly property int picMax: Math.max(260, (Window.height > 0 ? Window.height : 900) - 88 - 58 - 60 - 28 - 52 - (current.length > 1 ? 68 : 0) - (st && !ready ? 80 : 0))
    spacing: 14

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
        if (!ready || busy) return
        error = null; progress = 0; progressText = "Starting Blender"; starting = true
        Store.ppost("/render_photo", { preset: preset, finish: finish, color: color, fast: fast, layer_lines: layerLines }).then(function (r) {
            starting = false
            if (r.render) { shown = r.render; load(false); return }
            jobId = r.job; poll.restart()
        }, function (e) { starting = false; error = e })
    }
    function savePng() {
        if (!shown) return
        dlg.currentFolder = Bridge.downloads(); dlg.selectedFile = Bridge.downloads() + "/" + Store.pid + "_" + F.pad(shown.rev) + "_" + shown.preset + ".png"; Store.ask(dlg)
    }
    function accept() { go() }
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

    // the action bar: progress while Blender works, otherwise what the picture on screen is
    property Component footerLeft: Item { height: 28
        Row { visible: rs.busy; spacing: 12; anchors.verticalCenter: parent.verticalCenter
            Rectangle { width: 180; height: 4; radius: 2; color: Theme.well; anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: Math.max(4, parent.width * rs.progress); height: parent.height; radius: 2; color: Theme.datum
                    Behavior on width { Glide { duration: Theme.move(200) } } } }
            Txt { kind: "fine"; mono: true; text: Math.round(rs.progress * 100) + " %"; width: 34; horizontalAlignment: Text.AlignRight; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter }
            Txt { kind: "fine"; text: rs.progressText; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter } }
        Txt { visible: !rs.busy; kind: "fine"; width: parent.width; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap
            color: rs.st && !rs.ready ? Theme.amber : Theme.ink3
            text: !rs.st ? "Looking for Blender…" : !rs.ready ? "Blender is not available. Nothing can be rendered."
                : rs.fast ? "Fast preview: EEVEE, a few seconds." : "Cycles. Cached per geometry and settings." } }
    property Component footer: Row { spacing: 8
        Btn { text: "Save PNG…"; icon: "download"; enabled: !!rs.shown; onClicked: rs.savePng() }
        Btn { kind: "primary"; icon: "camera"; text: rs.busy ? "Rendering…" : rs.shown ? "Render again" : "Render"; busy: rs.busy; enabled: rs.ready; keys: "Return"; onClicked: rs.go() } }

    Note { visible: !!rs.st && !rs.ready; kind: "amber"; title: "Blender is not available"
        text: rs.st ? rs.st.blender.reason + " Everything else in FORM works without it." : "" }

    Row {
        width: parent.width; spacing: 24
        // ── left: what to render ──────────────────────────
        Column {
            id: ctl; width: 280; spacing: 18
            Row { visible: !rs.st; spacing: 8; height: 28
                Spinner { anchors.verticalCenter: parent.verticalCenter }
                Txt { tone: 2; text: "Reading the scenes…"; anchors.verticalCenter: parent.verticalCenter } }
            Column { width: parent.width; spacing: 8; visible: !!rs.st
                Txt { kind: "cap"; text: "Scene" }
                Column { width: ctl.width; spacing: 4
                    Repeater {
                        model: rs.st ? rs.st.presets : []
                        Rectangle {
                            id: pc
                            required property var modelData
                            readonly property bool on: rs.preset === modelData.id
                            width: ctl.width; height: Math.max(48, pcc.implicitHeight + 16); radius: Theme.rMd
                            color: on ? Theme.alpha(Theme.datum, 0.07) : pm.pressed ? Theme.washPress : pm.containsMouse ? Theme.washHover : "transparent"
                            border.color: on ? Theme.alpha(Theme.datum, 0.5) : pm.containsMouse ? Theme.rule2 : Theme.rule
                            opacity: rs.busy && !on ? 0.5 : 1
                            Behavior on color { Tint {} }
                            // a small picture of the light: backdrop tone and where the key light sits (scene colours, not interface colours)
                            Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 40; height: 32; radius: Theme.rXs; clip: true
                                gradient: Gradient {
                                    GradientStop { position: 0; color: pc.modelData.id === "dark" ? "#2a3136" : pc.modelData.id === "desk" ? "#a07a55" : "#d9d8d4" }
                                    GradientStop { position: 1; color: pc.modelData.id === "dark" ? "#0f1215" : pc.modelData.id === "desk" ? "#6b4a2c" : "#a9a9a6" } }
                                Rectangle { x: 13; y: 11; width: 14; height: 12; radius: 3; color: rs.color; border.color: Theme.shade } }
                            Column { id: pcc; x: 58; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 66 - 22; spacing: 1
                                Txt { text: pc.modelData.label; font.weight: Theme.wSemi; tone: pc.on ? 1 : 2 }
                                Txt { kind: "fine"; text: pc.modelData.note; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight } }
                            Icon { visible: pc.on; name: "check"; size: 14; color: Theme.datum; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter }
                            MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; enabled: !rs.busy
                                onClicked: rs.preset = pc.modelData.id }
                        }
                    }
                }
            }
            Column { width: parent.width; spacing: 8; visible: !!rs.st
                Item { width: parent.width; height: fcap.implicitHeight
                    Txt { id: fcap; kind: "cap"; text: "Filament" }
                    Txt { kind: "fine"; text: "invented, for the picture"; anchors.right: parent.right; anchors.baseline: fcap.baseline } }
                Seg { model: rs.st ? rs.st.finishes.map(function (f) { return { value: f.id, text: f.label } }) : []
                    value: rs.finish; enabled: !rs.busy; onPicked: function (v) { if (!rs.busy) rs.finish = v } }
                Flow { width: ctl.width + 4; x: -2; spacing: 2
                    Repeater {
                        model: rs.st ? rs.st.swatches : []
                        Item {
                            id: sw
                            required property var modelData
                            readonly property bool on: rs.color === modelData.hex
                            width: 26; height: 26
                            // the ring sits outside the colour, so a pale swatch still reads as chosen
                            Rectangle { anchors.fill: parent; radius: 13; color: "transparent"; border.width: 2; border.color: Theme.datum; opacity: sw.on ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
                            Rectangle { anchors.centerIn: parent; width: 18; height: 18; radius: 9; color: sw.modelData.hex
                                border.width: 1; border.color: Theme.rule3
                                scale: sm.pressed ? Theme.from(0.9) : sm.containsMouse && !sw.on ? Theme.from(1.12) : 1
                                Behavior on scale { Glide { duration: Theme.press } } }
                            MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; enabled: !rs.busy; onClicked: rs.color = sw.modelData.hex }
                            Tip { show: sm.containsMouse; text: sw.modelData.name }
                        }
                    }
                }
            }
            Column { width: parent.width; spacing: 10; visible: !!rs.st
                Txt { kind: "cap"; text: "Options" }
                Item { width: ctl.width; height: lcol.implicitHeight
                    Check { y: 1; checked: rs.layerLines; enabled: !!rs.st && !!rs.st.layer.mm && !rs.busy; onToggled: function (c) { rs.layerLines = c } }
                    Column { id: lcol; x: 26; width: parent.width - 26; spacing: 1
                        Row { spacing: 6
                            Txt { text: "Layer lines"; tone: rs.st && rs.st.layer.mm ? 1 : 3 }
                            Txt { visible: !!rs.st && !!rs.st.layer.mm; mono: true; text: rs.st && rs.st.layer.mm ? F.fmt(rs.st.layer.mm, 2) + " mm" : "" }
                            Tag { visible: !!rs.st && !!rs.st.layer.mm; text: "specified"; anchors.verticalCenter: parent.verticalCenter } }
                        Txt { kind: "fine"; width: parent.width; text: rs.st ? (rs.st.layer.mm ? "From the " + rs.st.layer.note : "Off: " + rs.st.layer.note) : "" } }
                    MouseArea { x: 20; width: parent.width - 20; height: parent.height; enabled: !!rs.st && !!rs.st.layer.mm && !rs.busy; onClicked: rs.layerLines = !rs.layerLines } }
                Item { width: ctl.width; height: fcol.implicitHeight
                    Check { y: 1; checked: rs.fast; enabled: !rs.busy; onToggled: function (c) { rs.fast = c } }
                    Column { id: fcol; x: 26; width: parent.width - 26; spacing: 1
                        Txt { text: "Fast preview" }
                        Txt { kind: "fine"; width: parent.width; text: "EEVEE instead of Cycles: seconds, softer shadows." } }
                    MouseArea { x: 20; width: parent.width - 20; height: parent.height; enabled: !rs.busy; onClicked: rs.fast = !rs.fast } }
            }
            Note { visible: !!rs.error; kind: "red"; width: ctl.width; title: rs.error ? rs.error.message : ""; text: rs.error ? (rs.error.hint || "") : ""
                Txt { visible: !!(rs.error && rs.error.log); width: parent.width; mono: true; font.pixelSize: 10; tone: 3; maximumLineCount: 8; elide: Text.ElideLeft
                    text: rs.error && rs.error.log ? rs.error.log.split("\n").slice(-8).join("\n") : "" } }
        }

        // ── right: the picture ────────────────────────────
        Column {
            id: pic
            width: parent.width - ctl.width - parent.spacing; spacing: 12
            Rectangle {
                width: parent.width; height: Math.min(Math.round(width * 3 / 4), rs.picMax); radius: Theme.rMd; color: Theme.well; border.color: Theme.rule; clip: true
                Image { id: img; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true; asynchronous: true
                    source: rs.shown ? rs.url(rs.shown.key) : ""; opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.base; easing.type: Easing.OutCubic } } }
                // empty, and the first render in progress
                Column { anchors.centerIn: parent; spacing: 8; visible: !rs.shown
                    Spinner { visible: rs.busy || !rs.st; size: 20; anchors.horizontalCenter: parent.horizontalCenter }
                    Icon { visible: !rs.busy && !!rs.st; name: "camera"; size: 26; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
                    Txt { tone: 2; anchors.horizontalCenter: parent.horizontalCenter
                        text: !rs.st ? "Looking for Blender…" : rs.busy ? "Rendering in Blender…" : rs.ready ? "No render of this revision yet." : "No render yet." }
                    Txt { kind: "fine"; visible: !!rs.st && !rs.busy && rs.ready; anchors.horizontalCenter: parent.horizontalCenter; text: "Pick a scene and a filament, then Render." } }
                // a new render over the old one
                Rectangle { anchors.fill: parent; color: Theme.alpha(Theme.plate, 0.5); opacity: rs.busy && !!rs.shown ? 1 : 0; visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                    Spinner { anchors.centerIn: parent; size: 20; running: parent.visible } }
                // the label travels with the picture
                Rectangle { visible: !!rs.shown && img.status === Image.Ready; anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 10
                    width: lb.implicitWidth + 16; height: 24; radius: Theme.rSm; color: Theme.alpha(Theme.plate, 0.78)
                    Txt { id: lb; anchors.centerIn: parent; kind: "fine"; tone: 2; text: rs.st ? rs.st.label : "" } }
            }
            Column { width: parent.width; spacing: 2; visible: !!rs.shown
                Row { spacing: 8
                    Txt { mono: true; font.weight: Theme.wMedium; text: rs.shown ? F.pad(rs.shown.rev) : "" }
                    Txt { font.weight: Theme.wMedium; wrapMode: Text.NoWrap
                        text: rs.shown ? rs.shown.preset_label + " · " + rs.shown.finish_label : "" }
                    Txt { mono: true; tone: 2; text: rs.shown ? rs.shown.color.toUpperCase() : "" } }
                Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: rs.shown ? (rs.shown.engine === "CYCLES" ? "Cycles" : "EEVEE") + " on " + rs.shown.device + " · " + rs.shown.samples + " samples · Blender " + rs.shown.blender
                                     + (rs.shown.seconds ? " · " + F.fmt(rs.shown.seconds, 0) + " s" : "") + (rs.shown.layer && rs.shown.layer.mm ? " · layer lines " + F.fmt(rs.shown.layer.mm, 2) + " mm" : "") : "" } }
            // other renders of this revision
            Row { spacing: 8; visible: rs.current.length > 1
                Repeater {
                    model: rs.current.slice(0, 8)
                    Rectangle {
                        id: th
                        required property var modelData
                        readonly property bool on: !!rs.shown && rs.shown.key === modelData.key
                        width: 72; height: 54; radius: Theme.rSm; color: Theme.well; clip: true
                        border.width: on ? 2 : 1
                        border.color: on ? Theme.datum : tm.containsMouse ? Theme.rule3 : Theme.rule
                        scale: tm.pressed ? Theme.from(0.97) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        Image { anchors.fill: parent; anchors.margins: 2; source: rs.url(th.modelData.key); fillMode: Image.PreserveAspectCrop; sourceSize.width: 160; asynchronous: true
                            opacity: th.on || tm.containsMouse ? 1 : 0.75; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
                        MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; onClicked: rs.shown = th.modelData }
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
