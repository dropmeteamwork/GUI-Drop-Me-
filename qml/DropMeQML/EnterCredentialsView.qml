import QML
import QtQuick

import DropMe

Item {
    id: view
    property string qrcode: SystemInfo.getImagePath("qrcode-out-of-service")
    property string phoneNumber: ""
    property bool phoneNumberVisible: false
    property bool phoneNumberPartialVisible: false
    signal enterWithPhoneNumber(string phoneNumber)
    signal enterWithQrCode
    signal invalidPhoneNumber

    Component.onCompleted: {
        Global.server.getQrCode()
    }

    Connections {
        target: Global.server
        
        function onQrCodeChanged(qrcode) {
            view.qrcode = qrcode
        }

        function onQrCodeScanned() {
            view.enterWithQrCode()
        }
    }

    Timer {
        interval: 3000
        running: parent.visible
        repeat: true
        onTriggered: Global.server.checkQrCodeScanned()
    }

    MultilingualResource {
        name: "background-enter-credentials"
        anchors.fill: parent

        Image {
            source: view.qrcode
            x: Global.ifArabic(105, 701)*Global.viewWidthScale
            y: 316*Global.viewHeightScale
            width: 257*Global.viewWidthScale
            height: 251*Global.viewHeightScale
        }

        Text {
            x: Global.ifArabic(520, 110)*Global.viewWidthScale
            y: 200*Global.viewHeightScale
            text: view.phoneNumberVisible
                  ? Global.convertToLanguageNumerals(view.phoneNumber)
                  : view.phoneNumberPartialVisible
                    ? "X".repeat(view.phoneNumber.length - 1) + Global.convertToLanguageNumerals(view.phoneNumber[view.phoneNumber.length - 1])
                    : "X".repeat(view.phoneNumber.length)
            color: "#243B6A"
            font.family: Global.fontBold.font.family
            font.weight: Global.fontBold.font.weight
            font.styleName: Global.fontBold.font.styleName
            font.pointSize: 48*Global.viewWidthScale
        }

        ResourceButton {
            x: Global.ifArabic(420, 580)*Global.viewWidthScale
            y: 217*Global.viewHeightScale
            resource: view.phoneNumberVisible ? "icon-visibility" : "icon-visibility-off"
            onPressed: view.phoneNumberVisible = !view.phoneNumberVisible
        }

        Timer {
            id: timerPhoneNumberPartialVisible
            interval: 1000
            onTriggered: view.phoneNumberPartialVisible = false            
        }

        Numpad {
            id: numpad
            x: Global.ifArabic(529, 119)*Global.viewWidthScale
            y: 324*Global.viewHeightScale
            onDigitPressed: digit => {
                if (view.phoneNumber.length >= 11) return
                timerPhoneNumberPartialVisible.stop()
                view.phoneNumber += digit
                view.phoneNumberPartialVisible = true
                timerPhoneNumberPartialVisible.start()
                
            }
            onCancelPressed: view.phoneNumber = ""
            onDeletePressed: view.phoneNumber = view.phoneNumber.substring(0, view.phoneNumber.length - 1)
            onEnterPressed: {
                if (view.phoneNumber.length == 11) {
                    view.enterWithPhoneNumber(view.phoneNumber)
                } else {
                    view.invalidPhoneNumber()
                    view.phoneNumber = ""
                }
            }
        }
    }
} 
