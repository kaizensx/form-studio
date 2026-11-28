import QtQuick
import "F.js" as F
import "FeatureKinds.js" as K

// A sketch nested under the feature it makes (extrude, cut, revolve by hand): one quieter line under the feature's,
// with its named dimensions as parameters. A click opens it in the sketch editor; nothing else is drawn for a feature
// that has no sketch (height 0).
Item {
    id: ts
    property string fid: ""
    property bool shown: true
    readonly property bool has: shown && /^(extrude|cut|revolve)$/.test(K.kindOf(fid))
    readonly property int dims: !has || !Store.recipe ? 0 : Store.recipe.params.filter(function (p) {
        return p.feature === ts.fid && !/_(depth|angle|end|reverse|draft|depth2|thin)$/.test(p.key) }).length
    objectName: has ? "treeSketch-" + fid : ""
    height: has ? 26 : 0
    visible: has
    Rectangle { x: 52; y: 0; width: 1; height: 13; color: Theme.rule2 }
    Rectangle { x: 52; y: 13; width: 8; height: 1; color: Theme.rule2 }
    Rectangle { x: 60; width: parent.width - 60; height: parent.height; radius: 8; color: sm.pressed ? Theme.washPress : sm.containsMouse ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Icon { x: 66; anchors.verticalCenter: parent.verticalCenter; name: "pen_tool"; size: 11; color: Theme.ink3 }
    Txt { x: 84; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; text: "Sketch" }
    Txt { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
        text: F.plural(ts.dims, "dimension") }
    MouseArea { id: sm; anchors.fill: parent; anchors.leftMargin: 60; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: Store.pget("/sketch?feature=" + ts.fid).then(function (r) {
            Store.openSheet("handsketch", { mode: "edit", feature: ts.fid, sketch: r.sketch, values: r.values }) }, function (e) { Store.fail(e) }) }
    Tip { show: sm.containsMouse; text: "Edit the sketch this feature is made from" }
}
