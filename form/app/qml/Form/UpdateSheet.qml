import QtQuick
import FormNative

// A newer FORM release exists. Shows its notes and gets it: the packaged app opens its download; a pip / uv / source
// install runs its upgrade command here ("Update now") with the output shown, then asks for a restart. Nothing is
// upgraded until the button is pressed, and the command that runs is the one shown.
Column {
    id: us
    readonly property var u: Store.update
    readonly property var rel: u && u.release ? u.release : null
    readonly property bool packaged: !!u && u.kind === "packaged"
    readonly property var job: Store.updateJob
    readonly property string phase: !job ? "idle" : job.state            // idle | running | done | failed | cancelled
    readonly property var tail: Store.updateLog.slice(-9)
    property bool showCommand: false
    property string title: phase === "done" ? "Form Studio is upgraded" : u && u.latest ? "Form Studio " + u.latest + " is available" : "Updates"
    property string note: u ? "You have " + u.current + (rel && rel.published ? " · released " + rel.published.slice(0, 10) : "") : ""
    property int sheetWidth: Theme.sheetM
    spacing: 14
    function accept() {
        if (packaged) Bridge.openLink(u.download.url)
        else if (phase === "done") Qt.quit()
        else if (phase !== "running") Store.installUpdate()
    }
    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "external_link"; text: "Release page"; visible: !!us.rel; onClicked: Bridge.openLink(us.rel.url) } }
    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; visible: us.phase !== "running"; text: us.phase === "done" ? "Later" : "Not now"
            onClicked: { Store.updateHidden = true; Store.openSheet(null) } }
        Btn { visible: us.phase === "running"; icon: "x"; text: "Cancel"; onClicked: Store.cancelUpdate() }
        Btn { objectName: "updatePrimary"; kind: "primary"; busy: us.phase === "running"; keys: "Return"
            icon: us.packaged ? "external_link" : us.phase === "done" ? "power" : "download"
            text: us.packaged ? (us.u && us.u.download && us.u.download.name ? "Download " + us.u.download.name : "Open the download page")
                : us.phase === "running" ? "Updating…" : us.phase === "done" ? "Quit Form Studio" : us.phase === "idle" ? "Update now" : "Try again"
            onClicked: us.accept() } }

    Note { visible: !!us.rel && !!us.rel.fake; kind: "amber"; title: "Development"
        text: "This release comes from FORM_FAKE_LATEST. Nothing was fetched from GitHub." }
    Rectangle { visible: !!us.rel && us.rel.notes !== "" && us.phase === "idle"
        width: parent.width; height: Math.min(notes.implicitHeight, 320) + 24; radius: 14; color: Theme.glass; clip: true
        Md { id: notes; x: 14; y: 12; width: parent.width - 28; color: Theme.ink2; lineHeight: 1.25; source: us.rel ? us.rel.notes : "" } }

    // packaged app: open the download in the browser
    Txt { visible: us.packaged; width: parent.width; tone: 2
        text: "Download the new app in your browser, then replace this one with it. Your projects stay where they are, in the projects folder." }

    // pip / uv / source: FORM runs the upgrade itself
    Column { visible: !!us.u && !us.packaged; width: parent.width; spacing: 10
        Txt { visible: us.phase === "idle"; width: parent.width; tone: 2
            text: "Update now upgrades Form Studio in place, then asks you to restart it. Your projects are not touched." }
        Note { visible: us.phase === "done"; kind: "green"; width: parent.width; title: "The new version is installed"
            text: "This window is still running " + (us.u ? us.u.current : "the old version") + ". Quit Form Studio and open it again to use the new one."
                + (us.job && us.job.fake ? " (FORM_INSTALL_FAKE is set: this was a simulation; nothing was installed.)" : "") }
        Note { visible: us.phase === "failed" || us.phase === "cancelled"; kind: us.phase === "failed" ? "red" : "plain"; width: parent.width
            title: us.phase === "failed" ? "The upgrade did not finish" : "The upgrade was cancelled"
            text: (us.job && us.job.steps.length && us.job.steps[0].message ? us.job.steps[0].message + ". " : "") + "Form Studio is unchanged and keeps working. The output is below." }
        // what the command printed
        Rectangle { objectName: "updateLog"; visible: us.phase !== "idle"; width: parent.width; height: 178; radius: Theme.rMd; color: Theme.glassWell; border.color: Theme.rule; clip: true
            Column { x: 12; width: parent.width - 24; spacing: 2; anchors.bottom: parent.bottom; anchors.bottomMargin: 10
                Repeater { model: us.tail
                    Txt { required property var modelData; width: parent.width; mono: true; font.pixelSize: 11; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        text: (modelData.kind === "cmd" ? "$ " : "") + modelData.text
                        color: modelData.kind === "err" ? Theme.signal : modelData.kind === "cmd" ? Theme.ink : modelData.kind === "note" ? Theme.ink3 : Theme.ink2 } } }
            Row { visible: us.phase === "running"; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 6
                Spinner { size: 10; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; mono: true; text: us.job ? Math.round(us.job.seconds) + " s" : "" } } }
        // the exact command, for anyone who wants to see it or run it themselves
        Item { width: parent.width; height: 22
            Btn { x: -8; small: true; kind: "quiet"; icon: us.showCommand ? "chevron_down" : "chevron_right"; text: "What Update now runs"
                onClicked: us.showCommand = !us.showCommand } }
        Rectangle { visible: us.showCommand; width: parent.width; height: cmd.implicitHeight + 20; radius: Theme.rMd; color: Theme.glassWell; border.color: Theme.rule
            Txt { x: 12; y: 10; mono: true; font.pixelSize: 12; tone: 4; text: "$" }
            Txt { id: cmd; x: 28; y: 10; width: parent.width - 40 - cp.width; mono: true; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; text: us.u ? us.u.command : "" }
            Btn { id: cp; small: true; kind: "quiet"; icon: "copy"; tip: "Copy the command"; anchors.right: parent.right; anchors.rightMargin: 4; y: 4
                onClicked: { Bridge.copy(us.u.command); Store.toast("Copied the upgrade command") } } } }
    Txt { kind: "fine"; width: parent.width
        text: "Form Studio checks GitHub for a new release at most once a day and never upgrades by itself. Turn the check off with [updates] check = false in studio.toml." }
}
