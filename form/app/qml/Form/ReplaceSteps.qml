import QtQuick
import FormNative

// The four steps of Replace a broken part (form/replace.py STEPS): Photo, Estimate, Measure, Design. `done` steps
// carry a tick, the `active` one a spinner; the rest wait. Above the conversation the steps are read from what the
// agent really did (Store.replaceProgress): a measurement asked and answered, a design created.
Item {
    id: rp
    objectName: "replaceSteps"
    property int done: 0                      // how many steps are finished, from the left
    property int active: -1                   // the step in progress, or -1
    readonly property var steps: [{ t: "Photo", d: "of the broken part" }, { t: "Estimate", d: "sizes from the photo" },
                                  { t: "Measure", d: "what decides the fit" }, { t: "Design", d: "the replacement" }]
    implicitHeight: 44; height: implicitHeight
    Row { anchors.fill: parent; spacing: 0
        Repeater { model: rp.steps
            Item { id: st; required property var modelData; required property int index
                readonly property bool fin: index < rp.done
                readonly property bool now: index === rp.active
                width: rp.width / 4; height: rp.height
                Rectangle { visible: st.index > 0; x: 0; width: 13; height: 1; y: 11
                    color: st.fin || st.now ? Theme.datum : Theme.rule2; Behavior on color { Tint {} } }
                Rectangle { id: dot; x: st.index > 0 ? 13 : 0; width: 22; height: 22; radius: 11
                    color: st.fin ? Theme.datum : "transparent"; border.width: st.fin ? 0 : 1
                    border.color: st.now ? Theme.datum : Theme.rule3
                    Behavior on color { Tint {} }
                    Icon { anchors.centerIn: parent; visible: st.fin; name: "check"; size: 12; color: Theme.plate1 }
                    Spinner { anchors.centerIn: parent; visible: st.now; size: 12 }
                    Txt { anchors.centerIn: parent; visible: !st.fin && !st.now; kind: "fine"; tone: 3; text: String(st.index + 1) } }
                Rectangle { x: dot.x + dot.width; width: parent.width - x; height: 1; y: 11
                    color: st.fin ? Theme.datum : Theme.rule2; Behavior on color { Tint {} } }
                Column { x: dot.x; y: 26; width: parent.width - dot.x - 4
                    Txt { text: st.modelData.t; font.pixelSize: 12; font.weight: st.fin || st.now ? Theme.wSemi : 420; tone: st.fin || st.now ? 1 : 3
                        wrapMode: Text.NoWrap; elide: Text.ElideRight; width: parent.width } }
                objectName: "replaceStep_" + st.modelData.t.toLowerCase()
                property string state_: st.fin ? "done" : st.now ? "active" : "waiting"
            }
        }
    }
}
