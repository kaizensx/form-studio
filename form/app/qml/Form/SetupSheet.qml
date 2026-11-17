import QtQuick
import FormNative

// Software: everything FORM uses, whether it was found, and a button that installs it. The same registry as the
// first-run steps and Settings › Software. Kept as its own sheet so Store.openSheet("setup") still works.
Column {
    id: ss
    property string title: "Software"
    property string note: "What Form Studio uses on this computer"
    property int sheetWidth: Theme.sheetL
    spacing: 14
    Component.onCompleted: if (!Store.software) Store.checkSoftware()
    function accept() { if (Store.installChosen.length > 0 && !Store.installing) Store.installSoftware() }
    // the same action bar as Settings › Software: what will happen on the left, the actions on the right
    property Component footerLeft: Txt { kind: "fine"; elide: Text.ElideRight; wrapMode: Text.NoWrap; verticalAlignment: Text.AlignVCenter
        text: Store.installing ? "Installing. Each command is in the log." : Store.softwareChecking ? "Looking at what is installed…" : "Nothing is installed until you press Install." }
    property Component footer: Row { spacing: 8
        Btn { visible: Store.installing; icon: "x"; text: "Cancel"; onClicked: Store.cancelInstall() }
        Btn { icon: "refresh_cw"; text: "Check again"; busy: Store.softwareChecking; enabled: !Store.installing
            onClicked: { Store.checkSoftware(); Store.checkSetup() } }
        Btn { kind: "primary"; icon: "download"; enabled: Store.installChosen.length > 0; busy: Store.installing; keys: "Return"
            text: Store.installing ? "Installing…" : Store.installChosen.length ? "Install " + Store.installChosen.length + " selected" : "Install selected"
            onClicked: Store.installSoftware() } }
    SoftwarePanel { width: parent.width; actions: false }
}
