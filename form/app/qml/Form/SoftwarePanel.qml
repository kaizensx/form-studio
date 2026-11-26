import QtQuick
import FormNative

// The whole installer registry in its groups, with one install button, a re-check and the live log.
// Used by Settings › Engines & software and the Software sheet. Each group is a titled card of rows (SetupList):
// installed or not, Install, and "Use in Form Studio" for what is installed.
Column {
    id: sp
    width: parent ? parent.width : 0
    spacing: 18
    readonly property var sw: Store.software
    readonly property int chosen: Store.installChosen.length
    property bool actions: true              // false when the host (Settings) puts Install / Check again in its action bar
    property bool intro: true                // false when the host says it in its own page header
    readonly property var list: sw ? sw.software.filter(function (r) { return r.id !== "claude.signin" && !r.absent }) : []
    readonly property int nInstalled: list.filter(function (r) { return r.status === "ok" }).length
    readonly property int nOff: list.filter(function (r) { return r.status === "ok" && !!r.use && !Store.useOn(r) }).length
    // what each group is, in one line under its title
    readonly property var subs: ({
        engine: "The geometry kernel, and optional engines that run on this computer.",
        ai: "Anthropic's agent, on your own account.",
        agents: "Other agents that can drive Form Studio. Pick one per conversation.",
        cad: "Apps Form Studio runs in the background or hands a design to.",
        slicer: "Only for 3D printing. One slicer is enough." })
    Txt { visible: sp.intro; tone: 2; width: parent.width
        text: "What Form Studio uses on this computer. Only the CAD kernel is required. Install sets one up in one click, and every command is shown before it runs. Once something is installed, “Use in Form Studio” says whether Form Studio calls it." }
    // at a glance
    Row { objectName: "softwareSummary"; visible: !!sp.sw; spacing: 8
        Repeater {
            model: [{ n: sp.nInstalled, t: "installed", c: Theme.pass }, { n: sp.nInstalled - sp.nOff, t: "in use", c: Theme.datum },
                    { n: sp.nOff, t: "switched off", c: Theme.ink3 }, { n: sp.list.length - sp.nInstalled, t: "available", c: Theme.ink3 }]
            Rectangle {
                required property var modelData
                visible: modelData.n > 0 || modelData.t === "installed"
                width: chip.implicitWidth + 22; height: 26; radius: 13; color: Theme.glass
                Row { id: chip; anchors.centerIn: parent; spacing: 6
                    Rectangle { width: 6; height: 6; radius: 3; color: parent.parent.modelData.c; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; mono: true; tone: 1; color: Theme.ink; text: String(parent.parent.modelData.n); anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; tone: 2; text: parent.parent.modelData.t; anchors.verticalCenter: parent.verticalCenter } } }
        }
        Txt { anchors.verticalCenter: parent.verticalCenter; kind: "fine"; visible: !!sp.sw && sp.sw.packaged; leftPadding: 4
            text: "Packaged app: the CAD kernel and parts libraries are included." } }
    Row { spacing: 8; visible: sp.actions
        Btn { kind: "primary"; icon: "download"; enabled: sp.chosen > 0; busy: Store.installing
            text: Store.installing ? "Installing…" : sp.chosen ? "Install " + sp.chosen + " selected" : "Install selected"
            onClicked: Store.installSoftware() }
        Btn { objectName: "autoSetup"; visible: !Store.installing; icon: "sparkles"; text: "Set up automatically"
            tip: "Install what Form Studio needs by itself; it pauses only when you have to sign in or download something"
            onClicked: Store.autoSetup(true) }
        Btn { visible: Store.installing; icon: "x"; text: "Cancel"; onClicked: Store.cancelInstall() }
        Btn { icon: "refresh_cw"; text: "Check again"; busy: Store.softwareChecking; enabled: !Store.installing
            onClicked: { Store.checkSoftware(); Store.checkSetup() } } }
    InstallLog { width: parent.width }
    Repeater {
        model: sp.sw ? sp.sw.groups : []
        Column {
            id: grp
            required property var modelData
            width: sp.width; spacing: 8; visible: list.rows.length > 0
            Column { width: parent.width; spacing: 2
                Txt { kind: "cap"; text: grp.modelData.title + (grp.modelData.id === "slicer" && !Store.printOn ? "  ·  3D printing is off" : "") }
                Txt { kind: "fine"; tone: 3; width: parent.width; visible: text !== ""; text: sp.subs[grp.modelData.id] || "" } }
            SetupList { id: list; width: parent.width; ids: grp.modelData.items }
            ClaudeSignIn { width: parent.width; visible: grp.modelData.id === "ai" }
        }
    }
    SetupList { visible: !sp.sw; width: parent.width; all: true }
    Rectangle { visible: !!Store.setup; width: parent.width; height: 44; radius: 14; color: Theme.glass
        Txt { x: 14; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; mono: true; width: parent.width - 28 - cp.width - 8; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
            text: Store.setup ? "MCP server for agents: " + Store.setup.mcp_command : "" }
        Btn { id: cp; small: true; kind: "quiet"; icon: "copy"; text: "Copy"; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
            onClicked: { Bridge.copy(Store.setup.mcp_command); Store.toast("Copied the MCP command") } } }
}
