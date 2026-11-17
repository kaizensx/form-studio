import QtQuick
import QtQuick.Dialogs
import FormNative

// Save dialogs for exports asked for from menus and the palette (home workstream): a design as a .formstudio file,
// a conversation as Markdown or JSON, and the import dialog. Lives in Main.qml so it works on every screen.
Item {
    id: ex
    visible: false
    Connections { target: Store
        function onExportRequested(kind, id, fmt) {
            if (kind === "project") { proj.pid = id; proj.currentFile = Bridge.downloads() + "/" + id + ".formstudio"; Store.ask(proj) }
            else if (kind === "conversation") { conv.cid = id; conv.fmt = fmt || "md"; conv.currentFile = Bridge.downloads() + "/conversation-" + id + "." + conv.fmt; Store.ask(conv) }
            else if (kind === "import") Store.ask(imp)
        } }
    FileDialog { id: proj; property string pid: ""; title: "Export the design"; fileMode: FileDialog.SaveFile; nameFilters: ["Form Studio projects (*.formstudio)"]
        onAccepted: { if (Bridge.save("/archive/" + pid + ".formstudio", selectedFile)) Store.toast("Exported", "The design, its history, its conversations and its code are in one file.")
                      else Store.toast("Could not write that file", "Choose another place.", true) } }
    FileDialog { id: conv; property string cid: ""; property string fmt: "md"; title: "Export the conversation"; fileMode: FileDialog.SaveFile
        nameFilters: fmt === "md" ? ["Markdown (*.md)"] : ["JSON (*.json)"]
        onAccepted: { if (Bridge.save("/archive/conversation/" + cid + "." + fmt, selectedFile)) Store.toast("Conversation exported", fmt === "md" ? "As Markdown, to read or share." : "As JSON: Import brings it back.")
                      else Store.toast("Could not write that file", "Choose another place.", true) } }
    FileDialog { id: imp; title: "Import into Form Studio"; nameFilters: ["Form Studio files (*.formstudio *.formproj *.json)"]; onAccepted: Store.importFile(selectedFile) }
}
