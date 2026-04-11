from __future__ import annotations

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtQml import QmlElement

from gui.logging import getLogger

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
class RecycleFlowCoordinator(QObject):
    """Owns recycle flow timers/state so QML views stay thin."""

    serialChanged = Signal()
    serverChanged = Signal()
    appStateChanged = Signal()

    processingItemChanged = Signal(bool)
    waitingPhoneFinishResponseChanged = Signal(bool)

    startSessionUiRequested = Signal()
    finishSessionUiRequested = Signal()

    showCameraRequested = Signal()
    showCaptureRequested = Signal(str)

    handsInsertedRequested = Signal()
    otherInsertedRequested = Signal()
    finishedNoPointsRequested = Signal()
    finishedQrCodeRequested = Signal()
    phoneFinishResultRequested = Signal(bool)  # isPending
    newUserFailedRequested = Signal()

    restartClockRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.logger = getLogger("dropme.recycle_flow_coordinator")

        self._serial: QObject | None = None
        self._server: QObject | None = None
        self._app_state: QObject | None = None

        self._processing_item = False
        self._waiting_phone_finish_response = False
        self._session_ui_started = False

        self._def_pred = ""
        self._def_pred_image = ""
        self._def_user_type = 0
        self._def_phone = ""
        self._cleanup_path = ""
        self._prediction_applied = False
        self._prediction_waiting_for_clear = False
        self._holding_capture_until_completion = False
        self._prediction_guard_elapsed = False

        self._camera_restore_timer = QTimer(self)
        self._camera_restore_timer.setSingleShot(True)
        self._camera_restore_timer.setInterval(2500)
        self._camera_restore_timer.timeout.connect(self.showCameraRequested.emit)

        self._phone_finish_fallback_timer = QTimer(self)
        self._phone_finish_fallback_timer.setSingleShot(True)
        self._phone_finish_fallback_timer.setInterval(2500)
        self._phone_finish_fallback_timer.timeout.connect(self._on_phone_finish_fallback)

        self._deferral_timer = QTimer(self)
        self._deferral_timer.setSingleShot(True)
        self._deferral_timer.setInterval(150)
        self._deferral_timer.timeout.connect(self._apply_deferred_prediction)

        self._prediction_guard_timer = QTimer(self)
        self._prediction_guard_timer.setSingleShot(True)
        self._prediction_guard_timer.setInterval(2000)
        self._prediction_guard_timer.timeout.connect(self._on_prediction_guard_elapsed)

        self._hand_wait_timer = QTimer(self)
        self._hand_wait_timer.setSingleShot(True)
        self._hand_wait_timer.setInterval(2000)
        self._hand_wait_timer.timeout.connect(self._on_hand_wait_timeout)

        self._processing_release_timer = QTimer(self)
        self._processing_release_timer.setSingleShot(True)
        self._processing_release_timer.setInterval(8000)
        self._processing_release_timer.timeout.connect(self._on_processing_release_timeout)

        self._cleanup_delay_timer = QTimer(self)
        self._cleanup_delay_timer.setSingleShot(True)
        self._cleanup_delay_timer.setInterval(2000)
        self._cleanup_delay_timer.timeout.connect(self._cleanup_temp_file)

        self._new_user_timer = QTimer(self)
        self._new_user_timer.setSingleShot(True)
        self._new_user_timer.setInterval(2000)
        self._new_user_timer.timeout.connect(self._send_new_user)

    def _invoke(self, obj: QObject | None, method_name: str, *args):
        if obj is None:
            return None
        method = getattr(obj, method_name, None)
        if method is None:
            return None
        try:
            return method(*args)
        except Exception as exc:
            self.logger.warning(f"{method_name} failed: {exc}")
            return None

    def _serial_detection_allowed(self) -> bool:
        result = self._invoke(self._serial, "isDetectionAllowed")
        return bool(result) if result is not None else True

    def _set_processing_item(self, value: bool) -> None:
        v = bool(value)
        if self._processing_item == v:
            return
        self._processing_item = v
        self.processingItemChanged.emit(v)

    def _set_waiting_phone_finish(self, value: bool) -> None:
        v = bool(value)
        if self._waiting_phone_finish_response == v:
            return
        self._waiting_phone_finish_response = v
        self.waitingPhoneFinishResponseChanged.emit(v)

    def get_serial(self) -> QObject | None:
        return self._serial

    def set_serial(self, value: QObject | None) -> None:
        if self._serial is value:
            return
        self._serial = value
        self.serialChanged.emit()

    serial = Property(QObject, get_serial, set_serial, notify=serialChanged)

    def get_server(self) -> QObject | None:
        return self._server

    def set_server(self, value: QObject | None) -> None:
        if self._server is value:
            return
        self._server = value
        self.serverChanged.emit()

    server = Property(QObject, get_server, set_server, notify=serverChanged)

    def get_app_state(self) -> QObject | None:
        return self._app_state

    def set_app_state(self, value: QObject | None) -> None:
        if self._app_state is value:
            return
        self._app_state = value
        self.appStateChanged.emit()

    appState = Property(QObject, get_app_state, set_app_state, notify=appStateChanged)

    @Slot()
    def startFlow(self) -> None:
        self._session_ui_started = False
        self.showCameraRequested.emit()
        self._new_user_timer.start()

    @Slot()
    def stopFlow(self) -> None:
        self._new_user_timer.stop()
        self._camera_restore_timer.stop()
        self._phone_finish_fallback_timer.stop()
        self._deferral_timer.stop()
        self._prediction_guard_timer.stop()
        self._hand_wait_timer.stop()
        self._processing_release_timer.stop()
        self._cleanup_delay_timer.stop()

        self._set_processing_item(False)
        self._set_waiting_phone_finish(False)
        self._session_ui_started = False
        self._prediction_applied = False
        self._prediction_waiting_for_clear = False
        self._holding_capture_until_completion = False
        self._prediction_guard_elapsed = False

        self._invoke(self._serial, "sendSignOut")
        self._invoke(self._app_state, "endRecycleSession")

    def _show_prediction_capture(self) -> None:
        if not self._def_pred_image:
            return
        self._camera_restore_timer.stop()
        self.showCaptureRequested.emit(self._def_pred_image)

    def _start_hand_wait_feedback(self) -> None:
        self.handsInsertedRequested.emit()
        self._hand_wait_timer.start()

    def _schedule_cleanup(self) -> None:
        if self._cleanup_path:
            self._cleanup_delay_timer.start()

    def _restore_camera_if_possible(self) -> None:
        if self._prediction_waiting_for_clear or self._holding_capture_until_completion:
            return
        if self._def_pred_image:
            self.showCameraRequested.emit()
        self._schedule_cleanup()
        self._def_pred_image = ""
        self._cleanup_path = ""

    def _apply_prediction_now(self) -> None:
        if self._prediction_applied:
            return
        resumed_from_hold = self._prediction_waiting_for_clear
        self.logger.info(
            f"Applying prediction: pred={self._def_pred} image={bool(self._def_pred_image)} cleanup={bool(self._cleanup_path)}"
        )
        self._prediction_applied = True
        self._prediction_waiting_for_clear = False
        self._holding_capture_until_completion = self._def_pred in {"plastic", "aluminum", "other"} and bool(self._def_pred_image)
        self._hand_wait_timer.stop()

        self._invoke(self._serial, "recordMlPrediction", self._def_pred)
        self._invoke(
            self._app_state,
            "onPredictionResult",
            self._def_pred,
            self._def_user_type,
            self._def_phone,
            self._def_pred_image,
        )
        if resumed_from_hold:
            self.logger.info(f"Resume completed -> action sent for held prediction: {self._def_pred}")

        if not self._holding_capture_until_completion:
            self._restore_camera_if_possible()

    def _prediction_needs_guard(self) -> bool:
        return self._def_pred in {"plastic", "aluminum", "other"}

    def _on_prediction_guard_elapsed(self) -> None:
        self._prediction_guard_elapsed = True
        if self._prediction_waiting_for_clear or not self._serial_detection_allowed():
            self.logger.info("Prediction safety window elapsed while hand/gate block is active; waiting for clear")
            self._prediction_waiting_for_clear = True
            self._start_hand_wait_feedback()
            return
        self._apply_prediction_now()

    def _on_hand_wait_timeout(self) -> None:
        if not self._prediction_waiting_for_clear:
            return
        if self._serial_detection_allowed():
            self.logger.info("Hand/gate block cleared during repeated safety check; resuming held prediction")
            QTimer.singleShot(0, self._apply_deferred_prediction)
            return
        self.logger.info("Hand/gate block still active; re-showing hand popup")
        self._start_hand_wait_feedback()

    def _send_new_user(self) -> None:
        if bool(self._invoke(self._serial, "isProcessing")):
            self.logger.info("Serial is still busy; delaying new recycle session start")
            self._new_user_timer.start()
            return
        self._invoke(self._serial, "sendNewUser")

    @Slot()
    def startSessionUi(self) -> None:
        self.startSessionUiRequested.emit()

    @Slot()
    def finishSessionUi(self) -> None:
        self.logger.info("Finish session requested from UI; ending hardware session")
        self._invoke(self._serial, "sendSignOut")
        self.finishSessionUiRequested.emit()

    @Slot()
    def onSerialReady(self) -> None:
        if self._session_ui_started:
            return
        self._session_ui_started = True
        self.startSessionUiRequested.emit()

    @Slot()
    def onNewUserFailed(self) -> None:
        self.newUserFailedRequested.emit()

    @Slot(bool)
    def onFinishedPhoneNumberRecycle(self, is_pending: bool) -> None:
        if not self._waiting_phone_finish_response:
            return
        self._phone_finish_fallback_timer.stop()
        self._set_waiting_phone_finish(False)
        self.phoneFinishResultRequested.emit(bool(is_pending))

    @Slot("QVariant", int, str, str)
    def onPredictionReady(self, results, user_type: int, phone_number: str, cleanup_path: str = "") -> None:
        result_list = list(results) if isinstance(results, (list, tuple)) else []
        self._def_pred = str(result_list[0]) if len(result_list) > 0 else ""
        self._def_pred_image = str(result_list[1]) if len(result_list) > 1 else ""
        self._def_user_type = int(user_type)
        self._def_phone = str(phone_number or "")
        self._cleanup_path = str(cleanup_path or "")
        self._prediction_applied = False
        self._prediction_waiting_for_clear = False
        self._holding_capture_until_completion = False
        self._prediction_guard_elapsed = False
        self._prediction_guard_timer.stop()
        self._hand_wait_timer.stop()
        self._deferral_timer.start()

    def _apply_deferred_prediction(self) -> None:
        self._show_prediction_capture()
        if not self._serial_detection_allowed():
            self.logger.info("Holding prediction while hand/gate alarm blocks detection")
            self._prediction_waiting_for_clear = True
            self._start_hand_wait_feedback()
            return
        if self._prediction_needs_guard() and not self._prediction_guard_elapsed:
            if not self._prediction_guard_timer.isActive():
                self.logger.info("Starting prediction safety window before hardware action")
                self._prediction_guard_timer.start()
            return
        self._apply_prediction_now()

    def _cleanup_temp_file(self) -> None:
        if not self._cleanup_path:
            return
        self._invoke(self._server, "cleanupFile", self._cleanup_path)
        self._cleanup_path = ""

    def _on_phone_finish_fallback(self) -> None:
        if not self._waiting_phone_finish_response:
            return
        self._set_waiting_phone_finish(False)
        self.phoneFinishResultRequested.emit(True)

    @Slot()
    def onItemProcessingStarted(self) -> None:
        self._set_processing_item(True)
        self._processing_release_timer.start()

    def _on_processing_release_timeout(self) -> None:
        if self._holding_capture_until_completion:
            self.logger.info("Processing fallback expired while waiting for hardware completion; keeping held capture")
            return
        self._set_processing_item(False)

    @Slot(str, int, int)
    def onPhoneFinishRequested(self, _phone_number: str, _plastic: int, _cans: int) -> None:
        self._set_waiting_phone_finish(True)
        self._phone_finish_fallback_timer.start()

    @Slot()
    def onRecycleUiClockRestart(self) -> None:
        self.restartClockRequested.emit()

    @Slot(str)
    def onRecycleUiShowCapture(self, image_path: str) -> None:
        path = str(image_path or "")
        if not path:
            return
        if self._def_pred_image and path == self._def_pred_image:
            return
        self.showCaptureRequested.emit(path)
        self._camera_restore_timer.stop()

    @Slot()
    def onRecycleUiHandsInserted(self) -> None:
        self.handsInsertedRequested.emit()

    @Slot()
    def onRecycleUiOtherInserted(self) -> None:
        self.otherInsertedRequested.emit()

    @Slot()
    def onRecycleUiFinishedNoPoints(self) -> None:
        self.finishedNoPointsRequested.emit()

    @Slot()
    def onRecycleUiFinishedQrCode(self) -> None:
        self.finishedQrCodeRequested.emit()

    @Slot(bool)
    def onHandBlockStateChanged(self, blocked: bool) -> None:
        is_blocked = bool(blocked)
        if is_blocked:
            if self._prediction_needs_guard() and not self._prediction_applied:
                self._prediction_waiting_for_clear = True
                if not self._hand_wait_timer.isActive():
                    self._start_hand_wait_feedback()
            return
        if self._prediction_waiting_for_clear:
            self._hand_wait_timer.stop()
            self.logger.info("Hand/gate block cleared; resuming held prediction")
            QTimer.singleShot(0, self._apply_deferred_prediction)
            return
        if self._prediction_applied and self._def_pred == "hand" and self._def_pred_image:
            self._restore_camera_if_possible()

    @Slot()
    def onHardwareCycleCompleted(self) -> None:
        self._processing_release_timer.stop()
        self._hand_wait_timer.stop()
        self._prediction_waiting_for_clear = False
        self._set_processing_item(False)
        if self._holding_capture_until_completion:
            self._holding_capture_until_completion = False
            self._restore_camera_if_possible()

