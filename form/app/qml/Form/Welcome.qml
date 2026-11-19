import QtQuick
import QtQuick.Controls
import FormNative

// First run, a launcher in three steps: 1 "What do you want to make?" (capability cards, form/capabilities.py, with a
// live download total), 2 your agent (agent apps, model provider APIs, local models), 3 an install run of only what
// was chosen (form/installer.py AutoJob: every command in the log; it pauses only where the person must act).
// Nothing is installed before step 3. 3D printing is optional and off unless it is ticked. The step reached is
// remembered in the data folder; everything can be changed later in Settings › General › Set up for.
Rectangle {
    id: wl
    color: Theme.plate
    readonly property var sw: Store.software
    readonly property int step: Store.onboardStep
    readonly property var steps: [
        { title: "What do you want to make?", sub: "Choose what to set up" },
        { title: "Your agent", sub: "Who designs with you in chat" },
        { title: "Set up", sub: "Only what you chose is downloaded" }
    ]
    readonly property var here: steps[step]
    readonly property var agentIds: ["claude", "claude.signin", "agent.claude", "codex", "gemini", "agent.codex", "agent.gemini", "agent.cursor", "agent.desktop"]

    // step 1: the cards' local pick, from the engine until the person changes it
    property var pick: []
    property bool picked: false
    readonly property var caps: Store.caps ? Store.caps.capabilities : []
    Connections { target: Store; function onCapsChanged() { if (!wl.picked && Store.caps) wl.pick = Store.caps.chosen.slice() } }
    function toggle(id, on) {
        var p = wl.pick.filter(function (x) { return x !== id })
        if (on) p.push(id)
        wl.pick = p; wl.picked = true
    }
    function mb(n) { return n >= 1000 ? "about " + (n / 1000).toFixed(1) + " GB" : "about " + n + " MB" }
    readonly property int pickMb: wl.caps.filter(function (c) { return wl.pick.indexOf(c.id) >= 0 }).reduce(function (a, c) { return a + c.size_mb }, 0)

    // step 3: what the run installs: what the chosen capabilities need, plus the agent apps ticked in step 2
    readonly property var capInstall: Store.caps ? Store.caps.install : []
    readonly property var agentInstall: Store.installChosen.filter(function (id) { return wl.agentIds.indexOf(id) >= 0 && wl.capInstall.indexOf(id) < 0 })
    readonly property var runIds: wl.capInstall.concat(wl.agentInstall)
    readonly property var runRows: wl.runIds.map(function (id) { return Store.softwareItem(id) }).filter(function (r) { return !!r })
    readonly property int runMb: wl.runRows.reduce(function (a, r) { var m = /([\d.]+)\s*(MB|GB)/i.exec(r.size || ""); return a + (m ? Number(m[1]) * (m[2].toUpperCase() === "GB" ? 1000 : 1) : 0) }, 0)
    readonly property bool ran: !!Store.installJob && Store.installJob.kind === "auto" && Store.installJob.state !== "running"
    Connections { target: Store; function onInstallingChanged() { if (!Store.installing) Store.loadCaps() } }

    function stepState(i) {          // done | todo | open — for the rail
        if (!sw || !Store.caps) return "open"
        if (i === 0) return Store.caps.decided ? "done" : "todo"
        if (i === 1) return Store.chat.available ? "done" : "todo"
        return wl.runIds.length ? "todo" : "done"
    }
    function stepNote(i) {
        if (!sw || !Store.caps) return "Checking…"
        if (i === 0) { var on = wl.caps.filter(function (c) { return wl.pick.indexOf(c.id) >= 0 }).length
                       return on + " of " + wl.caps.length + " chosen" + (wl.pick.indexOf("print") >= 0 ? " · with 3D printing" : "") }
        if (i === 1) { var n = Store.chatAgents.filter(function (a) { return a.available }).length
                       return n ? n + (n === 1 ? " agent ready" : " agents ready") : "Choose one" }
        return wl.runIds.length ? wl.runIds.length + (wl.runIds.length === 1 ? " item to install" : " items to install") : "Everything is ready"
    }
    function go(n) { Store.setOnboardStep(n) }
    // step 2: which way to reach a model is shown; it starts on the first one that has something ready
    function agentsOf(way) {
        return Store.chatAgents.filter(function (a) {
            return way === "cli" ? a.kind !== "api" : way === "local" ? a.kind === "api" && a.local : a.kind === "api" && !a.local })
    }
    property string way: ""
    readonly property var missingApps: sw ? ["claude", "codex", "gemini"].filter(function (id) { var r = Store.softwareItem(id); return r && r.status !== "ok" }) : []
    readonly property string firstWay: ["cli", "api", "local"].filter(function (w) { return wl.agentsOf(w).some(function (a) { return a.available }) })[0] || "cli"
    onFirstWayChanged: if (!wl.wayPicked) wl.way = wl.firstWay
    property bool wayPicked: false
    onWayChanged: if (wl.way !== wl.firstWay) wl.wayPicked = true
    readonly property var absentAgents: sw ? sw.software.filter(function (r) { return r.absent }).map(function (r) { return r.label.replace("Form Studio tools in ", "") }) : []
    Component.onCompleted: { wl.way = wl.firstWay; wl.loadKeys(); if (!Store.caps) Store.loadCaps(); else wl.pick = Store.caps.chosen.slice(); if (wl.step >= 1) wl.untickOthers() }
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
    onStepChanged: { fl.contentY = 0; arrive.restart(); if (step === 1) wl.untickOthers() }
    // other agents' settings are never edited without a click: their integrations start unticked here
    property bool othersUnticked: false
    function untickOthers() {
        if (wl.othersUnticked) return
        wl.othersUnticked = true
        var p = Object.assign({}, Store.installPick)
        ;["agent.codex", "agent.gemini", "agent.cursor", "agent.desktop"].forEach(function (id) { p[id] = false })
        Store.installPick = p
    }
    ParallelAnimation { id: arrive
        Glide { target: body; property: "opacity"; from: 0; to: 1; duration: Theme.slow }
        Glide { target: bodyShift; property: "y"; from: Theme.shift(10); to: 0; duration: Theme.slow } }
    function primary() {
        if (wl.step === 0) { Store.setCaps(wl.pick).then(function (r) { if (r) wl.go(1) }); return }
        if (wl.step === 1) { wl.go(2); return }
        if (wl.runIds.length && !wl.ran) Store.runSetup(wl.runIds)
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
            Txt { kind: "h2"; text: "Describe it. Form Studio engineers it."; width: parent.width; wrapMode: Text.WordWrap }
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
                    // forward only through Continue, so the choice of step 1 is always saved first
                    MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; enabled: !Store.installing && rs.index <= wl.step; onClicked: wl.go(rs.index) }
                }
            }
        }
        Column { x: 32; anchors.bottom: parent.bottom; anchors.bottomMargin: 28; width: parent.width - 64; spacing: 6
            Icon { name: "shield_check"; size: 16; color: Theme.ink3 }
            Txt { kind: "fine"; width: parent.width
                text: "Nothing is downloaded until the last step, and only what you chose. Every command is in the log; Cancel stops it. Form Studio never asks for a password." } }
    }

    // ── the step ────────────────────────────────────────────
    Flickable {
        id: fl
        anchors.left: rail.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: logBox.top
        contentHeight: body.implicitHeight + 88; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: body
            width: Math.min(720, fl.width - 96); x: Math.max(48, (fl.width - width) / 2); y: 52
            spacing: 20
            transform: Translate { id: bodyShift }
            Column { width: parent.width; spacing: 8
                Txt { kind: "cap"; text: "Step " + (wl.step + 1) + " of 3" }
                Txt { kind: "h1"; text: wl.here.title; width: parent.width; font.weight: Theme.wSemi }
                Txt { kind: "lead"; tone: 2; width: parent.width; lineHeight: 1.35
                    text: wl.step === 0 ? "Describe a part, a product or a mechanism and Form Studio engineers it as real, editable CAD. Pick what to set up; only that is downloaded, and you can change it any time in Settings."
                        : wl.step === 1 ? "Chat works with the agent you choose. Each one designs with Form Studio's tools and runs on your own account or computer. You can change it per conversation."
                        : "This installs only what you chose, one item after another, with every command in the log. It stops only where you need to sign in or download something yourself." } }

            // step 1: what do you want to make? capability cards, a live download total
            Column { visible: wl.step === 0; width: parent.width; spacing: 14
                CapCards { width: parent.width; pick: wl.pick; onToggled: function (id, on) { wl.toggle(id, on) } }
                Rectangle { objectName: "welcomeDownloadTotal"; width: parent.width; height: 44; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Row { x: 16; spacing: 10; anchors.verticalCenter: parent.verticalCenter
                        Icon { name: "cloud_download"; size: 15; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                        Txt { font.weight: Theme.wMedium; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                            text: !Store.caps ? "Looking at what is installed…" : wl.pickMb > 0 ? "To download: " + wl.mb(wl.pickMb) : "Nothing to download: what you chose is here" } }
                    Txt { kind: "fine"; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                        text: "Agents are the next step" } }
                Row { spacing: 10
                    Icon { name: "folder_open"; size: 14; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; elide: Text.ElideMiddle; width: Math.min(implicitWidth, body.width - 30)
                        text: "Designs are kept in " + Bridge.dataDirShort + "  ·  change it later in Settings" } }
            }

            // step 2: the agent: three ways to reach a model, with what was found for each
            Column { visible: wl.step === 1; width: parent.width; spacing: 16
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
                // an agent app: what is installed, and the agent apps Form Studio can install in the last step
                Column { visible: wl.way === "cli"; width: parent.width; spacing: 16
                    Rectangle { visible: wcli.children.length > 1; width: parent.width; height: wcli.implicitHeight; radius: Theme.rMd
                        color: Theme.plate1; border.color: Theme.rule
                        Column { id: wcli; width: parent.width
                            Repeater {
                                model: wl.step === 1 && wl.way === "cli" ? wl.agentsOf("cli").filter(function (a) { return a.available }) : []
                                AgentRow { width: wcli.width; a: modelData; first: index === 0
                                    required property var modelData
                                    required property int index } } } }
                    Txt { visible: wl.sw && wl.missingApps.length > 0; kind: "cap"; text: "Agent apps Form Studio can install" }
                    Txt { visible: wl.sw && wl.missingApps.length > 0; kind: "fine"; width: parent.width; text: "Tick the ones you want; they are installed in the last step with the rest." }
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
                                model: wl.step === 1 && wl.way === "api" ? wl.agentsOf("api") : []
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
                                model: wl.step === 1 && wl.way === "local" ? wl.agentsOf("local") : []
                                AgentRow { width: wloc.width; a: modelData; first: index === 0
                                    required property var modelData
                                    required property int index } } } } }
            }

            // step 3: the install run of only what was chosen
            Column { visible: wl.step === 2; width: parent.width; spacing: 14
                Rectangle { objectName: "welcomeInstallList"; width: parent.width; height: il.implicitHeight; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
                    Column { id: il; width: parent.width
                        Item { visible: wl.runRows.length === 0; width: parent.width; height: 62
                            Icon { x: 18; name: "circle_check"; size: 18; color: Theme.pass; anchors.verticalCenter: parent.verticalCenter }
                            Column { x: 50; width: parent.width - 68; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                Txt { font.weight: Theme.wSemi; text: "Everything you chose is ready" }
                                Txt { kind: "fine"; tone: 2; width: parent.width; text: "Nothing to download. Open Form Studio and describe what you want to make." } } }
                        Repeater {
                            model: wl.step === 2 ? wl.runRows : []
                            Item {
                                id: ir
                                required property var modelData
                                required property int index
                                readonly property var st: Store.installStep(modelData.id)
                                width: il.width; height: 58
                                Rectangle { visible: ir.index > 0; width: parent.width; height: 1; color: Theme.rule }
                                Item { x: 18; width: 18; height: 18; anchors.verticalCenter: parent.verticalCenter
                                    Icon { visible: !!ir.st && ir.st.state === "done"; anchors.centerIn: parent; name: "circle_check"; size: 16; color: Theme.pass }
                                    Spinner { visible: !!ir.st && (ir.st.state === "running" || ir.st.state === "needs_user"); anchors.centerIn: parent; size: 12 }
                                    Rectangle { visible: !ir.st || ["waiting", "failed", "skipped", "cancelled"].indexOf(ir.st.state) >= 0; anchors.centerIn: parent; width: 8; height: 8; radius: 4
                                        color: ir.st && ir.st.state === "failed" ? Theme.signal : Theme.ink3 } }
                                Column { x: 50; width: parent.width - 50 - 140; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                    Txt { text: ir.modelData.label; font.weight: 600; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: parent.width }
                                    Txt { kind: "fine"; tone: 2; width: parent.width; wrapMode: Text.NoWrap; elide: Text.ElideRight
                                        text: ir.st && ir.st.message ? ir.st.message : ir.modelData.why } }
                                Txt { anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; mono: true
                                    text: ir.st ? (ir.st.state === "needs_user" ? "your turn" : ir.st.state) : ir.modelData.installable ? (ir.modelData.size || "")
                                        : ir.modelData.plan && ir.modelData.plan.kind === "login" || ir.modelData.id.indexOf(".signin") > 0 ? "sign-in" : "download page" }
                            }
                        }
                    } }
                Txt { visible: wl.runRows.length > 0 && !Store.installing && !wl.ran; kind: "fine"; tone: 2; width: parent.width
                    text: "In all " + (wl.runMb > 0 ? wl.mb(wl.runMb) : "a small download") + ". Something Form Studio cannot install by itself opens its official download page, and the setup goes on when it is there." }
                Txt { visible: Store.caps && !Store.capOn("print"); kind: "fine"; width: parent.width
                    text: "3D printing is off. Turn it on any time in Settings › General › Set up for; only then is a slicer installed." }
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
                Btn { kind: "quiet"; text: "Skip setup"; visible: wl.step < 2; enabled: !Store.installing; tip: "You can run it again from the command palette"
                    onClicked: Store.closeWelcome("skipped") } }
            Row { spacing: 10; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Btn { objectName: "welcomeOpenWithout"; kind: "quiet"; visible: wl.step === 2 && !Store.installing && wl.runIds.length > 0
                    text: wl.ran ? "Open Form Studio" : "Open without installing"; onClicked: Store.closeWelcome("done") }
                Btn { visible: Store.installing; large: true; icon: "x"; text: "Cancel setup"; onClicked: Store.cancelInstall() }
                Btn { objectName: "welcomePrimary"; kind: "primary"; large: true; busy: Store.installing || !wl.sw || !Store.caps
                    autoBusy: false              // moving between steps saves the step in the background: never wait for it
                    icon: wl.step < 2 ? "arrow_right" : wl.runIds.length && !wl.ran ? "download" : "check"
                    text: Store.installing ? "Setting up…" : !wl.sw || !Store.caps ? "Checking…"
                        : wl.step < 2 ? "Continue"
                        : wl.runIds.length && !wl.ran ? "Install " + wl.runIds.length + (wl.runIds.length === 1 ? " item" : " items")
                        : wl.runIds.length ? "Try again" : "Open Form Studio"
                    onClicked: wl.step === 2 && wl.ran && wl.runIds.length ? Store.runSetup(wl.runIds) : wl.primary() } }
        }
    }
}
