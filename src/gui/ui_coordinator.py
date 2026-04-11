from __future__ import annotations

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtQml import QmlElement

from gui.logging import getLogger

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
class UiCoordinator(QObject):
    """
    Centralized UI policy coordinator.
    Keeps route/popup/hardware event decisions out of QML view files.
    """

    appStateChanged = Signal()
    serialChanged = Signal()

    backRequested = Signal()

    _KNOWN_POPUPS = {
        "hands",
        "hands_and_close",
        "non_recyclable",
        "timeout",
        "invalid_phone",
        "finished_qr",
        "finished_phone",
        "out_of_service",
    }

    def __init__(self) -> None:
        super().__init__()
        self.logger = getLogger("dropme.ui_coordinator")
        self._app_state: QObject | None = None
        self._serial: QObject | None = None
        self._hand_popup_timer = QTimer(self)
        self._hand_popup_timer.setSingleShot(True)
        self._hand_popup_timer.setInterval(2000)
        self._hand_popup_timer.timeout.connect(self._show_delayed_hand_popup)

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

    def _get_bool(self, name: str) -> bool:
        if self._app_state is None:
            return False
        try:
            return bool(self._app_state.property(name))
        except Exception:
            return False

    def _get_str(self, name: str) -> str:
        if self._app_state is None:
            return ""
        try:
            value = self._app_state.property(name)
            return str(value or "")
        except Exception:
            return ""

    def _set_prop(self, name: str, value) -> None:
        if self._app_state is None:
            return
        try:
            self._app_state.setProperty(name, value)
        except Exception as exc:
            self.logger.warning(f"Failed to set AppState.{name}: {exc}")

    def get_app_state(self) -> QObject | None:
        return self._app_state

    def set_app_state(self, value: QObject | None) -> None:
        if self._app_state is value:
            return
        self._app_state = value
        self.appStateChanged.emit()

    appState = Property(QObject, get_app_state, set_app_state, notify=appStateChanged)

    def get_serial(self) -> QObject | None:
        return self._serial

    def set_serial(self, value: QObject | None) -> None:
        if self._serial is value:
            return
        self._serial = value
        self.serialChanged.emit()

    serial = Property(QObject, get_serial, set_serial, notify=serialChanged)

    @Slot(str, "QVariant")
    def handleNavigate(self, route: str, payload=None) -> None:
        route_name = str(route or "")
        data = payload if payload is not None else {}

        if route_name == "back":
            self.backRequested.emit()
            return

        # Defensive guard: duplicate recycle navigation pushes can recreate the view
        # and cause rapid bottom-panel index flips (Slides <-> Camera).
        if route_name in ("recycle_qr", "recycle_phone"):
            current_route = self._get_str("currentRoute")
            if current_route == route_name:
                self.logger.info(f"Ignoring duplicate navigation to {route_name}")
                return

        if route_name in ("maintenance", "enter_credentials") and isinstance(data, dict) and "language" in data:
            self._set_prop("language", int(data.get("language", 1)))

        if route_name in ("recycle_qr", "recycle_phone"):
            self._invoke(self._app_state, "startRecycleSession")

        if route_name == "start":
            self._invoke(self._serial, "sendSignOut")
            self._set_prop("shouldSignOut", False)

        self._invoke(self._app_state, "navigateTo", route_name, data)

    @Slot(str, "QVariant")
    def handleShowPopup(self, popup_name: str, payload=None) -> None:
        data = payload if payload is not None else {}
        key = self.popupKey(str(popup_name or ""))
        if not key:
            self.logger.warning(f"Unknown popup key: {popup_name}")
            return
        self._invoke(self._app_state, "showPopup", key, data)

    @Slot(str, "QVariant", result="QVariant")
    def routeAction(self, route: str, payload=None):
        route_name = str(route or "")
        data = payload if isinstance(payload, dict) else {}

        if route_name == "start":
            return {"op": "reset", "target": "start", "props": {}, "background": "background"}
        if route_name == "select_language":
            return {"op": "push", "target": "select_language", "props": {}}
        if route_name == "maintenance":
            return {"op": "push", "target": "maintenance", "props": {}}
        if route_name == "enter_credentials":
            return {"op": "push", "target": "enter_credentials", "props": {}, "background": "background-with-logo"}
        if route_name == "recycle_qr":
            return {"op": "push", "target": "recycle_qr", "props": {}}
        if route_name == "recycle_phone":
            return {
                "op": "push",
                "target": "recycle_phone",
                "props": {"phoneNumber": str(data.get("phoneNumber", ""))},
            }
        return {"op": "none", "target": "", "props": {}}

    @Slot(str, result=str)
    def popupKey(self, name: str) -> str:
        popup = str(name or "")
        return popup if popup in self._KNOWN_POPUPS else ""

    @Slot(bool)
    def handleNewUserFailed(self, is_dev: bool) -> None:
        if bool(is_dev):
            return
        self._invoke(self._app_state, "showPopup", "out_of_service", {})

    @Slot()
    def handleResetToStart(self) -> None:
        self._invoke(self._serial, "sendSignOut")
        self._set_prop("shouldSignOut", False)
        self._invoke(self._app_state, "navigateTo", "start", {})

    @Slot()
    def handleHwHandInGate(self) -> None:
        if not self._get_bool("handInGate"):
            self._set_prop("handInGate", True)
        if not self._hand_popup_timer.isActive():
            self._hand_popup_timer.start()

    def _show_delayed_hand_popup(self) -> None:
        if not self._get_bool("handInGate"):
            return
        self._invoke(self._app_state, "showPopup", "hands", {})

    @Slot()
    def handleHwGateCleared(self) -> None:
        self._hand_popup_timer.stop()
        self._set_prop("handInGate", False)

        active_popup = self._get_str("activePopup")
        if active_popup in ("hands", "hands_and_close"):
            self._invoke(self._app_state, "clearPopup")

        if self._get_bool("shouldSignOut"):
            self._invoke(self._serial, "closeDoor")
            self._set_prop("shouldSignOut", False)
            self._invoke(self._app_state, "navigateTo", "start", {})

    @Slot(str)
    def handleHwBinFull(self, bin_name: str) -> None:
        self._invoke(self._app_state, "markRecycleBinFull", str(bin_name or ""))

    @Slot(str, bool)
    def handleHwBasketState(self, bin_name: str, is_full: bool) -> None:
        self._invoke(self._app_state, "setRecycleBinState", str(bin_name or ""), bool(is_full))

    @Slot(str)
    def handleAcceptedItemRollback(self, item_type: str) -> None:
        normalized = str(item_type or "").strip().lower()
        if normalized == "plastic":
            self._invoke(self._app_state, "decrementRecyclePlastic")
            return
        if normalized in ("can", "aluminum"):
            self._invoke(self._app_state, "decrementRecycleCans")
            return

    @Slot(str, int)
    def handleHwError(self, error_name: str, _error_id: int) -> None:
        critical_errors = {
            "CONNECTION_LOST",
            "MCU_ERROR",
            "NACK",
            "GATE_OPEN_TIMEOUT",
        }
        if str(error_name or "") not in critical_errors:
            self.logger.info(f"Ignoring non-critical hardware error for popup: {error_name}")
            return
        self._invoke(self._serial, "sendSignOut")
        self._invoke(self._app_state, "showPopup", "out_of_service", {})

    @Slot()
    def requestReturnToStart(self) -> None:
        if self._get_bool("handInGate"):
            self._set_prop("shouldSignOut", True)
            return
        self._invoke(self._serial, "sendSignOut")
        self._set_prop("shouldSignOut", False)
        self._invoke(self._app_state, "navigateTo", "start", {})

