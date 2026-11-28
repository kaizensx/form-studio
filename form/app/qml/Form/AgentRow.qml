import QtQuick
import FormNative

// One agent in Settings › Agents & models: an agent app (CLI), a model provider's API, or a local model server.
// `a` is its entry from GET /chat (form/agents); `k` the state of its API key from GET /secrets (never the key).
Item {
    id: ag
    property var a: ({})
    property var k: null
    property bool first: false
    signal install()
    signal saveKey(string value)
    signal clearKey()
    readonly property var si: a.signin || null
    readonly property bool api: a.kind === "api"
    readonly property int count: (a.models || []).filter(function (m) { return m.id !== "default" }).length
    readonly property bool needsKey: !!k && !k.set && !k.from_env
    readonly property bool untested: a.available && String(a.verified).indexOf("not run") === 0
    function status() {
        if (!a.available) {
            if (k && k.set) return "Stored privately on this computer. " + (a.why || "")
            return a.why || "Not installed."
        }
        if (!api) return si ? si.how : "Installed"
        var n = ag.count + (ag.count === 1 ? " model" : " models")
        if (a.local) return n + " · " + (a.cli || "")
        if (k && k.from_env) return n + " · key from " + (k.env_name || k.env)
        if (k && k.set) return n + " · Stored privately on this computer. It is not shown again."
        return n
    }
    width: parent ? parent.width : 400
    height: Math.max(left.implicitHeight, right.implicitHeight, 28) + 22
    Rectangle { x: 16; y: left.y + 6.5; width: 7; height: 7; radius: 3.5          // on the middle of the name's line
        color: !ag.a.available ? (ag.k && ag.k.set ? Theme.amber : Theme.ink4) : ag.si && ag.si.signed_in === false ? Theme.amber : Theme.pass }
    Column { id: left; x: 32; width: parent.width - 32 - right.width - 28; anchors.verticalCenter: parent.verticalCenter; spacing: 2
        Row { spacing: 8
            Txt { text: ag.a.label || ""; font.weight: Theme.wMedium }
            Tag { visible: ag.untested; text: "not yet verified"; kind: "assumed"; anchors.verticalCenter: parent.verticalCenter }
            Txt { visible: Store.chatDefault.agent === ag.a.id && ag.a.available; kind: "fine"; text: "default for new conversations"
                anchors.verticalCenter: parent.verticalCenter } }
        Txt { kind: "fine"; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight
            color: ag.a.available && ag.k && (ag.k.set || ag.k.from_env) ? Theme.pass : Theme.ink3; text: ag.status() }
        Txt { kind: "fine"; tone: 4; mono: true; font.pixelSize: 11; width: parent.width; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
            visible: ag.a.available && !ag.api
            text: (ag.a.cli || "") + (ag.count ? "  ·  " + ag.count + " listed models" : "") }
        Txt { kind: "fine"; tone: 4; width: parent.width; visible: ag.untested
            text: ag.api ? "Follows the provider's documented API; not yet verified with a live reply."
                         : "Follows the CLI's documented options and output; not yet verified with a live reply." } }
    Row { id: right; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 6
        Btn { visible: !ag.a.available && !ag.api; small: true; icon: "download"; text: "Install…"; onClicked: ag.install() }
        Field { id: kf; objectName: "secretField"; visible: ag.needsKey; width: 200; placeholder: "Paste the key"; mono: true
            input.echoMode: TextInput.Password
            onAccepted: function (t) { if (t.trim()) ag.saveKey(t) } }
        Btn { visible: ag.needsKey; small: true; kind: "quiet"; icon: "external_link"; tip: "Get a key"; anchors.verticalCenter: parent.verticalCenter
            onClicked: Bridge.openLink(ag.k.url) }
        Btn { visible: ag.needsKey; small: true; kind: "primary"; text: "Save key"; enabled: kf.text.trim().length > 0
            anchors.verticalCenter: parent.verticalCenter; onClicked: ag.saveKey(kf.text) }
        Btn { visible: !!ag.k && ag.k.set; small: true; kind: "quiet"; icon: "trash_2"; text: "Remove"
            anchors.verticalCenter: parent.verticalCenter; onClicked: { kf.text = ""; ag.clearKey() } }
        Btn { visible: ag.a.available && Store.chatDefault.agent !== ag.a.id; small: true; kind: "quiet"; text: "Make default"
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Store.post("/chat/defaults", { agent: ag.a.id, model: ag.a.last_model || "default", effort: "" }).then(function () { Store.reloadStudio() }, Store.fail) } }
}
