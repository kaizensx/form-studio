import QtQuick
import "F.js" as F

// A file on its way in (a fetched link, an attachment uploading): its name, how much has arrived, a thin bar. It shows
// only while one runs (Store.fetching) and says nothing it does not know: no fraction until the size is known.
Item {
    id: fp
    objectName: "fetchProgress"
    readonly property var p: Store.fetchProgress
    visible: Store.fetching > 0
    implicitHeight: visible ? 30 : 0
    Row { x: 2; y: 4; spacing: 8; width: parent.width - 4
        Icon { name: "loader_circle"; size: 12; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
        Txt { kind: "fine"; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideMiddle; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter
            text: !fp.p ? (Store.fetching > 1 ? "Bringing in " + Store.fetching + " files…" : "Bringing in the file…")
                : (fp.p.name ? fp.p.name : "Downloading") + " · " + F.bytes(fp.p.done) + (fp.p.total > 0 ? " of " + F.bytes(fp.p.total) : "")
                  + (fp.p.count > 1 ? " · " + fp.p.count + " files" : "") }
    }
    Rectangle { x: 2; y: 24; width: parent.width - 4; height: 2; radius: 1; color: Theme.rule
        Rectangle { visible: !!fp.p && fp.p.fraction >= 0; height: parent.height; radius: 1; color: Theme.datum
            width: fp.p && fp.p.fraction >= 0 ? parent.width * fp.p.fraction : 0
            Behavior on width { NumberAnimation { duration: Theme.fast } } } }
}
