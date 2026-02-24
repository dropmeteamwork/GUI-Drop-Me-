import QML
import QtQuick

Item {
    id: popup
    signal finished
    MultilingualResource {
        name: "popup-timeout"
        Timer {
            running: true
            interval: 5_000
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
