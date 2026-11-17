import QtQuick
import FormNative

// Markdown as agents write it (replies, release notes). `source` is the Markdown; it is turned into rich text by
// form/app/markdown.py, which lays lists out on the app's grid: Qt's own Markdown gives every list a 40 px indent.
// Links open outside. `text` holds the rich text, so the words of a reply are still found by the interface tests.
Txt {
    id: md
    property string source: ""
    property bool revs: false            // "r04" in a reply links to that revision (agent replies only)
    readonly property var look: ({ revs: revs, mono: Theme.mono, code_bg: String(Theme.well), rule: String(Theme.plate4), muted: String(Theme.ink3), link: String(Theme.datum),
                                   code_px: Theme.tBody - 1, head_px: Theme.tLead })
    textFormat: Text.RichText
    text: source === "" ? "" : Bridge.markdown(source, look)
    lineHeight: 1.45
    color: Theme.ink
    linkColor: Theme.datum
    onLinkActivated: function (l) { if (l.indexOf("form:rev/") === 0) Store.openRevRef(parseInt(l.slice(9))); else Bridge.openLink(l) }
    HoverHandler { enabled: md.hoveredLink !== ""; cursorShape: Qt.PointingHandCursor }
}
