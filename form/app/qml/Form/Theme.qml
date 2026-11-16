pragma Singleton
import QtQuick

// FORM — a metrology bench at night.
// Graphite build plate, one pale-mint datum colour, clay for the part itself.
// Colour is evidence: datum = settled, blueprint = draft/compare, amber = review, signal = fail.
QtObject {
    // surfaces, lowest to highest
    readonly property color well: "#0a0c0e"        // inset: inputs receive content
    readonly property color plate: "#0e1113"       // the bench
    readonly property color plate1: "#13171a"      // panels resting on the bench
    readonly property color plate2: "#191e22"      // raised: cards
    readonly property color plate3: "#21282d"      // highest: menus, buttons
    readonly property color plate4: "#2a3238"
    // ink
    readonly property color ink: "#e8edeb"
    readonly property color ink2: "#a8b2af"
    readonly property color ink3: "#717b78"
    readonly property color ink4: "#49524f"
    readonly property color rule: Qt.rgba(1, 1, 1, 0.07)
    readonly property color rule2: Qt.rgba(1, 1, 1, 0.12)
    // meaning
    readonly property color datum: "#b9e8d7"
    readonly property color datumInk: "#0d1a16"
    readonly property color blueprint: "#86a8ff"
    readonly property color amber: "#e9b860"
    readonly property color signal: "#ff6f51"
    readonly property color pass: "#86d9ad"
    readonly property color clay: "#d8d3c8"

    readonly property string sans: "Instrument Sans"
    readonly property string mono: "Geist Mono"
    readonly property string icons: "lucide"

    // type scale (ratio ~1.2 from 13)
    readonly property int tCap: 10
    readonly property int tFine: 11
    readonly property int tBody: 13
    readonly property int tLead: 15
    readonly property int tH3: 18
    readonly property int tH2: 22
    readonly property int tH1: 30
    readonly property int tHero: 44

    readonly property int rXs: 4
    readonly property int rSm: 6
    readonly property int rMd: 9
    readonly property int rLg: 14

    // spacing: 4px base
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s8: 32

    // motion
    readonly property int fast: 120
    readonly property int base: 180
    readonly property int slow: 320
    readonly property var easeOut: [0.23, 1, 0.32, 1, 1, 1]
    readonly property var easeMove: [0.77, 0, 0.175, 1, 1, 1]

    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    // how a number is known → colour
    function evidence(kind) {
        switch (kind) {
        case "measured": case "physical": case "calibrated": case "PASS": return pass
        case "specified": case "computed": case "interface": case "geometry": return datum
        case "assumed": case "photo": case "WARN": case "simulated": case "modelled": case "model": return amber
        case "FAIL": case "resized": case "moved": case "added": case "removed": return signal
        case "trimmed": case "draft": return blueprint
        }
        return ink2
    }
}
