import QtQuick

// Indeterminate progress. Quick on purpose: a fast spinner reads as a fast app.
Icon {
    id: sp
    property bool running: visible
    name: "loader_circle"; size: 14; color: Theme.datum
    RotationAnimation on rotation { running: sp.running; from: 0; to: 360; duration: 720; loops: Animation.Infinite }
}
