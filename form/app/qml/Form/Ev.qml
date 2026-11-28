import QtQuick

// An evidence word: how a number is known (computed, simulated, specified, measured, assumed…), in mono capitals
// beside the number. It is a word, not a pill: it takes its colour only when `lit` (the row it stands in is the one
// selected, or the word is the point of the line). Where a state needs a ground, use Tag.
Text {
    property bool lit: false
    property string kind: text
    color: lit ? Theme.evidence(kind) : Theme.ink3
    font.family: Theme.mono; font.pixelSize: Theme.tEv; font.weight: Theme.wMedium; font.letterSpacing: Theme.evTrack
    font.capitalization: Font.AllUppercase; renderType: Theme.textRender; textFormat: Text.PlainText; wrapMode: Text.NoWrap
}
