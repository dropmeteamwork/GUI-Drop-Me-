import QtQuick
import QtMultimedia

import DropMe

Item {
    id: controller
    visible: false
    width: 0
    height: 0

    required property Item view
    required property ImageCapture imageCapture

    RecycleCoordinator {
        id: recycleCoordinator
        serial: Global.serial
        server: Global.server
        appState: AppState
    }

    RecycleFlowCoordinator {
        id: flowCoordinator
        serial: Global.serial
        server: Global.server
        appState: AppState

        onStartSessionUiRequested: {
            controller.view.startClock()
            controller.view.showCamera()
        }

        onFinishSessionUiRequested: controller.view.forceFinishClock()
        onShowCameraRequested: controller.view.showCamera()

        onShowCaptureRequested: imagePath => {
            controller.view.showCapture(imagePath)
        }

        onProcessingItemChanged: value => controller.view.processingItem = value
        onWaitingPhoneFinishResponseChanged: value => controller.view.waitingPhoneFinishResponse = value

        onPhoneFinishResultRequested: isPending => {
            isPending ? controller.view.finishedWithPhoneNumberOffline() : controller.view.finishedWithPhoneNumber()
        }

        onNewUserFailedRequested: controller.view.newUserFailed()
        onRestartClockRequested: controller.view.restartClock()
        onHandsInsertedRequested: controller.view.handsInserted()
        onOtherInsertedRequested: controller.view.otherInserted()
        onFinishedNoPointsRequested: controller.view.finishedWithNoPoints()
        onFinishedQrCodeRequested: controller.view.finishedWithQrCode()
    }

    function startSessionUi() {
        flowCoordinator.startSessionUi()
    }

    function finishSessionUi() {
        flowCoordinator.finishSessionUi()
    }

    function simulateDevPrediction(itemName) {
        var capturePath = SystemInfo.getNextCapturePath()
        controller.imageCapture.captureToFile(capturePath)
        AppState.onPredictionResult(itemName, controller.view.userType, controller.view.phoneNumber, "")
        Global.server.sendDevPrediction(itemName, capturePath)
    }

    Connections {
        target: controller.imageCapture

        function onImageSaved(requestId, capturePath) {
            Global.server.getCapturePrediction(capturePath, controller.view.phoneNumber)
        }
    }

    Connections {
        target: Global.serial

        function onReady() {
            console.log("[RecycleFlowController] serial ready")
            flowCoordinator.onSerialReady()
        }

        function onNewUserFailed() {
            flowCoordinator.onNewUserFailed()
        }
    }

    Connections {
        target: Global.server

        function onFinishedPhoneNumberRecycle(isPending) {
            flowCoordinator.onFinishedPhoneNumberRecycle(isPending)
        }

        function onPredictionReady(results, capturePath, systemPathToDelete) {
            flowCoordinator.onPredictionReady(results, controller.view.userType, controller.view.phoneNumber, systemPathToDelete)
        }
    }

    Connections {
        target: recycleCoordinator

        function onItemProcessingStarted() {
            flowCoordinator.onItemProcessingStarted()
        }

        function onPhoneFinishRequested(phoneNumber, plastic, cans) {
            flowCoordinator.onPhoneFinishRequested(phoneNumber, plastic, cans)
        }
    }

    Connections {
        target: AppState

        function onRecycleUiClockRestart() {
            flowCoordinator.onRecycleUiClockRestart()
        }

        function onRecycleUiShowCapture(imagePath) {
            flowCoordinator.onRecycleUiShowCapture(imagePath)
        }

        function onRecycleUiHandsInserted() { flowCoordinator.onRecycleUiHandsInserted() }
        function onRecycleUiOtherInserted() { flowCoordinator.onRecycleUiOtherInserted() }
        function onRecycleUiFinishedNoPoints() { flowCoordinator.onRecycleUiFinishedNoPoints() }
        function onRecycleUiFinishedQrCode() { flowCoordinator.onRecycleUiFinishedQrCode() }
    }

    Connections {
        target: controller.view

        function onCaptureRequested() {
            var capturePath = SystemInfo.getNextCapturePath()
            controller.imageCapture.captureToFile(capturePath)
        }

        function onSessionClockFinished() {
            AppState.onRecycleClockFinished(controller.view.userType, controller.view.phoneNumber)
        }
    }

    Component.onCompleted: {
        console.log("[RecycleFlowController] component completed -> startFlow")
        flowCoordinator.startFlow()
    }

    Component.onDestruction: {
        console.log("[RecycleFlowController] component destruction -> stopFlow")
        flowCoordinator.stopFlow()
    }
}


