import QtQuick
import QtQuick.Controls
import FormNative

// First run (no marker in the data folder) or a required part missing: a calm full-window checklist.
// Nothing is installed until the user ticks an item and presses Apply.
Rectangle {
    id: wl
    color: Theme.plate
    readonly property var st: Store.setup
    readonly property bool busy: !!Store.setupJob && Store.setupJob.state === "running"
    readonly property bool ready: !!st && st.required_ok
    MouseArea { anchors.fill: parent; hoverEnabled: true }        // the home screen underneath stays inert
    Flickable {
        anchors.top: parent.top; anchors.bottom: bar.top; width: parent.width
        contentHeight: col.implicitHeight + 72; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col
            width: Math.min(720, wl.width - 64); x: (wl.width - width) / 2; y: 44
            spacing: 14
            Txt { kind: "h1"; text: "Welcome to FORM" }
            Txt { kind: "lead"; tone: 2; width: parent.width
                text: "An AI agent designs 3D-printable parts here with a real CAD kernel and a real slicer, and every number says how it is known." }
            Txt { tone: 3; width: parent.width
                text: "This is what FORM found on this computer. Tick what you want it to set up. Nothing is installed or changed until you press Apply, and each command is shown before it runs." }
            Note { visible: !!wl.st && !wl.st.required_ok; kind: "amber"; title: "FORM cannot design parts yet"
                text: "A required item below is not ready. Fix it, then press Check again." }
            Item { width: 1; height: 2 }
            SetupList { width: parent.width }
        }
    }
    // the actions stay in view however long the list is
    Rectangle {
        id: bar
        anchors.bottom: parent.bottom; width: parent.width; height: 64; color: Theme.plate1
        Rectangle { width: parent.width; height: 1; color: Theme.rule }
        Item { width: col.width; x: col.x; height: 30; anchors.verticalCenter: parent.verticalCenter
            Row { spacing: 8; anchors.verticalCenter: parent.verticalCenter
                Btn { kind: "primary"; icon: "wrench"; enabled: Store.setupChosen.length > 0 && !wl.busy
                    text: wl.busy ? "Setting up…" : Store.setupChosen.length ? "Apply selected (" + Store.setupChosen.length + ")" : "Apply selected"
                    onClicked: Store.applySetup() }
                Btn { icon: "refresh_cw"; text: Store.setupChecking ? "Checking…" : "Check again"; enabled: !Store.setupChecking && !wl.busy; onClicked: Store.checkSetup() }
                Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; leftPadding: 6; wrapMode: Text.NoWrap
                    text: "Later: “Check setup” in " + (Bridge.platform === "darwin" ? "⌘K" : "Ctrl K") } }
            Btn { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: wl.ready ? "default" : "quiet"; enabled: !wl.busy
                text: wl.ready ? "Continue to FORM" : "Skip for now"; icon: wl.ready ? "arrow_right" : ""
                onClicked: Store.closeWelcome(wl.ready ? "done" : "skipped") } }
    }
}
