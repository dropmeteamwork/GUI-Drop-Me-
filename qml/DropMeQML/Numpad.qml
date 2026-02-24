pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: numpad
    signal digitPressed(string digit)
    signal cancelPressed()
    signal deletePressed()
    signal enterPressed()

    Row {
        spacing: 15*Global.viewHeightScale
        Grid {
            layoutDirection: Global.ifArabic(Qt.RightToLeft, Qt.LeftToRight)
            columns: 3
            rowSpacing: 15*Global.viewWidthScale
            columnSpacing: 15*Global.viewHeightScale
            component DigitButton : ResourceButton {
                id: digitButton
                property string digit
                resource: "button-digit"
                onPressed: numpad.digitPressed(digit)
                Text {
                    text: Global.convertToLanguageNumerals(digitButton.digit)
                    color: "#606162"
                    anchors.centerIn: parent
                    font.family: Global.fontMedium.font.family
                    font.weight: Global.fontMedium.font.weight
                    font.styleName: Global.fontMedium.font.styleName
                    font.pointSize: 45*Global.viewWidthScale
                }
            }
            DigitButton { digit: "1" }
            DigitButton { digit: "2" }
            DigitButton { digit: "3" }
            DigitButton { digit: "4" }
            DigitButton { digit: "5" }
            DigitButton { digit: "6" }
            DigitButton { digit: "7" }
            DigitButton { digit: "8" }
            DigitButton { digit: "9" }
            Resource { name: "button-digit" }
            DigitButton { digit: "0" }
            Resource { name: "button-digit" }
        }
        Column {
            spacing: 15*Global.viewWidthScale
            MultilingualResourceButton { resource: "button-cancel"; onPressed: numpad.cancelPressed() }
            MultilingualResourceButton { resource: "button-delete"; onPressed: numpad.deletePressed() }
            MultilingualResourceButton { resource: "button-enter"; onPressed: numpad.enterPressed() }
        }
    }
}
