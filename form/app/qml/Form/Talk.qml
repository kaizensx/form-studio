import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// The agent column. Conversations are saved and switchable; each message runs the agent you chose (an agent app such
// as Claude Code or Codex, a model provider's API, or a local model) with Form Studio's tools. The same column shows
// what any other agent does to your designs.
Rectangle {
    id: talk
    color: Theme.plate1
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
    Component.onCompleted: sync()

    function liveText() {
        var L = Store.chatLive, who = Store.chatAgentLabel
        if (Store.chatAsking) return who + " is waiting for your answer"
        if (!L) return who + " is thinking…"
        if (L.kind === "tool") return (L.name === "create_design" || L.name === "update_design") ? "Writing design code… " + (L.chars / 1000).toFixed(1) + " kB" : "Calling " + L.name + "…"
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
        for (var a = 0; a < items.length; a++) if (items[a].t === "answer") answers[items[a].id] = items[a]
        for (var i = 0; i < items.length; i++) {
            var ev = items[i]
            if (ev.t === "tool" && ev.name === "suggest_replies") continue      // shown as the follow-up chips, not as a step
            if (ev.t === "tool") {
                if (!group) { group = { t: "steps", k: "s" + i, steps: [] }; out.push(group) }
                group.steps.push({ id: ev.id, tool: ev.name, input: ev.input, ts: ev.ts || 0 })
                continue
            }
            if (ev.t === "start") { model = Store.modelName(ev); agent = ev.agent || ""; continue }
            if (ev.t === "answer") continue
            group = null
            if (ev.t === "ask") {
                var q = { id: ev.id, question: ev.question, choices: ev.choices || [], multi: !!ev.multi, free: ev.free !== false,
                          why: ev.why || "", kind: ev.kind || "question", answer: answers[ev.id] || null,
                          open: !!Store.chatAsking && Store.chatAsking.id === ev.id && !answers[ev.id] }
                if (q.kind === "measure")                // a guided measurement: where, the picture, the unit and tolerance
                    ["project", "param", "unit", "tolerance_mm", "where", "diagram", "image_url", "mark", "current"].forEach(function (f) { q[f] = ev[f] === undefined ? null : ev[f] })
                out.push({ t: "ask", k: "q" + i, q: q })
                continue
            }
            if (ev.t === "suggest") { out.push({ t: "suggest", k: "g" + i, options: ev.options || [] }); continue }
            if (ev.t === "user") out.push({ t: "user", k: "u" + i, text: ev.text, attachments: ev.attachments || [], local: !!ev.local, n: ev.n === undefined ? -1 : ev.n })
            else if (ev.t === "text") out.push({ t: "text", k: "t" + i, text: ev.text, n: ev.n === undefined ? -1 : ev.n })
            else if (ev.t === "act") out.push({ t: "act", k: "a" + i, by: ev.by, text: ev.text })
            else if (ev.t === "end") out.push({ t: "end", k: "e" + i, cost: ev.cost_usd, steps: ev.steps, seconds: ev.seconds, stopped: !!ev.stopped,
                                                model: Store.modelName(ev) || model, agent: ev.agent || agent, change: ev.change || null,
                                                usage: ev.usage || null })
            else if (ev.t === "error") out.push({ t: "error", k: "x" + i, text: ev.text, hint: ev.hint || "" })
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
    function sync() {
        var b = build()
        for (var i = 0; i < b.length; i++) {
            var j = JSON.stringify(b[i])
            if (i < blocks.count) { if (blocks.get(i).j !== j) blocks.set(i, { k: b[i].k, j: j }) }
            else blocks.append({ k: b[i].k, j: j })
        }
        while (blocks.count > b.length) blocks.remove(blocks.count - 1)
    }
    Connections { target: Store
        function onChatItemsChanged() { talk.sync() }
        function onChatBusyChanged() { talk.sync() }
        function onChatAskingChanged() { talk.sync() }
        function onConvIdChanged() { talk.openGroups = ({}); feed.stick = true }
        function onChatFocusChanged() { ta.forceActiveFocus() }
        function onChatRecallChanged() { if (Store.chatRecall) { ta.text = Store.chatRecall; ta.cursorPosition = ta.text.length } } }

    FileDialog { id: pick; title: "Attach files"; fileMode: FileDialog.OpenFiles
        nameFilters: ["Images, PDFs, CAD and meshes (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.pdf *.step *.stp *.stl *.3mf *.obj)"]
        onAccepted: Store.attachFiles(selectedFiles) }
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.rule }

    readonly property int branchCount: Store.convBranches.length
    readonly property int branchAt: { for (var i = 0; i < Store.convBranches.length; i++) if (Store.convBranches[i].id === Store.convId) return i; return -1 }
    // ── header: the conversation switcher ──
    Item {
        id: head; width: parent.width; height: 40; z: 3
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
                visible: !talk.empty || Store.convId !== ""; onClicked: Store.newChat() } }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule }
        Pop {
            id: list; x: 8; y: head.height + 2; width: Math.max(talk.width - 17, 320); padding: 6; origin: Popup.TopLeft
            height: Math.min(cl.implicitHeight + 12, talk.height - 90)
            onOpened: { Store.loadConvs(); cl.reset() }
            Flickable { anchors.fill: parent; clip: true; contentHeight: cl.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { width: 6 }
                ConversationList { id: cl; width: parent.width; onChosen: list.close() } }
        }
    }

    // ── Replace a broken part: where the agent is in the four steps (Store.replaceProgress) ──
    Rectangle { id: rsteps; visible: Store.replaceActive && !talk.empty; z: 2
        anchors.top: head.bottom; width: parent.width - 1; height: visible ? 62 : 0; color: Theme.plate1
        ReplaceSteps { x: 14; y: 9; width: parent.width - 28; done: Store.replaceProgress.done; active: Store.replaceProgress.active }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.rule } }

    // ── nothing open yet: what you can ask ──
    Column {
        id: intro
        visible: talk.empty
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
        visible: talk.empty
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
        id: feed
        property bool stick: true              // follow the newest message unless the reader scrolled up
        property bool auto: false
        visible: !talk.empty
        anchors.top: rsteps.visible ? rsteps.bottom : head.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
        topMargin: 16; bottomMargin: 12; clip: true; spacing: 14
        boundsBehavior: Flickable.StopAtBounds
        model: blocks
        // a new message, step group or footer fades in where it lands; nothing moves, so the feed never jumps
        // and rises the last few pixels into place (a transform, so the rows around it never re-lay out)
        add: Transition { ParallelAnimation { Glide { property: "opacity"; from: 0; to: 1; duration: Theme.base }
            Glide { property: "rise"; from: Theme.shift(Theme.rise); to: 0; duration: Theme.move(Theme.panel) } } }
        function toEnd() { if (!stick) return; auto = true; positionViewAtEnd(); auto = false }
        onContentHeightChanged: Qt.callLater(toEnd)
        onHeightChanged: Qt.callLater(toEnd)
        onContentYChanged: if (!auto) stick = atYEnd || contentHeight <= height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }
        delegate: Item {
            id: it
            required property string j
            required property string k
            required property int index
            property real rise: 0
            transform: Translate { y: it.rise }
            readonly property var m: JSON.parse(j)
            width: feed.width; implicitHeight: body.item ? body.item.implicitHeight : 0; height: implicitHeight
            HoverHandler { id: hh }
            Loader { id: body; x: 16; width: parent.width - 32
                sourceComponent: it.m.t === "user" ? cUser : it.m.t === "text" ? cText : it.m.t === "steps" ? cSteps : it.m.t === "act" ? cAct
                               : it.m.t === "end" ? cEnd : it.m.t === "ask" ? cAsk : it.m.t === "suggest" ? cSuggest : cErr }
            // actions on hover: copy, fork from here, and for your own message, edit and send again
            Rectangle { readonly property bool want: (hh.hovered || cb.hovered || eb.hovered || fb.hovered) && (it.m.t === "user" || it.m.t === "text") && !it.m.local
                opacity: want ? 1 : 0; visible: opacity > 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                z: 2; anchors.right: parent.right; anchors.rightMargin: 14; y: it.m.t === "user" ? it.height - 6 : -10
                width: ar.implicitWidth + 4; height: 26; radius: Theme.rSm + 1; color: Theme.plate3; border.color: Theme.rule2
                Row { id: ar; anchors.centerIn: parent
                    Btn { id: cb; small: true; kind: "quiet"; icon: "copy"; tip: "Copy"; onClicked: { Bridge.copy(it.m.text); Store.toast("Copied") } }
                    Btn { id: fb; objectName: "msgFork"; small: true; kind: "quiet"; icon: "git_branch"; tip: "Fork from here: a new branch with the conversation up to this message"
                        visible: it.m.n >= 0 && !Store.chatBusy; onClicked: Store.forkConv(it.m.n) }
                    Btn { id: eb; small: true; kind: "quiet"; icon: "pencil"; tip: "Edit and send again"; visible: it.m.t === "user"; onClicked: Store.recallChat(it.m.text) } } }

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
            Component { id: cText; Md { id: rt; objectName: "replyText"; source: it.m.text; width: body.width; revs: true
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
            Component { id: cAct; Row { spacing: 6
                Icon { name: "zap"; size: 12; color: Theme.blueprint; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; width: body.width - 20; text: it.m.by + "  " + it.m.text; color: Theme.ink2 } } }
            Component { id: cEnd; Column { spacing: 8
              Item { width: body.width; height: 22
                Txt { id: ft; kind: "fine"; mono: true; tone: 3; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, parent.width - (rb.visible ? rb.width + 6 : 0)); elide: Text.ElideRight; wrapMode: Text.NoWrap
                    text: (it.m.stopped ? "stopped · " : "") + F.plural(it.m.steps || 0, "step") + " · " + talk.secs(it.m.seconds)
                        + talk.costText(it.m) + (it.m.model ? " · " + it.m.model : "") }
                Row { id: rb; visible: !!it.m.last; spacing: 2; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    Btn { small: true; kind: "quiet"; icon: "repeat"; tip: "Send it again with another model"; onClicked: talk.tryAnother() }
                    Btn { small: true; kind: "quiet"; icon: "rotate_cw"; tip: "Send your last message again"; onClicked: Store.retryChat() } } }
              // what this reply changed in the design: compare it, or go back
              TalkChange { visible: !!it.m.change; width: body.width; change: it.m.change } } }
            Component { id: cErr; Column { spacing: 6
                Note { kind: "red"; text: it.m.text + (it.m.hint ? "\n" + it.m.hint : ""); width: body.width }
                Row { visible: !!it.m.last; spacing: 6
                    Btn { small: true; icon: "rotate_cw"; text: "Retry"; onClicked: Store.retryChat() }
                    Btn { small: true; kind: "quiet"; icon: "repeat"; text: "Try another model…"; onClicked: talk.tryAnother() } } } }
        }
        // what is being written right now
        footer: Item { width: feed.width; visible: Store.chatBusy; height: Store.chatBusy ? lc.implicitHeight + 18 : 0
            Column { id: lc; x: 16; y: 10; width: parent.width - 32; spacing: 10
                // the reply as it is written: the block grows smoothly instead of jumping a line at a time
                Item { visible: !!Store.chatLive && Store.chatLive.kind === "text" && Store.chatLive.text !== ""; width: parent.width; clip: true
                    height: visible ? lt.implicitHeight : 0
                    Behavior on height { enabled: Store.chatBusy; NumberAnimation { duration: Theme.move(140); easing.type: Easing.OutQuad } }
                    Md { id: lt; source: Store.chatLive && Store.chatLive.text ? Store.chatLive.text : ""; width: parent.width } }
                Row { spacing: 8
                    Row { spacing: 3; anchors.verticalCenter: parent.verticalCenter
                        Repeater { model: 3
                            Rectangle { required property int index; width: 4; height: 4; radius: 2; color: Theme.datum
                                SequentialAnimation on opacity { running: Store.chatBusy; loops: Animation.Infinite
                                    PauseAnimation { duration: index * 160 } NumberAnimation { from: 0.25; to: 1; duration: 320 } NumberAnimation { to: 0.25; duration: 320 } PauseAnimation { duration: (2 - index) * 160 } } } } }
                    Txt { kind: "fine"; text: talk.liveText(); elide: Text.ElideRight; wrapMode: Text.NoWrap }
                    Txt { kind: "fine"; mono: true; tone: 4; visible: Store.chatSeconds >= 1; text: talk.secs(Store.chatSeconds) } } } }
    }

    // ── composer ──
    Item {
        id: foot; width: parent.width; height: comp.height + 36; z: 2
        y: talk.height - height
        Rectangle {
            id: comp; x: 12; y: 8; width: parent.width - 2 * x; height: inner.implicitHeight; radius: Theme.rLg
            color: Theme.well; border.width: 1; border.color: ta.activeFocus ? Theme.alpha(Theme.datum, 0.7) : ch.hovered ? Theme.rule3 : Theme.rule2
            Behavior on border.color { Tint {} }
            HoverHandler { id: ch }
            Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3; border.color: Theme.alpha(Theme.datum, 0.13)
                opacity: ta.activeFocus ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
            Column {
                id: inner; width: parent.width
                // files that go with the next message
                Item { visible: Store.chatAttach.length > 0; width: parent.width; height: visible ? chips.implicitHeight + 10 : 0
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
                                    onClicked: Store.dropAttachment(chip.modelData.id) } } } } }
                ScrollView {
                    width: parent.width; clip: true
                    height: Math.min(220, Math.max(2 * 19 + 18, ta.implicitHeight))
                    Behavior on height { NumberAnimation { duration: Theme.move(Theme.fast); easing.type: Easing.OutQuad } }
                    TextArea {
                        id: ta
                        objectName: "composer"
                        // "Ask about this feature…" from the viewport's context menu lands here
                        Connections { target: Store; function onChatPrefill(text) { Store.talkOpen = true; ta.text = text; ta.cursorPosition = text.length; ta.forceActiveFocus() } }
                        wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: 13
                        placeholderText: !Store.chat.available ? "No agent is connected" : Store.chatAsking && Store.chatAsking.free && Store.chatAsking.kind !== "measure" ? "Answer the question above…" : Store.project ? "Ask about " + Store.project.name + ", or describe a change…" : "Describe what you want to make…"
                        placeholderTextColor: Theme.ink4; enabled: Store.chat.available
                        selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
                        leftPadding: 12; rightPadding: 12; topPadding: 10; bottomPadding: 6; background: null; renderType: Text.NativeRendering
                        function submit() {
                            if (!text.trim()) return
                            if (Store.chatAsking && Store.chatAsking.free && Store.chatAsking.kind !== "measure") { Store.answerAsk(Store.chatAsking.id, text.trim(), []); text = ""; return }
                            if (!Store.chatBusy && Store.chatReady) { Store.send(text); text = "" } }
                        Keys.onTabPressed: nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason)
                        Keys.onBacktabPressed: nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason)
                        Keys.onPressed: function (e) {
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; submit() }
                            else if (e.key === Qt.Key_Up && text === "") {            // edit the last message: bring it back
                                var t = Store.lastUserText()
                                if (t) { e.accepted = true; text = t; cursorPosition = t.length }
                            }
                        }
                    }
                }
                Item { width: parent.width; height: 38
                    Row { x: 6; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Btn { small: true; kind: "quiet"; icon: "paperclip"; tip: "Attach a photo, sketch, PDF, or a STEP/STL part. You can also drop files here."
                            enabled: Store.chat.available; onClicked: Store.ask(pick) }
                        // agent and model for this conversation
                        Item { id: mchip; objectName: "modelChip"; width: ml.width + 31; height: 24
                            Rectangle { anchors.fill: parent; radius: Theme.rSm; color: mcm.pressed ? Theme.washPress : mcm.containsMouse || mpop.opened ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
                            Txt { id: ml; x: 7; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                                width: Math.min(implicitWidth, comp.width - 170); elide: Text.ElideRight
                                text: Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) + (Store.chatEffort ? " · " + Store.chatEffort : "") }
                            Icon { x: ml.width + 12; name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                            MouseArea { id: mcm; anchors.fill: parent; hoverEnabled: true; onClicked: mpop.opened ? mpop.close() : mpop.open() }
                            Tip { show: mcm.containsMouse && !mpop.opened; text: "Agent and model for this conversation" }
                            Pop {
                                id: mpop; x: -34; width: Math.min(380, talk.width - 24); padding: 6
                                onAboutToShow: mp.reset()
                                onOpened: mp.opened()
                                onClosed: Qt.callLater(function () {     // after a pick in the same moment has had its turn: it sends the message
                                    Store.retryAfterPick = false
                                    if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
                                height: Math.min(mp.implicitHeight + 12, talk.height - 70)
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
                        width: 28; height: 28; radius: 14
                        color: stops ? (sbm.containsMouse ? Theme.plate4 : Theme.plate3) : can ? (sbm.containsMouse ? Theme.datumHi : Theme.datum) : Theme.plate3
                        border.width: stops ? 1 : 0; border.color: Theme.rule2
                        scale: sbm.pressed && can ? Theme.from(0.92) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        Behavior on color { Tint {} }
                        Icon { anchors.centerIn: parent; size: sendBtn.stops ? 11 : 15; name: sendBtn.stops ? "square" : "arrow_up"
                            color: sendBtn.stops ? Theme.ink : sendBtn.can ? Theme.datumInk : Theme.ink4 }
                        MouseArea { id: sbm; anchors.fill: parent; hoverEnabled: true; onClicked: sendBtn.stops ? Store.stopChat() : ta.submit() }
                        Tip { show: sbm.containsMouse; keys: sendBtn.stops ? "" : "Return"
                            text: sendBtn.answering ? "Send your answer" : Store.chatBusy ? "Stop this reply. What was already committed stays." : sendBtn.can ? "Send" : !Store.chatReady ? "No agent is connected" : "Write a message first" } }
                }
            }
        }
        Txt { kind: "fine"; x: 16; anchors.top: comp.bottom; anchors.topMargin: 7; width: parent.width - 2 * x; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: 3
            color: Store.chatAsking ? Theme.amber : Theme.ink3
            text: Store.chatAsking ? (Store.chatAsking.kind === "measure" ? "The agent is waiting for a measurement: answer on the card above." : "The agent is waiting for your answer. Enter sends it.")
                : Store.chatBusy ? "Working. Other conversations can run meanwhile."
                : Store.conv && Store.conv.messages ? "Enter sends · ↑ brings back your last message"
                : "Enter sends · Shift+Enter for a new line · drop files to attach" }
    }

    // drop photos, sketches, PDFs, STEP/STL anywhere on the column
    DropArea {
        id: drop; anchors.fill: parent; z: 5
        onEntered: function (d) { d.accepted = d.hasUrls }
        onDropped: function (d) { if (d.hasUrls) { Store.attachFiles(d.urls); d.accepted = true } }
        Rectangle { anchors.fill: parent; anchors.margins: 6; visible: drop.containsDrag; radius: Theme.rLg
            color: Theme.alpha(Theme.plate, 0.86); border.width: 1; border.color: Theme.datum
            Column { anchors.centerIn: parent; spacing: 8
                Icon { name: "paperclip"; size: 22; color: Theme.datum; anchors.horizontalCenter: parent.horizontalCenter }
                Txt { text: "Drop to attach"; font.weight: Theme.wSemi; anchors.horizontalCenter: parent.horizontalCenter }
                Txt { kind: "fine"; text: "Images, PDFs, STEP or STL"; anchors.horizontalCenter: parent.horizontalCenter } } }
    }
}
