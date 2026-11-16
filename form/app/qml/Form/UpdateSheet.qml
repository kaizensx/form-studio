import QtQuick
import FormNative

// A newer FORM release exists. Shows its notes and how to get it. FORM never downloads or installs it itself.
Column {
    id: us
    readonly property var u: Store.update
    readonly property var rel: u && u.release ? u.release : null
    property string title: u && u.latest ? "FORM " + u.latest + " is available" : "Updates"
    property int sheetWidth: 640
    spacing: 12; bottomPadding: 20
    Txt { kind: "fine"; width: parent.width
        text: us.u ? "You have " + us.u.current + (us.rel && us.rel.published ? " · released " + us.rel.published.slice(0, 10) : "") : "" }
    Note { visible: !!us.rel && us.rel.fake; kind: "amber"; title: "Development"
        text: "This release comes from FORM_FAKE_LATEST. Nothing was fetched from GitHub." }
    Rectangle { visible: !!us.rel && us.rel.notes !== ""
        width: parent.width; height: Math.min(notes.implicitHeight, 320) + 24; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule; clip: true
        Txt { id: notes; x: 14; y: 12; width: parent.width - 28; tone: 2; textFormat: Text.MarkdownText; text: us.rel ? us.rel.notes : ""
            onLinkActivated: function (link) { Bridge.openLink(link) } } }

    // packaged app: open the download in the browser
    Column { visible: !!us.u && us.u.kind === "packaged"; width: parent.width; spacing: 8
        Txt { width: parent.width; tone: 2
            text: "Download the new app in your browser, then replace this one with it. Your projects stay where they are, in the projects folder." }
        Btn { kind: "primary"; icon: "external_link"; text: us.u && us.u.download && us.u.download.name ? "Download " + us.u.download.name : "Open the download page"
            onClicked: Bridge.openLink(us.u.download.url) } }
    // pip / uv / source: the exact command
    Column { visible: !!us.u && us.u.kind !== "packaged"; width: parent.width; spacing: 8
        Txt { width: parent.width; tone: 2; text: "To upgrade, run this in a terminal, then restart FORM:" }
        Rectangle { width: parent.width; height: cmd.implicitHeight + 18; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule
            Txt { id: cmd; x: 10; y: 9; width: parent.width - 20; mono: true; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; text: us.u ? us.u.command : "" } }
        Btn { kind: "primary"; icon: "copy"; text: "Copy command"; onClicked: { Bridge.copy(us.u.command); Store.toast("Copied the upgrade command") } } }

    Row { spacing: 8
        Btn { kind: "quiet"; icon: "external_link"; text: "Release page"; visible: !!us.rel; onClicked: Bridge.openLink(us.rel.url) }
        Btn { kind: "quiet"; text: "Not now"; onClicked: { Store.updateHidden = true; Store.openSheet(null) } } }
    Txt { kind: "fine"; width: parent.width
        text: "FORM checks GitHub for a new release at most once a day and never installs one by itself. Turn this off with [updates] check = false in studio.toml." }
}
