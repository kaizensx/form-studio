import QtQuick
import "F.js" as F

// "Find the best orientation": every way the part can lie on a flat face, ranked by a score whose terms are
// shown. The top three are drawn as they would print. Choosing one goes through the normal settings path.
Column {
    id: of
    width: parent ? parent.width : 0
    spacing: 10
    readonly property var res: Store.orient
    readonly property bool busy: Store.job !== ""
    readonly property var termInk: ({ support: Theme.signal, overhang: Theme.amber, contact: Theme.datum, height: Theme.ink3, layers: Theme.blueprint })
    readonly property var termName: ({ support: "support", overhang: "overhang", contact: "plate contact", height: "height", layers: "layer section" })
    readonly property var termOrder: ["support", "overhang", "contact", "height", "layers"]

    Row { spacing: 8
        Btn { icon: "rotate_3d"; text: Store.orientBusy ? "Comparing…" : of.res ? "Compare again" : "Find the best orientation"
            enabled: !Store.orientBusy; onClicked: Store.findOrientation()
            tip: "Evaluates the six axis orientations and every flat face on the part’s convex hull, and ranks them by a score you can read." }
        Btn { kind: "quiet"; text: "Hide"; visible: !!of.res; onClicked: Store.orient = null } }

    Repeater {
        model: of.res ? of.res.candidates.slice(0, 3) : []
        Rectangle {
            id: card
            required property var modelData
            required property int index
            readonly property var c: modelData
            width: of.width; height: Math.max(124, body.implicitHeight + 20); radius: Theme.rMd
            color: c.current ? Theme.alpha(Theme.datum, 0.06) : Theme.plate2; border.color: c.current ? Theme.alpha(Theme.datum, 0.3) : Theme.rule
            Rectangle { x: 10; y: 10; width: 104; height: 104; radius: Theme.rSm; color: Theme.well; clip: true
                OrientThumb { anchors.fill: parent; mesh: Store.view ? Store.view.mesh : []; cand: card.c } }
            Column { id: body; x: 124; y: 10; width: parent.width - 134; spacing: 5
                Item { width: parent.width; height: 20
                    Txt { mono: true; font.pixelSize: 11; tone: 3; text: String(card.c.rank); anchors.baseline: nm.baseline }
                    Txt { id: nm; x: 14; width: parent.width - 14 - act.width - 6; text: card.c.label; font.weight: 600; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: card.c.current ? Theme.datum : Theme.ink }
                    Item { id: act; anchors.right: parent.right; width: card.c.current ? cur.width : use.width; height: 20
                        Tag { id: cur; visible: card.c.current; text: "current"; kind: "specified"; anchors.verticalCenter: parent.verticalCenter }
                        Btn { id: use; visible: !card.c.current; small: true; kind: "primary"; text: "Use"; enabled: !of.busy && card.c.fits; y: -2
                            tip: card.c.fits ? "Set this print orientation (re-exports the STL, re-runs the checks and the slice)" : "Does not fit the build volume"
                            onClicked: Store.settings({ orientation: card.c.id }) } } }
                Row { spacing: 6
                    Txt { mono: true; font.pixelSize: 12; text: "score " + F.fmt(card.c.score, 3) }
                    Txt { kind: "fine"; text: card.index === 0 ? "lowest of " + of.res.candidates.length : ""; anchors.baseline: parent.children[0].baseline } }
                // what the score is made of: one segment per term, width = its contribution
                Row { width: parent.width; height: 5; spacing: 1
                    Repeater { model: of.termOrder
                        Rectangle { required property string modelData; height: 5; radius: 1; color: of.termInk[modelData]
                            width: Math.max(0, Math.round((body.width - 4) * card.c.terms[modelData])); visible: width > 0
                            opacity: 0.85 } }
                    Rectangle { visible: card.c.score < 0.004; width: 5; height: 5; radius: 1; color: Theme.ink4 } }
                Column { width: parent.width
                    Repeater {
                        model: [["Support", F.fmt(card.c.support_mm3 / 1000, 1) + " cm³"], ["Overhang", F.fmt(card.c.steep_mm2, 0) + " mm²"],
                                ["On the plate", F.fmt(card.c.contact_mm2, 0) + " mm²"], ["Height", F.fmt(card.c.height_mm, 1) + " mm"],
                                ["Smallest layer", card.c.min_layer_mm2 === null || card.c.min_layer_mm2 === undefined ? "no neck" : F.fmt(card.c.min_layer_mm2, 0) + " mm²"]]
                        Item { required property var modelData; width: parent.width; height: 16
                            Txt { kind: "fine"; text: parent.modelData[0]; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                            Txt { mono: true; font.pixelSize: 11; tone: 2; text: parent.modelData[1]; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } } }
                    Txt { kind: "fine"; color: Theme.signal; visible: !card.c.fits; text: "Does not fit the build volume" } }
            }
        }
    }
    Column { width: parent.width; spacing: 6; visible: !!of.res
        Flow { width: parent.width; spacing: 10
            Repeater { model: of.termOrder
                Row { required property string modelData; spacing: 5
                    Rectangle { width: 8; height: 8; radius: 2; color: of.termInk[modelData]; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; tone: 2; text: of.termName[modelData] + " × " + F.fmt(of.res ? of.res.weights[modelData] : 0, 2) } } } }
        Txt { kind: "fine"; width: parent.width
            text: of.res ? "Score = the weighted sum above, each term scaled 0 to 1 across the " + of.res.candidates.length + " candidates; lower is better. "
                + "Support is overhanging area times its height above the plate (an upper bound). Layer section is the smallest slice through "
                + (of.res.structure_features.length ? "the structure features" : "the part") + ": geometry, not strength." : "" }
        Rectangle { width: parent.width; height: nn.implicitHeight + 14; radius: Theme.rSm; color: Theme.alpha(Theme.amber, 0.07)
            Txt { id: nn; x: 9; y: 7; width: parent.width - 18; kind: "fine"; color: Qt.lighter(Theme.amber, 1.3); text: of.res ? of.res.not : "" } }
    }
}
