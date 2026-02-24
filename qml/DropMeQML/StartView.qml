import QML
import QtQuick

Item {
    id: view
    signal start()
    signal pattern(int language)

    Resource {
        name: "background-start"
        anchors.fill: parent
        Resource {
            id: buttonStart
            name: "button-start"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -20*Global.viewHeightScale
        }
        MouseArea {
            property int patternState: 0
            id: mouseArea
            anchors.fill: parent
            onClicked: mouse => {
                if (mouse.x > buttonStart.x && mouse.y > buttonStart.y
                    && mouse.x < buttonStart.x+buttonStart.width
                    && mouse.y < buttonStart.y+buttonStart.height) {
                    view.start()
                }
                var upperLeft = mouse.x < 100*Global.viewWidthScale && mouse.y < 100*Global.viewHeightScale
                var upperRight = mouse.x > (mouseArea.width-100)*Global.viewWidthScale && mouse.y < 100*Global.viewHeightScale
                var lowerLeft = mouse.x < 100*Global.viewWidthScale && mouse.y > (mouseArea.height-100)*Global.viewHeightScale
                var lowerRight = mouse.x > (mouseArea.width-100)*Global.viewWidthScale && mouse.y > (mouseArea.height-100)*Global.viewHeightScale
                if (patternState == 0 && (upperLeft || upperRight)) patternState = 1
                else if (patternState == 1 && (upperLeft || upperRight)) patternState = 2
                else if (patternState == 2 && (upperLeft || upperRight)) patternState = 3
                else if (patternState == 3 && (upperLeft || upperRight)) patternState = 4
                else if (patternState == 4 && (upperLeft || upperRight)) patternState = 5
                else if (patternState == 5 && (upperLeft || upperRight)) patternState = 6
                else if (patternState == 6 && (upperLeft || upperRight)) patternState = 7
                else if (patternState == 7 && (upperLeft || upperRight)) patternState = 8
                else if (patternState == 8 && (upperLeft || upperRight)) patternState = 9
                else if (patternState == 9 && upperLeft) {
                    view.pattern(Global.Language.English)
                    patternState = 0
                }
                else if (patternState == 9 && upperRight) {
                    view.pattern(Global.Language.Arabic)
                    patternState = 0
                }
                else patternState = 0
            }
        }
    }
}
