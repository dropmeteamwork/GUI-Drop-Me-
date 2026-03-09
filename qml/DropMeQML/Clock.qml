import QML
import QtQuick
import QtQuick.Window

Item {
    property real interval: 1_000
    signal triggered
    signal finished

    id: clock

    function reset() {
        timer.running = false
        resource.clockIndex = 0
    }

    function start() {
        resource.clockIndex = 0
        timer.running = true
    }

    function finish() {
        resource.clockIndex = resource.clockNames.length - 2
        timer.running = true
    }

    function forceFinish() {
        timer.running = false
        resource.clockIndex = resource.clockNames.length - 1
        clock.finished()
    }

    Resource {
        id: resource
        property list<string> clockNames: [
            "clock-1.png", "clock-2.png",
            "clock-3.png", "clock-4.png",
            "clock-5.png", "clock-6.png",
            "clock-7.png"
        ]
        property int clockIndex: 0

        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 15
        anchors.topMargin: 15
        name: clockNames[clockIndex]

        Timer {
            id: timer
            interval: clock.interval
            running: false
            repeat: true
            onTriggered: {
                resource.clockIndex += 1
                animation.running = true
                if (resource.clockIndex == resource.clockNames.length - 1) {
                    clock.finished()
                    running = false
                } else {
                    clock.triggered()
                }
            }
        }

        ParallelAnimation {
            id: animation
            SequentialAnimation {
                NumberAnimation { target: resource; property: "anchors.topMargin"; to: 5; duration: 75; }
                NumberAnimation { target: resource; property: "anchors.topMargin"; to: 15; duration: 75; }
            }
            SequentialAnimation {
                RotationAnimation { target: resource; property: "rotation"; from: 0; to: -30; duration: 50; }
                RotationAnimation { target: resource; property: "rotation"; from: -30; to: 30; duration: 50; }
                RotationAnimation { target: resource; property: "rotation"; from: 30; to: 0; duration: 50; }
            }
        }
    }
}
