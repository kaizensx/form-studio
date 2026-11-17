import QtQuick
import QtQuick.Controls
import "F.js" as F

// The legend of the analysis map on the model: what the colours mean (with units), how the numbers are known,
// and one line on what the map does not tell you. `map` is the engine result; `busy` while it is being computed.
// It lives in the viewport's dock (top right). Collapsed, it is its header: the map's name, how it is known and
// the first number. It never grows past `maxHeight`; the rest scrolls.
Rectangle {
    id: lg
    property var map: null
    property bool busy: false
    property string pending: ""          // label of the map being computed
    property var check: null             // the matching pipeline check, when there is one (e.g. Thinnest wall)
    property bool collapsed: false
    property real maxHeight: 520
    signal toggled()
    readonly property var legend: map ? map.legend : null
    readonly property var st: map && map.stats ? map.stats : ({})
    readonly property var facts: map ? factList() : []
    width: 252; radius: Theme.rMd
    height: collapsed ? 36 : Math.min(maxHeight, 36 + col.implicitHeight + 14)
    color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule

    function factList() {                // the two or three numbers worth reading first
        var f = []
        if (map.map === "thickness") {
            if (st.min_mm !== undefined) f.push(["Thinnest sample", F.fmt(st.min_mm, 2) + " mm"])
            if (st.median_mm !== undefined) f.push(["Median", F.fmt(st.median_mm, 2) + " mm"])
            f.push(["Under 2 perimeters", F.fmt(st.under_two_perimeters_pct, 1) + "% of surface"])
            if (check) f.push(["Check “" + check.label + "”", String(check.value)])
        } else if (map.map === "overhang") {
            f.push(["Unsupported overhang", F.fmt(st.steep_mm2, 0) + " mm²"])
            f.push(["Flat ceilings", F.fmt(st.ceiling_mm2, 0) + " mm²"])
            f.push(["On the plate", F.fmt(st.contact_mm2, 0) + " mm²"])
        } else if (map.map === "section") {
            f.push(["Largest slice", F.fmt(st.max_mm2, 0) + " mm²"])
            f.push(["Weakest neck", st.neck ? F.fmt(st.neck.area_mm2, 0) + " mm² at " + F.fmt(st.neck.z_mm, 1) + " mm" : "none"])
        } else {
            f.push(["Walls or edges under one nozzle", st.thin_markers ? F.fmt(st.thin_pct, 1) + "% of surface" : "none"])
            f.push(["Gaps under one nozzle", st.gap_markers ? F.fmt(st.gap_pct, 1) + "% of surface" : "none"])
            f.push(["Small holes", st.small_holes + " of " + st.holes])
        }
        return f
    }

    // header: always there
    Item { id: head; width: parent.width; height: 36
        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: Theme.rSm; color: hm.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent" }
        Txt { kind: "cap"; x: 14; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; elide: Text.ElideRight
            width: parent.width - 14 - right.width - 14
            text: lg.legend ? lg.legend.title : lg.pending }
        Row { id: right; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Txt { visible: lg.collapsed && lg.facts.length > 0; mono: true; font.pixelSize: 11; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                text: lg.facts.length ? lg.facts[0][1] : "" }
            Tag { anchors.verticalCenter: parent.verticalCenter
                text: lg.busy && !lg.map ? "computing" : "computed"; kind: lg.busy && !lg.map ? "assumed" : "computed" }
            Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter; rotation: lg.collapsed ? -90 : 0
                Behavior on rotation { NumberAnimation { duration: Motion.move(140); easing.type: Easing.OutCubic } } } }
        MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: lg.toggled() }
        Tip { show: hm.containsMouse; text: lg.collapsed ? "Show the legend" : "Fold the legend away" }
    }

    Flickable {
        visible: !lg.collapsed
        x: 0; y: 36; width: parent.width; height: parent.height - 36 - 2
        contentHeight: col.implicitHeight + 12; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 5 }
        Column {
            id: col; x: 14; width: parent.width - 28; spacing: 9
            Txt { kind: "fine"; width: parent.width; visible: lg.busy && !lg.map
                text: "Casting rays through the solid. A few seconds the first time; cached for this revision afterwards." }

            // colour scale
            Column { width: parent.width; spacing: 6; visible: !!lg.legend
                Repeater {
                    model: lg.legend ? lg.legend.stops : []
                    Item { id: sw
                        required property var modelData
                        width: parent.width; height: Math.max(18, sn.implicitHeight + 15)
                        Rectangle { y: 2; width: 30; height: 12; radius: 2; border.color: Theme.rule2
                            gradient: Gradient { orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: sw.modelData.color }
                                GradientStop { position: 1; color: sw.modelData.to || sw.modelData.color } } }
                        Txt { x: 40; mono: true; font.pixelSize: 12; text: sw.modelData.label
                            width: parent.width - 40; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { id: sn; x: 40; y: 15; kind: "fine"; width: parent.width - 40; text: sw.modelData.note || "" } } } }
            Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!lg.map && (lg.map.map === "overhang" || lg.map.map === "section")
                text: lg.map ? "Printed “" + lg.map.orientation_label + "”" + (lg.map.map === "overhang" ? ", angles in degrees past vertical" : "") : "" }

            // the numbers
            Column { width: parent.width; visible: !!lg.map
                Repeater {
                    model: lg.facts
                    Item { required property var modelData; required property int index
                        width: parent.width; height: 22
                        Rectangle { visible: parent.index > 0; width: parent.width; height: 1; color: Theme.rule }
                        Txt { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; text: parent.modelData[0]; width: parent.width - fv.width - 8; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Txt { id: fv; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; text: parent.modelData[1]; wrapMode: Text.NoWrap } } } }

            SectionChart { visible: !!lg.map && !!lg.map.chart; chart: lg.map ? lg.map.chart || null : null }

            Txt { kind: "fine"; tone: 2; width: parent.width; visible: !!lg.legend
                text: lg.legend ? lg.legend.what + " Revision " + F.pad(lg.map.rev) + ", tessellated at " + lg.map.tessellation_mm + " mm." : "" }
            Rectangle { width: parent.width; height: nt.implicitHeight + 14; radius: Theme.rSm; color: Theme.alpha(Theme.amber, 0.07); visible: !!lg.legend
                Txt { id: nt; x: 9; y: 7; width: parent.width - 18; kind: "fine"; color: Qt.lighter(Theme.amber, 1.3); text: lg.legend ? lg.legend.not : "" } }
        }
    }
}
