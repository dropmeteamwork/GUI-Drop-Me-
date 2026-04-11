from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtQml import QmlElement

from gui.logging import getLogger

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
class RecycleCoordinator(QObject):
    """
    Service layer for recycle flow side effects.
    Subscribes to AppState workflow signals and executes serial/server actions.
    """

    serialChanged = Signal()
    serverChanged = Signal()
    appStateChanged = Signal()

    itemProcessingStarted = Signal()
    phoneFinishRequested = Signal(str, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.logger = getLogger("dropme.recycle_coordinator")
        self._serial: QObject | None = None
        self._server: QObject | None = None
        self._app_state: QObject | None = None

    def _safe_disconnect(self, sig, handler) -> None:
        try:
            sig.disconnect(handler)
        except Exception:
            pass

    def _connect_app_state(self, app_state: QObject) -> None:
        app_state.recycleRequestHardwareAction.connect(self._on_hardware_request)
        app_state.recycleRequestServerAction.connect(self._on_server_request)
        app_state.recycleRequestFinishPhoneNumber.connect(self._on_finish_phone_request)
        app_state.recycleRequestFinishQrCode.connect(self._on_finish_qr_request)

    def _disconnect_app_state(self, app_state: QObject) -> None:
        self._safe_disconnect(app_state.recycleRequestHardwareAction, self._on_hardware_request)
        self._safe_disconnect(app_state.recycleRequestServerAction, self._on_server_request)
        self._safe_disconnect(app_state.recycleRequestFinishPhoneNumber, self._on_finish_phone_request)
        self._safe_disconnect(app_state.recycleRequestFinishQrCode, self._on_finish_qr_request)

    def _invoke(self, obj: QObject | None, method_name: str, *args) -> bool:
        if obj is None:
            self.logger.warning(f"{method_name}: target is not set")
            return False
        method = getattr(obj, method_name, None)
        if method is None:
            self.logger.warning(f"{method_name}: method not found on target")
            return False
        try:
            method(*args)
            return True
        except Exception as exc:
            self.logger.error(f"{method_name} failed: {exc}")
            return False

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
        if self._app_state is not None:
            self._disconnect_app_state(self._app_state)
        self._app_state = value
        if self._app_state is not None:
            self._connect_app_state(self._app_state)
        self.appStateChanged.emit()

    appState = Property(QObject, get_app_state, set_app_state, notify=appStateChanged)

    @Slot(str)
    def _on_hardware_request(self, action: str) -> None:
        action_name = str(action or "")
        if action_name in {"can", "plastic", "other"}:
            allowed = self._invoke(self._serial, "isDetectionAllowed")
            if allowed is not None and not bool(allowed):
                self.logger.info(f"Blocked hardware action while gate alarm/hand block is active: {action_name}")
                return
        if action_name == "can":
            if self._invoke(self._serial, "sendCan"):
                self.itemProcessingStarted.emit()
            return
        if action_name == "plastic":
            if self._invoke(self._serial, "sendPlastic"):
                self.itemProcessingStarted.emit()
            return
        if action_name == "other":
            if self._invoke(self._serial, "sendOther"):
                self.itemProcessingStarted.emit()
            return
        self.logger.warning(f"Unknown hardware action: {action_name}")

    @Slot(str)
    def _on_server_request(self, action: str) -> None:
        action_name = str(action or "")
        if action_name == "send_aluminum":
            self._invoke(self._server, "sendAluminumCan")
            return
        if action_name == "send_plastic":
            self._invoke(self._server, "sendPlasticBottle")
            return
        self.logger.warning(f"Unknown server action: {action_name}")

    @Slot(str, int, int)
    def _on_finish_phone_request(self, phone_number: str, plastic: int, cans: int) -> None:
        p = str(phone_number or "")
        b = int(plastic)
        c = int(cans)
        self.phoneFinishRequested.emit(p, b, c)
        self._invoke(self._server, "finishRecyclePhoneNumber", p, b, c)

    @Slot(str, int, int)
    def _on_finish_qr_request(self, _token_or_phone: str, _plastic: int, _cans: int) -> None:
        # Current Server API keeps finishRecycleQrCode as no-arg slot.
        self._invoke(self._server, "finishRecycleQrCode")
