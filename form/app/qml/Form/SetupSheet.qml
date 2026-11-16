import QtQuick
import FormNative

// Software: everything FORM uses, whether it was found, and a button that installs it. The same registry as the
// first-run steps and Settings › Software. Kept as its own sheet so Store.openSheet("setup") still works.
Column {
    id: ss
    property string title: "Software"
    property int sheetWidth: 780
    spacing: 14; bottomPadding: 20
    Component.onCompleted: if (!Store.software) Store.checkSoftware()
    SoftwarePanel { width: parent.width }
}
