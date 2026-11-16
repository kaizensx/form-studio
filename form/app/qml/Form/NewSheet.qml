import QtQuick
import QtQuick.Dialogs
import FormNative

// Start a design from a built-in recipe, from a guided brief (a template whose answers go to Claude), or restore a
// saved .formproj. Open on a tab with Store.openSheet("new", { tab: "brief", preset: "remote-holder", answers: {...} }).
Column {
    id: ns
    property string title: "New design"
    property int sheetWidth: 720
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    property string tab: props.tab || "recipe"
    property string pickId: Store.studio && Store.studio.recipes.length ? Store.studio.recipes[0].id : ""
    // ── brief tab state ──
    property var presets: []
    property string presetId: props.preset || ""
    property var answers: props.answers || ({})
    property bool measured: !!props.measured
    property bool sending: false
    readonly property var preset: { for (var i = 0; i < presets.length; i++) if (presets[i].id === presetId) return presets[i]; return null }
    readonly property var missing: preset ? preset.questions.filter(function (q) { return q.required && !String(answers[q.key] || "").trim() }) : []
    spacing: 12; bottomPadding: 20
    Component.onCompleted: Store.get("/presets").then(function (r) { ns.presets = r.presets }, Store.fail)

    function chosen() { var r = Store.studio.recipes; for (var i = 0; i < r.length; i++) if (r[i].id === pickId) return r[i]; return null }
    function setAnswer(k, v) { var o = Object.assign({}, answers); o[k] = v; answers = o }
    function startBrief(then) {
        sending = true
        Store.post("/briefs", { preset: presetId, answers: answers, measured: measured }).then(function (r) {
            sending = false; then(r)
        }, function (e) { sending = false; Store.fail(e) })
    }
    function ask() { startBrief(function (r) { Store.openSheet(null); Store.send(r.prompt) }) }
    function copy() { startBrief(function (r) { Bridge.copy(r.prompt); Store.toast("Prompt copied", "Paste it into any agent that has FORM's MCP tools.") }) }
    function envLine(e) { return e.setting + " · humidity " + e.humidity + " · UV " + e.uv }

    Seg { model: [{ value: "recipe", text: "Start from a recipe" }, { value: "brief", text: "Start from a brief" }]
        value: ns.tab; onPicked: function (v) { ns.tab = v } }

    // ── recipe ──────────────────────────────────────────────
    Column { width: parent.width; spacing: 12; visible: ns.tab === "recipe"
        Txt { tone: 2; width: parent.width; text: "Recipes are parametric designs with real engineering checks. For anything else, describe it to Claude and it writes the design as code." }
        Grid { width: parent.width; columns: 2; spacing: 8
            Repeater { model: Store.studio ? Store.studio.recipes : []
                Rectangle { id: rc; required property var modelData
                    width: (ns.width - 8) / 2; height: 62; radius: Theme.rMd
                    color: ns.pickId === modelData.id ? Theme.alpha(Theme.datum, 0.08) : rm.containsMouse ? Theme.plate3 : Theme.plate1
                    border.color: ns.pickId === modelData.id ? Theme.alpha(Theme.datum, 0.6) : Theme.rule
                    Column { x: 12; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 24; spacing: 2
                        Txt { text: rc.modelData.title; font.weight: 600 }
                        Txt { kind: "fine"; text: rc.modelData.summary || ""; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                    MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; onClicked: ns.pickId = rc.modelData.id } } } }
        Field { id: name; width: parent.width; placeholder: "Name, e.g. “Hallway phone dock”" }
        Area { id: brief; width: parent.width; minLines: 2; placeholder: "What is it for? (optional; you can write this later)" }
        Row { spacing: 8
            Btn { kind: "primary"; text: "Create"; icon: "plus"; enabled: ns.pickId !== ""
                onClicked: Store.create(name.text.trim() || (ns.chosen() ? ns.chosen().title : "Design"), ns.pickId, brief.text) }
            Btn { kind: "quiet"; text: "Restore a .formproj…"; icon: "upload"; onClicked: dlg.open() } }
        Txt { kind: "fine"; width: parent.width; text: "FORM works from a written brief, dimensions you measure, and reference photos with a marked scale. It does not reconstruct geometry from photos or scans." }
    }

    // ── brief: pick a template ──────────────────────────────
    Column { width: parent.width; spacing: 12; visible: ns.tab === "brief" && !ns.preset
        Txt { tone: 2; width: parent.width; text: "Answer the few questions that decide fit, material and mounting. Claude designs it from your answers and asks only for what is still missing." }
        Grid { width: parent.width; columns: 2; spacing: 8
            Repeater { model: ns.presets
                Rectangle { id: pc; required property var modelData
                    width: (ns.width - 8) / 2; height: 94; radius: Theme.rMd
                    color: pm.containsMouse ? Theme.plate3 : Theme.plate1; border.color: Theme.rule
                    Column { x: 12; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 24; spacing: 2
                        Txt { text: pc.modelData.title; font.weight: 600 }
                        Txt { kind: "fine"; text: pc.modelData.summary; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight }
                        Txt { kind: "fine"; tone: 3; text: pc.modelData.questions.length + " questions · starts from " + pc.modelData.material.suggested; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                    MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; onClicked: { ns.presetId = pc.modelData.id; ns.answers = ({}) } } } } }
        Txt { kind: "fine"; width: parent.width; visible: ns.presets.length === 0; text: "Loading templates…" }
    }

    // ── brief: guided form ──────────────────────────────────
    Column { width: parent.width; spacing: 12; visible: ns.tab === "brief" && !!ns.preset
        Row { spacing: 8; x: -8
            Btn { kind: "quiet"; small: true; icon: "arrow_left"; text: "All templates"; onClicked: ns.presetId = "" } }
        Column { width: parent.width; spacing: 2
            Txt { kind: "lead"; text: ns.preset ? ns.preset.title : ""; font.weight: 600 }
            Txt { tone: 2; width: parent.width; text: ns.preset ? ns.preset.summary : "" } }

        Sec { title: "Your answers"; note: "* needed"
            Column { width: parent.width
                Repeater { model: ns.preset ? ns.preset.questions : []
                    Item { id: qr; required property var modelData; required property int index
                        readonly property bool wide: modelData.kind === "text"
                        width: parent.width; implicitHeight: (wide ? ql.implicitHeight + 6 + qf.height : Math.max(ql.implicitHeight, 28)) + 14
                        Rectangle { visible: qr.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Column { id: ql; y: 8; width: qr.wide ? parent.width : parent.width - 232; spacing: 1
                            Txt { text: qr.modelData.label + (qr.modelData.required ? " *" : ""); font.weight: 600; width: parent.width }
                            Txt { kind: "fine"; text: qr.modelData.why; width: parent.width } }
                        Field { id: qf; visible: qr.modelData.kind !== "choice"
                            x: qr.wide ? 0 : parent.width - 220; y: qr.wide ? ql.y + ql.implicitHeight + 6 : 8; width: qr.wide ? parent.width : 220
                            numeric: qr.modelData.kind === "number"; unit: qr.modelData.unit || ""
                            placeholder: qr.modelData.placeholder || (qr.modelData.kind === "number" ? "not known yet" : "")
                            Component.onCompleted: text = ns.answers[qr.modelData.key] !== undefined ? String(ns.answers[qr.modelData.key]) : ""
                            onEdited: function (t) { ns.setAnswer(qr.modelData.key, t) } }
                        Pick { visible: qr.modelData.kind === "choice"; x: parent.width - 220; y: 8; width: 220
                            model: [{ value: "", text: "Choose…" }].concat((qr.modelData.choices || []).map(function (c) { return { value: c, text: c } }))
                            value: ns.answers[qr.modelData.key] || ""
                            onPicked: function (v) { ns.setAnswer(qr.modelData.key, v) } } } } }
            Item { width: parent.width; implicitHeight: Math.max(mt.implicitHeight, 16) + 6
                Check { id: mc; y: 3; checked: ns.measured; onToggled: function (c) { ns.measured = c } }
                Column { id: mt; x: 26; y: 2; width: parent.width - 26; spacing: 1
                    Txt { text: "I measured these numbers"; font.weight: 600 }
                    Txt { kind: "fine"; width: parent.width; text: "With calipers or a ruler on the real object. Otherwise they are carried as assumed until you confirm." } }
                MouseArea { x: 20; width: parent.width - 20; height: parent.height; onClicked: ns.measured = !ns.measured } } }

        Note { visible: !Store.chat.available; kind: "amber"; title: "Claude is not connected"
            text: (Store.chat.note || "") + " You can copy the prompt and paste it into any agent that has FORM's tools." }
        Txt { kind: "fine"; width: parent.width; visible: ns.missing.length > 0; color: Theme.amber
            text: "Still needed: " + ns.missing.map(function (q) { return q.label }).join(", ") + "." }
        Row { spacing: 8
            Btn { kind: "primary"; icon: "message_square"; text: ns.sending ? "Sending…" : "Ask Claude to design it"
                enabled: !!ns.preset && ns.missing.length === 0 && !ns.sending && Store.chat.available && !Store.chatBusy
                tip: Store.chatBusy ? "Claude is still answering the previous message" : ""
                onClicked: ns.ask() }
            Btn { kind: "quiet"; icon: "copy"; text: "Copy the prompt"; enabled: !!ns.preset && ns.missing.length === 0 && !ns.sending
                onClicked: ns.copy() } }
        Txt { kind: "fine"; width: parent.width
            text: "Your answers are saved with the project when Claude creates it. Nothing is printed or uploaded." }

        Sec { title: "Template defaults"; tag: "assumed"
            Txt { kind: "fine"; width: parent.width; text: "Claude starts from these and corrects them from your answers. Tell it where they are wrong." }
            Column { width: parent.width; visible: !!ns.preset
                KV { first: true; k: "Environment"; sub: ns.preset ? ns.envLine(ns.preset.environment) : ""
                    value: ns.preset ? ns.preset.environment.temperature_c[0] + " to " + ns.preset.environment.temperature_c[1] + " °C" : "" }
                KV { k: "Load"; sub: ns.preset ? ns.preset.environment.load.note : ""
                    value: ns.preset ? ns.preset.environment.load.kind + " · about " + ns.preset.environment.load.mass_g + " g" : "" }
                KV { k: "Material to start from"; sub: ns.preset ? ns.preset.material.why : ""; value: ns.preset ? ns.preset.material.suggested : "" } } }

        Sec { title: "Checks to plan for"; note: ns.preset ? ns.preset.checks.length + " · not run yet" : ""
            Column { width: parent.width; spacing: 4
                Repeater { model: ns.preset ? ns.preset.checks : []
                    Txt { required property var modelData; kind: "fine"; width: parent.width
                        text: "<b>" + modelData.name + "</b> — " + modelData.why; textFormat: Text.StyledText } } } }
    }

    FileDialog { id: dlg; title: "Restore a FORM project"; nameFilters: ["FORM projects (*.formproj *.zip)"]; onAccepted: Store.importArchive(selectedFile) }
}
