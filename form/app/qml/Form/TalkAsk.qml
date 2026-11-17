import QtQuick

// A question from the agent (Form Studio's ask_user tool), in the conversation. While the agent waits it takes
// an answer: a choice, several, or words. Afterwards it keeps what you answered, or says that nobody did.
Rectangle {
    id: qa
    objectName: "askCard"
    property var q: ({})                    // { id, question, choices, multi, free, why, kind, answer, open }
    readonly property bool open: !!q.open
    readonly property bool confirm: q.kind === "confirm"
    readonly property var choices: q.choices || []
    readonly property var ans: q.answer || null
    property var picked: []                 // several choices, before Send
    property bool sending: false
    implicitHeight: col.implicitHeight + 26
    radius: Theme.rLg
    color: open ? Theme.plate2 : Theme.plate1
    border.color: open ? Theme.alpha(Theme.amber, 0.55) : Theme.rule
    Behavior on border.color { Tint {} }
    Behavior on color { Tint {} }
    // the edge that says "this is waiting on you"
    Rectangle { visible: qa.open; x: 0; y: 12; width: 3; height: parent.height - 24; radius: 2; color: Theme.amber }

    function send(text, list) {
        if (qa.sending) return
        qa.sending = true
        Store.answerAsk(qa.q.id, text || "", list || [])
    }
    function toggle(c) {
        var p = qa.picked.slice(), i = p.indexOf(c)
        if (i >= 0) p.splice(i, 1); else p.push(c)
        qa.picked = p
    }

    Column {
        id: col; x: 16; y: 13; width: parent.width - 30; spacing: 9
        // who asks, and whether it is still waiting
        Item { width: parent.width; height: 16
            Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
                Icon { name: qa.confirm ? "shield_check" : "message_square"; size: 12; color: qa.open ? Theme.amber : Theme.ink3; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "cap"; text: qa.confirm ? "Needs your approval" : "Question from " + Store.chatAgentLabel; anchors.verticalCenter: parent.verticalCenter } }
            Row { visible: qa.open; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.amber; anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity { running: qa.open; loops: Animation.Infinite; alwaysRunToEnd: true
                        NumberAnimation { to: 0.3; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                Txt { kind: "fine"; text: "Waiting for you"; color: Theme.amber } }
        }
        Txt { objectName: "askQuestion"; width: parent.width; text: qa.q.question || ""; font.weight: Theme.wSemi; lineHeight: 1.35 }
        Txt { visible: !!qa.q.why; width: parent.width; kind: "fine"; text: qa.q.why || ""; lineHeight: 1.35 }

        // ── answering ──
        // approval: the actions as buttons, the first one primary
        Flow { visible: qa.open && qa.confirm; width: parent.width; spacing: 6
            Repeater { model: qa.open && qa.confirm ? qa.choices : []
                Btn { required property string modelData; required property int index
                    objectName: "askChoice"; small: true; kind: index === 0 ? "primary" : "default"; text: modelData; busy: qa.sending && index === 0
                    onClicked: qa.send("", [modelData]) } } }
        // choices as chips: one click answers; with several allowed, tick them and send
        Flow { visible: qa.open && !qa.confirm && qa.choices.length > 0; width: parent.width; spacing: 6
            Repeater { model: qa.open && !qa.confirm ? qa.choices : []
                Rectangle {
                    id: chip
                    required property string modelData
                    objectName: "askChoice"
                    readonly property bool on: qa.picked.indexOf(modelData) >= 0
                    width: Math.min(col.width, cl.implicitWidth + (qa.q.multi ? 40 : 24)); height: 28; radius: 14
                    color: on ? Theme.alpha(Theme.datum, 0.16) : cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.plate4 : Theme.plate3
                    border.color: on ? Theme.alpha(Theme.datum, 0.7) : cm.containsMouse ? Theme.rule3 : Theme.rule2
                    scale: cm.pressed ? Theme.from(0.97) : 1
                    Behavior on scale { Glide { duration: Theme.press } }
                    Behavior on color { Tint {} }
                    Rectangle { visible: !!qa.q.multi; x: 10; width: 12; height: 12; radius: 3; anchors.verticalCenter: parent.verticalCenter
                        color: chip.on ? Theme.datum : "transparent"; border.color: chip.on ? Theme.datum : Theme.ink4
                        Icon { visible: chip.on; anchors.centerIn: parent; name: "check"; size: 9; color: Theme.datumInk } }
                    Txt { id: cl; x: qa.q.multi ? 28 : 12; width: parent.width - x - 12; anchors.verticalCenter: parent.verticalCenter
                        text: chip.modelData; font.pixelSize: 12; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: chip.on || cm.containsMouse ? 1 : 2 }
                    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: qa.q.multi ? qa.toggle(chip.modelData) : qa.send("", [chip.modelData]) }
                } } }
        // words: always for an open question; "or" when there are choices too
        Row { visible: qa.open && !!qa.q.free; width: parent.width; spacing: 6
            Field { id: fld; objectName: "askField"; width: parent.width - sb.width - 6
                placeholder: qa.choices.length ? "Or type an answer" : "Your answer"
                onAccepted: function (t) { if (t.trim() || qa.picked.length) qa.send(t.trim(), qa.picked) } }
            Btn { id: sb; objectName: "askSend"; kind: "primary"; icon: "arrow_up"; text: "Answer"; busy: qa.sending
                enabled: fld.text.trim() !== "" || qa.picked.length > 0
                onClicked: qa.send(fld.text.trim(), qa.picked) } }
        Btn { visible: qa.open && !qa.q.free && !!qa.q.multi; objectName: "askSend"; small: true; kind: "primary"; text: "Send " + qa.picked.length + " selected"
            enabled: qa.picked.length > 0; busy: qa.sending; onClicked: qa.send("", qa.picked) }

        // ── afterwards ──
        Row { visible: !qa.open && !!qa.ans && !qa.ans.closed; width: parent.width; spacing: 7
            Icon { name: "corner_down_left"; size: 12; color: Theme.pass; anchors.verticalCenter: parent.verticalCenter }
            Txt { objectName: "askAnswer"; width: parent.width - 20; tone: 2
                text: qa.ans ? ((qa.ans.choices || []).join(", ") + (qa.ans.text ? ((qa.ans.choices || []).length ? " — " : "") + qa.ans.text : "")) : "" } }
        Txt { visible: !qa.open && (!qa.ans || !!qa.ans.closed); width: parent.width; kind: "fine"
            text: !qa.ans ? "Not answered." : qa.ans.closed === "timeout" ? "Not answered in time. The agent continued with assumptions and should say which."
                : qa.ans.closed === "stopped" ? "You stopped the reply before answering." : "The reply ended before an answer." }
    }
    Connections { target: Store; function onChatAskingChanged() { if (!Store.chatAsking || Store.chatAsking.id !== qa.q.id) qa.sending = false } }
}
