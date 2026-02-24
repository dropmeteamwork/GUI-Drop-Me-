import QML
import QtQuick

MultilingualResource {
    id: button
    signal pressed
    required property string resource
    name: resource
    MouseArea {
        id: buttonStartMouse
        anchors.fill: parent
        onPressed: button.pressed()
    }
}
