import QML
import QtQuick

Item {
    id: popup
    signal finished
    required property int points
    required property bool isPending
    MultilingualResource {
        name: "popup-finished-phone-number-recycle" + (popup.isPending ? "-offline" : "")
        Text {
            x: Global.ifArabic(390, 580)*Global.viewWidthScale
            y: Global.ifArabic(300, 275)*Global.viewHeightScale
            text: Global.convertToLanguageNumerals(popup.points.toString())
            color: "#96B43C"
            font.family: Global.fontBold.font.family
            font.weight: Global.fontBold.font.weight
            font.styleName: Global.fontBold.font.styleName
            font.pointSize: 48*Global.viewWidthScale
        }
        Timer {
            running: true
            interval: 5_000
            Component.onCompleted: triggered.connect(popup.finished)
        }
    }
}
