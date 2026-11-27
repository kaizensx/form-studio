import QtQuick
import FormNative
import QtQuick.Controls
import QtQuick.Dialogs
import "F.js" as F

// Home's composer: the one place a design starts. Words, a photo, a sketch, a part or a drawing, a link; the agent
// turns whatever is here into real CAD. Files and sketches attach to the conversation as soon as they are added, so
// what the agent receives is exactly what is on the card. Sending opens the workspace at once (Store.startDesign).
// Lightdesk: one pane of glass. In it the prompt well (a "›", the caret, the words, the tools and Design it)
// and, under the well, the numbered ways to start. 1, 2 and 3 pick them while the composer is empty.
Item {
    id: sc
    objectName: "startComposer"
    property bool dragging: false              // a file is being dragged over Home
    property bool linking: false               // the link field is open
    property var latest: null                  // the design changed last, offered as "Continue …" (null: none yet)
    readonly property alias area: ta
    readonly property bool hasAny: ta.text.trim() !== "" || Store.chatAttach.length > 0 || Store.chatLinks.length > 0
    readonly property bool can: hasAny && Store.chatReady && !Store.chatBusy
    readonly property bool narrow: width < 620
    signal sketchWanted()
    function submit() { if (!can) return; var t = ta.text; ta.text = ""; Store.startDesign(t) }
    // the numbered starts: 1 Start blank, 2 Replace a broken part, 3 Continue the design changed last
    function start(n) {
        if (n === 1) Store.startBlank()
        else if (n === 2) Store.openSheet("replace")
        else if (n === 3 && sc.latest) Store.open(sc.latest.id)
        else return false
        return true
    }

    implicitHeight: col.implicitHeight + 12
    // the pane: thin glass (it scrolls with the page, so nothing is blurred), its edge of light and a soft shadow
    Shadow { radius: 30; spread: 40; drop: 20; strength: Theme.dark ? 0.9 : 0.45 }
    Glass { anchors.fill: parent; flat: true; radius: 30 }

    FileDialog { id: pick; title: "Add a photo, a part or a drawing"; fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos, parts and drawings (*.png *.jpg *.jpeg *.webp *.heic *.gif *.bmp *.pdf *.step *.stp *.stl *.3mf)"]
        onAccepted: Store.attachFiles(selectedFiles) }
    Connections { target: Store; function onStartFocusChanged() { ta.forceActiveFocus() } }

    // one numbered way to start: the key square, then what it does. It lifts a little under the pointer.
    component Chip: Item {
        id: chip
        property string k: ""
        property string text: ""
        property string tip: ""
        property bool quiet: false
        signal clicked()
        readonly property real full: 10 + 20 + 11 + Math.ceil(lblM.advanceWidth) + 1 + 12
        implicitWidth: full; implicitHeight: 34; width: implicitWidth; height: 34
        activeFocusOnTab: true
        Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; chip.clicked() } }
        TextMetrics { id: lblM; font: lbl.font; text: chip.text }
        Item { id: body; width: parent.width; height: parent.height
            transform: Translate { y: cm.containsMouse && !cm.pressed ? -Theme.shift(1) : 0; Behavior on y { Glide { duration: Theme.fast } } }
            Shadow { radius: 12; spread: 12; drop: 5; strength: 0.55; opacity: cm.containsMouse && !cm.pressed ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
            Rectangle { anchors.fill: parent; radius: 12
                color: cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.alpha(Theme.lineBase, Theme.dark ? 0.1 : 0.06) : "transparent"
                Behavior on color { Tint {} } }
            Rectangle { id: key; x: 10; width: 20; height: 20; radius: 6; anchors.verticalCenter: parent.verticalCenter
                color: Theme.glass2; border.width: Theme.dark ? 0 : 1; border.color: Theme.rule2
                Rectangle { visible: Theme.dark; x: 5; width: 10; y: 0; height: 1; color: Theme.gleam }
                Text { anchors.centerIn: parent; text: chip.k; color: Theme.ink2; renderType: Theme.textRender
                    font.family: Theme.mono; font.pixelSize: 11; font.weight: Theme.wMedium } }
            Text { id: lbl; x: 41; width: Math.max(0, parent.width - 41 - 12); anchors.verticalCenter: parent.verticalCenter
                text: chip.text; elide: Text.ElideRight; renderType: Theme.textRender
                font.family: Theme.sans; font.pixelSize: 13; font.letterSpacing: -0.1
                color: chip.quiet && !cm.containsMouse ? Theme.ink2 : Theme.ink
                Behavior on color { Tint {} } } }
        FocusRing { on: chip.activeFocus; radius: 14 }
        MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
        Tip { show: cm.containsMouse && chip.tip !== "" && !cm.pressed; text: chip.tip }
    }

    Column {
        id: col; x: 6; y: 6; width: parent.width - 12

        // ════ the well: what you say, what goes with it, and Design it ════
        Rectangle {
            id: well; width: parent.width; height: wellCol.implicitHeight; radius: 24
            color: Theme.glassWell; border.width: 1
            border.color: sc.dragging ? Theme.alpha(Theme.datum, 0.85) : ta.activeFocus ? Theme.alpha(Theme.datum, 0.45) : Theme.rule
            Behavior on border.color { Tint {} }
            // dragging a file over Home: a soft ring of the accent, the well "receiving" it
            Rectangle { anchors.fill: parent; anchors.margins: -3; radius: parent.radius + 3; color: "transparent"; border.width: 3
                border.color: Theme.alpha(Theme.datum, 0.2); opacity: sc.dragging ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.base } } }

            Column {
                id: wellCol; width: parent.width

                FetchProgress { x: 18; width: parent.width - 36 }
                // ── what goes with the words: photos large enough to recognise, parts and drawings, sketches, links ──
                Item { visible: Store.chatAttach.length > 0 || Store.chatLinks.length > 0; width: parent.width; height: visible ? shelf.implicitHeight + 16 : 0
                    Flow { id: shelf; objectName: "startShelf"; x: 16; y: 16; width: parent.width - 32; spacing: 8
                        Repeater { model: Store.chatAttach
                            Rectangle { id: att; objectName: "startAttachment"; required property var modelData; required property int index
                                readonly property bool pic: modelData.kind === "image"
                                readonly property string label: modelData.kind === "sketch" ? "Sketch" : modelData.name
                                width: pic ? 72 : Math.min(shelf.width, an.implicitWidth + 60); height: pic ? 72 : 40; radius: Theme.rMd + 1
                                color: Theme.glass; border.color: am.hovered ? Theme.rule3 : Theme.rule2; clip: true
                                opacity: 0; scale: Theme.from(0.94)
                                Component.onCompleted: attIn.start()
                                ParallelAnimation { id: attIn; Glide { target: att; property: "opacity"; to: 1; duration: Theme.base } Glide { target: att; property: "scale"; to: 1; duration: Theme.base } }
                                Image { visible: att.pic; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                                    source: att.pic && Store.convId ? Store.attachmentUrl(att.modelData.file) : "" }
                                Rectangle { visible: !att.pic; x: 6; width: 28; height: 28; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
                                    color: att.modelData.kind === "sketch" ? Theme.alpha(Theme.datum, 0.14) : Theme.glass2
                                    Icon { anchors.centerIn: parent; size: 14; color: att.modelData.kind === "sketch" ? Theme.datum : Theme.ink2
                                        name: att.modelData.kind === "cad" ? "cuboid" : att.modelData.kind === "pdf" ? "file_text" : att.modelData.kind === "sketch" ? "pen_tool" : "file" } }
                                Column { visible: !att.pic; x: 42; width: parent.width - 66; anchors.verticalCenter: parent.verticalCenter; spacing: 0
                                    Txt { id: an; text: att.label; font.pixelSize: 12; font.weight: Theme.wMedium; width: Math.min(implicitWidth, 220); elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                                    Txt { kind: "fine"; tone: 3; wrapMode: Text.NoWrap
                                        text: att.modelData.kind === "cad" ? "Part · " + F.bytes(att.modelData.size) : att.modelData.kind === "pdf" ? "Drawing · " + F.bytes(att.modelData.size)
                                            : att.modelData.kind === "sketch" ? "Shapes and dimensions" : F.bytes(att.modelData.size) } }
                                HoverHandler { id: am }
                                Rectangle { visible: am.hovered; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: att.pic ? 4 : 6; width: 20; height: 20; radius: 10
                                    color: xm.containsMouse ? Theme.plate4 : Theme.alpha(Theme.plate, 0.85); border.color: Theme.rule2
                                    Icon { anchors.centerIn: parent; name: "x"; size: 11; color: Theme.ink }
                                    MouseArea { id: xm; anchors.fill: parent; hoverEnabled: true; onClicked: Store.dropAttachment(att.modelData.id) } }
                                Tip { show: am.hovered; text: att.modelData.kind === "image" ? att.modelData.name + ". The agent reads it; any size it takes from it is marked estimated."
                                        : att.modelData.kind === "cad" ? att.modelData.name + ". A part to design around, or a mesh to change."
                                        : att.modelData.kind === "sketch" ? "Your sketch, as shapes with dimensions in mm, and its picture." : att.modelData.name } } }
                        Repeater { model: Store.chatLinks
                            Rectangle { id: lk; objectName: "startLink"; required property var modelData
                                width: Math.min(shelf.width, lt.implicitWidth + 64); height: 40; radius: Theme.rMd + 1; color: Theme.glass; border.color: lkm.hovered ? Theme.rule3 : Theme.rule2
                                Rectangle { x: 6; width: 28; height: 28; radius: Theme.rSm; color: Theme.glass2; anchors.verticalCenter: parent.verticalCenter
                                    Icon { anchors.centerIn: parent; name: "globe"; size: 14; color: Theme.blueprint } }
                                Column { id: lt; x: 42; anchors.verticalCenter: parent.verticalCenter; spacing: 0
                                    Txt { text: lk.modelData.host; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap }
                                    Txt { kind: "fine"; tone: 3; text: "Link · passed on, nothing downloaded"; wrapMode: Text.NoWrap } }
                                HoverHandler { id: lkm }
                                Btn { small: true; kind: "quiet"; icon: "x"; tip: "Remove"; anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
                                    visible: lkm.hovered; onClicked: Store.dropLink(lk.modelData.url) }
                                Tip { show: lkm.hovered; text: lk.modelData.url } } } } }

                // ── the words: "›", then what you type ──
                Item { id: words; width: parent.width; height: Math.min(260, Math.max(sc.narrow ? 70 : 80, ta.implicitHeight))
                    readonly property int pad: sc.narrow ? 16 : 22
                    readonly property int line: 26                      // the first line's height: the prompt, the caret and the words share it
                    readonly property real textX: pad + gt.width + 12
                    readonly property bool empty: ta.text === "" && !ta.preeditText
                    Behavior on height { NumberAnimation { duration: Theme.move(Theme.fast); easing.type: Easing.OutQuad } }
                    Text { id: gt; x: words.pad; y: 20 + Math.round((words.line - height) / 2) + 1; text: "›"; color: Theme.datum; renderType: Theme.textRender
                        font.family: Theme.mono; font.pixelSize: 24; font.weight: Theme.wMedium }
                    // the caret, standing in the empty field while the keyboard is elsewhere (with it here, the field draws its own)
                    Caret { id: caret; objectName: "startCaret"; field: ta; resting: true; visible: words.empty && !ta.activeFocus; x: words.textX; y: 21; height: ta.cursorRectangle.height }
                    ScrollView { anchors.fill: parent; clip: true
                        TextArea {
                            id: ta
                            objectName: "startText"
                            wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: sc.narrow ? 16 : 19; font.letterSpacing: -0.2
                            selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
                            leftPadding: words.textX; rightPadding: 22; topPadding: 21; bottomPadding: 8; background: null; renderType: Theme.textRender
                            enabled: !!Store.studio
                            // the caret: the thin accent line of a command line, after the words and blinking once they are still
                            cursorDelegate: Caret { objectName: "startCursor" }
                            Keys.onTabPressed: nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason)
                            Keys.onBacktabPressed: nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason)
                            Keys.onPressed: function (e) {
                                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; sc.submit() }
                                // 1, 2, 3 on an empty composer pick the numbered starts under it
                                else if (!sc.hasAny && ta.text === "" && e.key >= Qt.Key_1 && e.key <= Qt.Key_3 && !(e.modifiers & ~Qt.KeypadModifier)) {
                                    if (sc.start(e.key - Qt.Key_0)) e.accepted = true }
                                else if (e.matches(StandardKey.Paste)) {
                                    var clip = String(Bridge.clipboardText()).trim()
                                    if (/^https?:\/\/\S+$/i.test(clip)) { e.accepted = true; Store.fetchLink(clip) }        // a pasted link is a link, not words
                                    else if (!clip) { var img = Bridge.clipboardImage(); if (String(img)) { e.accepted = true; Store.attachFiles([img]) } }   // a pasted photo
                                }
                            }
                        }
                    }
                    // the placeholder: examples of what can be said, changing slowly while the field is empty
                    Txt { id: ph; x: words.textX + 9; y: 20; height: words.line; width: parent.width - x - 22; visible: words.empty
                        verticalAlignment: Text.AlignVCenter; lineHeight: 1.0
                        font.pixelSize: ta.font.pixelSize; font.letterSpacing: -0.2; color: Theme.ink3; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        property int n: 0
                        readonly property var lines: !Store.chatReady && Store.studio ? ["No agent is connected. Start blank, or connect one in Settings › Agents & models."]
                            : ["Describe it, or drop a photo, a sketch, a part or a link…",
                               "A planetary gearbox for a NEMA 17 motor, about 1:16",
                               "A case for the board in this STEP file, with a snap lid",
                               "An ergonomic handle shaped to the palm, with a soft taper",
                               "A knob like the one in my photo, with a 6 mm D-shaft"]
                        text: lines[n % lines.length]
                        Timer { interval: 4200; repeat: true; running: ph.visible && ph.lines.length > 1 && !ta.activeFocus
                            onTriggered: phSwap.start() }
                        SequentialAnimation { id: phSwap
                            NumberAnimation { target: ph; property: "opacity"; to: 0; duration: 260; easing.type: Easing.InQuad }
                            ScriptAction { script: ph.n++ }
                            NumberAnimation { target: ph; property: "opacity"; to: 1; duration: 420; easing.type: Easing.OutCubic } } }
                }

                // ── a link, typed or pasted ──
                Item { visible: sc.linking; width: parent.width; height: visible ? 44 : 0
                    Field { id: lf; objectName: "startLinkField"; x: 16; width: parent.width - 32 - lgo.width - 8; anchors.verticalCenter: parent.verticalCenter
                        placeholder: "https://… a model page, or a direct STL, STEP, 3MF or PDF link"
                        onAccepted: function (t) { sc.addLink(t) }
                        Keys.onEscapePressed: { sc.linking = false; ta.forceActiveFocus() } }
                    Btn { id: lgo; objectName: "startLinkAdd"; kind: "primary"; small: true; text: "Add"; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                        enabled: lf.text.trim() !== ""; onClicked: sc.addLink(lf.text) } }

                // ── the tools, and Design it ──
                Item { width: parent.width; height: 54
                    Row { id: tools; x: words.pad - 13; y: 7; spacing: -2
                        Btn { objectName: "startAdd"; kind: "quiet"; icon: "paperclip"; text: sc.narrow ? "" : "Photo or file"; tip: "A photo (with a card, a coin or a ruler in it for scale), a STEP, STL or 3MF part, or a PDF drawing. You can also drop them anywhere here."
                            onClicked: Store.ask(pick) }
                        Btn { objectName: "startSketch"; kind: "quiet"; icon: "pencil"; text: sc.narrow ? "" : "Sketch"; tip: "Draw it: lines, rectangles, circles, arcs and dimensions in millimetres"
                            onClicked: sc.sketchWanted() }
                        Btn { objectName: "startLinkBtn"; kind: "quiet"; icon: "link"; text: sc.narrow ? "" : "Link"; active: sc.linking
                            tip: "A model page (Printables, Thingiverse…) or a direct link to an STL, STEP, 3MF or PDF. Only a file you link is downloaded."
                            onClicked: { sc.linking = !sc.linking; if (sc.linking) lf.input.forceActiveFocus(); else ta.forceActiveFocus() } }
                        Btn { kind: "quiet"; icon: "mic"; tip: Theme.mac ? "Speak instead of typing: press Fn twice (macOS dictation), then talk" : "Speak instead of typing: Windows+H starts dictation in this field"
                            onClicked: { ta.forceActiveFocus(); Store.toast("Dictation", Theme.mac ? "Press Fn twice and speak; the words go into the field." : "Press Windows+H and speak; the words go into the field.") } } }
                    // the agent and model that design it: the same chip as the conversation's composer (Talk.qml), beside
                    // Design it. What is picked here is what the request is sent with. Without an agent it says so and
                    // opens Settings › Agents & models. Its words shorten before the tools on the left are covered.
                    Item { id: mchip; objectName: "startModel"
                        readonly property real room: go.x - 6 - (tools.x + tools.width + 4)          // between the tools and Design it
                        readonly property bool bare: room < 55 + 56                                   // only the icon and the chevron fit
                        width: (bare ? 0 : ml.width) + (bare ? 48 : 55); height: 30; x: go.x - 6 - width; y: 7
                        visible: !!Store.studio && room >= 48
                        activeFocusOnTab: true
                        function act() { if (!Store.chatReady) Store.openSettings("agents"); else if (mpop.opened) mpop.close(); else mpop.open() }
                        Keys.onPressed: function (e) { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { e.accepted = true; mchip.act() } }
                        // (one thing more than the conversation's chip: a hairline at rest, so on Home it reads as a control)
                        Rectangle { anchors.fill: parent; radius: height / 2; color: mcm.pressed ? Theme.washPress : mcm.containsMouse || mpop.opened ? Theme.washHover : "transparent"; Behavior on color { Tint {} }
                            border.width: 1; border.color: Theme.rule2 }
                        Icon { x: 9; name: "sparkles"; size: 15; color: Theme.ink2; anchors.verticalCenter: parent.verticalCenter }
                        Txt { id: ml; objectName: "startModelLabel"; visible: !mchip.bare; x: 31; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(Math.ceil(implicitWidth), Math.max(0, mchip.room - 55)); elide: Text.ElideRight
                            text: !Store.chatReady ? "Connect an agent"
                                : Store.chatAgentLabel + " · " + Store.modelShort(Store.chatAgent, Store.chatModel) + (Store.chatEffort ? " · " + Store.chatEffort : "") }
                        Icon { x: mchip.bare ? 29 : ml.x + ml.width + 7; name: Store.chatReady ? "chevron_down" : "chevron_right"; size: 13; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                        FocusRing { on: mchip.activeFocus; radius: 15 }
                        MouseArea { id: mcm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: mchip.act() }
                        Tip { show: mcm.containsMouse && !mpop.opened
                            text: Store.chatReady ? "The agent and model that design it. Click to change them." : "No agent is connected: add one in Settings › Agents & models" }
                        Pop {
                            id: mpop; objectName: "startModelPop"; width: 380; padding: 6
                            // under the chip, its right edge on the chip's; above it when there is more room there
                            property bool up: false
                            x: Math.round(parent.width - width); y: up ? -height - 6 : parent.height + 6
                            origin: up ? Popup.BottomRight : Popup.TopRight
                            height: Math.min(mp.implicitHeight + 12, (sc.Window.height || 800) * 0.6)
                            onAboutToShow: { var at = mchip.mapToItem(null, 0, 0).y, h = sc.Window.height || 800
                                up = h - (at + mchip.height + 6) - 8 < height && at - 6 - 8 > h - (at + mchip.height + 6) - 8
                                mp.reset() }
                            onOpened: mp.opened()
                            onClosed: Qt.callLater(function () {
                                Store.retryAfterPick = false
                                if (Store.pendingSend) { Store.chatPrefill(Store.pendingSend); Store.pendingSend = "" } })
                            Flickable { anchors.fill: parent; clip: true; contentHeight: mp.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: ScrollBar { width: 6 }
                                TalkModelPicker { id: mp; width: parent.width; onDone: mpop.close() } } } }
                    // the one filled button. It is lit whenever an agent can take the request; with nothing written
                    // yet a click puts the cursor in the field.
                    Rectangle { id: go; objectName: "startSend"
                        readonly property bool lit: Store.chatReady && !Store.chatBusy
                        anchors.right: parent.right; anchors.rightMargin: 10; y: 0
                        width: gl.implicitWidth + 40; height: 44; radius: 22
                        color: !lit ? Theme.alpha(Theme.lineBase, Theme.dark ? 0.1 : 0.07) : gm.pressed ? Qt.darker(Theme.send, 1.08) : gm.containsMouse ? Theme.sendHi : Theme.send
                        scale: gm.pressed && lit ? Theme.from(0.97) : 1
                        Behavior on scale { Glide { duration: Theme.press } }
                        Behavior on color { Tint {} }
                        Rectangle { visible: go.lit; x: parent.radius; width: parent.width - 2 * parent.radius; y: 1; height: 1; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.5 : 0.16) }
                        Row { id: gl; x: 22; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            Text { text: "Design it"; color: go.lit ? Theme.sendInk : Theme.ink4; anchors.verticalCenter: parent.verticalCenter; renderType: Theme.textRender
                                font.family: Theme.sans; font.pixelSize: 14; font.weight: Theme.wSemi; font.letterSpacing: -0.1 }
                            Icon { name: "corner_down_left"; size: 15; color: go.lit ? Theme.sendInk : Theme.ink4; anchors.verticalCenter: parent.verticalCenter } }
                        MouseArea { id: gm; anchors.fill: parent; hoverEnabled: true; cursorShape: go.lit ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: { if (sc.can) sc.submit(); else ta.forceActiveFocus() } }
                        Tip { show: gm.containsMouse; keys: sc.can ? "Return" : ""
                            text: !Store.chatReady ? "No agent is connected" : Store.chatBusy ? "The agent is still answering" : sc.can ? "The agent designs it; the workspace opens now and the part appears as it is built" : "Write what it is, or add a photo, sketch, file or link" } }
                }
            }
        }

        // ════ other ways in, numbered: an empty studio, a replacement for a broken part, the design you were on ════
        Item { id: starts; objectName: "startAlternatives"; width: parent.width; height: 42
            Chip { id: c1; objectName: "startBlank"; x: 4; y: 6; k: "1"; text: "Start blank"
                tip: "An empty studio and the workspace. Describe, sketch or import what goes in it."
                onClicked: sc.start(1) }
            Chip { id: c2; objectName: "startReplace"; x: c1.x + c1.width + 10; y: 6; k: "2"; text: "Replace a broken part"
                tip: "From a photo: the agent estimates sizes, asks you for the ones that matter, then designs the new part."
                onClicked: sc.start(2) }
            Chip { id: c3; objectName: "homeContinue"; visible: !!sc.latest && width > 90; x: c2.x + c2.width + 10; y: 6; k: "3"; quiet: true
                width: Math.max(0, Math.min(full, starts.width - 4 - x))
                text: sc.latest ? "Continue “" + sc.latest.name + "” · " + F.pad(sc.latest.head) + " · " + F.ago(sc.latest.updated) : ""
                tip: "Open the design you changed last"
                onClicked: sc.start(3) }
        }
    }
    function pickFiles() { Store.ask(pick) }
    function pickModel() { if (Store.chatReady && !mpop.opened) mpop.open() }      // the agent and model picker, opened from elsewhere
    function openLink() { linking = true; lf.input.forceActiveFocus() }
    function addLink(t) {
        t = String(t || "").trim(); if (!t) return
        Store.fetchLink(t).then(function (r) { if (r) { lf.text = ""; sc.linking = false; ta.forceActiveFocus() } })
    }
}
