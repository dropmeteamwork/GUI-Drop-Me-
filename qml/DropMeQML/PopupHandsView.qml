import QML
import QtQuick

Item {
    id: popup
    signal finished
    property int interval: 5000
    property bool autoClose: true

    MultilingualResource {
        name: "popup-hands"
        Timer {
            running: popup.autoClose
            repeat: false
            interval: popup.interval
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
