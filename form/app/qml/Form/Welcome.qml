import QtQuick
import QtQuick.Controls
import FormNative

// First run: three short steps instead of one long list. 1 Form Studio itself, 2 your printer and slicer, 3 your agent:
// a choice between the agent apps found here, model provider APIs (keys found or added) and local models.
// A hands-free setup starts by itself (Store.autoSetup, form/installer.py AutoJob): what Form Studio needs is installed
// with every command in the log, and it pauses only where the person must act. Optional items stay ticks. The step you reached is remembered in the data folder. Afterwards you land on Home.
Rectangle {
    id: wl
    color: Theme.plate
    readonly property var sw: Store.software
    readonly property int step: Store.onboardStep
    readonly property var steps: [
        { title: "Form Studio itself", sub: "The CAD kernel and where your designs live", ids: ["kernel", "data", "parts"] },
        { title: "Your printer and slicer", sub: "So a design can be sliced for your machine", ids: ["slicer.bambu", "slicer.orca", "slicer.prusa"] },
        { title: "Your agent", sub: "Who designs with you in chat", ids: ["claude", "claude.signin", "agent.claude", "agent.codex", "agent.gemini", "agent.cursor", "agent.desktop"] }
    ]
    readonly property var here: steps[step]
    // ticked rows of this step only
    readonly property var chosen: Store.installChosen.filter(function (id) { return wl.here.ids.indexOf(id) >= 0 })
    readonly property bool anySlicer: !!sw && ["slicer.bambu", "slicer.orca", "slicer.prusa"].some(function (id) { var it = Store.softwareItem(id); return it && it.status === "ok" })
    readonly property bool designOnly: !!Store.studio && !!Store.studio.env.slicing && Store.studio.env.slicing.why === "settings"
    readonly property var absentAgents: sw ? sw.software.filter(function (r) { return r.absent }).map(function (r) { return r.label.replace("Form Studio tools in ", "") }) : []
    function stepState(i) {          // done | todo | open — for the rail
        if (!sw) return "open"
        var need = steps[i].ids.map(function (id) { return Store.softwareItem(id) }).filter(function (r) {
            return r && !r.absent && r.level !== "optional" && r.status !== "ok" && r.status !== "info" })
        if (i === 1) return wl.anySlicer || wl.designOnly ? "done" : "todo"
        if (i === 2) return Store.chat.available ? "done" : "todo"
        return need.length ? "todo" : "done"
    }
    function stepNote(i) {
        if (!sw) return "Checking…"
        if (i === 1) return wl.anySlicer ? "A slicer is ready" : wl.designOnly ? "Design only" : "No slicer yet"
        if (i === 2) { var n = Store.chatAgents.filter(function (a) { return a.available }).length
                       return n ? n + (n === 1 ? " agent ready" : " agents ready") : "Choose one" }
        var rows = steps[i].ids.map(function (id) { return Store.softwareItem(id) }).filter(function (r) { return r && !r.absent && r.status !== "info" })
        var ok = rows.filter(function (r) { return r.status === "ok" }).length
        return ok + " of " + rows.length + " ready"
    }
    function go(n) { Store.setOnboardStep(n) }
    // step 3: which way to reach a model is shown; it starts on the first one that has something ready
    function agentsOf(way) {
        return Store.chatAgents.filter(function (a) {
            return way === "cli" ? a.kind !== "api" : way === "local" ? a.kind === "api" && a.local : a.kind === "api" && !a.local })
    }
    property string way: ""
    readonly property var missingApps: sw ? ["claude", "codex", "gemini"].filter(function (id) { var r = Store.softwareItem(id); return r && r.status !== "ok" }) : []
    readonly property string firstWay: ["cli", "api", "local"].filter(function (w) { return wl.agentsOf(w).some(function (a) { return a.available }) })[0] || "cli"
    onFirstWayChanged: if (!wl.picked) wl.way = wl.firstWay
    property bool picked: false
    onWayChanged: if (wl.way !== wl.firstWay) wl.picked = true
    Component.onCompleted: { wl.way = wl.firstWay; wl.loadKeys() }
    property var keys: []
    function loadKeys() { Store.get("/secrets").then(function (r) { wl.keys = r.keys }, function () {}) }
    function keyFor(name) { for (var i = 0; i < wl.keys.length; i++) if (wl.keys[i].name === name) return wl.keys[i]; return null }
    function saveKey(name, value) {
        return Store.post("/secrets", { name: name, value: value }).then(function (r) {
            wl.keys = r.keys; Store.toast(r.key.label + " saved", "Kept in a private file on this computer and sent only to its provider.")
            Store.refreshAgents() }, Store.fail) }
    function clearKey(name) {
        return Store.post("/secrets", { name: name, clear: true }).then(function (r) { wl.keys = r.keys; Store.refreshAgents() }, Store.fail) }
    // each step arrives the same way: the page fades in and settles upward
    onStepChanged: { fl.contentY = 0; arrive.restart() }
    ParallelAnimation { id: arrive
        Glide { target: body; property: "opacity"; from: 0; to: 1; duration: Theme.slow }
        Glide { target: bodyShift; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } }
    function primary() {
        if (wl.chosen.length) Store.installSoftware(wl.chosen)
        else if (wl.step < 2) wl.go(wl.step + 1)
        else Store.closeWelcome("done")
    }
    MouseArea { anchors.fill: parent; hoverEnabled: true; onWheel: function (w) { w.accepted = true } }     // Home underneath stays inert

    // ── progress rail ────────────────────────────────────────
    Rectangle {
        id: rail
        width: 320; height: parent.height; color: Theme.plate1
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.rule }
        Column { x: 32; y: 44; width: parent.width - 64; spacing: 6
            Logo { size: 24 }
            Item { width: 1; height: 22 }
            Txt { kind: "cap"; text: "Set up Form Studio" }
            Txt { kind: "h2"; text: "Three short steps"; width: parent.width }
            Item { width: 1; height: 18 }
            Repeater {
                model: wl.steps
                Item {
                    id: rs
                    required property var modelData
                    required property int index
                    readonly property bool current: index === wl.step
                    readonly property string state_: wl.stepState(index)
                    width: parent.width; height: 74
                    Rectangle { visible: rs.index < 2; x: 12; y: 30; width: 2; height: 44; radius: 1
                        color: rs.state_ === "done" ? Theme.alpha(Theme.pass, 0.5) : Theme.rule2
                        Behavior on color { ColorAnimation { duration: Theme.slow } } }
                    Rectangle { width: 26; height: 26; radius: 13
                        color: rs.state_ === "done" ? Theme.alpha(Theme.pass, 0.16) : rs.current ? Theme.datum : Theme.plate3
                        border.width: rs.current && rs.state_ === "done" ? 1 : 0; border.color: Theme.pass
                        Behavior on color { ColorAnimation { duration: Theme.slow } }
                        Icon { visible: rs.state_ === "done"; anchors.centerIn: parent; name: "check"; size: 14; color: Theme.pass }
                        Txt { visible: rs.state_ !== "done"; anchors.centerIn: parent; mono: true; font.pixelSize: 12; text: rs.index + 1
                            color: rs.current ? Theme.datumInk : Theme.ink3 } }
                    Column { x: 40; y: 3; width: parent.width - 40; spacing: 2
                        Txt { text: rs.modelData.title; font.weight: rs.current ? Theme.wSemi : Theme.wMedium; tone: rs.current ? 1 : 2; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; text: wl.stepNote(rs.index); wrapMode: Text.NoWrap
                            color: rs.state_ === "done" ? Theme.pass : rs.state_ === "todo" && rs.index < wl.step ? Theme.amber : Theme.ink3 } }
                    Rectangle { x: -10; y: -8; width: parent.width + 20; height: 54; radius: Theme.rMd; z: -1; color: sm.pressed ? Theme.washPress : sm.containsMouse && !rs.current ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                    MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; enabled: !Store.installing; onClicked: wl.go(rs.index) }
                }
            }
        }
        Column { x: 32; anchors.bottom: parent.bottom; anchors.bottomMargin: 28; width: parent.width - 64; spacing: 6
            Icon { name: "shield_check"; size: 16; color: Theme.ink3 }
            Txt { kind: "fine"; width: parent.width
                text: "Form Studio installs what it needs by itself and pauses only when you have to sign in or download something. Every command is in the log; Cancel stops it. It never asks for a password." } }
    }

    // ── the step ────────────────────────────────────────────
    Flickable {
        id: fl
        anchors.left: rail.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: logBox.top
        contentHeight: body.implicitHeight + 88; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: body
            width: Math.min(680, fl.width - 96); x: Math.max(48, (fl.width - width) / 2); y: 52
            spacing: 20
            transform: Translate { id: bodyShift }
            Column { width: parent.width; spacing: 8
                Txt { kind: "cap"; text: "Step " + (wl.step + 1) + " of 3" }
                Txt { kind: "h1"; text: wl.here.title; width: parent.width; font.weight: Theme.wSemi }
                Txt { kind: "lead"; tone: 2; width: parent.width; lineHeight: 1.35
                    text: wl.step === 0 ? "Form Studio builds real geometry with a CAD kernel and keeps every design in a folder you own. This is checked for you."
                        : wl.step === 1 ? "A slicer turns a design into a print plan. Form Studio drives one that is installed here and reads the printer, filament and process selected in it."
                        : "Chat works with the agent you choose. Each one designs with Form Studio's tools and runs on your own account or computer. You can change it per conversation." } }

            // step 1: a checklist that fills in as each part answers
            Column { visible: wl.step === 0; width: parent.width; spacing: 16
                Rectangle { width: parent.width; height: cl.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Column { id: cl; width: parent.width
                        Repeater {
                            model: wl.step === 0 ? ["kernel", "data", "parts"] : []
                            Item {
                                id: ck
                                required property var modelData
                                required property int index
                                readonly property var r: Store.softwareItem(modelData)
                                // the kernel row waits for the real kernel to answer (GET /setup), not only for the files
                                readonly property var live: modelData === "kernel" ? Store.setupItem("kernel") : null
                                readonly property bool ok: !!r && r.status === "ok" && (modelData !== "kernel" || (!!live && live.status === "ok"))
                                readonly property bool pending: !r || (modelData === "kernel" && !live)
                                property bool shownOk: false
                                onOkChanged: if (ok) tick.restart(); else shownOk = false
                                Component.onCompleted: if (ok) tick.restart()
                                SequentialAnimation { id: tick
                                    PauseAnimation { duration: 180 + ck.index * 260 }
                                    ScriptAction { script: ck.shownOk = true }
                                    Glide { target: mark; property: "scale"; from: Theme.from(0.6); to: 1; duration: Theme.cross } }
                                width: cl.width; height: 62
                                Rectangle { visible: ck.index > 0; width: parent.width; height: 1; color: Theme.rule }
                                Item { x: 18; width: 22; height: 22; anchors.verticalCenter: parent.verticalCenter
                                    Rectangle { anchors.fill: parent; radius: 11; color: "transparent"; border.width: 2
                                        border.color: ck.shownOk ? Theme.pass : (!ck.pending && !ck.ok) ? Theme.amber : Theme.rule2
                                        Behavior on border.color { ColorAnimation { duration: Theme.slow } } }
                                    Icon { id: mark; visible: ck.shownOk; anchors.centerIn: parent; name: "check"; size: 13; color: Theme.pass }
                                    Spinner { visible: !ck.shownOk && (ck.pending || ck.ok); anchors.centerIn: parent; size: 12; color: Theme.ink3; running: visible && wl.step === 0 } }
                                Column { x: 56; width: parent.width - 56 - 120; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                    Txt { text: ck.r ? ck.r.label : ({ kernel: "CAD kernel", data: "Project folder", parts: "Standard-parts libraries" })[ck.modelData]; font.weight: 600 }
                                    Txt { kind: "fine"; tone: 2; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                                        text: ck.pending ? (ck.modelData === "kernel" ? "Starting the kernel… this takes a few seconds the first time" : "Checking…")
                                            : ck.live && ck.live.status === "ok" ? ck.live.detail : ck.live ? ck.live.detail : ck.r.status === "ok" ? ck.r.detail : ck.r.why } }
                                Txt { anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; kind: "fine"
                                    text: ck.shownOk ? "ready" : ck.pending || ck.ok ? "checking" : ck.r.level === "required" ? "needs attention" : "not installed"
                                    color: ck.shownOk ? Theme.pass : ck.pending || ck.ok ? Theme.ink3 : Theme.amber }
                            }
                        }
                    } }
                // only what is not ready gets the full row with its command
                SetupList { width: parent.width; visible: rows.length > 0
                    ids: wl.sw ? ["kernel", "data", "parts"].filter(function (id) { var r = Store.softwareItem(id); return r && r.status !== "ok" }) : [] }
                Row { spacing: 10
                    Icon { name: "folder_open"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; elide: Text.ElideMiddle; width: Math.min(implicitWidth, body.width - 30)
                        text: "Designs are kept in " + Bridge.dataDirShort + "  ·  change it later in Settings" } }
            }

            // step 2: slicer and printer
            Column { visible: wl.step === 1; width: parent.width; spacing: 16
                Rectangle { visible: wl.anySlicer && Store.slicer.available; width: parent.width; height: uc.implicitHeight + 28; radius: Theme.rMd
                    color: Theme.alpha(Theme.pass, 0.06); border.color: Theme.alpha(Theme.pass, 0.25)
                    Column { id: uc; x: 16; y: 14; width: parent.width - 32; spacing: 4
                        Row { spacing: 8
                            Icon { name: "printer"; size: 15; color: Theme.pass; anchors.verticalCenter: parent.verticalCenter }
                            Txt { font.weight: 600; text: "Form Studio will slice with " + (Store.slicer.label || "your slicer"); anchors.verticalCenter: parent.verticalCenter } }
                        Txt { kind: "fine"; tone: 2; width: parent.width
                            text: Store.slicer.available ? Store.slicer.presets.machine.name + "  ·  " + Store.slicer.presets.filament.name + "  ·  " + Store.slicer.presets.process.name : "" }
                        Txt { kind: "fine"; width: parent.width; text: "Read from what is selected in the slicer. Change the printer or filament there and Form Studio follows." } } }
                Txt { visible: !!wl.sw && !wl.anySlicer; width: parent.width; tone: 2
                    text: "No slicer was found. Pick the one that matches your printer; Bambu Studio is ticked because it is Form Studio's default. Everything except slicing also works without one." }
                // Design only: design, check, export and release without any slicer (it can be turned on later in Settings)
                Rectangle { visible: !!wl.sw && !wl.anySlicer; width: parent.width; height: dc.implicitHeight + 28; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    readonly property bool off: wl.designOnly
                    Column { id: dc; x: 16; y: 14; width: parent.width - 32; spacing: 8
                        Txt { font.weight: 600; text: parent.parent.off ? "Design only is on" : "Only designing for now?" }
                        Txt { kind: "fine"; tone: 2; width: parent.width
                            text: "Design only: no slicer is installed or used. Designs, checks, STEP, STL and 3MF exports, renders and releases all work; a release says it was not sliced. Turn slicing on any time in Settings." }
                        Btn { objectName: "welcomeDesignOnly"; text: parent.parent.off ? "Slice designs after all" : "Design only, no slicer"
                            icon: parent.parent.off ? "layers" : "pencil"; enabled: !Store.installing || !parent.parent.off
                            onClicked: Store.designOnlyEverywhere(!parent.parent.off) } } }
                SetupList { width: parent.width; ids: ["slicer.bambu", "slicer.orca", "slicer.prusa"] }
                // no slicer: the bed size is the one thing FORM still needs to know
                Rectangle { visible: !!wl.sw && !wl.anySlicer; width: parent.width; height: bc.implicitHeight + 28; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Column { id: bc; x: 16; y: 14; width: parent.width - 32; spacing: 10
                        Txt { font.weight: 600; text: "Or tell Form Studio your printer's size" }
                        Txt { kind: "fine"; tone: 2; width: parent.width
                            text: "Without a slicer Form Studio still checks that a part fits the bed. With a slicer, the printer selected there is used instead." }
                        Row { spacing: 8
                            Field { id: pn; width: 220; placeholder: "Printer name"; text: Store.studio ? Store.studio.env.printer.name : "" }
                            Field { id: px; width: 78; numeric: true; unit: "X"; text: Store.studio ? String(Store.studio.env.printer.envelope_mm[0]) : "" }
                            Field { id: py; width: 78; numeric: true; unit: "Y"; text: Store.studio ? String(Store.studio.env.printer.envelope_mm[1]) : "" }
                            Field { id: pz; width: 78; numeric: true; unit: "Z"; text: Store.studio ? String(Store.studio.env.printer.envelope_mm[2]) : "" }
                            Txt { kind: "fine"; text: "mm"; anchors.verticalCenter: parent.verticalCenter }
                            Btn { text: "Save size"; anchors.verticalCenter: parent.verticalCenter
                                onClicked: Store.saveConfig({ "printer.name": pn.text, "printer.envelope_mm": [Number(px.text), Number(py.text), Number(pz.text)] }) } } } }
            }

            // step 3: the agent: three ways to reach a model, with what was found for each
            Column { visible: wl.step === 2; width: parent.width; spacing: 16
                Row { id: ways; width: parent.width; spacing: 10
                    Repeater {
                        model: [{ id: "cli", icon: "monitor", title: "An agent app", sub: "Claude Code, Codex, Gemini CLI and others, on their own accounts" },
                                { id: "api", icon: "globe", title: "A model API", sub: "Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek or Groq, with your key" },
                                { id: "local", icon: "cuboid", title: "A local model", sub: "Ollama, LM Studio or llama.cpp on this computer" }]
                        Rectangle {
                            id: way
                            required property var modelData
                            readonly property bool on: wl.way === modelData.id
                            readonly property var found: wl.agentsOf(modelData.id).filter(function (a) { return a.available })
                            objectName: "agentWay_" + modelData.id
                            width: (ways.width - 20) / 3; height: wc.implicitHeight + 26; radius: Theme.rMd
                            color: on ? Theme.alpha(Theme.datum, 0.07) : wm.containsMouse ? Theme.washHover : Theme.plate1
                            border.color: on ? Theme.datum : Theme.rule; border.width: on ? 1.5 : 1
                            Behavior on color { Tint {} }
                            Column { id: wc; x: 14; y: 13; width: parent.width - 28; spacing: 4
                                Row { spacing: 8
                                    Icon { name: way.modelData.icon; size: 15; color: way.on ? Theme.datum : Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                                    Txt { text: way.modelData.title; font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter } }
                                Txt { kind: "fine"; tone: 2; width: parent.width; text: way.modelData.sub }
                                Txt { kind: "fine"; width: parent.width; color: way.found.length ? Theme.pass : Theme.ink3
                                    text: way.found.length ? "Found: " + way.found.map(function (a) { return a.label }).join(", ") : "None found yet" } }
                            MouseArea { id: wm; anchors.fill: parent; hoverEnabled: true; onClicked: wl.way = way.modelData.id }
                        }
                    }
                }
                // an agent app: what is installed, and the installs and sign-ins for the ones Form Studio can set up
                Column { visible: wl.way === "cli"; width: parent.width; spacing: 16
                    Rectangle { visible: wcli.children.length > 1; width: parent.width; height: wcli.implicitHeight; radius: Theme.rMd
                        color: Theme.plate1; border.color: Theme.rule
                        Column { id: wcli; width: parent.width
                            Repeater {
                                model: wl.step === 2 && wl.way === "cli" ? wl.agentsOf("cli").filter(function (a) { return a.available }) : []
                                AgentRow { width: wcli.width; a: modelData; first: index === 0
                                    required property var modelData
                                    required property int index } } } }
                    Txt { visible: wl.sw && wl.missingApps.length > 0; kind: "cap"; text: "Agent apps Form Studio can install" }
                    SetupList { width: parent.width; visible: wl.missingApps.length > 0; ids: wl.missingApps }
                    ClaudeSignIn { width: parent.width; visible: !!Store.softwareItem("claude") && Store.softwareItem("claude").status === "ok" }
                    Column { width: parent.width; spacing: 6; visible: others.rows.length > 0
                        Txt { kind: "cap"; text: "Form Studio's tools in your agents" }
                        Txt { kind: "fine"; width: parent.width; text: "So the agent can also use Form Studio from its own window or a terminal." }
                        SetupList { id: others; width: parent.width; ids: ["agent.claude", "agent.codex", "agent.gemini", "agent.cursor", "agent.desktop"] } }
                    Txt { kind: "fine"; width: parent.width; visible: wl.absentAgents.length > 0
                        text: "Not found here: " + wl.absentAgents.join(", ") + ". If you install one later, add Form Studio to it under Settings, Software." } }
                // a model API: keys found in the environment, or added here
                Column { visible: wl.way === "api"; width: parent.width; spacing: 10
                    Txt { kind: "fine"; tone: 2; width: parent.width
                        text: "Form Studio talks to the provider directly, with its own tools. Usage is billed to your account with that provider. A key you add is kept in a private file on this computer and sent only to its provider." }
                    Rectangle { width: parent.width; height: wapi.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                        Column { id: wapi; width: parent.width
                            Repeater {
                                model: wl.step === 2 && wl.way === "api" ? wl.agentsOf("api") : []
                                AgentRow { width: wapi.width; a: modelData; first: index === 0; k: wl.keyFor(modelData.key || "")
                                    required property var modelData
                                    required property int index
                                    onSaveKey: function (v) { wl.saveKey(modelData.key, v) }
                                    onClearKey: wl.clearKey(modelData.key) } } } } }
                // a local model: servers found on their usual ports
                Column { visible: wl.way === "local"; width: parent.width; spacing: 10
                    Item { width: parent.width; height: 28
                        Txt { kind: "fine"; tone: 2; width: parent.width - 130; anchors.verticalCenter: parent.verticalCenter
                            text: "Nothing leaves this computer. Start the server with a model that supports tool calls, then look again." }
                        Btn { small: true; kind: "quiet"; icon: "refresh_cw"; text: "Look again"; busy: Store.agentsChecking; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter; onClicked: Store.refreshAgents() } }
                    Rectangle { width: parent.width; height: wloc.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                        Column { id: wloc; width: parent.width
                            Repeater {
                                model: wl.step === 2 && wl.way === "local" ? wl.agentsOf("local") : []
                                AgentRow { width: wloc.width; a: modelData; first: index === 0
                                    required property var modelData
                                    required property int index } } } } }
            }
        }
    }
    // the live log stays in view above the button, closed until asked for
    Rectangle {
        id: logBox
        anchors.bottom: bar.top; anchors.left: rail.right; anchors.right: parent.right
        height: lg.visible ? lg.implicitHeight + 20 : 0; color: Theme.plate
        Rectangle { visible: lg.visible; width: parent.width; height: 1; color: Theme.rule }
        InstallLog { id: lg; x: body.x; y: 10; width: body.width }
    }

    // ── one primary button per step ───────────────────────────
    Rectangle {
        id: bar
        anchors.bottom: parent.bottom; anchors.left: rail.right; anchors.right: parent.right; height: 68; color: Theme.plate
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Item { width: body.width; x: body.x; height: 32; anchors.verticalCenter: parent.verticalCenter
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Btn { kind: "quiet"; icon: "arrow_left"; text: "Back"; visible: wl.step > 0; enabled: !Store.installing; onClicked: wl.go(wl.step - 1) }
                Btn { kind: "quiet"; text: "Skip setup"; enabled: !Store.installing; tip: "You can run it again from the command palette"
                    onClicked: Store.closeWelcome("skipped") } }
            Row { spacing: 10; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; visible: !Store.installing && wl.chosen.length > 0
                    text: "Untick everything to continue without installing" }
                Btn { visible: Store.installing; large: true; icon: "x"; text: Store.installJob && Store.installJob.kind === "auto" ? "Cancel setup" : "Cancel install"; onClicked: Store.cancelInstall() }
                Btn { kind: "primary"; large: true; busy: Store.installing || !wl.sw
                    icon: wl.chosen.length ? "download" : wl.step < 2 ? "arrow_right" : "check"
                    text: Store.installing ? (Store.installJob && Store.installJob.kind === "auto" ? "Setting up…" : "Installing…") : !wl.sw ? "Checking…" : wl.chosen.length ? "Install " + wl.chosen.length + " selected"
                        : wl.step < 2 ? "Continue" : "Open Form Studio"
                    onClicked: wl.primary() } }
        }
    }
}
