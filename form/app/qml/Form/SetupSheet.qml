import QtQuick
import FormNative

// Setup, any time: the same checklist as the first-run welcome, in a sheet.
Column {
    id: ss
    property string title: "Setup"
    property int sheetWidth: 760
    readonly property bool busy: !!Store.setupJob && Store.setupJob.state === "running"
    spacing: 14; bottomPadding: 20
    Txt { tone: 2; width: parent.width
        text: "What FORM uses, and whether it is ready. Tick what you want set up; nothing runs until you press Apply." }
    Row { spacing: 8
        Btn { kind: "primary"; icon: "wrench"; enabled: Store.setupChosen.length > 0 && !ss.busy
            text: ss.busy ? "Setting up…" : Store.setupChosen.length ? "Apply selected (" + Store.setupChosen.length + ")" : "Apply selected"
            onClicked: Store.applySetup() }
        Btn { icon: "refresh_cw"; text: Store.setupChecking ? "Checking…" : "Check again"; enabled: !Store.setupChecking && !ss.busy; onClicked: Store.checkSetup() } }
    SetupList { width: parent.width; attentionFirst: true }
    Row { visible: !!Store.setup; spacing: 8; width: parent.width
        Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, ss.width - 120); elide: Text.ElideMiddle; wrapMode: Text.NoWrap
            text: Store.setup ? "MCP server for agents: " + Store.setup.mcp_command : "" }
        Btn { small: true; kind: "quiet"; icon: "copy"; text: "Copy"; onClicked: { Bridge.copy(Store.setup.mcp_command); Store.toast("Copied the MCP command") } } }
}
