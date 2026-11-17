import QtQuick
import FormNative

// Markdown as agents write it (replies, release notes). `source` is the Markdown; it is turned into rich text by
// form/app/markdown.py, which lays lists out on the app's grid: Qt's own Markdown gives every list a 40 px indent.
// Links open outside. `text` holds the rich text, so the words of a reply are still found by the interface tests.
Txt {
    id: md
    property string source: ""
    readonly property var look: ({ mono: Theme.mono, code_bg: String(Theme.well), rule: String(Theme.plate4), muted: String(Theme.ink3), link: String(Theme.datum),
                                   code_px: Theme.tBody - 1, head_px: Theme.tLead })
    textFormat: Text.RichText
    text: source === "" ? "" : Bridge.markdown(source, look)
    lineHeight: 1.45
    color: Theme.ink
    linkColor: Theme.datum
    onLinkActivated: function (l) { Bridge.openLink(l) }
    HoverHandler { enabled: md.hoveredLink !== ""; cursorShape: Qt.PointingHandCursor }
}
