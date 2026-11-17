import QtQuick

// "Fix with <agent>" on anything that failed: sends the failure, word for word, to this design's conversation.
// subject: one line (what failed); details: everything the agent needs (messages, values, hints).
Btn {
    id: fx
    objectName: "fixBtn"
    property string subject: ""
    property string details: ""
    property bool compact: false             // icon only (tight rows); the tooltip names the agent
    visible: !!Store.chat.available && Store.chatReady && !!Store.project
    enabled: !Store.chatBusy
    small: true
    icon: "wrench"
    text: compact ? "" : "Fix with " + Store.chatAgentLabel
    tip: Store.chatBusy ? "The conversation is still answering" : "Send this failure to " + Store.chatAgentLabel + " in this design's conversation"
    onClicked: Store.fixWith(subject, details)
}
