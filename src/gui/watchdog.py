from __future__ import annotations

import time

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtQml import QmlElement

from gui.logging import getLogger

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
class Watchdog(QObject):
    """Runtime watchdog: monitors UI heartbeat and serial connectivity."""

    serialChanged = Signal()
    appStateChanged = Signal()
    enabledChanged = Signal()

    watchdogAlert = Signal(str)
    watchdogRecovered = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.logger = getLogger("dropme.watchdog")

        self._serial: QObject | None = None
        self._app_state: QObject | None = None
        self._enabled = True

        self._ui_timeout_sec = float(15)
        self._serial_timeout_sec = float(20)
        self._recovery_cooldown_sec = float(10)

        now = time.monotonic()
        self._last_ui_beat = now
        self._last_serial_seen = now
        self._last_recovery = 0.0

        self._serial_alert_active = False
        self._ui_alert_active = False

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    def _invoke(self, obj: QObject | None, method_name: str, *args):
        if obj is None:
            return None
        fn = getattr(obj, method_name, None)
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception as exc:
            self.logger.warning(f"{method_name} failed: {exc}")
            return None

    def _is_serial_connected(self) -> bool:
        result = self._invoke(self._serial, "isConnected")
        return bool(result)

    def _is_startup_settling(self) -> bool:
        result = self._invoke(self._serial, "isStartupSettling")
        return bool(result)

    def _both_recycle_bins_full(self) -> bool:
        plastic_full = self._invoke(self._app_state, "property", "recyclePlasticBinFull")
        can_full = self._invoke(self._app_state, "property", "recycleCanBinFull")
        return bool(plastic_full) and bool(can_full)

    def _attempt_recovery(self, reason: str) -> None:
        now = time.monotonic()
        if (now - self._last_recovery) < self._recovery_cooldown_sec:
            return

        self._last_recovery = now
        self.logger.warning(f"Watchdog recovery attempt for {reason}")

        if self._both_recycle_bins_full():
            self._invoke(self._app_state, "showPopup", "out_of_service", {})

        # Best-effort serial reset if transport looks unhealthy
        if reason.startswith("SERIAL"):
            self._invoke(self._serial, "resetSystem")

    def _raise_alert(self, reason: str) -> None:
        self.logger.warning(f"Watchdog alert: {reason}")
        self.watchdogAlert.emit(reason)
        self._attempt_recovery(reason)

    def _clear_alert(self, reason: str) -> None:
        self.logger.info(f"Watchdog recovered: {reason}")
        self.watchdogRecovered.emit(reason)

    def _check(self) -> None:
        if not self._enabled:
            return

        now = time.monotonic()

        # UI heartbeat watchdog
        ui_stale = (now - self._last_ui_beat) > self._ui_timeout_sec
        if ui_stale and not self._ui_alert_active:
            self._ui_alert_active = True
            self._raise_alert("UI_HEARTBEAT_TIMEOUT")
        elif not ui_stale and self._ui_alert_active:
            self._ui_alert_active = False
            self._clear_alert("UI_HEARTBEAT_TIMEOUT")

        # Serial connectivity watchdog
        if self._is_serial_connected():
            if self._serial_alert_active:
                self._serial_alert_active = False
                self._clear_alert("SERIAL_DISCONNECTED_TIMEOUT")
            self._last_serial_seen = now
        else:
            if self._is_startup_settling():
                return
            disconnected_too_long = (now - self._last_serial_seen) > self._serial_timeout_sec
            if disconnected_too_long and not self._serial_alert_active:
                self._serial_alert_active = True
                self._raise_alert("SERIAL_DISCONNECTED_TIMEOUT")

    def get_serial(self) -> QObject | None:
        return self._serial

    def set_serial(self, value: QObject | None) -> None:
        if self._serial is value:
            return
        self._serial = value
        self.serialChanged.emit()

    serial = Property(QObject, get_serial, set_serial, notify=serialChanged)

    def get_app_state(self) -> QObject | None:
        return self._app_state

    def set_app_state(self, value: QObject | None) -> None:
        if self._app_state is value:
            return
        self._app_state = value
        self.appStateChanged.emit()

    appState = Property(QObject, get_app_state, set_app_state, notify=appStateChanged)

    def get_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        enabled = bool(value)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.enabledChanged.emit()

    enabled = Property(bool, get_enabled, set_enabled, notify=enabledChanged)

    @Slot()
    def beatUi(self) -> None:
        self._last_ui_beat = time.monotonic()

    @Slot()
    def beatBackend(self) -> None:
        # Optional external beat hook if backend subsystems want explicit liveness updates.
        self._last_serial_seen = time.monotonic()

    @Slot()
    def forceCheck(self) -> None:
        self._check()
