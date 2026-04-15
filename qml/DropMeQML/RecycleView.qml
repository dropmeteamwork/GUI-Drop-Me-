import QML
import QtQuick
import QtQuick.Controls
import QtMultimedia

import DropMe

Item {
    required property int userType
    required property var captureSource

    property string phoneNumber: ""
    property bool processingItem: false
    property bool waitingPhoneFinishResponse: false

    signal finishedWithNoPoints
    signal finishedWithQrCode
    signal finishedWithPhoneNumber
    signal finishedWithPhoneNumberOffline
    signal newUserFailed
    signal otherInserted
    signal handsInserted
    signal showCapture(string path)
    signal showCamera
    signal captureRequested
    signal sessionClockFinished

    id: view

    function startClock() { clock.start() }
    function restartClock() { clock.reset(); clock.start() }
    function forceFinishClock() { clock.forceFinish() }

    readonly property bool plasticBinFull: AppState.recyclePlasticBinFull
    readonly property bool canBinFull: AppState.recycleCanBinFull
    readonly property string activeFullBin: AppState.recycleActiveFullBin

    RecycleFlowController {
        id: flowController
        view: view
        captureSource: view.captureSource
    }

    Item {
        id: recycleFrame
        anchors.fill: parent
        clip: true

        Image {
            id: recycleBackground
            anchors.fill: parent
            source: Global.getMultilingualImage(recycleFrame.frameImageName)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
        }

        component ViewText : Text {
            required property string viewText
            text: viewText
            color: "#243B6A"
            font.family: Global.fontBold.font.family
            font.weight: Global.fontBold.font.weight
            font.styleName: Global.fontBold.font.styleName
            font.pointSize: 48*Global.viewWidthScale
        }

        readonly property bool bothBinsFull: view.plasticBinFull && view.canBinFull
        readonly property bool onlyPlasticFull: view.plasticBinFull && !view.canBinFull
        readonly property bool onlyCanFull: view.canBinFull && !view.plasticBinFull
        readonly property string frameImageName: recycleFrame.bothBinsFull
                                               ? "overlay-bin-full-both"
                                               : (recycleFrame.onlyPlasticFull
                                                  ? "overlay-bin-full-plastic"
                                                  : (recycleFrame.onlyCanFull
                                                     ? "overlay-bin-full-can"
                                                     : "background-recycle"))

        property bool devPanelOpen: false

        Rectangle {
            visible: SystemInfo.dev
            z: 20
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 16*Global.viewWidthScale
            anchors.bottomMargin: 16*Global.viewHeightScale
            width: 180*Global.viewWidthScale
            height: 56*Global.viewHeightScale
            radius: 10
            color: "#203354"
            border.color: "#5A78A3"

            Text {
                anchors.centerIn: parent
                text: recycleFrame.devPanelOpen ? "Hide Dev Tools" : "Show Dev Tools"
                color: "white"
                font.pixelSize: 18*Global.viewWidthScale
            }

            MouseArea {
                anchors.fill: parent
                onClicked: recycleFrame.devPanelOpen = !recycleFrame.devPanelOpen
            }
        }

        Rectangle {
            visible: SystemInfo.dev && recycleFrame.devPanelOpen
            z: 21
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 16*Global.viewWidthScale
            anchors.bottomMargin: (80 + 16)*Global.viewHeightScale
            width: 260*Global.viewWidthScale
            height: 420*Global.viewHeightScale
            radius: 10
            color: "#111A2BCC"
            border.color: "#5A78A3"
            clip: true

            Flickable {
                anchors.fill: parent
                anchors.margins: 8
                contentWidth: width
                contentHeight: toolsColumn.implicitHeight
                clip: true

                Column {
                    id: toolsColumn
                    width: parent.width
                    spacing: 6

                    Button { text: "start"; width: parent.width; palette.buttonText: "black"; onPressed: flowController.startSessionUi() }
                    Button { text: "end"; width: parent.width; palette.buttonText: "black"; onPressed: flowController.finishSessionUi() }

                    Button {
                        text: "ml: hand"
                        width: parent.width
                        palette.buttonText: "black"
                        onPressed: flowController.simulateDevPrediction("hand")
                    }
                    Button {
                        text: "ml: aluminum"
                        width: parent.width
                        palette.buttonText: "black"
                        onPressed: flowController.simulateDevPrediction("aluminum")
                    }
                    Button {
                        text: "ml: plastic"
                        width: parent.width
                        palette.buttonText: "black"
                        onPressed: flowController.simulateDevPrediction("plastic")
                    }
                    Button {
                        text: "ml: other"
                        width: parent.width
                        palette.buttonText: "black"
                        onPressed: flowController.simulateDevPrediction("other")
                    }

                    Button {
                        text: SystemInfo.devLocalSensorOverride ? "sensor: hand block" : "sensor: hand block (sim only)"
                        width: parent.width
                        enabled: SystemInfo.devLocalSensorOverride
                        palette.buttonText: "black"
                        onPressed: Global.serial.devSetGateAlarmBlocked(true)
                    }
                    Button {
                        text: SystemInfo.devLocalSensorOverride ? "sensor: hand clear" : "sensor: hand clear (sim only)"
                        width: parent.width
                        enabled: SystemInfo.devLocalSensorOverride
                        palette.buttonText: "black"
                        onPressed: Global.serial.devSetGateAlarmBlocked(false)
                    }
                    Button {
                        text: SystemInfo.devLocalSensorOverride ? "sensor: exit passed" : "sensor: exit passed (sim only)"
                        width: parent.width
                        enabled: SystemInfo.devLocalSensorOverride
                        palette.buttonText: "black"
                        onPressed: Global.serial.devSetExitGatePassed(true)
                    }
                    Button {
                        text: SystemInfo.devLocalSensorOverride ? "sensor: exit clear" : "sensor: exit clear (sim only)"
                        width: parent.width
                        enabled: SystemInfo.devLocalSensorOverride
                        palette.buttonText: "black"
                        onPressed: Global.serial.devSetExitGatePassed(false)
                    }

                }
            }
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recyclePlasticBottles.toString())
            x: Global.ifArabic(370, 363)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recycleCans.toString())
            x: Global.ifArabic(600, 592)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recyclePoints.toString())
            x: Global.ifArabic(775, 750)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        MultilingualResourceButton {
            resource: "button-end"
            x: 380*Global.viewWidthScale
            y: 535*Global.viewHeightScale
            onPressed: flowController.finishSessionUi()
        }

        Clock {
            id: clock
            interval: 3000
            onTriggered: view.captureRequested()
            onFinished: view.sessionClockFinished()
        }
    }
}
