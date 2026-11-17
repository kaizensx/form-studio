import QtQuick
import FormNative

// A newer FORM release exists. Shows its notes and how to get it. FORM never downloads or installs it itself.
Column {
    id: us
    readonly property var u: Store.update
    readonly property var rel: u && u.release ? u.release : null
    readonly property bool packaged: !!u && u.kind === "packaged"
    property string title: u && u.latest ? "FORM " + u.latest + " is available" : "Updates"
    property string note: u ? "You have " + u.current + (rel && rel.published ? " · released " + rel.published.slice(0, 10) : "") : ""
    property int sheetWidth: Theme.sheetM
    spacing: 14
    function accept() { if (packaged) Bridge.openLink(u.download.url); else { Bridge.copy(u.command); Store.toast("Copied the upgrade command") } }
    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "external_link"; text: "Release page"; visible: !!us.rel; onClicked: Bridge.openLink(us.rel.url) } }
    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Not now"; onClicked: { Store.updateHidden = true; Store.openSheet(null) } }
        Btn { kind: "primary"; icon: us.packaged ? "external_link" : "copy"
            text: us.packaged ? (us.u && us.u.download && us.u.download.name ? "Download " + us.u.download.name : "Open the download page") : "Copy command"
            onClicked: us.accept() } }

    Note { visible: !!us.rel && !!us.rel.fake; kind: "amber"; title: "Development"
        text: "This release comes from FORM_FAKE_LATEST. Nothing was fetched from GitHub." }
    Rectangle { visible: !!us.rel && us.rel.notes !== ""
        width: parent.width; height: Math.min(notes.implicitHeight, 320) + 24; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule; clip: true
        Txt { id: notes; x: 14; y: 12; width: parent.width - 28; tone: 2; textFormat: Text.MarkdownText; text: us.rel ? us.rel.notes : ""
            linkColor: Theme.datum; onLinkActivated: function (link) { Bridge.openLink(link) } } }

    // packaged app: open the download in the browser
    Txt { visible: us.packaged; width: parent.width; tone: 2
        text: "Download the new app in your browser, then replace this one with it. Your projects stay where they are, in the projects folder." }
    // pip / uv / source: the exact command
    Column { visible: !!us.u && !us.packaged; width: parent.width; spacing: 8
        Txt { width: parent.width; tone: 2; text: "To upgrade, run this in a terminal, then restart FORM:" }
        Rectangle { width: parent.width; height: cmd.implicitHeight + 20; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
            Txt { x: 12; y: 10; mono: true; font.pixelSize: 12; tone: 4; text: "$" }
            Txt { id: cmd; x: 28; y: 10; width: parent.width - 40; mono: true; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; text: us.u ? us.u.command : "" } } }
    Txt { kind: "fine"; width: parent.width
        text: "FORM checks GitHub for a new release at most once a day and never installs one by itself. Turn this off with [updates] check = false in studio.toml." }
}
