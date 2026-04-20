import QtQuick
import QtMultimedia

Item {
    id: root

    property alias videoOutput: liveView
    property int maskEnabled: 1
    property real maskOpacity: 0.92
    property real maskMidOpacity: 0.52
    property real maskInnerOpacity: 0.12
    property real maskTopRatio: 0.24
    property real maskRightRatio: 0.12
    property real maskBottomRatio: 0.08
    property real maskLeftRatio: 0.12

    signal captureSaved(string path, bool success)

    function captureToFile(path) {
        root.grabToImage(function(result) {
            const ok = result ? result.saveToFile(path) : false
            root.captureSaved(path, ok)
        })
    }

    readonly property real topMaskHeight: height * maskTopRatio
    readonly property real bottomMaskHeight: height * maskBottomRatio
    readonly property real leftMaskWidth: width * maskLeftRatio
    readonly property real rightMaskWidth: width * maskRightRatio

    VideoOutput {
        id: liveView
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    Item {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.topMaskHeight

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, root.maskOpacity) }
                GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, root.maskMidOpacity) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, root.maskInnerOpacity) }
            }
        }
    }

    Item {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.bottomMaskHeight

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, root.maskInnerOpacity) }
                GradientStop { position: 0.45; color: Qt.rgba(0, 0, 0, root.maskMidOpacity) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, root.maskOpacity) }
            }
        }
    }

    Item {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.leftMaskWidth

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, root.maskOpacity) }
                GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, root.maskMidOpacity) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, root.maskInnerOpacity) }
            }
        }
    }

    Item {
        visible: root.maskEnabled === 1
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.rightMaskWidth

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, root.maskInnerOpacity) }
                GradientStop { position: 0.45; color: Qt.rgba(0, 0, 0, root.maskMidOpacity) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, root.maskOpacity) }
            }
        }
    }
}
