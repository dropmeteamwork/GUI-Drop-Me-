import QtQuick
import QtMultimedia

Item {
    id: root

    property alias videoOutput: liveView
    property int maskEnabled: 1
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

    Rectangle {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.topMaskHeight
        color: "black"
    }

    Rectangle {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.bottomMaskHeight
        color: "black"
    }

    Rectangle {
        visible: root.maskEnabled === 1
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.leftMaskWidth
        color: "black"
    }

    Rectangle {
        visible: root.maskEnabled === 1
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.rightMaskWidth
        color: "black"
    }
}
