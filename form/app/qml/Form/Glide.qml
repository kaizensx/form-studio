import QtQuick

// The house ease-out for anything entering or answering the pointer. Set `duration` from a Theme motion token.
//   Behavior on opacity { Glide {} }        Glide { property: "scale"; from: Theme.from(0.97); to: 1; duration: Theme.pop }
NumberAnimation { duration: Theme.base; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
