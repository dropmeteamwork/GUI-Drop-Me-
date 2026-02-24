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

    Connections {
        target: Global.serial

        function onHandInGate() {
            if (Global.handInGate) return
            Global.handInGate = true
            view.push(popupHandsAndCloseView)
        }

        function onBinFull(binName) {
        //view.push(popupBinFullView, {"binName": binName})
        view.push(popupOutOfServiceView)
        }
    
        function onErrorOccurred(errorName, errorId) {
        console.log("MCU Error:", errorName, errorId)
        view.push(popupOutOfServiceView)
        }

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
        }
        Image {
            source: SystemInfo.getImagePath("no-signal")
            visible: !videos.playing
            width: parent.width
            height: 0.3*parent.height
        }
        Item {
            id: viewContainer
            width: Global.viewWidth
            height: Global.viewHeight

            StackView {
                id: view
                anchors.fill: parent
                initialItem: startView
                background: Resource { name: "background" }
                onEmptyChanged: background.name = "background"
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
            VideoOutput {
                id: cameraVideoOutput
            }
            Image {
                id: captureImage
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false            // optional: avoid caching large images
            }
        }
    }

    CaptureSession {
        id: captureSession
        camera: Camera {
            active: true
        }
        imageCapture: ImageCapture {
        }
        videoOutput: cameraVideoOutput
    }

    Videos {
        id: videos
        folder: SystemInfo.videoAdsFolder
        videoOutput: videoOutput
    }

    Component {
        id: startView
        StartView {
            onStart: view.push(selectLanguageView)
            onPattern: language => {
                Global.language = language
                view.push(maintenanceView)
            }
        }
    }

    Component {
        id: selectLanguageView
        SelectLanguageView {
            onSelectLanguage: language => {
                Global.language = language
                view.push(enterCredentialsView)
                view.background.name = "background-with-logo"
                transitionedFromStart = false
            }
        }
    }

    Component {
        id: enterCredentialsView
        EnterCredentialsView {
            Resource {
                name: "button-back"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 20*Global.viewWidthScale
                anchors.topMargin: 20*Global.viewHeightScale
                MouseArea {
                    anchors.fill: parent
                    onPressed: view.pop()
                }
            }
            onEnterWithQrCode: view.push(recycleView, {"userType": Global.UserType.QrCode, "imageCapture": captureSession.imageCapture})
            onEnterWithPhoneNumber: phoneNumber => view.push(recycleView, {"userType": Global.UserType.PhoneNumber, "phoneNumber": phoneNumber, "imageCapture": captureSession.imageCapture})
            onInvalidPhoneNumber: view.push(invalidPhoneNumberView)
        }
    }

    Component {
        id: maintenanceView
        MaintenanceView {
            Resource {
                name: "button-back"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 20*Global.viewWidthScale
                anchors.topMargin: 20*Global.viewHeightScale
                MouseArea {
                    anchors.fill: parent
                    onPressed: view.pop()
                }
            }
        }
    }

    Component {
        id: recycleView
        RecycleView {
            onNewUserFailed: {
                if (!SystemInfo.dev)
                    view.push(popupOutOfServiceView)
            }
            onHandsInserted: view.push(popupHandsView)
            onOtherInserted: view.push(popupNonRecyclableView)
            onFinishedWithNoPoints: view.push(popupTimeoutView)
            onFinishedWithQrCode: view.push(popupFinishedQrCodeRecycleView, {"points": points})
            onFinishedWithPhoneNumber: view.push(popupFinishedPhoneNumberRecycleView, {"points": points, "isPending": false})
            onFinishedWithPhoneNumberOffline: view.push(popupFinishedPhoneNumberRecycleView, {"points": points, "isPending": true})
            onShowCamera: bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
            onShowCapture: imagePath => {
                captureImage.source = imagePath
                bottomView.currentIndex = MainWindow.BottomViewItem.CaptureImage
            }
            Component.onCompleted: {
                captureSession.camera.start()
                bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
            }
            Component.onDestruction: {
                captureSession.camera.stop()
                bottomView.currentIndex = MainWindow.BottomViewItem.Slides
            }
        }
    }

    Component {
        id: popupHandsView
        PopupHandsView {
            interval: 2_000
            onFinished: view.pop()
        }
    }


    Component {
        id: popupHandsAndCloseView
        PopupHandsView {
            interval: 5_000
            onFinished: {
                Global.handInGate = false
                Global.serial.closeDoor()
                view.pop()
                if (Global.shouldSignOut) {
                    view.clear()
                    view.push(startView)
                    Global.shouldSignOut = false
                }
            }
        }
    }

    Component {
        id: popupNonRecyclableView
        PopupNonRecyclableView {
            interval: 2_000
            onFinished: view.pop()
        }
    }

    Component {
        id: popupFinishedQrCodeRecycleView
        PopupFinishedQrCodeRecycleView {
            onFinished: {
                if (Global.handInGate) {
                    Global.shouldSignOut = true
                    return
                }
                view.clear()
                view.push(startView)
            }
        }
    }

    Component {
        id: popupFinishedPhoneNumberRecycleView
        PopupFinishedPhoneNumberRecycleView {
            onFinished: {
                if (Global.handInGate) {
                    Global.shouldSignOut = true
                    return
                }
                view.clear()
                view.push(startView)
            }
        }
    }

    Component {
        id: popupTimeoutView
        PopupTimeoutView {
            onFinished: {
                if (Global.handInGate) {
                    Global.shouldSignOut = true
                    return
                }
                view.clear()
                view.push(startView)
            }
        }
    }

    Component {
        id: popupOutOfServiceView
        PopupOutOfServiceView {
            onFinished: {
                if (Global.handInGate) {
                    Global.shouldSignOut = true
                    return
                }
                view.clear()
                view.push(startView)
            }
        }
    }

    Component {
        id: invalidPhoneNumberView
        PopupInvalidPhoneNumberView {
            onFinished: view.pop()
        }
    }
}