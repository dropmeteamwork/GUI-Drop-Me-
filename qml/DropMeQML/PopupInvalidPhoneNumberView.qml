import QML
import QtQuick

Item {
    id: popup
    signal finished
    MultilingualResource {
        name: "popup-invalid-phone-number"
        Timer {
            running: true
            interval: 2_500
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
