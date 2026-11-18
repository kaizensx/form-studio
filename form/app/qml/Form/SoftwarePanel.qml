import QtQuick
import FormNative

// The whole installer registry in its groups, with one install button, a re-check and the live log.
// Used by Settings › Software and the Software sheet.
Column {
    id: sp
    width: parent ? parent.width : 0
    spacing: 14
    readonly property var sw: Store.software
    readonly property int chosen: Store.installChosen.length
    property bool actions: true              // false when the host (Settings) puts Install / Check again in its action bar
    Txt { tone: 2; width: parent.width
        text: "What Form Studio uses on this computer. Only the CAD kernel is required; everything else is optional and unlocks one feature, and is offered again where that feature is used. Tick what you want, then press Install: each command is shown before it runs, and Form Studio never asks for a password." }
    Item { width: parent.width; height: 28; visible: sp.actions || (!!sp.sw && sp.sw.packaged)
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
        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; visible: !!sp.sw && sp.sw.packaged
            text: "Packaged app: the CAD kernel and parts libraries are included." } }
    InstallLog { width: parent.width }
    Repeater {
        model: sp.sw ? sp.sw.groups : []
        Column {
            id: grp
            required property var modelData
            width: sp.width; spacing: 6; visible: list.rows.length > 0
            Txt { kind: "cap"; text: grp.modelData.title + (grp.modelData.id === "slicer" && !Store.prints ? "  ·  not needed: you just design" : "") }
            SetupList { id: list; width: parent.width; ids: grp.modelData.items }
            ClaudeSignIn { width: parent.width; visible: grp.modelData.id === "ai" }
        }
    }
    SetupList { visible: !sp.sw; width: parent.width; all: true }
    Row { visible: !!Store.setup; spacing: 8; width: parent.width
        Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, sp.width - 120); elide: Text.ElideMiddle; wrapMode: Text.NoWrap
            text: Store.setup ? "MCP server for agents: " + Store.setup.mcp_command : "" }
        Btn { small: true; kind: "quiet"; icon: "copy"; text: "Copy"; onClicked: { Bridge.copy(Store.setup.mcp_command); Store.toast("Copied the MCP command") } } }
}
