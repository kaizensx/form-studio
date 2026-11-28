import QtQuick
import QtQuick.Shapes

// The view cube: where you look from, at the stage's top right (direction I, decision 12). It replaces the row of view
// buttons that stood at the foot of the stage. A face is a view: the top is Top, the left face Front, the right face
// Side; the rim between the faces is Iso, and a double click looks from Under. The face you are looking at is lit in
// the accent. Keys 1 to 5 do the same. It is drawn once and never animates.
Glass {
    id: vc
    objectName: "viewCube"
    width: 64; height: 64; radius: 20
    property string view: Store.viewName
    signal picked(string name)
    readonly property color line: Theme.ink2
    readonly property color face: Theme.glass2
    readonly property color lit: Theme.alpha(Theme.datum, Theme.dark ? 0.22 : 0.16)
    // the cube in a 44 × 44 box, as drawn in the mockup: top (22,4) (37,12.5) (22,21) (7,12.5); the body down to (22,38)
    function faceAt(x, y) {
        var px = x - 10, py = y - 10
        function inside(p) { var c = false; for (var i = 0, j = p.length - 1; i < p.length; j = i++) { var a = p[i], b = p[j]
            if ((a[1] > py) !== (b[1] > py) && px < (b[0] - a[0]) * (py - a[1]) / (b[1] - a[1]) + a[0]) c = !c } return c }
        // the middle of each face is the face; the rim between them is the corner view
        if (inside([[22, 7.5], [31, 12.5], [22, 17.5], [13, 12.5]])) return "top"
        if (inside([[9.5, 17], [19.5, 22.7], [19.5, 33.5], [9.5, 27.8]])) return "front"
        if (inside([[24.5, 22.7], [34.5, 17], [34.5, 27.8], [24.5, 33.5]])) return "side"
        return "iso"
    }
    Rectangle { anchors.fill: parent; anchors.margins: 4; radius: vc.radius - 4; color: cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Item { id: art; x: 10; y: 10; width: 44; height: 44
        Shape { anchors.fill: parent; preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: vc.view === "front" ? Theme.datum : vc.line; strokeWidth: 1.2; joinStyle: ShapePath.RoundJoin; fillColor: vc.view === "front" ? vc.lit : vc.face
                PathMove { x: 7; y: 12.5 } PathLine { x: 22; y: 21 } PathLine { x: 22; y: 38 } PathLine { x: 7; y: 29.5 } PathLine { x: 7; y: 12.5 } }
            ShapePath { strokeColor: vc.view === "side" ? Theme.datum : vc.line; strokeWidth: 1.2; joinStyle: ShapePath.RoundJoin; fillColor: vc.view === "side" ? vc.lit : vc.face
                PathMove { x: 37; y: 12.5 } PathLine { x: 22; y: 21 } PathLine { x: 22; y: 38 } PathLine { x: 37; y: 29.5 } PathLine { x: 37; y: 12.5 } }
            ShapePath { strokeColor: vc.view === "top" || vc.view === "iso" ? Theme.datum : vc.line; strokeWidth: 1.2; joinStyle: ShapePath.RoundJoin
                fillColor: vc.view === "top" || vc.view === "iso" ? vc.lit : vc.face
                PathMove { x: 22; y: 4 } PathLine { x: 37; y: 12.5 } PathLine { x: 22; y: 21 } PathLine { x: 7; y: 12.5 } PathLine { x: 22; y: 4 } }
            // looking from under: the foot of the cube is the lit edge
            ShapePath { strokeColor: vc.view === "under" ? Theme.datum : "transparent"; strokeWidth: 1.6; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin; fillColor: "transparent"
                PathMove { x: 7; y: 29.5 } PathLine { x: 22; y: 38 } PathLine { x: 37; y: 29.5 } }
        }
    }
    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true
        property string over: "iso"
        onPositionChanged: function (e) { over = vc.faceAt(e.x, e.y) }
        onClicked: function (e) { vc.picked(vc.faceAt(e.x, e.y)) }
        onDoubleClicked: vc.picked("under") }
    Tip { show: cm.containsMouse && !cm.pressed      // over the cube: the shading chip stands under it
        text: ({ top: "Top", front: "Front", side: "Side", iso: "Iso" })[cm.over] + " view. Double-click looks from under."; keys: ({ iso: "1", front: "2", side: "3", top: "4" })[cm.over] }
}
