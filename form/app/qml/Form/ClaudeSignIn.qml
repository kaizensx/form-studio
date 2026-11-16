import QtQuick
import FormNative

// Sign in to Claude Code without a terminal. FORM runs `claude auth login` in the background and shows the link it
// prints; the sign-in itself happens on Anthropic's page in the browser. No password or account detail reaches FORM.
Rectangle {
    id: si
    width: parent ? parent.width : 0
    readonly property var item: Store.softwareItem("claude.signin")
    readonly property var job: Store.claudeLogin
    readonly property bool running: !!job && job.state === "running"
    readonly property bool signedIn: !!item && item.status === "ok"
    readonly property bool hasClaude: !!Store.softwareItem("claude") && Store.softwareItem("claude").status === "ok"
    height: col.implicitHeight + 26; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule
    Item { x: 16; y: 14; width: 16; height: 16
        Icon { visible: si.signedIn; name: "circle_check"; size: 15; color: Theme.pass; anchors.centerIn: parent }
        Icon { visible: si.running; name: "loader_circle"; size: 14; color: Theme.ink2; anchors.centerIn: parent
            RotationAnimation on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: si.running } }
        Rectangle { visible: !si.signedIn && !si.running; width: 8; height: 8; radius: 4; anchors.centerIn: parent; color: Theme.ink3 } }
    Column {
        id: col; x: 44; y: 13; width: parent.width - 60; spacing: 6
        Item { width: parent.width; height: 18
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Txt { text: "Claude sign-in"; font.weight: 600; wrapMode: Text.NoWrap }
                Tag { visible: !si.signedIn && si.hasClaude; text: "recommended"; kind: "specified"; anchors.verticalCenter: parent.verticalCenter } }
            Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; wrapMode: Text.NoWrap
                text: si.signedIn ? "ready" : si.running ? "waiting for the browser" : "not signed in"; color: si.signedIn ? Theme.pass : Theme.ink3 } }
        Txt { kind: "fine"; tone: 2; width: parent.width
            text: si.signedIn ? si.item.detail : !si.hasClaude ? "Install Claude Code first. Then sign in here."
                : "Chat runs on your own Claude account. Sign in once; your password goes to Anthropic's page in your browser, never to FORM." }
        // waiting for the browser
        Column { visible: si.running; width: parent.width; spacing: 6; topPadding: 2
            Txt { width: parent.width; text: si.job && si.job.url ? "Finish signing in on the page that opened in your browser. If no page opened, use the link." : "Starting Claude Code's sign-in…" }
            Rectangle { visible: !!si.job && si.job.url !== ""; width: parent.width; height: 28; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
                Txt { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 2
                    elide: Text.ElideMiddle; wrapMode: Text.NoWrap; text: si.job ? si.job.url : "" } }
            Row { spacing: 8
                Btn { small: true; icon: "external_link"; text: "Open the link"; visible: !!si.job && si.job.url !== ""; onClicked: Bridge.openLink(si.job.url) }
                Btn { small: true; kind: "quiet"; icon: "copy"; text: "Copy link"; visible: !!si.job && si.job.url !== ""; onClicked: { Bridge.copy(si.job.url); Store.toast("Copied the sign-in link") } }
                Btn { small: true; kind: "quiet"; text: "Cancel"; onClicked: Store.cancelClaudeLogin() } }
            Row { spacing: 8; width: parent.width
                Field { id: code; width: Math.min(320, parent.width - 110); placeholder: "If the page shows a code, paste it here"
                    onAccepted: function (t) { if (t.trim()) { Store.sendClaudeCode(t.trim()); code.text = "" } } }
                Btn { small: true; text: "Send code"; enabled: code.text.trim() !== ""; anchors.verticalCenter: parent.verticalCenter
                    onClicked: { Store.sendClaudeCode(code.text.trim()); code.text = "" } } } }
        Txt { visible: !!si.job && si.job.state === "failed"; kind: "fine"; width: parent.width; color: Theme.signal; text: si.job ? si.job.message : "" }
        Row { visible: !si.signedIn && !si.running && si.hasClaude; spacing: 10; topPadding: 2
            Btn { small: true; kind: "primary"; icon: "external_link"; text: "Sign in with your browser"; onClicked: Store.startClaudeLogin() }
            Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; text: "Runs  claude auth login  in the background" } }
    }
}
