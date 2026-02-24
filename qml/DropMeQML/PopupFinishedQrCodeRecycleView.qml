import QML
import QtQuick

Item {
    id: popup
    signal finished
    required property int points
    MultilingualResource {
        name: "popup-finished-qrcode-recycle"
        Text {
            x: Global.ifArabic(390, 580)*Global.viewWidthScale
            y: Global.ifArabic(290, 300)*Global.viewHeightScale
            text: Global.convertToLanguageNumerals(popup.points.toString())
            color: "#96B43C"
            font.family: Global.fontBold.font.family
            font.weight: Global.fontBold.font.weight
            font.styleName: Global.fontBold.font.styleName
            font.pointSize: 42*Global.viewWidthScale
        }
        Timer {
            running: true
            interval: 5_000
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
