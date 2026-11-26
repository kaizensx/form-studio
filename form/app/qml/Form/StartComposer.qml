import QtQuick
import FormNative
import QtQuick.Controls
import QtQuick.Dialogs
import "F.js" as F

// Home's composer: the one place a design starts. Words, a photo, a sketch, a part or a drawing, a link; the agent
// turns whatever is here into real CAD. Files and sketches attach to the conversation as soon as they are added, so
// what the agent receives is exactly what is on the card. Sending opens the workspace at once (Store.startDesign).
Rectangle {
    id: sc
    objectName: "startComposer"
    property bool dragging: false              // a file is being dragged over Home
    property bool linking: false               // the link field is open
    readonly property alias area: ta
    readonly property bool hasAny: ta.text.trim() !== "" || Store.chatAttach.length > 0 || Store.chatLinks.length > 0
    readonly property bool can: hasAny && Store.chatReady && !Store.chatBusy
    readonly property bool narrow: width < 620
    signal sketchWanted()
    function submit() { if (!can) return; var t = ta.text; ta.text = ""; Store.startDesign(t) }

    implicitHeight: col.implicitHeight
    radius: Theme.rXl + 4
    color: Theme.alpha(Theme.plate1, 0.94)
    border.width: 1
    border.color: dragging ? Theme.alpha(Theme.datum, 0.85) : ta.activeFocus ? Theme.alpha(Theme.datum, 0.5) : hov.hovered ? Theme.rule3 : Theme.rule2
    Behavior on border.color { Tint {} }
    HoverHandler { id: hov }
    Shadow { radius: parent.radius; spread: 34; drop: 18; strength: 1.1 }
    // focus halo: a soft ring of the datum colour, the plate "receiving" attention
    Rectangle { anchors.fill: parent; anchors.margins: -4; radius: parent.radius + 4; color: "transparent"; border.width: 4
        border.color: Theme.alpha(Theme.datum, sc.dragging ? 0.22 : 0.1); opacity: ta.activeFocus || sc.dragging ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.base } } }

    FileDialog { id: pick; title: "Add a photo, a part or a drawing"; fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos, parts and drawings (*.png *.jpg *.jpeg *.webp *.heic *.gif *.bmp *.pdf *.step *.stp *.stl *.3mf)"]
        onAccepted: Store.attachFiles(selectedFiles) }
    Connections { target: Store; function onStartFocusChanged() { ta.forceActiveFocus() } }

    Column {
        id: col; width: parent.width

        FetchProgress { x: 18; width: parent.width - 36 }
        // ── what goes with the words: photos large enough to recognise, parts and drawings, sketches, links ──
        Item { visible: Store.chatAttach.length > 0 || Store.chatLinks.length > 0; width: parent.width; height: visible ? shelf.implicitHeight + 18 : 0
            Flow { id: shelf; objectName: "startShelf"; x: 16; y: 16; width: parent.width - 32; spacing: 8
                Repeater { model: Store.chatAttach
                    Rectangle { id: att; objectName: "startAttachment"; required property var modelData; required property int index
                        readonly property bool pic: modelData.kind === "image"
                        readonly property string label: modelData.kind === "sketch" ? "Sketch" : modelData.name
                        width: pic ? 72 : Math.min(shelf.width, an.implicitWidth + 60); height: pic ? 72 : 40; radius: Theme.rMd + 1
                        color: Theme.plate2; border.color: am.containsMouse ? Theme.rule3 : Theme.rule2; clip: true
                        opacity: 0; scale: Theme.from(0.94)
                        Component.onCompleted: attIn.start()
                        ParallelAnimation { id: attIn; Glide { target: att; property: "opacity"; to: 1; duration: Theme.base } Glide { target: att; property: "scale"; to: 1; duration: Theme.base } }
                        Image { visible: att.pic; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                            source: att.pic && Store.convId ? Store.attachmentUrl(att.modelData.file) : "" }
                        Rectangle { visible: !att.pic; x: 6; width: 28; height: 28; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
                            color: att.modelData.kind === "sketch" ? Theme.alpha(Theme.datum, 0.14) : Theme.plate3
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
                        width: Math.min(shelf.width, lt.implicitWidth + 64); height: 40; radius: Theme.rMd + 1; color: Theme.plate2; border.color: lkm.hovered ? Theme.rule3 : Theme.rule2
                        Rectangle { x: 6; width: 28; height: 28; radius: Theme.rSm; color: Theme.plate3; anchors.verticalCenter: parent.verticalCenter
                            Icon { anchors.centerIn: parent; name: "globe"; size: 14; color: Theme.blueprint } }
                        Column { id: lt; x: 42; anchors.verticalCenter: parent.verticalCenter; spacing: 0
                            Txt { text: lk.modelData.host; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap }
                            Txt { kind: "fine"; tone: 3; text: "Link · passed on, nothing downloaded"; wrapMode: Text.NoWrap } }
                        HoverHandler { id: lkm }
                        Btn { small: true; kind: "quiet"; icon: "x"; tip: "Remove"; anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
                            visible: lkm.hovered; onClicked: Store.dropLink(lk.modelData.url) }
                        Tip { show: lkm.hovered; text: lk.modelData.url } } } } }

        // ── the words ──
        Item { width: parent.width; height: Math.min(260, Math.max(sc.narrow ? 76 : 92, ta.implicitHeight + 8))
            Behavior on height { NumberAnimation { duration: Theme.move(Theme.fast); easing.type: Easing.OutQuad } }
            ScrollView { anchors.fill: parent; clip: true
                TextArea {
                    id: ta
                    objectName: "startText"
                    wrapMode: TextArea.Wrap; color: Theme.ink; font.family: Theme.sans; font.pixelSize: sc.narrow ? 15 : 17; font.letterSpacing: -0.15
                    selectionColor: Theme.alpha(Theme.datum, 0.3); selectedTextColor: Theme.ink; selectByMouse: true
                    leftPadding: 22; rightPadding: 22; topPadding: 20; bottomPadding: 6; background: null; renderType: Text.NativeRendering
                    enabled: !!Store.studio
                    Keys.onTabPressed: nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason)
                    Keys.onBacktabPressed: nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onPressed: function (e) {
                        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) { e.accepted = true; sc.submit() }
                        else if (e.matches(StandardKey.Paste)) {
                            var clip = String(Bridge.clipboardText()).trim()
                            if (/^https?:\/\/\S+$/i.test(clip)) { e.accepted = true; Store.fetchLink(clip) }        // a pasted link is a link, not words
                            else if (!clip) { var img = Bridge.clipboardImage(); if (String(img)) { e.accepted = true; Store.attachFiles([img]) } }   // a pasted photo
                        }
                    }
                }
            }
            // the placeholder: examples of what can be said, changing slowly while the field is empty
            Txt { id: ph; x: 22; y: 20; width: parent.width - 44; visible: ta.text === "" && !ta.preeditText
                font.pixelSize: ta.font.pixelSize; font.letterSpacing: -0.15; color: Theme.ink4; wrapMode: Text.NoWrap; elide: Text.ElideRight
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

        // ── the tools, and Send ──
        Item { width: parent.width; height: 56
            Row { x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                Btn { objectName: "startAdd"; kind: "quiet"; icon: "paperclip"; text: sc.narrow ? "" : "Photo or file"; tip: "A photo (with a card, a coin or a ruler in it for scale), a STEP, STL or 3MF part, or a PDF drawing. You can also drop them anywhere here."
                    onClicked: Store.ask(pick) }
                Btn { objectName: "startSketch"; kind: "quiet"; icon: "pen_tool"; text: sc.narrow ? "" : "Sketch"; tip: "Draw it: lines, rectangles, circles, arcs and dimensions in millimetres"
                    onClicked: sc.sketchWanted() }
                Btn { objectName: "startLinkBtn"; kind: "quiet"; icon: "link"; text: sc.narrow ? "" : "Link"; active: sc.linking
                    tip: "A model page (Printables, Thingiverse…) or a direct link to an STL, STEP, 3MF or PDF. Only a file you link is downloaded."
                    onClicked: { sc.linking = !sc.linking; if (sc.linking) lf.input.forceActiveFocus(); else ta.forceActiveFocus() } }
                Btn { kind: "quiet"; icon: "mic"; tip: Theme.mac ? "Speak instead of typing: press Fn twice (macOS dictation), then talk" : "Speak instead of typing: Windows+H starts dictation in this field"
                    onClicked: { ta.forceActiveFocus(); Store.toast("Dictation", Theme.mac ? "Press Fn twice and speak; the words go into the field." : "Press Windows+H and speak; the words go into the field.") } } }
            Row { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                Rectangle { id: go; objectName: "startSend"
                    width: gl.implicitWidth + 44; height: 38; radius: 19; anchors.verticalCenter: parent.verticalCenter
                    color: !sc.can ? Theme.plate3 : gm.pressed ? Theme.datum : gm.containsMouse ? Theme.datumHi : Theme.datum
                    scale: gm.pressed && sc.can ? Theme.from(0.96) : 1
                    Behavior on scale { Glide { duration: Theme.press } }
                    Behavior on color { Tint {} }
                    Row { id: gl; anchors.centerIn: parent; spacing: 8
                        Txt { text: "Design it"; font.weight: Theme.wSemi; color: sc.can ? Theme.datumInk : Theme.ink4; anchors.verticalCenter: parent.verticalCenter }
                        Icon { name: "arrow_right"; size: 15; color: sc.can ? Theme.datumInk : Theme.ink4; anchors.verticalCenter: parent.verticalCenter } }
                    MouseArea { id: gm; anchors.fill: parent; hoverEnabled: true; cursorShape: sc.can ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: sc.submit() }
                    Tip { show: gm.containsMouse; keys: sc.can ? "Return" : ""
                        text: !Store.chatReady ? "No agent is connected" : Store.chatBusy ? "The agent is still answering" : sc.can ? "The agent designs it; the workspace opens now and the part appears as it is built" : "Write what it is, or add a photo, sketch, file or link" } } }
        }
    }
    function pickFiles() { Store.ask(pick) }
    function openLink() { linking = true; lf.input.forceActiveFocus() }
    function addLink(t) {
        t = String(t || "").trim(); if (!t) return
        Store.fetchLink(t).then(function (r) { if (r) { lf.text = ""; sc.linking = false; ta.forceActiveFocus() } })
    }
}
