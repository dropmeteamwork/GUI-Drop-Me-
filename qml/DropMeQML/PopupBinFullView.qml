import QML
import QtQuick
import QtQuick.Controls

Item {
    id: popup
    signal finished
    property string binName: ""
    property int interval: 5_000

    Rectangle {
        anchors.fill: parent
        color: "#80000000"
        MouseArea {
            anchors.fill: parent
            onClicked: popup.finished()
        }
    }

    Rectangle {
        width: Math.min(parent.width * 0.7, 400)
        height: 120
        anchors.centerIn: parent
        color: "#243B6A"
        radius: 12
        border.color: "#fff"

        Column {
            anchors.centerIn: parent
            spacing: 12
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: popup.binName.length ? (popup.binName + " bin is full") : "Bin is full"
                color: "white"
                font.pixelSize: 24
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Please empty it to continue."
                color: "#ccc"
                font.pixelSize: 16
            }
        }
    }

    Timer {
        running: true
        interval: popup.interval
        onTriggered: popup.finished()
    }
}
