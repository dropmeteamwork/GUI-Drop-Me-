import QML
import QtQuick
import QtQuick.Window

Item {
    id: view
    signal selectLanguage(int language)
    property bool transitionedFromStart: true

    Resource {
        name: view.transitionedFromStart ? "background-select-language-with-logo" : "background-select-language"
        anchors.fill: parent

        ResourceButton {
            resource: "button-select-english"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 80*Global.viewHeightScale
            anchors.horizontalCenterOffset: -200*Global.viewWidthScale
            onPressed: view.selectLanguage(Global.Language.English)
        }

        ResourceButton {
            resource: "button-select-arabic"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 80*Global.viewHeightScale
            anchors.horizontalCenterOffset: 200*Global.viewWidthScale
            onPressed: view.selectLanguage(Global.Language.Arabic)
        }
    }
}
