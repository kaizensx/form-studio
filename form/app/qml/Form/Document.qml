import QtQuick

// Under the Document chapter of the Bench (Bench.qml lists the documents, BenchCard opens the selected one): what to do
// when none is selected. Nothing here is a row: every document is the engine's own entry (form/studies.py).
Column {
    width: parent ? parent.width : 0
    topPadding: 2; bottomPadding: 8; spacing: 8
    Txt { objectName: "docHint"; x: 12; width: parent.width - 24; kind: "fine"; tone: 2
        text: "Select a document to see what it makes, what it needs and the request it sends." }
}
