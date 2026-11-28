import QtQuick
import QtCore
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// The conversation. In a workspace it is one bar under the part (`bar`): a status line, numbered suggestions, the
// prompt. It opens upward into a glass transcript sheet with everything a conversation has (cards, revisions,
// Compare, attachments, concepts, questions), and folds back to the bar while a build plays, so the part and its cue
// have the room. On Home it is a glass column. Conversations are saved and switchable; each message runs the agent you chose (an agent app such
// as Claude Code or Codex, a model provider's API, or a local model) with Form Studio's tools. The same column shows
// what any other agent does to your designs.
Rectangle {
    id: talk
    objectName: "talk"
    readonly property var attachFilters: pick.nameFilters     // what the attach dialog offers (tests/journeys/open_conv.py)
    color: "transparent"
    property bool bar: false                 // one bar under the part that opens upward (a workspace); false: a column (Home)
    property bool docked: false              // the column of a workspace (Main.qml): it folds to the bar under the part
    property real veil: 1                    // 0..1: its words, while the pane travels between the bar and the column (Main.qml)
    property bool onScreen: true             // false while it is parked beside the window (Home with no conversation open): nothing in it ticks
    property real roomAbove: 600             // how tall something that opens upward from the bar may be (Main.qml)
    // a build is playing: the bar is slim and the transcript waits, so the cue has the room
    readonly property bool cueing: bar && (!!Store.building || Store.revealing.length > 0)
    // the bar opens upward into a drawer only where there is no column for the conversation (while a design is being
    // made); in a workspace it opens into the column instead, and upward only for the list of conversations
    property bool drawer: true
    readonly property bool expanded: !bar || (((drawer && Store.talkOpen && !empty) || list.opened) && !cueing)
    readonly property bool slim: bar && !expanded && (!empty || cueing)          // just the prompt, on one line
    readonly property bool suggOn: bar && empty && !cueing && Store.chat.available && !!Store.project && forProject.length > 0
    readonly property int leadH: bar && !cueing ? 32 : 0      // while a build plays the cue says what is happening
    readonly property real barHeight: leadH + foot.height                          // folded
    // how tall the folded bar is once no build plays (while one plays it is one line): the camera frames a part
    // mid-build over this, so nothing moves when the build is in
    readonly property real restHeight: 32 + (!empty ? 64 : 102 + (Store.chat.available && !!Store.project && forProject.length > 0
                                             ? Math.ceil(forProject.length / (width - 16 > 440 ? 2 : 1)) * 34 + 8 : 0))
    readonly property real popRoom: bar ? roomAbove : height
    // what the open transcript wants above the prompt: its header, the strips under it, and what was said
    readonly property real bodyWant: head.height + 8 + (rsteps.visible ? rsteps.height : 0) + (strip.visible ? strip.height : 0) + feed.contentHeight + feed.topMargin + feed.bottomMargin + 6
    function pickSuggestion(m) { if (m.sheet) Store.openSheet(m.sheet); else if (m.review) Store.askReview(); else Store.send(m.prompt) }
    function toggle() { if (empty) { ta.forceActiveFocus(); return } Store.toggleTalk() }
    onXChanged: pane.place(); onYChanged: pane.place()
    Glass { id: pane; source: Store.backdrop; z: -1; y: talk.leadH; width: parent.width; height: parent.height - talk.leadH; radius: talk.bar ? 26 : Theme.rPane }
    readonly property bool empty: Store.chatItems.length === 0 && !Store.chatBusy
    property var openGroups: ({})             // step group key → unfolded
    // suggestions for the open design, from its real state
    readonly property var forProject: {
        var d = Store.data, out = []
        if (!d || !Store.project) return out
        var roll = d.checks ? d.checks.rollup : null, rev = F.pad(Store.project.head)
        if (roll && roll.FAIL) out.push({ label: "Fix what fails in " + rev, prompt: "The checks on " + rev + " of this design report " + roll.FAIL + " failure(s). Read them with Form Studio's tools, explain each in one line, and preview the smallest change that fixes them. Do not commit until I say so." })
        else if (roll && roll.WARN) out.push({ label: "Explain the " + F.plural(roll.WARN, "warning") + " on " + rev, prompt: "Explain the warnings on " + rev + " of this design: what each one means for " + (!Store.printUi ? "the part" : "the print or the fit") + ", and which I can safely acknowledge." })
        var model = !Store.printUi
        out.push({ label: "Review " + rev + (model ? ": design and engineering" : ": design, engineering, print"), review: true })
        out.push({ label: "Make it lighter without failing a check", sheet: "lighter" })
        if (model) out.push({ label: "Which dimensions are still assumed?", prompt: "Which numbers in this design are assumed rather than measured or specified? Tell me which matter most and how to confirm each." })
        else out.push({ label: "What should I measure before printing?", prompt: "Which numbers in this design are assumed rather than measured, and which of them matter for the fit? Tell me exactly what to measure and with what." })
        if (d.fit && d.fit.yield < 0.95) out.push({ label: "Improve the modelled fit yield", prompt: "The modelled fit yield is " + Math.round(d.fit.yield * 100) + "%. What drives it, and what change would raise it? It is a model, so say what a test print should confirm." })
        return out.slice(0, 4)
    }
    Component.onCompleted: { sync(); try { Store.savedPrompts = JSON.parse(kept.prompts) } catch (e) { Store.savedPrompts = [] } }
    // the messages saved as commands outlive the session
    Settings { id: kept; category: "talk"; property string prompts: "[]" }
    Connections { target: Store; function onSavedPromptsChanged() { kept.prompts = JSON.stringify(Store.savedPrompts) } }
    // the step the agent is on in this turn: every tool call since your message
    readonly property int stepNow: { var n = 0, it = Store.chatItems; for (var i = it.length - 1; i >= 0 && it[i].t !== "user"; i--) if (it[i].t === "tool") n++; return n }
    function liveDetail() {
        var L = Store.chatLive, b = Store.building
        if (b && b.of) return (b.index !== undefined ? b.index + 1 : b.at) + " of " + b.of
        if (L && L.kind === "tool") return L.name + " · step " + (talk.stepNow + 1)
        if (L && (L.kind === "thinking" || L.kind === "text") && L.chars) return (L.chars / 1000).toFixed(1) + " kB"
        return talk.stepNow ? F.plural(talk.stepNow, "step") : ""
    }

    function liveText() {
        var L = Store.chatLive, who = Store.chatAgentLabel
        if (Store.chatAsking) return who + " is waiting for your answer"
        if (!L) return who + " is thinking…"
        if (Store.building && Store.building.label) return "Building " + Store.building.label
        if (L.kind === "tool") return F.toolSay(L.name)
        if (L.kind === "text") return "Writing…"
        if (L.kind === "thinking") return "Thinking…" + (L.chars ? " " + (L.chars / 1000).toFixed(1) + " kB" : "")
        return "Working…"
    }
    function showList() { list.open() }
    function showModels() { mpop.open() }
    function money(v) { return v === null || v === undefined ? "" : v < 0.01 ? "under $0.01" : "$" + v.toFixed(2) }
    function tokens(u) {
        if (!u) return ""
        var n = (u.input_tokens || 0) + (u.output_tokens || 0)
        if (!n) return ""
        return (n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n)) + " tokens"
    }
    function costText(m) {
        if (m.cost !== null && m.cost !== undefined) return " · " + talk.money(m.cost)
        if (m.stopped) return ""
        var t = talk.tokens(m.usage)
        return t ? " · " + t : " · cost not reported"
    }
    Connections { target: Store; function onModelPickWanted() { Qt.callLater(function () { if (!mpop.opened) mpop.open() }) } }
    function tryAnother() { Store.retryAfterPick = true; Qt.callLater(function () { mpop.open() }) }   // after the click ends: the menu may open under the pointer
    function secs(s) { return s === null || s === undefined ? "" : s < 90 ? Math.round(s) + " s" : Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" }

    // ── the feed as blocks: messages, folded step groups, footers ──
    ListModel { id: blocks }
    function build() {
        var out = [], items = Store.chatItems, group = null, model = "", agent = "", answers = ({})
        // what this turn's reply rests on: the tool calls whose results say how they are known (form/cite.py), in the
        // order they were made; `said` are the turn's reply blocks, which get the indices once the turn has ended
        var srcs = [], said = [], plan = null
        function closeTurn(ended, more) {
            more = more || []          // given but not opened, opened earlier, model knowledge: rows without a number
            if (ended && (srcs.length || more.length)) {
                var cites = srcs.map(function (x) { return [x.n, x.figures] })
                said.forEach(function (b) { b.cites = cites })
                out.push({ t: "sources", k: "src" + out.length, count: srcs.length,
                           list: srcs.map(function (x) { return { n: x.n, title: x.title, how: x.how } }).concat(more.map(function (x) { return { n: 0, title: x.title, how: x.how } })) })
            }
            srcs = []; said = []; plan = null
        }
        for (var a = 0; a < items.length; a++) if (items[a].t === "answer") answers[items[a].id] = items[a]
        for (var i = 0; i < items.length; i++) {
            var ev = items[i]
            if (ev.t === "tool" && ev.name === "suggest_replies") continue      // shown as the follow-up chips, not as a step
            if (ev.t === "tool") {
                if (!group) { group = { t: "steps", k: "s" + i, steps: [] }; out.push(group) }
                group.steps.push({ id: ev.id, tool: ev.name, input: ev.input, ts: ev.ts || 0 })
                var got = Store.chatTools[ev.id]
                if (got && got.source && !srcs.some(function (x) { return x.title === got.source.title && x.how === got.source.how }))
                    srcs.push({ n: srcs.length + 1, title: got.source.title, how: got.source.how, figures: got.source.figures || [] })
                // its plan (plan_design), as a card: an approval the agent asks for next is answered on it
                if (ev.name === "plan_design" && got && got.plan && got.plan.length) { group = null; plan = { t: "plan", k: "p" + i, steps: got.plan, q: null }; out.push(plan) }
                // the concepts it proposed, right here in the conversation: what they look like, and a pick
                var res = ev.name === "propose_concepts" ? Store.chatTools[ev.id] : null
                if (res && res.concepts && res.concepts.group) { group = null; out.push({ t: "concepts", k: "c" + i, group: res.concepts.group }) }
                continue
            }
            if (ev.t === "start") {
                model = Store.modelName(ev); agent = ev.agent || ""
                // effort raised for a hard task (form/agents/effort.py): said in the conversation, Settings turns it off
                if (ev.effort_why) { group = null; out.push({ t: "act", k: "f" + i, by: "Form Studio", text: ev.effort_why }) }
                continue
            }
            if (ev.t === "answer") continue
            group = null
            if (ev.t === "ask") {
                var q = { id: ev.id, question: ev.question, choices: ev.choices || [], multi: !!ev.multi, free: ev.free !== false,
                          why: ev.why || "", kind: ev.kind || "question", answer: answers[ev.id] || null,
                          open: !!Store.chatAsking && Store.chatAsking.id === ev.id && !answers[ev.id] }
                if (q.kind === "measure")                // a guided measurement: where, the picture, the unit and tolerance
                    ["project", "param", "unit", "tolerance_mm", "where", "diagram", "image_url", "mark", "current"].forEach(function (f) { q[f] = ev[f] === undefined ? null : ev[f] })
                if (plan && !plan.q && q.kind === "confirm") { plan.q = q; continue }
                out.push({ t: "ask", k: "q" + i, q: q })
                continue
            }
            if (ev.t === "suggest") { out.push({ t: "suggest", k: "g" + i, options: ev.options || [] }); continue }
            if (ev.t === "user") { closeTurn(false); out.push({ t: "user", k: "u" + i, text: ev.text, attachments: ev.attachments || [], local: !!ev.local, n: ev.n === undefined ? -1 : ev.n }) }
            else if (ev.t === "text") { var tb = { t: "text", k: "t" + i, text: ev.text, n: ev.n === undefined ? -1 : ev.n, cites: [] }; said.push(tb); out.push(tb) }
            else if (ev.t === "act" && ev.change && String(ev.by).toLowerCase() === "you") {
                // changes made by hand since the last reply: one note that names them, and the newest revision's card
                var hn = out.length && out[out.length - 1].t === "hand" ? out[out.length - 1] : null
                if (!hn) { hn = { t: "hand", k: "h" + i, edits: [], change: null }; out.push(hn) }
                hn.edits.push({ text: ev.text, to: ev.change.to })
                if (ev.change.from !== ev.change.to) hn.change = ev.change       // a card only for a revision that was made
            }
            else if (ev.t === "act") out.push({ t: "act", k: "a" + i, by: ev.by, text: ev.text, change: ev.change || null })
            else if (ev.t === "end") closeTurn(true, ev.cite_rows), out.push({ t: "end", k: "e" + i, cost: ev.cost_usd, steps: ev.steps, seconds: ev.seconds, stopped: !!ev.stopped,
                                                model: Store.modelName(ev) || model, agent: ev.agent || agent, change: ev.change || null,
                                                usage: ev.usage || null })
            else if (ev.t === "error") out.push({ t: "error", k: "x" + i, text: ev.text, hint: ev.hint || "", agent: ev.agent || agent })
        }
        // follow-ups: only the newest, only until you write again, and shown under the reply's footer
        var sg = -1
        for (var g = 0; g < out.length; g++) if (out[g].t === "suggest") sg = g
        var keep = sg >= 0 && !Store.chatBusy && !out.slice(sg).some(function (b) { return b.t === "user" || b.t === "error" })
        var tip = keep ? out[sg] : null
        out = out.filter(function (b) { return b.t !== "suggest" })
        if (tip && tip.options.length) out.push(tip)
        if (out.length) {
            var last = out[out.length - 1]
            if (last.t === "suggest" && out.length > 1) last = out[out.length - 2]
            if (last.t === "steps") last.running = Store.chatBusy
            if (last.t === "end" || last.t === "error") last.last = !Store.chatBusy
        }
        return out
    }
    // A block that arrives while you watch (a reply, a step, your message) fades in where it lands. A saved
    // conversation that opens arrives all at once and is drawn as it is: nothing fades, so nothing can be left
    // half-drawn when the feed jumps to its end (a ListView add transition stopped by that jump left whole
    // messages at opacity 0: an empty column with only the last footer).
    readonly property int arrivals: 3            // at most this many new blocks at once count as arriving live
    function sync() {
        var b = build(), live = b.length - blocks.count <= talk.arrivals && blocks.count > 0, now = Date.now()
        for (var i = 0; i < b.length; i++) {
            var j = JSON.stringify(b[i])
            if (i < blocks.count) { if (blocks.get(i).j !== j) blocks.set(i, { k: b[i].k, j: j }) }
            else blocks.append({ k: b[i].k, j: j, born: live ? now : 0 })
        }
        while (blocks.count > b.length) blocks.remove(blocks.count - 1)
    }
    Connections { target: Store
        function onChatItemsChanged() { talk.sync() }
        function onChatToolsChanged() { talk.sync() }
        function onChatBusyChanged() { talk.sync() }
        function onChatAskingChanged() { talk.sync() }
        function onConvIdChanged() { talk.openGroups = ({}); feed.stick = true }
        function onChatFocusChanged() { ta.forceActiveFocus() }
        function onChatRecallChanged() { if (Store.chatRecall) { ta.text = Store.chatRecall; ta.cursorPosition = ta.text.length } } }

    FileDialog { id: pick; title: "Attach files"; fileMode: FileDialog.OpenFiles
        nameFilters: Bridge.fileFilters("attach")      // one table of formats for every way in (form/formats.py)
        onAccepted: Store.attachFiles(selectedFiles) }

    readonly property int branchCount: Store.convBranches.length
    readonly property int branchAt: { for (var i = 0; i < Store.convBranches.length; i++) if (Store.convBranches[i].id === Store.convId) return i; return -1 }
    // ── header: the conversation switcher ──
    Item {
        id: head; width: parent.width; height: 40; z: 3; y: talk.leadH + (talk.bar ? 4 : 0)
        opacity: (talk.expanded ? 1 : 0) * talk.veil; visible: opacity > 0.01; enabled: talk.expanded
        Behavior on opacity { enabled: talk.veil === 1; NumberAnimation { duration: talk.expanded ? Theme.base : Theme.exit } }
        Item { id: sw; objectName: "convSwitch"; x: 8; width: parent.width - 16 - tools.width; height: 28; anchors.verticalCenter: parent.verticalCenter
            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: swm.pressed ? Theme.washPress : swm.containsMouse || list.opened ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
            Rectangle { id: sdot; x: 8; width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                color: Store.chatAsking ? Theme.amber : Store.chatBusy ? Theme.datum : Store.chatReady ? Theme.pass : Theme.ink4
                SequentialAnimation on opacity { running: Store.chatBusy; loops: Animation.Infinite; alwaysRunToEnd: true
                    NumberAnimation { to: 0.3; duration: 600 } NumberAnimation { to: 1; duration: 600 } } }
            Txt { id: ttl; x: 23; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; wrapMode: Text.NoWrap; elide: Text.ElideRight
                width: Math.min(implicitWidth, parent.width - 23 - 22); text: Store.convTitle() }
            Icon { anchors.left: ttl.right; anchors.leftMargin: 4; name: "chevron_down"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
            MouseArea { id: swm; anchors.fill: parent; hoverEnabled: true; onClicked: list.opened ? list.close() : list.open() }
            Tip { show: swm.containsMouse && !list.opened; text: "Conversations" } }
        Row { id: tools; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 0
            // a conversation with branches: which one this is, and the others
            Btn { id: branchBtn; objectName: "branchSwitch"; small: true; kind: "quiet"; icon: "git_branch"; visible: talk.branchCount > 1
                text: talk.branchAt >= 0 ? "Branch " + (talk.branchAt + 1) + " of " + talk.branchCount : F.plural(talk.branchCount, "branch")
                tip: "Branches of this conversation"; active: branchMenu.opened
                anchors.verticalCenter: parent.verticalCenter; onClicked: branchMenu.opened ? branchMenu.close() : branchMenu.open()
                PopMenu { id: branchMenu; objectName: "branchMenu"; y: branchBtn.height + 6; x: branchBtn.width - width; width: 300
                    model: Store.convBranches.map(function (b, i) {
                        return { icon: i === 0 ? "message_square" : "git_branch", checked: b.id === Store.convId,
                                 text: (i === 0 ? "Original" : "Branch " + (i + 1)) + (b.fork_reason ? " · " + b.fork_reason : "") + " · " + F.ago(b.updated),
                                 run: function () { if (b.id !== Store.convId) Store.openConv(b.id) } } }) } }
            Btn { objectName: "talkNewChat"; kind: "quiet"; icon: "message_square_plus"; tip: "New conversation"; keys: "Ctrl+Shift+O"
                visible: !talk.empty || Store.convId !== ""; onClicked: Store.newChat() }
            Btn { objectName: "talkFold"; kind: "quiet"; icon: "panel_left_close"; tip: "Fold the conversation to the bar"; keys: "Ctrl+J"
                visible: talk.docked; onClicked: Store.talkOpen = false } }
        Rectangle { anchors.bottom: parent.bottom; x: 14; width: parent.width - 28; height: 1; color: Theme.rule }
        Pop {
            id: list; x: 8; y: head.height + 2; width: Math.max(talk.width - 17, 320); padding: 6; origin: Popup.TopLeft
            height: Math.min(cl.implicitHeight + 12, Math.max(200, talk.height - 90))
            onOpened: { Store.loadConvs(); cl.reset() }
            Flickable { anchors.fill: parent; clip: true; contentHeight: cl.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { width: 6 }
                ConversationList { id: cl; width: parent.width; onChosen: list.close() } }
        }
    }

    // ── Replace a broken part: where the agent is in the four steps (Store.replaceProgress) ──
    Rectangle { id: rsteps; visible: Store.replaceActive && !talk.empty && talk.expanded; z: 2
        anchors.top: head.bottom; width: parent.width - 1; height: visible ? 62 : 0; color: "transparent"
        ReplaceSteps { x: 14; y: 9; width: parent.width - 28; done: Store.replaceProgress.done; active: Store.replaceProgress.active }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule } }

    // ── the designs this conversation made, when it made more than one: click one to open it ──
    Rectangle {
        id: strip; objectName: "designStrip"; z: 2; opacity: talk.veil
        visible: Store.designsHere.length > 1 && talk.expanded
        anchors.top: rsteps.visible ? rsteps.bottom : head.bottom; width: parent.width - 1; height: visible ? 52 : 0; color: "transparent"
        ListView {
            id: stripList; x: 10; y: 8; width: parent.width - 20; height: 36; orientation: ListView.Horizontal; spacing: 6; clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: Store.designsHere
            delegate: Rectangle {
                id: dsi; objectName: "designStripItem"; required property var modelData; required property int index
                readonly property bool here: modelData.project === Store.pid
                readonly property string title: modelData.name
                width: Math.min(200, dl.implicitWidth + 50); height: 36; radius: Theme.rMd
                color: here ? Theme.plate3 : dm.pressed ? Theme.washPress : dm.containsMouse && modelData.live ? Theme.washHover : "transparent"
                border.color: here ? Theme.alpha(Theme.datum, 0.45) : Theme.rule
                opacity: modelData.live ? 1 : 0.55
                Behavior on color { Tint {} }
                Rectangle { x: 4; width: 28; height: 28; radius: Theme.rSm; color: Theme.plate; clip: true; anchors.verticalCenter: parent.verticalCenter
                    MiniView { visible: dsi.modelData.live; anchors.fill: parent; projectId: dsi.modelData.live ? dsi.modelData.project : "" }
                    Icon { visible: !dsi.modelData.live; anchors.centerIn: parent; name: "trash_2"; size: 12; color: Theme.ink4 } }
                Txt { id: dl; x: 38; width: parent.width - 46; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; font.weight: dsi.here ? Theme.wSemi : Theme.wMedium
                    tone: dsi.here ? 1 : 2; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: dsi.modelData.name }
                MouseArea { id: dm; anchors.fill: parent; hoverEnabled: true; enabled: dsi.modelData.live
                    cursorShape: dsi.modelData.live && !dsi.here ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: Store.openConvDesign(dsi.modelData.project) }
                Tip { show: dm.containsMouse; text: !dsi.modelData.live ? dsi.modelData.name + " is in the trash" : dsi.here ? dsi.modelData.name + " is open"
                    : "Open " + dsi.modelData.name + ({ concept: " (a concept)", continued: " (carried on here)" }[dsi.modelData.role] || "") }
            }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
    }

    // ── nothing open yet: what you can ask ──
    Column {
        id: intro
        visible: talk.empty && !talk.bar
        x: 16; width: parent.width - 2 * x; spacing: 10
        anchors.top: head.bottom; anchors.topMargin: 24
        Txt { kind: "h3"; width: parent.width; lineHeight: 1.08; font.weight: Theme.wSemi
            text: Store.project ? "Ask about this design,\nor describe a change." : "Describe a change,\nor a new part." }
        Txt { tone: 2; width: parent.width; lineHeight: 1.4
            text: "The agent works on the design with Form Studio's tools. Changes arrive as a draft or a new revision you can compare and undo." }
        Note { visible: !Store.chat.available && !!Store.studio; kind: "amber"; title: "No agent is connected"
            text: (Store.chat.note || "") + " You can still start a blank design and edit everything by hand." }
    }
    // suggestions for the open design fill the space the feed will use
    Flickable {
        id: start
        visible: talk.empty && !talk.bar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: intro.bottom; anchors.topMargin: 16
        anchors.bottom: foot.top
        contentHeight: sc.implicitHeight + 20; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: sc; x: 16; width: parent.width - 2 * x; spacing: 6
            Repeater {
                model: !Store.chat.available || !Store.project ? [] : talk.forProject
                Rectangle {
                    id: idea
                    required property var modelData
                    required property int index
                    width: sc.width; height: 34; radius: Theme.rMd
                    color: im.pressed ? Theme.plate1 : im.containsMouse ? Theme.plate3 : Theme.plate2; border.color: im.containsMouse ? Theme.rule2 : Theme.rule
                    scale: im.pressed ? Theme.from(0.985) : 1
                    Behavior on scale { Glide { duration: Theme.press } }
                    Behavior on color { Tint {} }
                    // each suggestion arrives a beat after the one above
                    opacity: 0; Component.onCompleted: arrive.start()
                    SequentialAnimation { id: arrive; PauseAnimation { duration: 80 + idea.index * Theme.stagger }
                        ParallelAnimation { Glide { target: idea; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: slide; property: "y"; from: Theme.shift(6); to: 0; duration: Theme.slow } } }
                    transform: Translate { id: slide }
                    Txt { x: 12; width: parent.width - 40; text: idea.modelData.label; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: im.containsMouse ? 1 : 2 }
                    Icon { name: "arrow_right"; size: 13; anchors.right: parent.right; anchors.rightMargin: im.containsMouse ? 8 : 10; anchors.verticalCenter: parent.verticalCenter; color: im.containsMouse ? Theme.datum : Theme.ink4
                        Behavior on anchors.rightMargin { Glide { duration: Theme.fast } } }
                    MouseArea { id: im; anchors.fill: parent; hoverEnabled: true
                        onClicked: idea.modelData.sheet ? Store.openSheet(idea.modelData.sheet) : idea.modelData.review ? Store.askReview() : Store.send(idea.modelData.prompt) }
                }
            }
        }
    }

    // ── the feed ──
    ListView {
        id: feed; objectName: "talkFeed"
        property bool stick: true              // follow the newest message unless the reader scrolled up
        property bool auto: false
        visible: !talk.empty && opacity > 0.01; enabled: talk.expanded
        opacity: (talk.expanded ? 1 : 0) * talk.veil
        Behavior on opacity { enabled: talk.veil === 1; NumberAnimation { duration: talk.expanded ? Theme.cross : Theme.exit } }
        anchors.top: strip.visible ? strip.bottom : rsteps.visible ? rsteps.bottom : head.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
        topMargin: 16; bottomMargin: 12; clip: true; spacing: 14
        boundsBehavior: Flickable.StopAtBounds
        model: blocks
        function toEnd() { if (!stick) return; auto = true; positionViewAtEnd(); auto = false }
        onContentHeightChanged: Qt.callLater(toEnd)
        onHeightChanged: Qt.callLater(toEnd)
        onContentYChanged: if (!auto && talk.veil === 1) stick = atYEnd || contentHeight <= height      // (not while the pane travels: nobody scrolled)
        // a question that waits is shown: the feed goes to it, wherever the reader had scrolled
        Connections { target: Store; function onChatAskingChanged() { if (Store.chatAsking) { feed.stick = true; Qt.callLater(feed.toEnd) } } }
        Connections { target: talk; function onVeilChanged() { if (talk.veil === 1) Qt.callLater(feed.toEnd) } }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }
        delegate: Item {
            id: it
            required property string j
            required property string k
            required property int index
            required property real born
            property real rise: 0
            transform: Translate { y: it.rise }
            // a new message, step group or footer fades in where it lands and rises the last few pixels into place
            // (a transform, so the rows around it never re-lay out). The delegate runs it itself, so the view moving
            // can never stop it half-way; made again later (scrolled back to), it is simply there.
            Component.onCompleted: if (born > 0 && Date.now() - born < 400) arrive.start()
            ParallelAnimation { id: arrive; alwaysRunToEnd: true
                Glide { target: it; property: "opacity"; from: 0; to: 1; duration: Theme.base }
                Glide { target: it; property: "rise"; from: Theme.shift(Theme.rise); to: 0; duration: Theme.move(Theme.panel) } }
            readonly property var m: JSON.parse(j)
            width: feed.width; implicitHeight: body.item ? body.item.implicitHeight : 0; height: implicitHeight
            HoverHandler { id: hh }
            Loader { id: body; x: 16; width: parent.width - 32
                sourceComponent: it.m.t === "user" ? cUser : it.m.t === "text" ? cText : it.m.t === "steps" ? cSteps : it.m.t === "act" ? cAct
                               : it.m.t === "end" ? cEnd : it.m.t === "ask" ? cAsk : it.m.t === "suggest" ? cSuggest
                               : it.m.t === "concepts" ? cConcepts : it.m.t === "sources" ? cSources : it.m.t === "plan" ? cPlan
                               : it.m.t === "hand" ? cHand : cErr }
            // actions on hover: copy, fork from here, and for your own message, edit and send again
            Rectangle { readonly property bool want: (hh.hovered || cb.hovered || eb.hovered || fb.hovered || sb.hovered) && (it.m.t === "user" || it.m.t === "text") && !it.m.local
                opacity: want ? 1 : 0; visible: opacity > 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                z: 2; anchors.right: parent.right; anchors.rightMargin: 14; y: it.m.t === "user" ? it.height - 6 : -10
                width: ar.implicitWidth + 4; height: 26; radius: Theme.rSm + 1; color: Theme.plate3; border.color: Theme.rule2
                Row { id: ar; anchors.centerIn: parent
                    Btn { id: cb; small: true; kind: "quiet"; icon: "copy"; tip: "Copy"; onClicked: { Bridge.copy(it.m.text); Store.toast("Copied") } }
                    Btn { id: fb; objectName: "msgFork"; small: true; kind: "quiet"; icon: "git_branch"; tip: "Fork from here: a new branch with the conversation up to this message"
                        visible: it.m.n >= 0 && !Store.chatBusy; onClicked: Store.forkConv(it.m.n) }
                    Btn { id: eb; small: true; kind: "quiet"; icon: "pencil"; tip: "Edit and send again"; visible: it.m.t === "user"; onClicked: Store.recallChat(it.m.text) }
                    Btn { id: sb; objectName: "msgSave"; small: true; kind: "quiet"; icon: "bookmark"; active: Store.promptSaved(it.m.text)
                        tip: Store.promptSaved(it.m.text) ? "Saved as a command: remove it" : "Save as a command: it appears in the palette (Ctrl+K)"
                        visible: it.m.t === "user"; onClicked: Store.togglePrompt(it.m.text) } } }

            Component { id: cUser; Item { implicitHeight: ub.height
                Rectangle { id: ub; anchors.right: parent.right; radius: Theme.rLg; color: Theme.plate3; border.color: Theme.rule; opacity: it.m.local ? 0.7 : 1
                    width: Math.min(parent.width - 28, Math.max(ut.implicitWidth, af.visible ? af.implicitWidth : 0) + 26)
                    height: uc.implicitHeight + 18
                    Column { id: uc; x: 13; y: 9; width: parent.width - 26; spacing: 8
                        Flow { id: af; visible: it.m.attachments.length > 0; width: body.width - 50; spacing: 6
                            Repeater { model: it.m.attachments
                                Rectangle { id: ach; required property var modelData
                                    readonly property bool pic: modelData.kind === "image"
                                    width: pic ? 64 : acl.implicitWidth + 34; height: pic ? 64 : 26; radius: Theme.rSm; color: Theme.plate1; border.color: ah.hovered && pic ? Theme.rule3 : Theme.rule; clip: true
                                    TapHandler { enabled: ach.pic; onTapped: Store.showImage(Store.attachmentUrl(ach.modelData.file, aimg.cid), ach.modelData.name, "Attached to this message") }
                                    // The address is fixed when the thumbnail is made. Bound to Store.convId it would be asked for
                                    // again under the next conversation's id while this message is being removed.
                                    Image { id: aimg; visible: ach.pic; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                                        property string cid: ""
                                        function arm() { if (!cid && ach.pic && Store.convId) { cid = Store.convId; source = Store.attachmentUrl(ach.modelData.file, cid) } }
                                        Component.onCompleted: arm()
                                        Connections { target: Store; function onConvIdChanged() { aimg.arm() } } }
                                    Icon { visible: !ach.pic; x: 8; size: 13; anchors.verticalCenter: parent.verticalCenter; name: ach.modelData.kind === "cad" ? "box" : "file_text" }
                                    Txt { id: acl; visible: !ach.pic; x: 26; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; wrapMode: Text.NoWrap; text: ach.modelData.name }
                                    HoverHandler { id: ah }
                                    Tip { show: ah.hovered; text: ach.modelData.name } } } }
                        Txt { id: ut; width: Math.min(implicitWidth, body.width - 54); text: it.m.text; lineHeight: 1.4 } } } } }
            Component { id: cSources; TalkSources { width: body.width; list: it.m.list; count: it.m.count } }
            Component { id: cPlan; TalkPlan { width: body.width; steps: it.m.steps; q: it.m.q; onEdit: ta.forceActiveFocus() } }
            // by hand since the last reply: what you changed, named, and the newest revision's card
            Component { id: cHand; Column { objectName: "handNote"; spacing: 8
                Item { width: body.width; height: hnt.implicitHeight
                    Icon { x: 1; y: 3; name: "user"; size: 14; color: Theme.ink3 }
                    Txt { id: hnt; objectName: "handNoteText"; x: 24; width: parent.width - 24; tone: 2; font.pixelSize: 13; lineHeight: 1.35; textFormat: Text.StyledText
                        text: "By hand since the last reply: " + it.m.edits.map(function (e) {
                            var s = String(e.text).replace(/&/g, "&amp;").replace(/</g, "&lt;"), c = s.indexOf(":")
                            return (c > 0 ? "<b><font color=\"" + Theme.ink + "\">" + s.slice(0, c) + "</font></b>," + s.slice(c + 1) : s) + (e.to !== null && e.to !== undefined ? " (" + F.pad(e.to) + ")" : "") }).join("; ") + "." } }
                TalkChange { visible: !!it.m.change; width: body.width; change: it.m.change } } }
            Component { id: cText; Md { id: rt; objectName: "replyText"; source: it.m.text; width: body.width; revs: true; cites: it.m.cites || []
                // while the reply is still being written, a caret sits after its last word
                property real endX: 0; property real endY: 0; property real endH: 16
                onLineLaidOut: function (line) { rt.endX = line.x + line.implicitWidth; rt.endY = line.y; rt.endH = line.height }
                Rectangle { objectName: "streamCaret"; visible: Store.chatBusy && it.index === feed.count - 1
                    x: Math.min(rt.width - 2, rt.endX + 3); y: rt.endY + (rt.endH - height) / 2; width: 2; height: 15; radius: 1; color: Theme.datum
                    SequentialAnimation on opacity { running: parent.visible; loops: Animation.Infinite; alwaysRunToEnd: true
                        PauseAnimation { duration: 380 } NumberAnimation { to: 0.15; duration: 220 } PauseAnimation { duration: 220 } NumberAnimation { to: 1; duration: 160 } } } } }
            Component { id: cAsk; Loader { width: body.width; sourceComponent: it.m.q.kind === "measure" ? cMeasure : cQuestion
                Component { id: cQuestion; TalkAsk { width: body.width; q: it.m.q } }
                Component { id: cMeasure; MeasureAsk { width: body.width; q: it.m.q } } } }
            // what you might say next, offered by the agent (suggest_replies): one click sends it
            Component { id: cSuggest; Flow { objectName: "suggestions"; width: body.width; spacing: 6
                Repeater { model: it.m.options
                    Rectangle { id: sgc; objectName: "suggestChip"; required property string modelData; required property int index
                        width: Math.min(body.width, sgt.implicitWidth + 40); height: 28; radius: 14
                        color: sgm.pressed ? Theme.washPress : sgm.containsMouse ? Theme.plate3 : "transparent"; border.color: sgm.containsMouse ? Theme.rule3 : Theme.rule2
                        Behavior on color { Tint {} }
                        opacity: 0; Component.onCompleted: sgIn.start()
                        SequentialAnimation { id: sgIn; PauseAnimation { duration: 60 + sgc.index * Theme.stagger }
                            Glide { target: sgc; property: "opacity"; to: 1; duration: Theme.base } }
                        Icon { x: 11; name: "corner_down_left"; size: 11; color: sgm.containsMouse ? Theme.datum : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
                        Txt { id: sgt; x: 27; width: parent.width - 38; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: sgc.modelData; tone: sgm.containsMouse ? 1 : 2 }
                        MouseArea { id: sgm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: Store.chatReady
                            onClicked: Store.send(sgc.modelData) }
                        Tip { show: sgm.containsMouse && sgt.truncated; text: sgc.modelData } } } } }
            Component { id: cSteps; TalkSteps { objectName: "stepGroup"; width: body.width; steps: it.m.steps; running: !!it.m.running
                expanded: !!talk.openGroups[it.k]
                onToggle: { var o = Object.assign({}, talk.openGroups); o[it.k] = !o[it.k]; talk.openGroups = o } } }
            // concepts the agent proposed (propose_concepts): each a real design, side by side; Pick continues with one,
            // the card opens the concepts sheet. A group already decided says which one was picked.
            Component { id: cConcepts; Rectangle { id: cc; objectName: "chatConcepts"
                readonly property string gid: it.m.group
                readonly property var listed: { var l = Store.concepts; for (var i = 0; i < l.length; i++) if (l[i].id === cc.gid) return l[i]; return null }
                property var board: null            // a group no longer open: read once, to say what became of it
                readonly property var g: listed || board
                readonly property bool waiting: !!listed
                readonly property var members: g ? g.members.filter(function (m) { return !m.error && !m.trashed }) : []
                function look() { if (!cc.listed && !cc.board) Store.get("/concepts/" + cc.gid).then(function (r) { cc.board = r }, function () {}) }
                Component.onCompleted: look()
                onListedChanged: if (!listed) { board = null; look() }
                width: body.width; implicitHeight: ccol.implicitHeight + 26; radius: Theme.rLg
                color: Theme.plate2; border.color: cch.hovered && cc.waiting ? Theme.alpha(Theme.datum, 0.5) : Theme.alpha(Theme.datum, cc.waiting ? 0.28 : 0.12)
                Behavior on border.color { Tint {} }
                HoverHandler { id: cch }
                Column { id: ccol; x: 13; y: 13; width: parent.width - 26; spacing: 10
                    Item { width: parent.width; height: 22
                        Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                            Rectangle { width: 7; height: 7; radius: 3.5; color: cc.waiting ? Theme.datum : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
                            Txt { kind: "cap"; color: cc.waiting ? Theme.datum : Theme.ink3; anchors.verticalCenter: parent.verticalCenter
                                text: !cc.g ? "Concepts" : cc.waiting ? F.plural(cc.members.length, "concept") + " · pick one"
                                    : cc.g.state === "picked" ? "Concept picked" : "Concepts closed" } }
                        Btn { objectName: "chatConceptsOpen"; visible: cc.waiting; small: true; kind: "quiet"; icon: "maximize_2"; text: "Side by side"
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            tip: "Open the concepts, turning, with their sizes"; onClicked: Store.openConcepts(cc.gid) } }
                    Txt { visible: !!cc.g; width: parent.width; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: cc.g ? cc.g.name : "" }
                    Row { id: tiles; spacing: 8; width: parent.width
                        readonly property real tw: Math.floor((width - (cc.members.length - 1) * spacing) / Math.max(1, cc.members.length))
                        Repeater { model: cc.members
                            Rectangle { id: tile; objectName: "chatConcept"; required property var modelData; required property int index
                                readonly property bool picked: !!cc.g && cc.g.picked === modelData.project
                                width: tiles.tw; height: ttc.y + ttc.implicitHeight + 10; radius: Theme.rMd + 2; clip: true
                                color: Theme.plate1; border.color: tile.picked ? Theme.alpha(Theme.datum, 0.7) : th2.hovered && cc.waiting ? Theme.rule3 : Theme.rule
                                opacity: cc.waiting || tile.picked ? 1 : 0.55
                                Behavior on border.color { Tint {} }
                                HoverHandler { id: th2 }
                                Item { id: tv; x: 1; y: 1; width: parent.width - 2; height: Math.round(width * 0.78); clip: true
                                    MiniView { anchors.fill: parent; projectId: tile.modelData.project; turning: th2.hovered }
                                    Txt { x: 8; y: 6; text: tile.modelData.letter; font.weight: Theme.wBold; color: Theme.datum; font.pixelSize: 12 } }
                                Column { id: ttc; x: 8; y: tv.height + 8; width: parent.width - 16; spacing: 6
                                    Txt { width: parent.width; font.pixelSize: 12; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: tile.modelData.title }
                                    Txt { visible: !!tile.modelData.rationale; width: parent.width; kind: "fine"; tone: 3; maximumLineCount: 2; elide: Text.ElideRight
                                        wrapMode: Text.WordWrap; text: tile.modelData.rationale || "" }
                                    Btn { objectName: "chatConceptPick"; visible: cc.waiting; small: true; kind: "quiet"; icon: "check"; text: "Pick"
                                        tip: "Continue with " + tile.modelData.letter + ": " + tile.modelData.title
                                        onClicked: Store.pickConcept(cc.gid, tile.modelData.project, false) }
                                    Txt { visible: tile.picked; kind: "fine"; color: Theme.datum; text: "Picked" } }
                                Tip { show: th2.hovered && !!tile.modelData.rationale; text: tile.modelData.title + ". " + (tile.modelData.rationale || "") } } } }
                } } }
            Component { id: cAct; Column { spacing: 8
              Row { spacing: 6
                Icon { name: it.m.change ? "pencil_ruler" : "zap"; size: 12; color: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; width: body.width - 20; text: it.m.by + "  " + it.m.text; color: Theme.ink2 } }
              // a change made by hand (form/modelling.py): the same revision card an agent's reply gets
              TalkChange { visible: !!it.m.change; width: body.width; change: it.m.change } } }
            Component { id: cEnd; Column { spacing: 8
              // the revision this reply made: what changed, compare it, or go back
              TalkChange { visible: !!it.m.change; width: body.width; change: it.m.change }
              // how the reply was made, small and out of the way at the right; on the newest reply, send it again
              Item { width: body.width; height: 20
                Row { id: rb; visible: !!it.m.last; spacing: 2; x: -4; anchors.verticalCenter: parent.verticalCenter
                    Btn { small: true; kind: "quiet"; icon: "rotate_cw"; tip: "Send your last message again"; onClicked: Store.retryChat() }
                    Btn { small: true; kind: "quiet"; icon: "repeat"; tip: "Send it again with another model"; onClicked: talk.tryAnother() } }
                Txt { id: ft; objectName: "replyMeta"; mono: true; tone: 4; font.pixelSize: Theme.tCap; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    horizontalAlignment: Text.AlignRight; width: Math.min(implicitWidth, parent.width - (rb.visible ? rb.width + 6 : 0)); elide: Text.ElideLeft; wrapMode: Text.NoWrap
                    text: (it.m.stopped ? "stopped · " : "") + F.plural(it.m.steps || 0, "step") + " · " + talk.secs(it.m.seconds)
                        + talk.costText(it.m) + (it.m.model ? " · " + it.m.model : "") } } } }
            Component { id: cErr; Column { id: ec; spacing: 6
                // a usage limit is not a failure: a calm card that says which agent, until when, and what is kept
                readonly property var limit: Store.usageLimit(it.m)
                readonly property string who: { var a = Store.agentInfo(it.m.agent || Store.chatAgent); return a ? a.label : "The agent" }
                property bool later: false
                Rectangle { objectName: "usageLimitCard"; visible: !!ec.limit; width: body.width; height: visible ? lc2.implicitHeight + 26 : 0
                    radius: Theme.rLg; color: Theme.plate2; border.color: Theme.rule2
                    Column { id: lc2; x: 14; y: 13; width: parent.width - 28; spacing: 6
                        Row { spacing: 8
                            Icon { name: "clock"; size: 14; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
                            Txt { font.weight: Theme.wSemi; anchors.verticalCenter: parent.verticalCenter
                                text: ec.who + " has reached its usage limit" } }
                        Txt { tone: 2; width: parent.width; wrapMode: Text.WordWrap; lineHeight: 1.35
                            text: (ec.limit && ec.limit.again ? "It can work again " + ec.limit.again + ". " : "It can work again once the limit resets. ")
                                + (Store.liveDesignsHere.length ? "Everything committed so far is saved: " + Store.liveDesignsHere.map(function (d) { return d.name }).join(", ") + "."
                                                                : "Nothing was lost; what it committed before the limit is saved.") }
                        Row { visible: !!it.m.last && !ec.later; spacing: 6; topPadding: 4
                            Btn { objectName: "limitSwitch"; small: true; kind: "primary"; icon: "repeat"; text: "Use another agent…"; onClicked: talk.tryAnother() }
                            Btn { objectName: "limitLater"; small: true; kind: "quiet"; text: "Continue later"; onClicked: ec.later = true } }
                        Btn { visible: ec.later && !!it.m.last; small: true; kind: "quiet"; icon: "rotate_cw"; text: "Send my last message again"; onClicked: Store.retryChat() } } }
                Note { visible: !ec.limit; kind: "red"; text: it.m.text + (it.m.hint ? "\n" + it.m.hint : ""); width: body.width }
                Row { visible: !!it.m.last && !ec.limit; spacing: 6
                    Btn { small: true; icon: "rotate_cw"; text: "Retry"; onClicked: Store.retryChat() }
                    Btn { small: true; kind: "quiet"; icon: "repeat"; text: "Try another model…"; onClicked: talk.tryAnother() } } } }
        }
        // what is being written right now
        // (not while a question waits: its card says so, and in a column the card needs the room)
        footer: Item { readonly property bool on: Store.chatBusy && !Store.chatAsking
            width: feed.width; visible: on; height: on ? lc.implicitHeight + 18 : 0
            Column { id: lc; x: 16; y: 10; width: parent.width - 32; spacing: 10
                // the reply as it is written: the block grows smoothly instead of jumping a line at a time
                Item { visible: !!Store.chatLive && Store.chatLive.kind === "text" && Store.chatLive.text !== ""; width: parent.width; clip: true
                    height: visible ? lt.implicitHeight : 0
                    Behavior on height { enabled: Store.chatBusy; NumberAnimation { duration: Theme.move(140); easing.type: Easing.OutQuad } }
                    Md { id: lt; source: Store.chatLive && Store.chatLive.text ? Store.chatLive.text : ""; width: parent.width } }
                Item { objectName: "liveStatus"; width: parent.width; height: 20
                    Item { id: ldot; width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                        Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(Theme.datum, 0.22)
                            SequentialAnimation on scale { running: Store.chatBusy && talk.onScreen && !Theme.reduced; loops: Animation.Infinite; alwaysRunToEnd: true
                                NumberAnimation { to: 1.35; duration: 700; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine } } }
                        Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.datum } }
                    Txt { id: lsay; objectName: "liveSay"; x: 24; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 13; text: talk.liveText()
                        width: Math.min(implicitWidth, parent.width - 24 - ldet.width - 10); elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Txt { id: ldet; objectName: "liveDetail"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; tone: 3; font.pixelSize: Theme.tCap; wrapMode: Text.NoWrap
                        width: Math.min(implicitWidth, parent.width * 0.55); elide: Text.ElideLeft; horizontalAlignment: Text.AlignRight
                        text: talk.liveDetail() + (Store.chatSeconds >= 1 ? (talk.liveDetail() ? " · " : "") + talk.secs(Store.chatSeconds) : "") } } } }
    }

    // ── the bar's status line: what the agent is doing, or what you can do; click it to open or fold the transcript ──
    Item {
        id: lead; objectName: "talkLead"; visible: talk.bar && !talk.cueing; width: parent.width; height: 22; z: 3; opacity: talk.veil
        readonly property string say: Store.chatAsking ? (Store.chatAsking.kind === "measure" ? "The agent is waiting for a measurement" : "The agent is waiting for your answer")
            : Store.chatBusy ? talk.liveText()
            : !Store.chat.available && !!Store.studio ? "No agent is connected. Everything can still be edited by hand."
            : talk.empty ? (Store.project ? "Ask about this design, or describe a change." : "Describe a change, or a new part.")
            : talk.expanded ? "Fold the conversation" : Store.convTitle() + " · " + F.plural(Store.chatItems.filter(function (e) { return e.t === "user" || e.t === "text" }).length, "message")
        Row { id: leadRow; anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter; spacing: 9
            Item { width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                // the accent: this is where the conversation is (amber while it waits for you, grey with no agent)
                readonly property color c: Store.chatAsking ? Theme.amber : Store.chatReady || Store.chatBusy ? Theme.datum : Theme.ink4
                Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(parent.c, 0.22)
                    SequentialAnimation on scale { running: Store.chatBusy && talk.bar && !Theme.reduced; loops: Animation.Infinite; alwaysRunToEnd: true
                        NumberAnimation { to: 1.4; duration: 700; easing.type: Easing.InOutSine } NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine } } }
                Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: parent.c; Behavior on color { Tint {} } } }
            Txt { id: leadTxt; anchors.verticalCenter: parent.verticalCenter; tone: lm.containsMouse && !talk.empty ? 1 : 2; font.pixelSize: 13; wrapMode: Text.NoWrap
                width: Math.min(implicitWidth, talk.width - 150); elide: Text.ElideRight; text: lead.say }
            Icon { visible: !talk.empty; anchors.verticalCenter: parent.verticalCenter; size: 13; color: Theme.ink3; name: "chevron_up"
                rotation: talk.expanded ? 180 : 0; Behavior on rotation { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } } } }
        MouseArea { id: lm; x: leadRow.x - 10; width: leadRow.width + 20; height: parent.height; hoverEnabled: true
            cursorShape: talk.empty ? Qt.ArrowCursor : Qt.PointingHandCursor; onClicked: talk.toggle() }
        Tip { show: lm.containsMouse && !talk.empty; keys: "Ctrl+J"; text: talk.cueing ? "The conversation opens again when the build is in" : talk.expanded ? "Fold the conversation" : "Open the conversation" }
        // folded: the conversations and a new one stay one click away
        Row { visible: !talk.expanded; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 0
            Btn { objectName: "barConversations"; small: true; kind: "quiet"; icon: "history"; tip: "Conversations"; onClicked: talk.showList() }
            Btn { objectName: "barNewChat"; small: true; kind: "quiet"; icon: "message_square_plus"; tip: "New conversation"; keys: "Ctrl+Shift+O"
                visible: !talk.empty || Store.convId !== ""; onClicked: Store.newChat() } }
    }

    // ── composer ──
    Item {
        id: foot; width: parent.width; height: comp.height + sugg.height + (talk.bar ? 12 : talk.docked ? 42 : 36); z: 2; opacity: talk.veil
        y: talk.height - height
        // numbered suggestions for the open design, from its real state; keys 1 to 4 pick them while the prompt is empty
        Grid {
            id: sugg; objectName: "talkSuggestions"; x: 8; y: 8; width: parent.width - 16; columns: width > 440 ? 2 : 1; columnSpacing: 4; rowSpacing: 0
            visible: talk.suggOn; height: visible ? implicitHeight + 8 : 0
            Repeater {
                model: talk.suggOn ? talk.forProject : []
                Item {
                    id: idea; objectName: "talkSuggestion"
                    required property var modelData
                    required property int index
                    width: (sugg.width - (sugg.columns - 1) * 4) / sugg.columns; height: 34
                    // each one arrives a beat after the one before; under the pointer it lifts
                    opacity: 0; Component.onCompleted: arrive.start()
                    SequentialAnimation { id: arrive; PauseAnimation { duration: 60 + idea.index * Theme.stagger }
                        Glide { target: idea; property: "opacity"; to: 1; duration: Theme.base } }
                    Rectangle { anchors.fill: parent; radius: 12; color: im.pressed ? Theme.washPress : im.containsMouse ? Theme.glass2 : "transparent"
                        Behavior on color { Tint {} }
                        transform: Translate { y: im.containsMouse && !im.pressed ? -Theme.shift(1) : 0; Behavior on y { Glide { duration: Theme.fast } } }
                        Rectangle { visible: im.containsMouse; x: parent.radius; width: parent.width - 2 * parent.radius; height: 1; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.1 : 0.8) } }
                    Kbd { id: key; x: 10; anchors.verticalCenter: parent.verticalCenter; keys: String(idea.index + 1) }
                    Txt { x: 41; width: parent.width - 51; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 13; text: idea.modelData.label
                        elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    MouseArea { id: im; anchors.fill: parent; hoverEnabled: true; onClicked: talk.pickSuggestion(idea.modelData) }
                }
            }
        }
        Rectangle {
            id: comp; x: talk.bar ? 6 : 12; y: (talk.bar ? 6 : 8) + sugg.height; width: parent.width - 2 * x; height: inner.implicitHeight; radius: 20
            color: Theme.glassWell; border.width: 1; border.color: ta.activeFocus ? Theme.alpha(Theme.datum, 0.55) : ch.hovered ? Theme.rule2 : Theme.rule
            Behavior on border.color { Tint {} }
            HoverHandler { id: ch }
            // the prompt: an accent "›" before whatever is typed
            // (22 px mono: its line box is 28.6 px; it stands on the middle of the first line of the prompt, as the caret does)
            Rectangle { id: scope; objectName: "promptScope"; visible: Store.selScope !== "" && sv.contentItem.contentY < 4
                x: 12; y: sv.y + ta.topPadding - 3; height: 26; radius: 13; width: visible ? scopeTxt.implicitWidth + 22 : 0
                color: Theme.alpha(Theme.datum, 0.12); border.width: 1; border.color: Theme.alpha(Theme.datum, 0.22)
                Txt { id: scopeTxt; anchors.centerIn: parent; mono: true; font.pixelSize: 12; color: Theme.strong(Theme.datum); wrapMode: Text.NoWrap; text: Store.selScope }
                HoverHandler { id: sch }
                Tip { show: sch.hovered; text: "Your message goes with what is picked on the part, with its numbers. Clear the selection to ask about the whole design." } }
            Text { x: 16; y: sv.y + ta.topPadding - 5; visible: sv.contentItem.contentY < 4 && !scope.visible; text: "›"; color: Theme.datum; font.family: Theme.mono; font.pixelSize: 22; font.weight: Theme.wBody; renderType: Theme.textRender }
            // the caret, standing in the empty prompt while the keyboard is elsewhere (with it here, the field draws its own)
            Caret { id: restCaret; objectName: "promptCaret"; field: ta; resting: true; x: ta.leftPadding; y: sv.y + ta.topPadding; height: ta.cursorRectangle.height
                visible: !ta.activeFocus && ta.text === "" && ta.enabled }
            Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.alpha(Theme.datum, 0.13)
                opacity: ta.activeFocus ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
            // what an empty prompt says, after the caret: one line, cut with an ellipsis where the controls begin
            Txt { objectName: "promptPlaceholder"; visible: ta.text === "" && ta.preeditText === ""; x: ta.leftPadding + 9; y: sv.y + ta.topPadding + (ta.contentHeight - height) / 2
                width: comp.width - x - ta.rightPadding; elide: Text.ElideRight; wrapMode: Text.NoWrap; lineHeight: 1
                font.pixelSize: ta.font.pixelSize; font.letterSpacing: -0.1; color: Theme.ink3; text: ta.placeholder }
            Column {
                id: inner; width: parent.width
                // a file on its way in
                FetchProgress { x: 12; width: parent.width - 24 }
                // files that go with the next message
                Item { visible: Store.chatAttach.length > 0 || Store.chatLinks.length > 0; width: parent.width; height: visible ? chips.implicitHeight + 10 : 0
                    Flow { id: chips; x: 10; y: 10; width: parent.width - 20; spacing: 6
                        Repeater { model: Store.chatAttach
                            Rectangle { id: chip; objectName: "attachChip"; required property var modelData
                                readonly property bool pic: modelData.kind === "image"
                                width: Math.min(chips.width, (pic ? 30 : 26) + cn.implicitWidth + 30); height: 30; radius: Theme.rSm; color: Theme.plate2; border.color: Theme.rule2
                                Rectangle { visible: chip.pic; x: 3; y: 3; width: 24; height: 24; radius: 4; clip: true; color: Theme.plate
                                    Image { anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 64
                                        source: chip.pic && Store.convId ? Store.attachmentUrl(chip.modelData.file) : "" } }
                                Icon { visible: !chip.pic; x: 8; size: 13; anchors.verticalCenter: parent.verticalCenter; name: chip.modelData.kind === "cad" ? "box" : "file_text" }
                                Txt { id: cn; x: chip.pic ? 33 : 27; width: parent.width - x - 26; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; elide: Text.ElideMiddle; wrapMode: Text.NoWrap; text: chip.modelData.name }
                                Btn { small: true; kind: "quiet"; icon: "x"; anchors.right: parent.right; anchors.rightMargin: 2; anchors.verticalCenter: parent.verticalCenter
                                    tip: chip.modelData.kind === "cad" ? "Remove. The agent is told to import this part as a reference." : "Remove"
                                    onClicked: Store.dropAttachment(chip.modelData.id) } } }
                        // a page link (not a file): it goes with the message; nothing is downloaded
                        Repeater { model: Store.chatLinks
                            Rectangle { id: lchip; objectName: "linkChip"; required property var modelData
                                width: Math.min(chips.width, ln.implicitWidth + 56); height: 30; radius: Theme.rSm; color: Theme.plate2; border.color: Theme.rule2
                                Icon { x: 8; size: 13; anchors.verticalCenter: parent.verticalCenter; name: "globe"; color: Theme.blueprint }
                                Txt { id: ln; x: 27; width: parent.width - x - 26; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                                    text: lchip.modelData.host || lchip.modelData.url }
                                HoverHandler { id: lh }
                                Tip { show: lh.hovered; text: lchip.modelData.url + "\n" + (lchip.modelData.reason ? lchip.modelData.reason + (lchip.modelData.how ? " " + lchip.modelData.how : "") : "A page: it goes with the message as a link. Nothing is downloaded.") }
                                Btn { small: true; kind: "quiet"; icon: "x"; anchors.right: parent.right; anchors.rightMargin: 2; anchors.verticalCenter: parent.verticalCenter
                                    tip: "Remove"; onClicked: Store.dropLink(lchip.modelData.url) } } } } }
                ScrollView {
                    id: sv; width: parent.width; clip: true
                    height: Math.min(220, Math.max(talk.slim ? 52 : talk.bar ? 44 : 2 * 19 + 18, ta.implicitHeight))
                    Behavior on height { NumberAnimation { duration: Theme.move(Theme.fast); easing.type: Easing.OutQuad } }
                    TextArea {
                        id: ta
                        objectName: "composer"
                        // The prompt under the part is a place to write: taking it up leaves the column folded and the part
                        // its room (Store.talkCalm, Focus). Sending brings the conversation back (Store.send).
                        // "Ask about this feature…" from the viewport's context menu lands here
                        Connections { target: Store; function onChatPrefill(text) { Store.talkOpen = true; ta.text = text; ta.cursorPosition = text.length; ta.forceActiveFocus() } }
                        wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: talk.slim ? 14 : 15; font.letterSpacing: -0.1
                        // the caret is the thin accent line of a command line: it stands after the words and blinks once they are still
                        cursorDelegate: Caret { objectName: "composerCaret" }
                        readonly property string placeholder: !Store.chat.available ? "No agent is connected" : Store.chatAsking && Store.chatAsking.free && Store.chatAsking.kind !== "measure" ? "Answer the question above…" : Store.project ? "Ask about " + Store.project.name + ", or describe a change…" : "Describe what you want to make…"
                        enabled: Store.chat.available
                        selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
                        // on one line (slim) the controls stand right of the words, so the words stop before them
                        leftPadding: scope.visible ? scope.width + 24 : 39; rightPadding: talk.slim ? footRow.width + 62 : 14; topPadding: talk.slim ? 17 : 13; bottomPadding: talk.slim ? 16 : 6; background: null; renderType: Theme.textRender
                        function submit() {
                            if (!text.trim()) return
                            if (Store.chatAsking && Store.chatAsking.free && Store.chatAsking.kind !== "measure") { Store.answerAsk(Store.chatAsking.id, text.trim(), []); text = ""; return }
                            if (!Store.chatBusy && Store.chatReady) { Store.sendWithLinks(Store.scoped(text)); text = "" } }
                        Keys.onTabPressed: nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason)
                        Keys.onBacktabPressed: nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason)
                        Keys.onPressed: function (e) {
                            // 1 to 4 pick a suggestion while nothing is typed
                            if (talk.suggOn && text === "" && !(e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) && e.text >= "1" && e.text <= "4") {
                                var sg = talk.forProject[parseInt(e.text) - 1]
                                if (sg) { e.accepted = true; talk.pickSuggestion(sg); return } }
                            if (e.matches(StandardKey.Paste)) {         // a pasted link is fetched like one added on Home; a pasted photo is attached
                                var clip = String(Bridge.clipboardText()).trim()
                                if (/^https?:\/\/\S+$/i.test(clip)) { e.accepted = true; Store.fetchLink(clip); return }
                                if (!clip) { var img = Bridge.clipboardImage(); if (String(img)) { e.accepted = true; Store.attachFiles([img]); return } }
                            }
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; submit() }
                            else if (e.key === Qt.Key_Up && text === "") {            // edit the last message: bring it back
                                var t = Store.lastUserText()
                                if (t) { e.accepted = true; text = t; cursorPosition = t.length }
                            }
                        }
                    }
                }
                // attach, the agent, send: a row under the words, or right of them when the bar is one line
                // (it lies at the foot of the well whatever the column above holds; the column only keeps its room)
                Item { width: parent.width; height: talk.slim ? 0 : 46
                  Item { id: ctl; parent: comp; z: 2; width: comp.width; height: talk.slim ? 52 : 46; y: comp.height - height
                    Row { id: footRow; x: talk.slim ? parent.width - width - 52 : 8; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Btn { small: true; kind: "quiet"; icon: "paperclip"; iconSize: 16; width: 30; height: 30; anchors.verticalCenter: parent.verticalCenter; tip: "Attach a photo, a PDF drawing, or a STEP, STL, 3MF or OBJ part. You can also drop files here, or paste a link."
                            enabled: Store.chat.available; onClicked: Store.ask(pick) }
                        // agent and model for this conversation
                        Item { id: mchip; objectName: "modelChip"; width: ml.width + (talk.slim ? 42 : 55); height: 30; anchors.verticalCenter: parent.verticalCenter
                            Rectangle { anchors.fill: parent; radius: height / 2; color: mcm.pressed ? Theme.washPress : mcm.containsMouse || mpop.opened ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                            Icon { x: 9; name: "sparkles"; size: 15; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                            Txt { id: ml; x: 31; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                                width: Math.min(implicitWidth, comp.width - (talk.slim ? 300 : 190)); elide: Text.ElideRight
                                text: Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) + (Store.chatEffort ? " · " + Store.chatEffort : "") }
                            Icon { visible: !talk.slim; x: ml.x + ml.width + 7; name: "chevron_down"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                            MouseArea { id: mcm; anchors.fill: parent; hoverEnabled: true; onClicked: mpop.opened ? mpop.close() : mpop.open() }
                            Tip { show: mcm.containsMouse && !mpop.opened; text: "Agent and model for this conversation" }
                            Pop {
                                id: mpop; x: -34; width: Math.min(380, talk.width - 24); padding: 6
                                onAboutToShow: mp.reset()
                                onOpened: mp.opened()
                                onClosed: Qt.callLater(function () {     // after a pick in the same moment has had its turn: it sends the message
                                    Store.retryAfterPick = false
                                    if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
                                height: Math.min(mp.implicitHeight + 12, talk.popRoom - 70)
                                y: -height - 6
                                origin: Popup.BottomLeft
                                Flickable { anchors.fill: parent; clip: true; contentHeight: mp.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar { width: 6 }
                                    TalkModelPicker { id: mp; width: parent.width; onDone: mpop.close() } }
                            }
                        }
                    }
                    // send, or stop while a reply is being written: one round button in one place
                    Rectangle { id: sendBtn; objectName: "sendBtn"
                        readonly property bool answering: !!Store.chatAsking && !!Store.chatAsking.free && Store.chatAsking.kind !== "measure" && ta.text.trim() !== ""
                        readonly property bool stops: Store.chatBusy && !answering
                        readonly property bool can: Store.chatBusy || (Store.chatReady && ta.text.trim() !== "")
                        anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                        // send is the one filled thing in the bar; while a reply is written it turns into stop: the disc
                        // goes to glass and the arrow gives way to a square
                        width: 36; height: 36; radius: 18
                        color: stops ? (sbm.containsMouse ? Theme.alpha(Theme.lineBase, 0.22) : Theme.glass2) : can || Store.chatReady ? (sbm.containsMouse ? Theme.sendHi : Theme.send) : Theme.alpha(Theme.lineBase, Theme.dark ? 0.1 : 0.07)
                        border.width: 0
                        scale: sbm.pressed && can ? Theme.from(0.92) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        Behavior on color { Tint {} }
                        Icon { anchors.centerIn: parent; size: 17; name: "corner_down_left"; color: sendBtn.can || Store.chatReady ? Theme.sendInk : Theme.ink4
                            opacity: sendBtn.stops ? 0 : 1; scale: sendBtn.stops ? Theme.from(0.4) : 1; rotation: sendBtn.stops && !Theme.reduced ? -90 : 0
                            Behavior on opacity { Glide { duration: Theme.base } } Behavior on scale { Glide { duration: Theme.base } } Behavior on rotation { Glide { duration: Theme.base } } }
                        Rectangle { anchors.centerIn: parent; width: 11; height: 11; radius: 3; color: Theme.ink
                            opacity: sendBtn.stops ? 1 : 0; scale: sendBtn.stops ? 1 : Theme.from(0.3)
                            Behavior on opacity { Glide { duration: Theme.base } } Behavior on scale { NumberAnimation { duration: Theme.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeSpring } } }
                        // the ring that turns while it can be stopped
                        Rectangle { anchors.fill: parent; radius: 18; color: "transparent"; border.width: 1; border.color: Theme.alpha(Theme.datum, 0.55); visible: sendBtn.stops }
                        MouseArea { id: sbm; anchors.fill: parent; hoverEnabled: true; onClicked: { if (sendBtn.stops) Store.stopChat(); else if (ta.text.trim() === "") ta.forceActiveFocus(); else ta.submit() } }
                        Tip { show: sbm.containsMouse; keys: sendBtn.stops ? "" : "Return"
                            text: sendBtn.answering ? "Send your answer" : Store.chatBusy ? "Stop this reply. What was already committed stays." : sendBtn.can ? "Send" : !Store.chatReady ? "No agent is connected" : "Write a message first" } }
                  }
                }
            }
        }
        Txt { id: hint; kind: "fine"; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: 3
            x: talk.bar ? comp.x + footRow.x + footRow.width + 14 : 16; width: talk.bar ? comp.width - (footRow.x + footRow.width + 14) - 56 : parent.width - 2 * x
            y: talk.bar ? comp.y + comp.height - 23 - height / 2 : comp.y + comp.height + 7; horizontalAlignment: talk.bar ? Text.AlignRight : Text.AlignLeft
            visible: !talk.slim && (!talk.bar || width > 150)
            color: Store.chatAsking ? Theme.amber : Theme.ink3
            text: Store.chatAsking ? (Store.chatAsking.kind === "measure" ? "The agent is waiting for a measurement: answer on the card above." : "The agent is waiting for your answer. Enter sends it.")
                : Store.chatBusy ? "Working. Other conversations can run meanwhile."
                : Store.conv && Store.conv.messages ? "Enter sends · ↑ brings back your last message"
                : "Enter sends · Shift+Enter for a new line · drop files to attach" }
    }

    // drop photos, sketches, PDFs, parts, meshes, scans and zips anywhere on the column
    DropArea {
        id: drop; anchors.fill: parent; z: 5
        onEntered: function (d) { d.accepted = d.hasUrls || (d.hasText && /^https?:\/\/\S+$/i.test(String(d.text).trim())) }
        onDropped: function (d) {
            var files = [], links = []
            for (var i = 0; i < (d.urls || []).length; i++) { var u = String(d.urls[i]); if (/^file:/i.test(u)) files.push(d.urls[i]); else if (/^https?:/i.test(u)) links.push(u) }
            if (!files.length && !links.length && d.hasText && /^https?:\/\/\S+$/i.test(String(d.text).trim())) links.push(String(d.text).trim())
            if (files.length) Store.attachFiles(files)
            links.forEach(function (l) { Store.fetchLink(l) })
            d.accepted = files.length + links.length > 0 }
        Rectangle { anchors.fill: parent; anchors.margins: 6; visible: drop.containsDrag; radius: Theme.rLg
            color: Theme.alpha(Theme.plate, 0.86); border.width: 1; border.color: Theme.datum
            Column { anchors.centerIn: parent; spacing: 8
                Icon { name: "paperclip"; size: 22; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter }
                Txt { text: "Drop to attach"; font.weight: Theme.wSemi; anchors.horizontalCenter: parent.horizontalCenter }
                Txt { kind: "fine"; text: "Photos, PDFs, parts, meshes, scans, zips or a link"; anchors.horizontalCenter: parent.horizontalCenter } } }
    }
}
