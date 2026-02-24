import QML
import QtQuick

Item {
    id: popup
    signal finished
    property int interval: 5_000
    MultilingualResource {
        name: "popup-hands"
        Timer {
            running: true
            interval: popup.interval
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
