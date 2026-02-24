import QML
import QtQuick
import QtQuick.Window

Item {
    id: view
    property int doorStatus: 0

    Connections {
        target: Global.serial
        function onDoorStatusReceived(doorStatus: int) {
            view.doorStatus = doorStatus
        }
    }

    Resource {
        id: priv
        property int lockNumber: 0
        property string lockPassword: ""
        name: lockNumber > 0 ? "background-numpad" : Global.languageCode + "-background-maintenance"
        anchors.fill: parent
        //Component.onCompleted: Global.serial.getDoorStatus()
        Resource {
            visible: priv.lockNumber == 0
            name: view.doorStatus & 0b010 ? "button-unlocked" : "button-locked"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -150*Global.viewHeightScale
            anchors.horizontalCenterOffset: Global.ifArabic(370, -370)*Global.viewWidthScale
        }
        MouseArea {
            onPressed: priv.lockNumber = 1
            anchors.centerIn: parent
            width: parent.width
            height: 100*Global.viewHeightScale
            anchors.verticalCenterOffset: -150*Global.viewHeightScale
        }
        Resource {
            visible: priv.lockNumber == 0
            name: view.doorStatus & 0b001 ? "button-unlocked" : "button-locked"
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: Global.ifArabic(370, -370)*Global.viewWidthScale
        }
        MouseArea {
            onPressed: priv.lockNumber = 2
            anchors.centerIn: parent
            width: parent.width
            height: 100*Global.viewHeightScale
        }
        Resource {
            visible: priv.lockNumber == 0
            name: view.doorStatus & 0b100 ? "button-unlocked" : "button-locked"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 150*Global.viewHeightScale
            anchors.horizontalCenterOffset: Global.ifArabic(370, -370)*Global.viewWidthScale
        }
        MouseArea {
            onPressed: priv.lockNumber = 3
            anchors.centerIn: parent
            width: parent.width
            height: 100*Global.viewHeightScale
            anchors.verticalCenterOffset: 150*Global.viewHeightScale
        }
        Numpad {
            visible: priv.lockNumber > 0
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: -210*Global.viewWidthScale
            anchors.verticalCenterOffset: -10*Global.viewHeightScale
            onDigitPressed: digit => { if (priv.lockPassword.length < 4) priv.lockPassword += digit }
            onCancelPressed: priv.lockPassword = ""
            onDeletePressed: priv.lockPassword = priv.lockPassword.substring(0, priv.lockPassword.length - 1)
            onEnterPressed: {
                if (priv.lockPassword == "3101") {
                    Global.server.updateGUI()
                } else if (priv.lockNumber == 1 && priv.lockPassword == "1993") {
                    Global.serial.sendOpenDoor()
                    view.doorStatus |= 2
                } else if (priv.lockNumber == 2 && priv.lockPassword == "1117") {
                    Global.serial.doorToggle(2)
                    view.doorStatus |= 1
                } else if (priv.lockNumber == 3 && priv.lockPassword == "6666") {
                    Global.serial.doorToggle(3)
                    view.doorStatus |= 4
                }
                priv.lockPassword = ""
                priv.lockNumber = 0
            }        
        }
        MultilingualResource {
            visible: priv.lockNumber > 0
            name: "input-door-" + Math.max(priv.lockNumber, 1)
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -200*Global.viewHeightScale
            Text {
                text: Global.convertToLanguageNumerals(priv.lockPassword)
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 10*Global.viewHeightScale
                color: "#59b280"
                font.family: Global.fontBold.font.family
                font.weight: Global.fontBold.font.weight
                font.styleName: Global.fontBold.font.styleName
                font.pointSize: 48*Global.viewWidthScale
                font.letterSpacing: 30
            }
        }
    }
}

