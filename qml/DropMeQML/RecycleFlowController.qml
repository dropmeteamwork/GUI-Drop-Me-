import QtQuick
import QtMultimedia

import DropMe

Item {
    id: controller
    visible: false
    width: 0
    height: 0
    property string pendingCleanupPath: ""
    property bool captureDeferredByGateAlarm: false

    function shouldCaptureNow() {
        return Global.serial.isDetectionAllowed()
            && !controller.view.processingItem
            && !controller.view.waitingPhoneFinishResponse
            && !AppState.recycleHasFinished
    }

    function _resumeDeferredCapture() {
        if (!controller.captureDeferredByGateAlarm)
            return
        controller.captureDeferredByGateAlarm = false
        EventBus.hwGateCleared()
        if (!controller.shouldCaptureNow()) {
            console.log("[RecycleFlowController] deferred capture cancelled: session no longer ready")
            return
        }
        var capturePath = SystemInfo.getNextCapturePath()
        controller.captureSource.captureToFile(capturePath)
    }

    required property Item view
    required property var captureSource

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
        // Route through the SAME predictionReady signal as production ML.
        // This exercises: isDetectionAllowed() check, recordMlPrediction(),
        // AppState.onPredictionResult(), and coordinator logic.
        console.log("[DEV_SIM] simulateDevPrediction:", itemName)
        Global.server.simulateDevPredictionResult(itemName)
    }

    Timer {
        id: cleanupDelayTimer
        interval: 2000
        repeat: false
        onTriggered: {
            if (controller.pendingCleanupPath !== "") {
                Global.server.cleanupFile(controller.pendingCleanupPath)
                controller.pendingCleanupPath = ""
            }
        }
    }

    Timer {
        id: gateAlarmRetryTimer
        interval: 150
        repeat: true
        onTriggered: {
            if (Global.serial.isGateBlocked())
                return
            gateAlarmRetryTimer.stop()
            controller._resumeDeferredCapture()
        }
    }

    Connections {
        target: controller.captureSource

        function onCaptureSaved(capturePath, success) {
            if (!success) {
                console.log("[RecycleFlowController] masked capture failed:", capturePath)
                return
            }
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

        function onConnectionLost() {
            gateAlarmRetryTimer.stop()
            controller.captureDeferredByGateAlarm = false
            EventBus.hwGateCleared()
            flowCoordinator.onHandBlockStateChanged(false)
            flowCoordinator.onHardwareCycleCompleted()
        }

        function onConveyorDone() {
            flowCoordinator.onHardwareCycleCompleted()
        }

        function onItemRejected() {
            flowCoordinator.onHardwareCycleCompleted()
        }

        function onRejectDone() {
            flowCoordinator.onHardwareCycleCompleted()
        }

        function onRejectHomeOk() {
            flowCoordinator.onHardwareCycleCompleted()
        }
    }

    Connections {
        target: Global.server

        function onFinishedPhoneNumberRecycle(isPending) {
            flowCoordinator.onFinishedPhoneNumberRecycle(isPending)
        }

        function onPredictionReady(results, capturePath, systemPathToDelete) {
            const pred = (results && results.length > 0) ? String(results[0] || "") : ""
            console.log("[RecycleFlowController] predictionReady ->", pred, "image?", (results && results.length > 1) ? String(results[1] || "") !== "" : false)
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

        function onHandInGateChanged() {
            flowCoordinator.onHandBlockStateChanged(AppState.handInGate)
        }

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
            if (!controller.shouldCaptureNow()) {
                console.log("[RecycleFlowController] capture skipped: busy/finished/hand-blocked")
                return
            }
            if (Global.serial.isGateBlocked()) {
                console.log("[RecycleFlowController] capture deferred: gate alarm is active")
                controller.captureDeferredByGateAlarm = true
                EventBus.hwHandInGate()
                if (!gateAlarmRetryTimer.running)
                    gateAlarmRetryTimer.start()
                return
            }
            var capturePath = SystemInfo.getNextCapturePath()
            controller.captureSource.captureToFile(capturePath)
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
        gateAlarmRetryTimer.stop()
        controller.captureDeferredByGateAlarm = false
        console.log("[RecycleFlowController] component destruction -> stopFlow")
        flowCoordinator.stopFlow()
    }
}
