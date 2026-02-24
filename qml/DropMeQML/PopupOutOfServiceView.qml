import QML
import QtQuick

Item {
    id: popup
    signal finished
    Resource {
        name: "background-out-of-service"
        Timer {
            running: true
            interval: 5_000
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
