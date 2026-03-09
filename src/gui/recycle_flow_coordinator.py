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

        self._camera_restore_timer = QTimer(self)
        self._camera_restore_timer.setSingleShot(True)
        self._camera_restore_timer.setInterval(1500)
        self._camera_restore_timer.timeout.connect(self.showCameraRequested.emit)

        self._phone_finish_fallback_timer = QTimer(self)
        self._phone_finish_fallback_timer.setSingleShot(True)
        self._phone_finish_fallback_timer.setInterval(2500)
        self._phone_finish_fallback_timer.timeout.connect(self._on_phone_finish_fallback)

        self._deferral_timer = QTimer(self)
        self._deferral_timer.setSingleShot(True)
        self._deferral_timer.setInterval(150)
        self._deferral_timer.timeout.connect(self._apply_deferred_prediction)

        self._processing_release_timer = QTimer(self)
        self._processing_release_timer.setSingleShot(True)
        self._processing_release_timer.setInterval(3000)
        self._processing_release_timer.timeout.connect(lambda: self._set_processing_item(False))

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
        self._processing_release_timer.stop()
        self._cleanup_delay_timer.stop()

        self._set_processing_item(False)
        self._set_waiting_phone_finish(False)
        self._session_ui_started = False

        self._invoke(self._serial, "sendSignOut")
        self._invoke(self._app_state, "endRecycleSession")

    def _send_new_user(self) -> None:
        self._invoke(self._serial, "sendNewUser")

    @Slot()
    def startSessionUi(self) -> None:
        self.startSessionUiRequested.emit()

    @Slot()
    def finishSessionUi(self) -> None:
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
        self._deferral_timer.start()

    def _apply_deferred_prediction(self) -> None:
        self._invoke(self._app_state, "onPredictionResult", self._def_pred, self._def_user_type, self._def_phone, self._def_pred_image)
        if self._cleanup_path:
            self._cleanup_delay_timer.start()

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
        self.showCaptureRequested.emit(path)
        self._camera_restore_timer.start()

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

