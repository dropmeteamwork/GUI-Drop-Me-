pragma ComponentBehavior: Bound

import QML
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Universal
import QtQuick.Window
import QtQuick.Layouts
import QtMultimedia

import DropMe

Window {
    id: window
    visible: true
    title: "Drop Me GUI"
    color: "black"
    visibility: SystemInfo.dev ? Window.Windowed : Window.FullScreen
    flags: SystemInfo.dev ? Qt.Window : Qt.Window
        | Qt.WindowFullScreen
        | Qt.WindowStaysOnTopHint
        | Qt.MaximizeUsingFullscreenGeometryHint
        | Qt.FramelessWindowHint

    Component.onCompleted: {
        Global.window = window
    }


    Watchdog {
        id: runtimeWatchdog
        serial: Global.serial
        appState: AppState
        enabled: true
        onWatchdogAlert: reason => console.log("[Watchdog] alert:", reason)
        onWatchdogRecovered: reason => console.log("[Watchdog] recovered:", reason)
    }

    Timer {
        id: uiHeartbeatTimer
        interval: 1000
        repeat: true
        running: true
        onTriggered: runtimeWatchdog.beatUi()
    }

    // Forward hardware events -> EventBus (decoupling MainWindow from flow decisions)
    Connections {
        target: Global.serial
        function onConnectionEstablished(portName) { runtimeWatchdog.beatBackend() }
        function onConnectionLost() { runtimeWatchdog.beatBackend(); EventBus.hwGateCleared() }
        function onCommandSent(cmdName, payload) { runtimeWatchdog.beatBackend() }
        function onHandInGate() { runtimeWatchdog.beatBackend(); EventBus.hwHandInGate() }
        function onGateOpened() { runtimeWatchdog.beatBackend(); EventBus.hwGateCleared() }
        function onGateClosed() { runtimeWatchdog.beatBackend(); EventBus.hwGateCleared() }
        function onBinFull(binName) { runtimeWatchdog.beatBackend(); EventBus.hwBinFull(binName) }
        function onBasketStateChanged(binName, isFull) { runtimeWatchdog.beatBackend(); EventBus.hwBasketState(binName, isFull) }
        function onErrorOccurred(errorName, errorId) { runtimeWatchdog.beatBackend(); EventBus.hwError(errorName, errorId) }
    }

    enum BottomViewItem {
        Slides,
        CameraVideoOutput,
        CaptureImage
    }

    Column {
        width: Global.screenWidth
        height: Global.screenHeight
        anchors.centerIn: parent

        VideoOutput {
            id: videoOutput
            width: parent.width
            height: 0.3*parent.height
            visible: videos.playing
            fillMode: VideoOutput.PreserveAspectCrop
        }

        Image {
            source: SystemInfo.getImagePath("no-signal")
            asynchronous: true
            cache: true
            visible: !videos.playing
            width: parent.width
            height: 0.3*parent.height
            fillMode: Image.PreserveAspectCrop
        }

        Item {
            id: viewContainer
            width: Global.viewWidth
            height: Global.viewHeight
            clip: true

            StateManager {
                id: stateManager
                anchors.fill: parent
                captureImage: captureImage
                bottomView: bottomView
                captureSession: captureSession
                cameraCapture: cameraVideoOutput
            }
        }

        StackLayout {
            id: bottomView
            currentIndex: MainWindow.BottomViewItem.Slides
            width: parent.width
            height: 0.3*parent.height

            Slides {
                id: slides
                folder: SystemInfo.slidesFolder

                Rectangle {
                    width: parent.width
                    height: 60*Global.viewHeightScale
                    anchors.bottom: parent.bottom
                    color: "black"

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 30*Global.viewWidthScale
                        text: "RVM ID: " + SystemInfo.machineID + (SystemInfo.dev ? "-DEV" : "")
                        color: "#59b280"
                        font.family: Global.fontBold.font.family
                        font.weight: Global.fontBold.font.weight
                        font.styleName: Global.fontBold.font.styleName
                        font.pointSize: 30*Global.viewWidthScale
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 30*Global.viewWidthScale
                        text: "Contact Us: 01121591362"
                        color: "#59b280"
                        font.family: Global.fontBold.font.family
                        font.weight: Global.fontBold.font.weight
                        font.styleName: Global.fontBold.font.styleName
                        font.pointSize: 30*Global.viewWidthScale
                    }
                }
            }

            CameraMaskedCapture {
                id: cameraVideoOutput
            }

            Image {
                id: captureImage
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
            }
        }
    }

    CaptureSession {
        id: captureSession
        camera: Camera { active: true }
        imageCapture: ImageCapture { }
        videoOutput: cameraVideoOutput.videoOutput
    }

    Videos {
        id: videos
        folder: SystemInfo.videoAdsFolder
        videoOutput: videoOutput
    }
}
