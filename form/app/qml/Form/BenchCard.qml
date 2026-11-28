import QtQuick
import "F.js" as F

// The selected row of the Bench, opened under the list (direction I, decision 6): what it found, how that is known,
// what you get and what it needs, the exact request Run makes, and the buttons. No modal and no second pane: the list
// above stays as the way out. Everything it says is the engine's entry (form/studies.py); a row that has not run
// shows no number, and one that cannot run says what it needs.
Rectangle {
    id: card
    objectName: "benchCard"
    property var e: null
    property bool wide: false            // the Bench sheet's foot: the request and the buttons side by side
    readonly property bool off: !!e && (e.state === "unavailable" || e.state === "n/a")
    readonly property bool has: !!e && (e.state === "current" || e.state === "stale") && !!e.headline
    // the headline's first number stands large; the words around it say what it is
    readonly property var cut: { var m = has ? /^(.*?)(\d[\d.,]*(?:\s?(?:of|×|h|\/)\s?\d[\d.,]*)*)(.*)$/.exec(e.headline) : null
        return rcard.lead ? rcard.lead : m ? [m[2], (m[1] + " " + m[3]).replace(/\s+/g, " ").replace(/^[\s·]+|[\s·]+$/g, "")] : ["", has ? e.headline : ""] }
    readonly property string action: !e || off || e.state === "running" ? "" : e.by === "agent" ? "Ask your agent" : e.by === "person" ? "Go to the release"
        : e.state === "current" ? (opens && !drawn ? openWord : "Run again") : e.state === "stale" ? "Run for " + Store.revWord(e.head) : "Run"
    // what a current entry opens in the window (Store.openStudy); any other with a file shows the file
    readonly property var surfaces: ["simulate", "mass", "slicerOpen", "lighter", "share", "turntable", "render", "game", "parts", "fit", "orient", "exportProject"]
    readonly property bool surface: !!e && ((e.app || "").indexOf("map.") === 0 || surfaces.indexOf(e.app || "") >= 0)
    // an entry whose result is drawn on the part, or as the sheet, while its row is the selected one (Results.qml)
    readonly property bool drawn: Results.draws(e)
    readonly property bool filed: !!e && !!e.files && e.files.length > 0
    readonly property bool opens: !!e && e.state === "current" && e.by === "engine" && (surface || filed)
    readonly property string openWord: !e ? "" : (e.app || "").indexOf("map.") === 0 ? "Show on the part" : e.app === "simulate" ? "Play it" : e.app === "mass" ? "Show the centre of mass"
        : e.app === "slicerOpen" ? "Open in the slicer" : surface ? "Open" : "Show the file"
    function act() { if (!e) return; if (drawn && e.state === "current") Store.runStudy(e.id, true); else if (opens && surface) Store.openStudy(e); else if (opens) Bridge.reveal(Bridge.fileUrl(e.files[0])); else Store.runStudy(e.id, e.state === "current") }
    width: parent ? parent.width : 0
    height: e ? col.implicitHeight + 28 : 0; visible: !!e
    radius: 14; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.045 : 0.035); border.color: Theme.rule
    Column { id: col; x: 14; y: 14; width: parent.width - 28; spacing: 9
        Item { width: parent.width; height: 20
            Txt { objectName: "cardName"; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15; text: card.e ? card.e.label : ""
                width: parent.width - says.width - 26; elide: Text.ElideRight; wrapMode: Text.NoWrap }
            Rectangle { anchors.right: says.left; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3
                readonly property string k: card.e ? Store.benchDot(card.e) : "none"
                readonly property color c: k === "ok" ? Theme.pass : k === "warn" || k === "stale" ? Theme.amber : k === "fail" ? Theme.signal : k === "live" ? Theme.datum : Theme.ink3
                color: k === "none" || k === "stale" ? "transparent" : c; border.width: k === "none" || k === "stale" ? 1 : 0; border.color: c }
            Txt { id: says; objectName: "cardState"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; tone: 3; wrapMode: Text.NoWrap
                text: card.e ? Store.benchSays(card.e) : "" } }
        // the number, then how it is known
        Flow { visible: card.has; width: parent.width; spacing: 8
            Txt { objectName: "cardNumber"; visible: text !== ""; text: card.cut[0]; mono: true; font.pixelSize: 28; font.weight: Font.Light; tone: 1; wrapMode: Text.NoWrap; height: 34; verticalAlignment: Text.AlignBottom }
            Txt { visible: text !== ""; text: card.cut[1]; tone: 2; width: Math.min(implicitWidth, col.width); height: 31; verticalAlignment: Text.AlignBottom; elide: Text.ElideRight; wrapMode: Text.NoWrap }
            Ev { objectName: "cardEvidence"; text: card.e ? (rcard.lead ? Store.evWord(card.e.evidence) : card.e.evidence || "") : ""; lit: true; height: 30; verticalAlignment: Text.AlignBottom } }
        Txt { visible: !!card.e && card.e.state === "failed"; width: parent.width; color: Theme.signal
            text: card.e && card.e.error ? (card.e.error.message || "It failed.") + (card.e.error.hint ? " " + card.e.error.hint : "") : "" }
        Txt { visible: text !== "" && !card.drawn; width: parent.width; kind: "fine"; tone: 2; text: card.e && card.has ? card.e.detail || "" : "" }
        // what the result says, line by line (a strength study's convergence, a check's rules, a setup's operations)
        ResultCard { id: rcard; e: card.drawn ? card.e : null; width: parent.width }
        Txt { visible: text !== ""; width: parent.width; kind: "fine"; tone: 3; text: card.e ? card.e.note || "" : "" }
        Repeater { model: !card.e ? [] : [["You get", card.e.doc || ""], ["Needs", card.off ? card.e.why || "" : ""], ["Made of", card.has ? "" : (card.e.inputs || []).join(", ")],
                                         ["File", card.e.files && card.e.files.length ? String(card.e.files[0]).replace(/^.*[\/\\]/, "") + (card.e.files.length > 1 ? " and " + (card.e.files.length - 1) + " more" : "") : ""]]
                                        .filter(function (r) { return r[1] !== "" })
            Item { required property var modelData; width: col.width; height: Math.max(16, dv.implicitHeight)
                Txt { kind: "fine"; tone: 3; text: modelData[0]; width: 58; wrapMode: Text.NoWrap }
                Txt { id: dv; x: 62; width: parent.width - 62; kind: "fine"; tone: 2; text: modelData[1] } } }
        Rectangle { visible: rq.text !== ""; width: parent.width; height: rq.implicitHeight + 14; radius: 8; color: Theme.glassWell
            Txt { id: rq; objectName: "cardRequest"; x: 9; y: 7; width: parent.width - 18; mono: true; font.pixelSize: 11; tone: 2; wrapMode: Text.WrapAnywhere
                text: card.e && !card.off ? Store.benchRequest(card.e) : "" } }
        Row { spacing: 8; visible: card.action !== "" || (!!card.e && card.e.state === "running")
            Btn { objectName: "cardRun"; small: true; kind: "primary"; visible: card.action !== ""; text: card.action
                icon: card.e && card.e.by === "agent" ? "sparkles" : ""; onClicked: card.act() }
            Btn { objectName: "cardAgain"; small: true; visible: card.opens && !card.drawn; text: "Run again"; onClicked: Store.runStudy(card.e.id, true) }
            Btn { small: true; kind: "quiet"; visible: !!card.e && card.e.state === "running"; busy: true; text: "Running…"; enabled: false }
            Btn { objectName: "cardReveal"; small: true; kind: "quiet"; visible: card.filed && !(card.opens && !card.surface); text: "Show the file"
                onClicked: Bridge.reveal(Bridge.fileUrl(card.e.files[0])) } }
    }
}
