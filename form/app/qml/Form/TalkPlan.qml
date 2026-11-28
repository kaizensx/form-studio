import QtQuick
import "F.js" as F

// The agent's plan, before a big change: the steps its plan_design call returned, numbered. When the agent then asks
// for approval (an ask_user approval card that follows the plan), the question is answered here: Approve sends its
// first choice, Edit puts the keyboard in the prompt, where what you write goes back as the answer. With no question
// the card is the plan and nothing more: it never says "approved" unless you answered.
TalkCard {
    id: plan
    objectName: "planCard"
    property var steps: []                   // lines
    property var q: null                     // the approval that goes with it, or null: { id, choices, open, answer }
    signal edit()
    readonly property bool waiting: !!q && q.open
    readonly property var given: q && q.answer ? q.answer : null
    readonly property bool approved: !!given && !!q.choices.length && (given.choices || []).indexOf(q.choices[0]) >= 0 && !given.text
    title: "Plan"
    lit: waiting
    note: waiting ? "waits for you" : approved ? "approved by you" : given && given.text ? "changed by you" : given ? "answered by you" : F.plural(steps.length, "step")
    noteColor: waiting ? Theme.datum : Theme.ink3
    Repeater {
        model: plan.steps
        Item {
            objectName: "planStep"
            required property string modelData; required property int index
            width: parent.width; height: Math.max(23, line.implicitHeight + 5)
            Txt { x: 0; anchors.baseline: line.baseline; width: 16; mono: true; font.pixelSize: 12; tone: 3; text: index + 1 }
            Txt { id: line; x: 20; y: 2; width: parent.width - 20; font.pixelSize: 13; lineHeight: 1.3; wrapMode: Text.WordWrap; text: modelData }
        }
    }
    Txt { visible: !!plan.given && !!plan.given.text; width: parent.width; topPadding: 6; kind: "fine"; tone: 2; wrapMode: Text.WordWrap
        text: plan.given && plan.given.text ? "You: " + plan.given.text : "" }
    Item { visible: plan.waiting; width: parent.width; height: visible ? 42 : 0
        Row { y: 10; spacing: 6
            Btn { objectName: "planApprove"; small: true; kind: "primary"; icon: "check"; text: plan.q && plan.q.choices.length ? plan.q.choices[0] : "Approve"
                onClicked: Store.answerAsk(plan.q.id, "", [plan.q.choices[0]]) }
            Btn { objectName: "planEdit"; small: true; kind: "quiet"; icon: "pencil"; text: "Edit"; tip: "Say what to change: your words go back to the agent as the answer"
                onClicked: plan.edit() }
            Btn { objectName: "planSkip"; visible: !!plan.q && plan.q.choices.length > 1; small: true; kind: "quiet"; text: plan.q && plan.q.choices.length > 1 ? plan.q.choices[1] : ""
                onClicked: Store.answerAsk(plan.q.id, "", [plan.q.choices[1]]) } } }
}
