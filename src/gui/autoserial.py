"""
DropMe AutoSerial - Automatic Serial Port Discovery and Protocol Handler
(senior-grade, cross-platform safe)

Changes:
- Fix accept state machine completion (CONVEYOR_DONE bug)
- Separate gate obstruction from fraud prevention:
    gate_blocked  = physical gate obstruction (MCU feedback)
    fraud_hold    = ML "hand in camera" prevention (PC-side)
- Stronger RX parsing and structured TX/RX logging
- Protocol logs moved into project folder (same repo), not AppData
"""

from __future__ import annotations

import os
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtQml import QmlElement
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from gui import mcu
from gui import logging
from gui.aws_uploader import AWSUploader
from gui.protocol_telemetry_service import ProtocolTelemetryService
from gui.stm_interface import QtStmInterface

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0
MIN_ITEM_WEIGHT_GRAMS = 10
CONSIDER_ITEM_DROPPED = str(os.environ.get("DROPME_CONSIDER_ITEM_DROPPED", "0")).strip().lower() in ("1", "true", "yes", "on")
CONSIDER_EXIT_GATE = str(os.environ.get("DROPME_CONSIDER_EXIT_GATE", "0")).strip().lower() in ("1", "true", "yes", "on")
CONSIDER_WEIGHT = str(os.environ.get("DROPME_CONSIDER_WEIGHT", "0")).strip().lower() in ("1", "true", "yes", "on")


@QmlElement
class AutoSerial(QObject):
    # Connection
    connectionEstablished = Signal(str)
    connectionLost = Signal()

    # System Status
    systemReady = Signal()
    systemBusy = Signal()
    systemIdle = Signal()

    # Gate Status
    gateOpened = Signal()
    gateClosed = Signal()
    gateBlocked = Signal()

    # Motion Feedback
    conveyorDone = Signal()
    sortDone = Signal(int)
    rejectDone = Signal()
    rejectHomeOk = Signal()

    # Item Processing Complete
    plasticAccepted = Signal()
    canAccepted = Signal()
    itemRejected = Signal()

    # Sensor Data
    weightReceived = Signal(int)
    binFull = Signal(str)
    basketStateChanged = Signal(str, bool)
    acceptedItemRollback = Signal(str)

    # Errors
    errorOccurred = Signal(str, int)

    # Debug
    commandSent = Signal(str, int)

    # Compatibility aliases (keep)
    ready = Signal()
    handInGate = Signal()
    newUserFailed = Signal()
    doorStatusReceived = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger("dropme.autoserial")

        # Serial port
        self.port = QSerialPort()
        self.connected_port_name: str | None = None
        self._configured_port_name = self._normalize_port_name(os.environ.get("DROPME_MCU_PORT", ""))
        self._check_baskets_enabled = str(os.environ.get("DROPME_CHECK_BASKETS", "1")).strip().lower() not in ("0", "false", "no", "off")
        self._allow_local_sensor_override = str(os.environ.get("DROPME_DEV_LOCAL_SENSOR_OVERRIDE", "0")).strip().lower() in ("1", "true", "yes", "on")
        self._dev_mode = str(os.environ.get("DROPME_DEV", "0")).strip().lower() in ("1", "true", "yes", "on")
        self.seq_manager = mcu.SequenceManager()
        self.rx_buffer = bytearray()
        self.last_response_time = 0.0
        self._pending_requests: deque[dict] = deque()

        # ==================== STATE TRACKING ====================
        self._session_id: str | None = None
        self._gate_blocked = False          # physical obstruction (MCU)
        self._gate_open = False
        self._operation_active = False
        self._system_busy = False
        self._session_stage = "disconnected"
        self._basket_precheck_pending: set[int] = set()
        self._gate_open_deadline = 0.0
        self._gate_close_deadline = 0.0
        self._current_prediction = ""
        self._current_prediction_confidence = 0.0
        self._last_prediction_ts = 0.0
        self._fraud_active = False
        self._fraud_logged_for_block = False
        self._poll_cursor = 0
        self._pending_exit_verification: dict | None = None
        self._reject_clear_polls = 0
        self._startup_scan_started_at = time.monotonic()
        self._awaiting_first_item_after_gate_open = False
        self._sensor_states: dict[str, int] = {
            "gate_opened": 0,
            "gate_closed": 0,
            "gate_alarm": 0,
            "exit_gate": 0,
            "drop_sensor": 0,
            "basket_1": 0,
            "basket_2": 0,
            "basket_3": 0,
        }

        # Fraud prevention hold (PC-side, from ML hand detection)
        self._fraud_hold = False

        # Serial transport abstraction
        self._stm_interface = QtStmInterface()

        # ==================== TIMERS ====================
        self._credentials_timeout_timer = QTimer(self)
        self._credentials_timeout_timer.setSingleShot(True)
        self._credentials_timeout_timer.setInterval(20000)
        self._credentials_timeout_timer.timeout.connect(self._on_credentials_timeout)

        self._command_timeout_timer = QTimer(self)
        self._command_timeout_timer.setSingleShot(True)
        self._command_timeout_timer.setInterval(2500)
        self._command_timeout_timer.timeout.connect(self._on_command_timeout)

        self._session_idle_timer = QTimer(self)
        self._session_idle_timer.setSingleShot(True)
        self._session_idle_timer.setInterval(10000)
        self._session_idle_timer.timeout.connect(self._on_session_idle_timeout)

        self._sensor_poll_timer = QTimer(self)
        self._sensor_poll_timer.setInterval(700)
        self._sensor_poll_timer.timeout.connect(self._poll_runtime_sensors)

        self._fraud_timer = QTimer(self)
        self._fraud_timer.setSingleShot(True)
        self._fraud_timer.setInterval(2000)
        self._fraud_timer.timeout.connect(self._on_fraud_timeout)

        self._exit_gate_timeout_timer = QTimer(self)
        self._exit_gate_timeout_timer.setSingleShot(True)
        self._exit_gate_timeout_timer.setInterval(3000)
        self._exit_gate_timeout_timer.timeout.connect(self._on_exit_gate_timeout)

        # ==================== Telemetry Service ====================
        project_root = Path(__file__).resolve().parents[1]
        telemetry_dir = project_root / "dropme_protocol_logs"

        self._telemetry = ProtocolTelemetryService(
            logger=self.logger,
            log_dir=telemetry_dir,
            machine_name=os.environ.get("MACHINE_NAME", "RVM-001"),
            telemetry_uploader=AWSUploader(),
        )

        self._bin_plastic_full = False
        self._bin_can_full = False
        self._bin_reject_full = False
        self._last_weight_grams = None
        self._last_error = ""

        self._telemetry.initialize()
        self._restore_persisted_basket_state()
        self._write_sensor_snapshot()
        # ==================== Port scanning timer ====================
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self._scan_ports)
        if not self._dev_mode:
            self.scan_timer.start(2000)
        else:
            self.logger.info("[DEV_SIM] Port scanning disabled (hardware simulation active)")

        # Keep-alive ping timer
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self._send_ping)
        self.ping_timer.setInterval(10000)

        # Bin poll timer (log only)
        self.bin_poll_timer = QTimer(self)
        self.bin_poll_timer.timeout.connect(self._poll_bin_status)
        self.bin_poll_timer.setInterval(43200000)

        if self._dev_mode:
            self.logger.info("AutoSerial initialized [DEV_SIM] - hardware simulation enabled (no serial port required)")
        else:
            self.logger.info("AutoSerial initialized (using QtSerialPort) - State machine enabled")

    # ==================== LOG INIT ====================

    def _sensor_snapshot_data(self) -> dict:
        return {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "port": self.connected_port_name or "",
            "session_id": self._session_id or "",
            "system": {
                "busy": self._system_busy,
                "operation_active": self._operation_active,
                "stage": self._session_stage,
            },
            "gate": {
                "open": self._gate_open,
                "blocked": self._gate_blocked,
            },
            "bins": {
                "plastic_full": self._bin_plastic_full,
                "can_full": self._bin_can_full,
                "reject_full": self._bin_reject_full,
            },
            "last_weight_grams": self._last_weight_grams,
            "prediction": {
                "label": self._current_prediction,
                "confidence": self._current_prediction_confidence,
            },
            "sensors": dict(self._sensor_states),
            "last_error": self._last_error,
        }

    def _init_weights_log(self) -> None:
        self._telemetry.initialize()

    def _log_weight(self, weight_grams: int) -> None:
        self._telemetry.log_weight(weight_grams, self._session_id, self.connected_port_name)

    def _append_protocol_event(self, event: dict) -> None:
        self._telemetry.append_protocol_event(event, self._session_id)

    def _init_sensor_logs(self) -> None:
        self._telemetry.write_sensor_snapshot(self._sensor_snapshot_data())

    def _write_sensor_snapshot(self) -> None:
        self._telemetry.write_sensor_snapshot(self._sensor_snapshot_data())

    def _restore_persisted_basket_state(self) -> None:
        try:
            import json

            snapshot = {}
            if self._telemetry.sensor_snapshot_file.exists():
                snapshot = json.loads(self._telemetry.sensor_snapshot_file.read_text(encoding="utf-8"))
            bins = snapshot.get("bins", {}) if isinstance(snapshot, dict) else {}
            self._apply_basket_state("Plastic", bool(bins.get("plastic_full", False)), emit_event=False, source="persisted")
            self._apply_basket_state("Can", bool(bins.get("can_full", False)), emit_event=False, source="persisted")
            self._apply_basket_state("Reject", bool(bins.get("reject_full", False)), emit_event=False, source="persisted")
        except Exception as exc:
            self.logger.warning(f"Failed to restore persisted basket state: {exc}")

    def _append_sensor_event(self, kind: str, payload: int = 0, extra: dict | None = None) -> None:
        self._telemetry.append_sensor_event(
            kind=kind,
            payload=payload,
            session_id=self._session_id,
            port_name=self.connected_port_name,
            snapshot=self._sensor_snapshot_data(),
            extra=extra,
        )

    def _write_protocol_state_if_changed(self, force: bool = False) -> None:
        self._telemetry.write_protocol_state_if_changed(force=force)

    def _sync_connection_state(self, connected: bool) -> None:
        self._telemetry.sync_connection_state(connected=connected, port_name=self.connected_port_name)

    def _reduce_protocol_state(self, direction: str, frame: mcu.Frame, raw: bytes) -> None:
        self._telemetry.reduce_protocol_state(
            direction=direction,
            frame=frame,
            raw=raw,
            connected=self.port.isOpen(),
            port_name=self.connected_port_name,
        )

    def _log_session_event(
        self,
        *,
        direction: str,
        event_name: str,
        raw_hex: str = "",
        crc_valid: bool | None = None,
        payload_summary: str = "",
        note: str = "",
    ) -> None:
        self._telemetry.log_session_event(
            session_id=self._session_id,
            stage=self._session_stage,
            direction=direction,
            event_name=event_name,
            raw_hex=raw_hex,
            crc_valid=crc_valid,
            payload_summary=payload_summary,
            prediction=self._current_prediction,
            confidence=self._current_prediction_confidence if self._current_prediction else None,
            weight_grams=self._last_weight_grams,
            sensors=self._sensor_snapshot_data().get("sensors", {}),
            note=note,
        )

    # ==================== CONNECTION MANAGEMENT ====================

    def _normalize_port_name(self, value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None

        normalized = raw.upper().rstrip(":")
        if normalized.startswith("\\\\.\\"):
            normalized = normalized[4:]
        if normalized.isdigit():
            normalized = f"COM{normalized}"
        return normalized

    def _candidate_ports(self) -> list[QSerialPortInfo]:
        available = list(QSerialPortInfo.availablePorts())
        if not available:
            return []

        if not self._configured_port_name:
            return available

        configured: list[QSerialPortInfo] = []
        fallback: list[QSerialPortInfo] = []
        for info in available:
            if self._normalize_port_name(info.portName()) == self._configured_port_name:
                configured.append(info)
            else:
                fallback.append(info)
        return configured + fallback

    def _adopt_connected_port(self, test_port: QSerialPort, port_name: str) -> bool:
        self.port = test_port
        self.port.readyRead.connect(self._read_data)
        self.connected_port_name = port_name
        self.last_response_time = time.time()

        self.scan_timer.stop()
        self.ping_timer.start()
        self.bin_poll_timer.start()

        self._session_stage = "connected"
        self.logger.info(f"Connected to {port_name}")
        self._log_session_event(direction="STATE", event_name="connection_established", note=port_name)
        self.connectionEstablished.emit(port_name)
        self._sync_connection_state(True)
        self._refresh_basket_state_from_mcu()
        return True

    def _open_and_probe_port(self, info: QSerialPortInfo) -> bool:
        port_name = info.portName()
        descriptor = ", ".join(
            part for part in (info.description(), info.manufacturer(), info.systemLocation()) if part
        )
        self.logger.info(f"Trying port: {port_name}" + (f" [{descriptor}]" if descriptor else ""))

        test_port = QSerialPort(info)
        try:
            if not test_port.open(QSerialPort.ReadWrite):
                return False

            test_port.setBaudRate(mcu.BAUD_RATE)
            test_port.setDataBits(QSerialPort.Data8)
            test_port.setParity(QSerialPort.NoParity)
            test_port.setStopBits(QSerialPort.OneStop)

            for attempt in range(3):
                if self._stm_interface.probe_ready(test_port, self.seq_manager.next()):
                    return self._adopt_connected_port(test_port, port_name)

                self.logger.warning(f"Ping probe failed on {port_name} (attempt {attempt + 1}/3)")
                time.sleep(0.2)

            if self._configured_port_name and self._normalize_port_name(port_name) == self._configured_port_name:
                self.logger.warning(
                    f"Probe never ACKed on configured port {port_name}; adopting the open port anyway"
                )
                return self._adopt_connected_port(test_port, port_name)
            return False
        except Exception as e:
            self.logger.error(f"Error testing {port_name}: {e}")
            return False
        finally:
            if self.port != test_port and test_port.isOpen():
                test_port.close()

    def _scan_ports(self) -> None:
        if self.port.isOpen():
            return

        self._startup_scan_started_at = min(self._startup_scan_started_at, time.monotonic())
        for info in self._candidate_ports():
            if self._open_and_probe_port(info):
                return

    def _send_ping(self) -> None:
        if self.port.isOpen():
            self._send(mcu.SystemControl.PING)
            if self.last_response_time > 0 and (time.time() - self.last_response_time) > 30:
                self.logger.warning("Connection timeout")
                self._handle_disconnect()

    def _poll_bin_status(self) -> None:
        self.logger.info("Bin status poll (12h interval)")
        self._refresh_basket_state_from_mcu()
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "BIN_POLL",
            "note": "12-hour bin status check"
        })

    def _refresh_basket_state_from_mcu(self) -> None:
        for sensor in (mcu.SensorSelector.BASKET_1, mcu.SensorSelector.BASKET_2, mcu.SensorSelector.BASKET_3):
            self._send(mcu.ReadCommand.READ_SENSOR, sensor)

    def _handle_disconnect(self) -> None:
        was_connected = self.port.isOpen() or bool(self.connected_port_name)
        if self.port.isOpen():
            self.port.close()
        self.connected_port_name = None
        self._sync_connection_state(False)
        self._log_session_event(direction="STATE", event_name="connection_lost")
        self._reset_state()
        self.ping_timer.stop()
        self.bin_poll_timer.stop()
        self.scan_timer.start()
        if was_connected:
            self.errorOccurred.emit("CONNECTION_LOST", 0)
        self.connectionLost.emit()

    def _reset_state(self) -> None:
        self._gate_blocked = False
        self._gate_open = False
        self._operation_active = False
        self._system_busy = False
        self._fraud_hold = False

        self._bin_plastic_full = False
        self._bin_can_full = False
        self._bin_reject_full = False
        self._last_weight_grams = None
        self._last_error = ""
        self._session_stage = "disconnected"
        self._basket_precheck_pending.clear()
        self._gate_open_deadline = 0.0
        self._gate_close_deadline = 0.0
        self._current_prediction = ""
        self._current_prediction_confidence = 0.0
        self._last_prediction_ts = 0.0
        self._fraud_active = False
        self._fraud_logged_for_block = False
        self._pending_requests.clear()
        self._pending_exit_verification = None
        self._reject_clear_polls = 0
        self._awaiting_first_item_after_gate_open = False
        self._sensor_states.update({
            "gate_opened": 0,
            "gate_closed": 0,
            "gate_alarm": 0,
            "exit_gate": 0,
            "drop_sensor": 0,
            "basket_1": 0,
            "basket_2": 0,
            "basket_3": 0,
        })

        self._credentials_timeout_timer.stop()
        self._command_timeout_timer.stop()
        self._session_idle_timer.stop()
        self._sensor_poll_timer.stop()
        self._fraud_timer.stop()
        self._exit_gate_timeout_timer.stop()

    def _apply_basket_state(self, bin_name: str, is_full: bool, *, emit_event: bool, source: str) -> None:
        normalized = str(bin_name or "").strip().lower()
        full = bool(is_full)

        if normalized == "plastic":
            previous = self._bin_plastic_full
            self._bin_plastic_full = full
            self._sensor_states["basket_1"] = int(full)
            display = "Plastic"
        elif normalized == "can":
            previous = self._bin_can_full
            self._bin_can_full = full
            self._sensor_states["basket_2"] = int(full)
            display = "Can"
        elif normalized == "reject":
            previous = self._bin_reject_full
            self._bin_reject_full = full
            self._sensor_states["basket_3"] = int(full)
            display = "Reject"
        else:
            return

        if not self._check_baskets_enabled and normalized in {"plastic", "can"}:
            full = False

        if previous == full and not emit_event:
            return

        self.basketStateChanged.emit(display, full)
        if full and previous != full:
            self.binFull.emit(display)

    # ==================== SESSION ====================

    def _start_session(self) -> None:
        self._session_id = uuid.uuid4().hex
        self._operation_active = True
        self._session_stage = "basket_precheck"
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "SESSION_START"
        })
        self._log_session_event(direction="STATE", event_name="session_started")
        self.logger.info(f"Session started: {self._session_id}")

    def _end_session(self) -> None:
        if self._session_id is None:
            return
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "SESSION_END"
        })
        self._log_session_event(direction="STATE", event_name="session_ended")
        self.logger.info(f"Session ended: {self._session_id}")
        self._session_id = None
        self._operation_active = False
        self._session_stage = "connected" if self.port.isOpen() else "disconnected"

    # ==================== CREDENTIALS TIMEOUT ====================

    def _on_credentials_timeout(self) -> None:
        self.logger.warning("Credentials timeout - cancelling operation")
        self.cancelOperation()

    @Slot()
    def startCredentialsTimeout(self) -> None:
        self._credentials_timeout_timer.start()
        self.logger.info("Credentials timeout started (20s)")

    @Slot()
    def stopCredentialsTimeout(self) -> None:
        self._credentials_timeout_timer.stop()
        self.logger.info("Credentials timeout stopped")

    # ==================== FRAUD HOLD (NEW) ====================

    @Slot(bool)
    def setFraudHold(self, enabled: bool) -> None:
        """
        Call this from your ML/QML layer:
          - enabled=True when ML predicts HAND (fraud prevention)
          - enabled=False when hand is removed / next frame is clean
        This is intentionally separate from physical gate obstruction.
        """
        self._fraud_hold = bool(enabled)
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "FRAUD_HOLD",
            "enabled": self._fraud_hold,
        })
        self.logger.info(f"Fraud hold set to {self._fraud_hold}")
        self._update_fraud_state()

    @Slot(result=bool)
    def isFraudHold(self) -> bool:
        return self._fraud_hold

    @Slot(str)
    def recordMlPrediction(self, prediction: str) -> None:
        normalized = str(prediction or "").strip().lower()
        self._current_prediction = normalized
        self._current_prediction_confidence = 1.0 if normalized else 0.0
        self._last_prediction_ts = time.time() if normalized else 0.0
        if normalized and normalized != "hand":
            self._mark_first_item_after_gate_open_seen()
            self._restart_session_idle_timer()
        self._log_session_event(direction="INFER", event_name="ml_prediction", payload_summary=normalized)
        self._update_fraud_state()

    def _refresh_pending_timeout(self) -> None:
        if not self._pending_requests:
            self._command_timeout_timer.stop()
            return

        oldest = self._pending_requests[0]
        remaining_ms = max(1, int((oldest["deadline"] - time.time()) * 1000))
        self._command_timeout_timer.start(remaining_ms)

    def _queue_request_if_needed(self, cmd: int, payload: bytes) -> None:
        expected: tuple[int, ...] = ()
        timeout_s = 0.0
        if cmd == int(mcu.SystemControl.PING):
            expected = (int(mcu.ResponseCode.ACK),)
            timeout_s = 2.5
        elif cmd == int(mcu.SystemControl.GET_MCU_STATUS):
            expected = (int(mcu.ResponseCode.DATA),)
            timeout_s = 2.5
        elif cmd == int(mcu.ReadCommand.POLL_WEIGHT):
            expected = (int(mcu.ResponseCode.DATA),)
            timeout_s = 2.5
        elif cmd == int(mcu.ReadCommand.READ_SENSOR):
            expected = (int(mcu.ResponseCode.DATA),)
            timeout_s = 2.5
        elif cmd == int(mcu.SessionControl.REQUEST_SEQUENCE_STATUS):
            expected = (int(mcu.AsyncEvent.STATUS_OK),)
            timeout_s = 3.0
        elif cmd == int(mcu.SessionControl.ACCEPT_ITEM):
            if CONSIDER_ITEM_DROPPED:
                expected = (int(mcu.AsyncEvent.ITEM_DROPPED),)
                timeout_s = 5.0
        elif cmd == int(mcu.SessionControl.END_SESSION):
            expected = (int(mcu.AsyncEvent.BASKET_STATUS),)
            timeout_s = 5.0

        if not expected:
            return

        self._pending_requests.append({
            "cmd": int(cmd),
            "payload": bytes(payload),
            "expected": expected,
            "sent_at": time.time(),
            "deadline": time.time() + timeout_s,
            "stage": self._session_stage,
        })
        self._refresh_pending_timeout()

    def _pending_matches_response(self, pending: dict, response_cmd: int, payload: bytes = b"") -> bool:
        if int(response_cmd) not in pending["expected"]:
            return False

        pending_cmd = int(pending["cmd"])
        pending_payload = bytes(pending.get("payload", b""))

        if int(response_cmd) != int(mcu.ResponseCode.DATA):
            return True

        if pending_cmd == int(mcu.ReadCommand.READ_SENSOR):
            if len(payload) < 2 or not pending_payload:
                return False
            return payload[0] == pending_payload[0]

        if pending_cmd == int(mcu.ReadCommand.POLL_WEIGHT):
            return len(payload) >= 4

        if pending_cmd == int(mcu.SystemControl.GET_MCU_STATUS):
            return len(payload) >= 1

        return True

    def _pop_pending_for_response(self, response_cmd: int, payload: bytes = b"") -> dict | None:
        for _ in range(len(self._pending_requests)):
            pending = self._pending_requests.popleft()
            if self._pending_matches_response(pending, response_cmd, payload):
                self._refresh_pending_timeout()
                return pending
            self._pending_requests.append(pending)
        self._refresh_pending_timeout()
        return None

    def _pop_oldest_pending(self) -> dict | None:
        if not self._pending_requests:
            self._refresh_pending_timeout()
            return None
        pending = self._pending_requests.popleft()
        self._refresh_pending_timeout()
        return pending

    def _drop_pending_requests(
        self,
        *,
        cmd: int | None = None,
        sensor_ids: set[int] | None = None,
    ) -> int:
        kept: deque[dict] = deque()
        removed = 0
        for pending in self._pending_requests:
            drop = False
            if cmd is not None and int(pending["cmd"]) == int(cmd):
                if sensor_ids is None:
                    drop = True
                else:
                    payload = bytes(pending.get("payload", b""))
                    drop = bool(payload) and payload[0] in sensor_ids
            if drop:
                removed += 1
                continue
            kept.append(pending)
        self._pending_requests = kept
        self._refresh_pending_timeout()
        return removed

    def _restart_session_idle_timer(self) -> None:
        if self._session_stage in {"active", "await_item_drop", "await_reject_done"}:
            if self._session_stage == "active" and self._awaiting_first_item_after_gate_open:
                return
            self._session_idle_timer.start()

    def _mark_first_item_after_gate_open_seen(self) -> None:
        if not self._awaiting_first_item_after_gate_open:
            return
        self._awaiting_first_item_after_gate_open = False
        self._log_session_event(direction="STATE", event_name="first_item_after_gate_open")
        self._restart_session_idle_timer()

    def _is_detection_stage(self) -> bool:
        return self._session_stage in {"await_gate_open", "active", "await_item_drop", "await_reject_done"}

    def _is_hand_blocked(self) -> bool:
        return self._gate_blocked or self._fraud_hold

    def _log_immediate_fraud(self, note: str) -> None:
        if self._fraud_logged_for_block:
            return
        self._fraud_logged_for_block = True
        self._log_session_event(direction="FRAUD", event_name="fraud_attempt", note=note)

    def _has_item_evidence(self) -> bool:
        has_prediction = self._current_prediction in {"plastic", "aluminum", "other"}
        has_weight = (
            CONSIDER_WEIGHT
            and self._last_weight_grams is not None
            and self._last_weight_grams >= MIN_ITEM_WEIGHT_GRAMS
        )
        return has_prediction or has_weight

    def _update_fraud_state(self) -> None:
        should_track = (
            self._session_stage == "active"
            and self._gate_blocked
            and self._has_item_evidence()
        )
        if should_track:
            if not self._fraud_timer.isActive() and not self._fraud_active:
                self._fraud_timer.start()
                self._log_session_event(direction="STATE", event_name="fraud_timer_started")
            return

        if self._fraud_timer.isActive():
            self._fraud_timer.stop()
            self._log_session_event(direction="STATE", event_name="fraud_timer_cleared")
        if self._fraud_active:
            self._fraud_active = False
            self._log_session_event(direction="STATE", event_name="fraud_cleared")
        if not self._is_hand_blocked():
            self._fraud_logged_for_block = False

    def _on_fraud_timeout(self) -> None:
        if not (self._session_stage == "active" and self._gate_blocked and self._has_item_evidence()):
            return
        self._fraud_active = True
        self._log_session_event(direction="FRAUD", event_name="fraud_attempt", note="hand_block_plus_item_evidence_2s")
        self.handInGate.emit()

    def _clear_item_evidence(self) -> None:
        self._current_prediction = ""
        self._current_prediction_confidence = 0.0
        self._last_prediction_ts = 0.0
        self._last_weight_grams = 0
        self._reject_clear_polls = 0
        self._update_fraud_state()

    def _complete_reject_sequence(self) -> None:
        if self._session_stage != "await_reject_done":
            return
        self._log_session_event(direction="STATE", event_name="reject_complete_inferred")
        self._session_stage = "active"
        self._clear_item_evidence()
        self._restart_session_idle_timer()
        self.rejectDone.emit()
        self.rejectHomeOk.emit()
        self.itemRejected.emit()

    def _start_exit_gate_verification(self, item_type: str) -> None:
        if not CONSIDER_EXIT_GATE:
            self._pending_exit_verification = None
            self._exit_gate_timeout_timer.stop()
            self._log_session_event(direction="STATE", event_name="exit_gate_verification_skipped", note=str(item_type))
            self._clear_item_evidence()
            return
        self._pending_exit_verification = {
            "item_type": str(item_type),
            "started_at": time.time(),
        }
        self._exit_gate_timeout_timer.start()
        self._log_session_event(direction="STATE", event_name="exit_gate_verification_started", note=str(item_type))

    def _confirm_exit_gate_passed(self) -> None:
        if self._pending_exit_verification is None:
            return
        item_type = self._pending_exit_verification["item_type"]
        self._pending_exit_verification = None
        self._exit_gate_timeout_timer.stop()
        self._log_session_event(direction="STATE", event_name="exit_gate_passed", note=str(item_type))
        self._clear_item_evidence()

    def _on_exit_gate_timeout(self) -> None:
        if self._pending_exit_verification is None:
            return
        item_type = str(self._pending_exit_verification["item_type"])
        self._pending_exit_verification = None
        self._log_session_event(direction="FRAUD", event_name="fraud_attempt", note=f"exit_gate_not_reached:{item_type}")
        self.acceptedItemRollback.emit(item_type)
        self._clear_item_evidence()

    def _poll_runtime_sensors(self) -> None:
        if not self.port.isOpen():
            return
        if self._session_stage == "await_gate_open":
            self.readSensor(int(mcu.SensorSelector.GATE_OPENED))
            self.readSensor(int(mcu.SensorSelector.GATE_CLOSED))
            self.readSensor(int(mcu.SensorSelector.GATE_ALARM))
            if self._gate_open_deadline and time.time() > self._gate_open_deadline:
                self.logger.error("Gate open confirmation timed out")
                self._log_session_event(direction="STATE", event_name="gate_open_timeout")
                self.newUserFailed.emit()
                self.errorOccurred.emit("GATE_OPEN_TIMEOUT", 0)
                # Graceful cleanup: send END_SESSION so the MCU can reset the gate,
                # instead of _handle_disconnect() which drops the serial connection.
                self._request_forced_end_session()
            return

        if self._session_stage == "await_gate_close":
            self.readSensor(int(mcu.SensorSelector.GATE_CLOSED))
            self.readSensor(int(mcu.SensorSelector.GATE_ALARM))
            if self._gate_close_deadline and time.time() > self._gate_close_deadline:
                self.logger.error("Gate close confirmation timed out")
                self._log_session_event(direction="STATE", event_name="gate_close_timeout")
                self.errorOccurred.emit("GATE_CLOSE_TIMEOUT", 0)
                # Graceful cleanup: stop polling and end session locally.
                # The MCU is still reachable; don't drop the connection.
                self._sensor_poll_timer.stop()
                self._session_idle_timer.stop()
                self._gate_close_deadline = 0.0
                self._end_session()
            return

        if self._session_stage not in {"active", "await_item_drop", "await_reject_done"}:
            return

        if self._session_stage == "await_reject_done":
            sensor_rounds = [
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.REJECT_HOME)),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.GATE_ALARM)),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.DROP_SENSOR)),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.EXIT_GATE)),
                (mcu.ReadCommand.POLL_WEIGHT, None),
            ]
        else:
            sensor_rounds = [
                (mcu.ReadCommand.POLL_WEIGHT, None),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.GATE_ALARM)),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.DROP_SENSOR)),
                (mcu.ReadCommand.READ_SENSOR, int(mcu.SensorSelector.EXIT_GATE)),
            ]
        cmd, payload = sensor_rounds[self._poll_cursor % len(sensor_rounds)]
        self._poll_cursor += 1
        if payload is None:
            self.pollWeight()
        else:
            self.readSensor(payload)

    def _begin_basket_precheck(self) -> bool:
        if not self.port.isOpen():
            self.newUserFailed.emit()
            return False
        if self._session_id is None:
            self._start_session()
        if not self._check_baskets_enabled:
            self._session_stage = "basket_precheck"
            self._basket_precheck_pending.clear()
            self._apply_basket_state("Plastic", False, emit_event=True, source="testing_mode")
            self._apply_basket_state("Can", False, emit_event=True, source="testing_mode")
            self._log_session_event(direction="STATE", event_name="basket_precheck_skipped", note="DROPME_CHECK_BASKETS=0")
            self._start_session_command()
            return True
        self._session_stage = "basket_precheck"
        self._basket_precheck_pending = {
            int(mcu.SensorSelector.BASKET_1),
            int(mcu.SensorSelector.BASKET_2),
            int(mcu.SensorSelector.BASKET_3),
        }
        self._log_session_event(direction="STATE", event_name="basket_precheck_started")
        self._refresh_basket_state_from_mcu()
        return True

    def _start_session_command(self) -> None:
        if not self._send(mcu.SessionControl.START_SESSION):
            self.newUserFailed.emit()
            return
        self._session_stage = "await_gate_open"
        self._gate_open_deadline = time.time() + 25.0
        self._sensor_poll_timer.start()
        self._log_session_event(direction="STATE", event_name="start_session_sent")

    def _handle_gate_open_confirmed(self) -> None:
        if self._session_stage != "await_gate_open":
            return
        self._drop_pending_requests(
            cmd=int(mcu.ReadCommand.READ_SENSOR),
            sensor_ids={
                int(mcu.SensorSelector.GATE_OPENED),
                int(mcu.SensorSelector.GATE_CLOSED),
                int(mcu.SensorSelector.GATE_ALARM),
            },
        )
        self._session_stage = "active"
        self._gate_open_deadline = 0.0
        self._awaiting_first_item_after_gate_open = True
        self._log_session_event(direction="STATE", event_name="gate_open_confirmed")
        self.ready.emit()

    def _promote_to_active_from_item_placed(self, weight_mg: int) -> None:
        if self._session_stage != "await_gate_open":
            return
        self._drop_pending_requests(
            cmd=int(mcu.ReadCommand.READ_SENSOR),
            sensor_ids={
                int(mcu.SensorSelector.GATE_OPENED),
                int(mcu.SensorSelector.GATE_CLOSED),
                int(mcu.SensorSelector.GATE_ALARM),
            },
        )
        # Some MCU/fixture combinations deliver ITEM_PLACED before the gate-open
        # sensor flips. Treat that item event as sufficient evidence to continue.
        self._session_stage = "active"
        self._gate_open_deadline = 0.0
        self._restart_session_idle_timer()
        self._log_session_event(
            direction="STATE",
            event_name="gate_open_inferred_from_item_placed",
            note=f"{weight_mg}mg",
        )
        self.ready.emit()

    def _handle_gate_close_confirmed(self) -> None:
        if self._session_stage != "await_gate_close":
            return
        self._drop_pending_requests(
            cmd=int(mcu.ReadCommand.READ_SENSOR),
            sensor_ids={
                int(mcu.SensorSelector.GATE_CLOSED),
                int(mcu.SensorSelector.GATE_ALARM),
                int(mcu.SensorSelector.BASKET_1),
                int(mcu.SensorSelector.BASKET_2),
                int(mcu.SensorSelector.BASKET_3),
            },
        )
        self._session_stage = "connected"
        self._gate_close_deadline = 0.0
        self._sensor_poll_timer.stop()
        self._session_idle_timer.stop()
        self._log_session_event(direction="STATE", event_name="gate_close_confirmed")
        self._end_session()

    def _request_end_session(self) -> None:
        if self._session_stage not in {"active", "await_item_drop", "await_reject_done"}:
            return
        self._session_stage = "await_gate_close"
        self._session_idle_timer.stop()
        self._sensor_poll_timer.start()
        self._fraud_timer.stop()
        self._fraud_active = False
        self._reject_clear_polls = 0
        self._gate_close_deadline = time.time() + 20.0
        self._log_session_event(direction="STATE", event_name="end_session_requested")
        self._send(mcu.SessionControl.END_SESSION)

    def _on_session_idle_timeout(self) -> None:
        if self._session_stage != "active":
            return
        if self._awaiting_first_item_after_gate_open:
            return
        if self._gate_blocked or self._has_item_evidence():
            self._restart_session_idle_timer()
            return
        self._request_end_session()

    # ==================== RX ====================

    def _read_data(self) -> None:
        self.rx_buffer.extend(self.port.readAll().data())

        while self.rx_buffer:
            frame, consumed = mcu.Frame.try_parse_from_buffer(self.rx_buffer)
            if consumed == 0:
                break

            frame_bytes = bytes(self.rx_buffer[:consumed])
            del self.rx_buffer[:consumed]

            if frame:
                self._handle_frame(frame, frame_bytes)
            else:
                self.logger.warning(f"Invalid frame: {frame_bytes.hex(' ')}")
                crc_valid = mcu.validate_frame_bytes(frame_bytes)
                self._append_protocol_event({
                    "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "direction": "RX_INVALID",
                    "raw": frame_bytes.hex(" "),
                    "crc_valid": crc_valid,
                    "reason": "crc_invalid" if not crc_valid else "malformed",
                })
                self._log_session_event(
                    direction="RX",
                    event_name="crc_invalid" if not crc_valid else "malformed_frame",
                    raw_hex=frame_bytes.hex(" "),
                    crc_valid=crc_valid,
                )

    def _apply_sensor_state(self, sensor_id: int, sensor_state: int, *, source: str = "mcu") -> None:
        if sensor_id == int(mcu.SensorSelector.GATE_CLOSED):
            self._sensor_states["gate_closed"] = int(sensor_state)
            if sensor_state:
                self._gate_open = False
                self.gateClosed.emit()
                self._handle_gate_close_confirmed()
            return

        if sensor_id == int(mcu.SensorSelector.GATE_OPENED):
            self._gate_open = bool(sensor_state)
            self._sensor_states["gate_opened"] = int(sensor_state)
            if sensor_state:
                self.gateOpened.emit()
                self._handle_gate_open_confirmed()
            return

        if sensor_id == int(mcu.SensorSelector.GATE_ALARM):
            was_blocked = self._gate_blocked
            self._gate_blocked = bool(sensor_state)
            self._sensor_states["gate_alarm"] = int(sensor_state)
            if self._gate_blocked:
                self.gateBlocked.emit()
                self.handInGate.emit()
                if self._session_stage == "await_gate_close":
                    self._gate_close_deadline = max(self._gate_close_deadline, time.time() + 20.0)
                elif self._is_detection_stage():
                    self._log_immediate_fraud("hand_detected_by_gate_alarm_during_session")
            elif was_blocked:
                if self._session_stage == "await_gate_close":
                    self._gate_close_deadline = time.time() + 20.0
                    self._send(mcu.SessionControl.END_SESSION)
                if self._gate_open:
                    self.gateOpened.emit()
                else:
                    self.gateClosed.emit()
            self._update_fraud_state()
            return

        if sensor_id == int(mcu.SensorSelector.EXIT_GATE):
            self._sensor_states["exit_gate"] = int(sensor_state)
            if sensor_state:
                self._confirm_exit_gate_passed()
            return

        if sensor_id == int(mcu.SensorSelector.DROP_SENSOR):
            self._sensor_states["drop_sensor"] = int(sensor_state)
            return

        if sensor_id == int(mcu.SensorSelector.BASKET_1):
            self._apply_basket_state("Plastic", bool(sensor_state), emit_event=True, source=source)
            return

        if sensor_id == int(mcu.SensorSelector.BASKET_2):
            self._apply_basket_state("Can", bool(sensor_state), emit_event=True, source=source)
            return

        if sensor_id == int(mcu.SensorSelector.BASKET_3):
            self._apply_basket_state("Reject", bool(sensor_state), emit_event=True, source=source)
            return

    def _handle_data_response(self, payload: bytes) -> None:
        pending = self._pop_pending_for_response(int(mcu.ResponseCode.DATA), payload)
        if pending is None:
            self.logger.warning(f"DATA response received with no matching pending request: {payload.hex(' ')}")
            self._log_session_event(
                direction="RX",
                event_name="unexpected_rx",
                payload_summary=payload.hex(" "),
                note="data_without_pending_request",
            )
            return

        request_cmd = pending["cmd"]
        request_payload = pending["payload"]
        if request_cmd == int(mcu.SystemControl.GET_MCU_STATUS):
            status_byte = payload[0] if payload else 0
            self.doorStatusReceived.emit(status_byte)
            self._append_sensor_event("MCU_STATUS", status_byte)
            self.logger.info(f"MCU status byte: 0x{status_byte:02X}")
            return

        if request_cmd == int(mcu.ReadCommand.POLL_WEIGHT):
            weight_mg = int.from_bytes(payload[:4].ljust(4, b"\x00"), "little", signed=True)
            weight_grams = int(round(weight_mg / 1000.0))
            self._last_weight_grams = weight_grams
            self._log_weight(weight_grams)
            self.weightReceived.emit(weight_grams)
            self._append_sensor_event("WEIGHT_DATA", weight_grams, {"milligrams": weight_mg})
            if CONSIDER_WEIGHT and weight_grams >= MIN_ITEM_WEIGHT_GRAMS:
                self._restart_session_idle_timer()
            self._update_fraud_state()
            self.logger.info(f"Weight response: {weight_mg} mg ({weight_grams} g)")
            return

        sensor_id = request_payload[0] if request_payload else (payload[0] if payload else 0)
        sensor_state = payload[1] if len(payload) > 1 else 0
        sensor_name = mcu.get_payload_description(mcu.ReadCommand.READ_SENSOR, bytes([sensor_id]))
        self._apply_sensor_state(sensor_id, sensor_state, source="mcu")
        self._append_sensor_event("SENSOR_DATA", sensor_state, {"sensor_id": sensor_id, "sensor_name": sensor_name})
        self.logger.info(f"Sensor {sensor_name}: {sensor_state}")

        if sensor_id == int(mcu.SensorSelector.REJECT_HOME) and self._session_stage == "await_reject_done":
            if sensor_state:
                self._log_session_event(direction="STATE", event_name="reject_home_detected")
                self._complete_reject_sequence()
            else:
                self._reject_clear_polls = 0

        if sensor_id in self._basket_precheck_pending:
            self._basket_precheck_pending.discard(sensor_id)
            if not self._basket_precheck_pending and self._session_stage == "basket_precheck":
                self._log_session_event(direction="STATE", event_name="basket_precheck_complete")
                self._start_session_command()

    def _handle_basket_status(self, payload: bytes) -> None:
        pending = self._pop_pending_for_response(int(mcu.AsyncEvent.BASKET_STATUS))
        if pending is None:
            self.logger.info("Received basket status without a tracked END_SESSION request")
            self._log_session_event(direction="RX", event_name="unexpected_rx", payload_summary=payload.hex(" "), note="basket_status_without_pending_end_session")
        self._append_sensor_event("BASKET_STATUS", 0, {"raw_hex": payload.hex(" ")})
        if payload:
            mask = payload[0]
            self._apply_basket_state("Plastic", bool(mask & 0x01), emit_event=True, source="mcu_mask")
            self._apply_basket_state("Can", bool(mask & 0x02), emit_event=True, source="mcu_mask")
            self._apply_basket_state("Reject", bool(mask & 0x04), emit_event=True, source="mcu_mask")
        self.readSensor(int(mcu.SensorSelector.GATE_CLOSED))
        self._refresh_basket_state_from_mcu()

    def _handle_frame(self, frame: mcu.Frame, raw: bytes) -> None:
        self.last_response_time = time.time()

        cmd = frame.cmd
        cmd_name = mcu.get_command_name(cmd)
        payload_value = frame.payload_int

        self.logger.debug(f"RX: {cmd_name} PL={mcu.get_payload_description(cmd, frame.payload)} STAGE={self._session_stage}")

        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "RX",
            "cmd": cmd_name,
            "payload": payload_value,
            "payload_hex": frame.payload.hex(" "),
            "state": self._session_stage,
            "raw": raw.hex(" ")
        })
        self._log_session_event(
            direction="RX",
            event_name=cmd_name,
            raw_hex=raw.hex(" "),
            crc_valid=True,
            payload_summary=mcu.get_payload_description(cmd, frame.payload),
        )
        self._reduce_protocol_state("RX", frame, raw)

        if cmd == mcu.ResponseCode.ACK:
            pending = self._pop_pending_for_response(int(mcu.ResponseCode.ACK))
            if frame.payload == b"OK":
                self.logger.info("ACK OK received")
            elif pending is None:
                self._log_session_event(direction="RX", event_name="unexpected_rx", payload_summary=frame.payload.hex(" "), note="ack_without_pending_request")
            return

        if cmd == mcu.ResponseCode.NACK:
            pending = self._pop_oldest_pending()
            self._last_error = "NACK"
            self.errorOccurred.emit("NACK", payload_value)
            self._append_sensor_event("NACK", payload_value, {"raw_hex": frame.payload.hex(" ")})
            pending_desc = "none"
            if pending is not None:
                pending_cmd = int(pending["cmd"])
                pending_payload = bytes(pending.get("payload", b""))
                pending_cmd_name = mcu.get_command_name(pending_cmd)
                pending_payload_desc = mcu.get_payload_description(pending_cmd, pending_payload)
                pending_desc = f"{pending_cmd_name}({pending_payload_desc})"
            self._log_session_event(
                direction="RX",
                event_name="NACK",
                raw_hex=raw.hex(" "),
                crc_valid=True,
                payload_summary=frame.payload.hex(" "),
                note=f"rejected_pending={pending_desc}",
            )
            self.logger.error(
                f"NACK received: {frame.payload.hex(' ')}; rejected pending request: {pending_desc}"
            )
            return

        if cmd == mcu.ResponseCode.DATA:
            self._handle_data_response(frame.payload)
            return

        if cmd == mcu.ResponseCode.ERROR:
            pending = self._pop_oldest_pending()
            self._last_error = "MCU_ERROR"
            self.errorOccurred.emit("MCU_ERROR", payload_value)
            self._append_sensor_event("MCU_ERROR", payload_value, {"raw_hex": frame.payload.hex(" ")})
            self._log_session_event(
                direction="RX",
                event_name="ERROR",
                raw_hex=raw.hex(" "),
                crc_valid=True,
                payload_summary=frame.payload.hex(" "),
                note=f"pending={pending['cmd'] if pending else 'none'}",
            )
            self.logger.error(f"MCU error response: {frame.payload.hex(' ')}")
            return

        if cmd == mcu.AsyncEvent.STATUS_OK:
            pending = self._pop_pending_for_response(int(mcu.AsyncEvent.STATUS_OK))
            self._system_busy = False
            self.systemReady.emit()
            if pending is None:
                self._log_session_event(direction="RX", event_name="unexpected_rx", raw_hex=raw.hex(" "), crc_valid=True, note="status_ok_without_pending_request")
            self.logger.info("STATUS_OK event received")
            return

        if cmd == mcu.AsyncEvent.ITEM_PLACED:
            if len(frame.payload) < 4:
                self.logger.warning(f"ITEM_PLACED payload too short: {frame.payload.hex(' ')}")
                self._log_session_event(
                    direction="RX",
                    event_name="unexpected_rx",
                    raw_hex=raw.hex(" "),
                    crc_valid=True,
                    payload_summary=frame.payload.hex(" "),
                    note="item_placed_short_payload",
                )
                return
            weight_mg = int.from_bytes(frame.payload[:4], "little", signed=True)
            weight_grams = int(round(weight_mg / 1000.0))
            if weight_grams < MIN_ITEM_WEIGHT_GRAMS:
                self._last_weight_grams = 0
                self.weightReceived.emit(0)
                self._append_sensor_event(
                    "ITEM_PLACED_IGNORED",
                    weight_grams,
                    {"milligrams": weight_mg, "raw_hex": raw.hex(" "), "reason": f"below_{MIN_ITEM_WEIGHT_GRAMS}g"},
                )
                self._log_session_event(
                    direction="STATE",
                    event_name="item_placed_ignored",
                    note=f"{weight_mg}mg_below_{MIN_ITEM_WEIGHT_GRAMS}g",
                )
                self.logger.info(
                    f"ITEM_PLACED ignored: {weight_mg} mg ({weight_grams} g) is below {MIN_ITEM_WEIGHT_GRAMS} g threshold"
                )
                return
            self._last_weight_grams = weight_grams
            self._log_weight(weight_grams)
            self.weightReceived.emit(weight_grams)
            self._append_sensor_event("ITEM_PLACED", weight_grams, {"milligrams": weight_mg, "raw_hex": raw.hex(" ")})
            if self._session_stage == "await_reject_done":
                self._reject_clear_polls = 0
                self._update_fraud_state()
                self.logger.info(
                    f"ITEM_PLACED observed during reject completion; keeping reject stage ({weight_mg} mg / {weight_grams} g)"
                )
                return
            if self._session_stage == "await_gate_open" and not self._gate_open:
                self._log_session_event(
                    direction="STATE",
                    event_name="item_placed_before_gate_open_ignored",
                    note=f"{weight_mg}mg",
                )
                self.logger.info(
                    f"ITEM_PLACED received before gate-open confirmation; ignoring until gate opens ({weight_mg} mg)"
                )
                return
            self._mark_first_item_after_gate_open_seen()
            self._session_stage = "active"
            self._restart_session_idle_timer()
            self._update_fraud_state()
            self.logger.info(f"ITEM_PLACED event received: {weight_mg} mg ({weight_grams} g)")
            return

        if cmd == mcu.AsyncEvent.ITEM_DROPPED:
            pending = self._pop_pending_for_response(int(mcu.AsyncEvent.ITEM_DROPPED))
            item_type = None
            if pending is not None and pending["payload"]:
                item_type = pending["payload"][0]
            if item_type == int(mcu.ItemType.PLASTIC):
                self.plasticAccepted.emit()
                self._start_exit_gate_verification("plastic")
            elif item_type == int(mcu.ItemType.ALUMINUM):
                self.canAccepted.emit()
                self._start_exit_gate_verification("can")
            self.conveyorDone.emit()
            self._session_stage = "active"
            self._restart_session_idle_timer()
            self.logger.info("ITEM_DROPPED event received")
            return

        if cmd == mcu.AsyncEvent.BASKET_STATUS:
            self._handle_basket_status(frame.payload)
            self.logger.info("BASKET_STATUS event received")
            return

        self.logger.warning(f"Unhandled RX frame for current spec: {raw.hex(' ')}")
        self._log_session_event(direction="RX", event_name="unexpected_rx", raw_hex=raw.hex(" "), crc_valid=True)

    def _on_command_timeout(self) -> None:
        pending = self._pop_oldest_pending()
        self.logger.error(f"COMMAND TIMEOUT in stage: {self._session_stage}")
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "TIMEOUT",
            "state": self._session_stage,
            "note": "MCU did not respond in time"
        })
        if pending:
            pending_payload_desc = mcu.get_payload_description(pending["cmd"], pending["payload"])
            self._log_session_event(
                direction="STATE",
                event_name="command_timeout",
                note=f"cmd=0x{pending['cmd']:02X} payload={pending_payload_desc} stage={pending['stage']}",
            )
            if pending["cmd"] == int(mcu.SystemControl.PING):
                if self._session_stage == "active" and self._awaiting_first_item_after_gate_open:
                    self.logger.warning(
                        "Ping timeout during fresh active session before first item; keeping session alive"
                    )
                    return
                if self._session_stage in {"active", "await_item_drop", "await_gate_open", "await_gate_close"}:
                    self.logger.warning(
                        f"Ping timeout during {self._session_stage}; requesting clean end-session instead of dropping the connection"
                    )
                    self._request_forced_end_session()
                    return
                self._handle_disconnect()
                return
            if pending["cmd"] in {
                int(mcu.ReadCommand.READ_SENSOR),
                int(mcu.ReadCommand.POLL_WEIGHT),
            } and self._session_stage in {"active", "await_gate_open", "await_gate_close", "await_reject_done"}:
                self.logger.warning(
                    f"Soft timeout for 0x{pending['cmd']:02X} ({pending_payload_desc}) in stage {self._session_stage}; keeping session alive"
                )
                return
            elif pending["cmd"] == int(mcu.SessionControl.ACCEPT_ITEM):
                self._session_stage = "active"
            elif pending["cmd"] == int(mcu.SessionControl.END_SESSION):
                self.errorOccurred.emit("END_SESSION_TIMEOUT", 0)
        self.errorOccurred.emit("COMMAND_TIMEOUT", 0)

    # ==================== TX ====================

    def _send(self, cmd: int, payload: int | bytes = b"") -> bool:
        if not self.port.isOpen():
            self.logger.warning("Cannot send - not connected")
            return False

        frame, raw, written = self._stm_interface.write_command(self.port, self.seq_manager.next(), cmd, payload)

        cmd_name = mcu.get_command_name(cmd)
        payload_value = mcu.payload_to_int(frame.payload)
        self.logger.debug(f"TX: {cmd_name} PL={mcu.get_payload_description(cmd, frame.payload)}")

        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "TX",
            "cmd": cmd_name,
            "payload": payload_value,
            "payload_hex": frame.payload.hex(" "),
            "state": self._session_stage,
            "raw": raw.hex(" ")
        })
        self._log_session_event(
            direction="TX",
            event_name=cmd_name,
            raw_hex=raw.hex(" "),
            payload_summary=mcu.get_payload_description(cmd, frame.payload),
        )
        self.commandSent.emit(cmd_name, payload_value)
        self._reduce_protocol_state("TX", frame, raw)
        self._queue_request_if_needed(cmd, frame.payload)

        return written == len(raw)

    # ==================== STATE QUERIES ====================

    @Slot(result=bool)
    def isGateBlocked(self) -> bool:
        return self._gate_blocked

    @Slot(result=bool)
    def isGateOpen(self) -> bool:
        return self._gate_open

    @Slot(result=bool)
    def isConnected(self) -> bool:
        if self._dev_mode:
            # In dev mode we never open a real port; report "connected" whenever
            # a session is active so the watchdog doesn't fire.
            return self._session_stage not in {"disconnected"}
        return self.port.isOpen()

    @Slot(result=bool)
    def isStartupSettling(self) -> bool:
        if self._dev_mode:
            # In dev mode we never connect to a port, so tell the watchdog we're
            # always settling — suppressing SERIAL_DISCONNECTED_TIMEOUT forever.
            return True
        return (not self.port.isOpen()) and ((time.monotonic() - self._startup_scan_started_at) < 45.0)

    @Slot(result=str)
    def getPortName(self) -> str:
        return self.connected_port_name or ""

    @Slot(result=bool)
    def isProcessing(self) -> bool:
        return self._session_stage not in {"connected", "disconnected"}

    @Slot()
    def clearGateBlocked(self) -> None:
        self._apply_sensor_state(int(mcu.SensorSelector.GATE_ALARM), 0, source="manual")
        self.logger.info("Gate blocked cleared")

    # ==================== SYSTEM CONTROL ====================

    @Slot()
    def initSystem(self) -> None:
        self.requestSequenceStatus()

    @Slot()
    def resetSystem(self) -> None:
        self._reset_state()
        self._send(mcu.SystemControl.SYSTEM_RESET)

    @Slot()
    def pingSystem(self) -> None:
        self._send(mcu.SystemControl.PING)

    @Slot()
    def stopAll(self) -> None:
        self.logger.warning("stopAll() has no direct command in the new MCU protocol; sending SYSTEM_RESET as a compatibility fallback")
        self._send(mcu.SystemControl.SYSTEM_RESET)

    # ==================== OPERATION CONTROL ====================

    @Slot()
    def startOperation(self) -> None:
        if self._session_stage not in {"connected", "disconnected"}:
            self.logger.info(f"Ignoring startOperation while session stage is {self._session_stage}")
            self._log_session_event(direction="STATE", event_name="start_ignored", note=f"stage={self._session_stage}")
            return
        self.logger.info("Starting operation")
        self._begin_basket_precheck()

    @Slot()
    def cancelOperation(self) -> None:
        self.logger.info("Cancelling operation (no dedicated cancel command in new MCU protocol)")
        self._credentials_timeout_timer.stop()
        self._session_idle_timer.stop()
        self._sensor_poll_timer.stop()
        self._end_session()
        QTimer.singleShot(0, self.resetSystem)

    @Slot()
    def endOperation(self) -> None:
        self.logger.info("Ending operation")
        self._credentials_timeout_timer.stop()
        if self._session_stage in {"active", "await_item_drop", "await_reject_done"}:
            self._request_end_session()
            return
        if self._session_stage in {"basket_precheck", "await_gate_open"}:
            self._request_forced_end_session()
            return
        if self._session_stage == "await_gate_close":
            return
        self._sensor_poll_timer.stop()
        self._session_idle_timer.stop()
        self._end_session()

    # ==================== GATE CONTROL ====================

    @Slot()
    def openGate(self) -> None:
        self._credentials_timeout_timer.stop()
        self.logger.info("openGate() maps to START_SESSION in the new MCU protocol")
        self._start_session_command()

    @Slot()
    def closeGate(self) -> None:
        self.logger.info("closeGate() maps to END_SESSION in the new MCU protocol")
        self._request_forced_end_session()

    # ==================== ITEM PROCESSING (SEQUENCED) ====================

    def _blocked_by_fraud_or_gate(self, reason: str) -> bool:
        """
        This implements your requirement:
        - physical gate obstruction blocks motion
        - fraud hold (ML hand) blocks motion
        """
        if self._fraud_hold:
            self.logger.warning(f"FRAUD PREVENTION: {reason} - hand detected (fraud hold)!")
            # Do NOT emit gateBlocked here (different concept).
            return True
        if self._gate_blocked:
            self.logger.warning(f"Cannot {reason} - gate physically blocked!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)
            return True
        return False

    @Slot(result=bool)
    def isDetectionAllowed(self) -> bool:
        return self._session_stage == "active" and not self._is_hand_blocked()

    @Slot(bool)
    def devSetGateAlarmBlocked(self, blocked: bool) -> None:
        if not self._allow_local_sensor_override:
            self.logger.warning("Local sensor override is disabled; use the MCU simulator for parity testing or set DROPME_DEV_LOCAL_SENSOR_OVERRIDE=1 for non-parity shortcuts")
            return
        if not self.port.isOpen():
            return
        self._append_sensor_event("DEV_GATE_ALARM", int(bool(blocked)), {"source": "dev"})
        self._apply_sensor_state(int(mcu.SensorSelector.GATE_ALARM), int(bool(blocked)), source="dev")

    @Slot(bool)
    def devSetExitGatePassed(self, passed: bool) -> None:
        if not self._allow_local_sensor_override:
            self.logger.warning("Local sensor override is disabled; use the MCU simulator for parity testing or set DROPME_DEV_LOCAL_SENSOR_OVERRIDE=1 for non-parity shortcuts")
            return
        if not self.port.isOpen():
            return
        self._append_sensor_event("DEV_EXIT_GATE", int(bool(passed)), {"source": "dev"})
        self._apply_sensor_state(int(mcu.SensorSelector.EXIT_GATE), int(bool(passed)), source="dev")

    def _start_accept_sequence(self, item_type: str) -> bool:
        if self._fraud_hold:
            self.logger.warning(f"FRAUD PREVENTION: accept {item_type} - hand detected (fraud hold)!")
            return False

        if self._gate_blocked:
            self.logger.warning(f"Cannot accept {item_type} - gate physically blocked!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)
            return False

        if self._check_baskets_enabled and item_type == "plastic" and self._bin_plastic_full:
            self.logger.warning("Cannot accept plastic - basket is full")
            self._log_session_event(direction="STATE", event_name="accept_blocked", note="plastic_bin_full")
            return False
        if self._check_baskets_enabled and item_type == "can" and self._bin_can_full:
            self.logger.warning("Cannot accept can - basket is full")
            self._log_session_event(direction="STATE", event_name="accept_blocked", note="can_bin_full")
            return False

        self.logger.info(f"Starting accept sequence for {item_type}")
        payload = mcu.ItemType.PLASTIC if item_type == "plastic" else mcu.ItemType.ALUMINUM
        if CONSIDER_ITEM_DROPPED:
            self._session_stage = "await_item_drop"
            return self._send(mcu.SessionControl.ACCEPT_ITEM, payload)

        ok = self._send(mcu.SessionControl.ACCEPT_ITEM, payload)
        if ok:
            self._session_stage = "active"
            if item_type == "plastic":
                self.plasticAccepted.emit()
                self._start_exit_gate_verification("plastic")
            else:
                self.canAccepted.emit()
                self._start_exit_gate_verification("can")
            self.conveyorDone.emit()
            self._restart_session_idle_timer()
            self._log_session_event(direction="STATE", event_name="accept_completed_without_item_dropped", note=item_type)
        return ok

    def _start_reject_sequence(self) -> bool:
        if self._fraud_hold:
            self.logger.warning("FRAUD PREVENTION: reject item - hand detected (fraud hold)!")
            return False

        if self._gate_blocked:
            self.logger.warning("Cannot reject item - gate physically blocked!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)
            return False

        self.logger.info("Starting reject sequence")
        ok = self._send(mcu.SessionControl.REJECT_ITEM, b"\x01")
        if ok:
            self._log_session_event(direction="STATE", event_name="reject_sent", note="completion_not_blocking_next_item")
            self._session_stage = "active"
            self._clear_item_evidence()
            self._restart_session_idle_timer()
            self.rejectDone.emit()
            self.rejectHomeOk.emit()
            self.itemRejected.emit()
        else:
            self._session_stage = "active"
        return ok

    # ==================== High-level QML methods ====================

    @Slot()
    def sendNewUser(self) -> None:
        if not self.port.isOpen():
            if self._dev_mode:
                self._dev_sim_start_session()
                return
            self.newUserFailed.emit()
            return
        self.startOperation()

    @Slot()
    def sendPlastic(self) -> None:
        if self._dev_mode and not self.port.isOpen():
            self._dev_sim_accept("plastic")
            return
        self._start_accept_sequence("plastic")

    @Slot()
    def sendCan(self) -> None:
        if self._dev_mode and not self.port.isOpen():
            self._dev_sim_accept("can")
            return
        self._start_accept_sequence("can")

    @Slot()
    def sendOther(self) -> None:
        if self._dev_mode and not self.port.isOpen():
            self._dev_sim_reject()
            return
        self._start_reject_sequence()

    @Slot()
    def sendSignOut(self) -> None:
        if self._dev_mode and not self.port.isOpen():
            self._dev_sim_end_session()
            return
        self.endOperation()

    def _request_forced_end_session(self) -> None:
        if not self.port.isOpen():
            self._sensor_poll_timer.stop()
            self._session_idle_timer.stop()
            self._end_session()
            return
        self._session_stage = "await_gate_close"
        self._session_idle_timer.stop()
        self._sensor_poll_timer.start()
        self._fraud_timer.stop()
        self._fraud_active = False
        self._gate_close_deadline = time.time() + 20.0
        self._log_session_event(direction="STATE", event_name="forced_end_session_requested")
        self._send(mcu.SessionControl.END_SESSION)

    @Slot()
    def sendOpenDoor(self) -> None:
        self.openGate()

    @Slot()
    def closeDoor(self) -> None:
        self.closeGate()

    @Slot(int)
    def doorToggle(self, door_id: int) -> None:
        self.logger.info(f"Door toggle {door_id} maps to START_SESSION in the new MCU protocol")
        self._start_session_command()

    @Slot()
    def getDoorStatus(self) -> None:
        self.getMcuStatus()

    # ==================== New PC -> MCU command surface ====================

    @Slot()
    def getMcuStatus(self) -> None:
        self._send(mcu.SystemControl.GET_MCU_STATUS)

    @Slot()
    def pollWeight(self) -> None:
        self._send(mcu.ReadCommand.POLL_WEIGHT)

    @Slot()
    def requestSequenceStatus(self) -> None:
        self._send(mcu.SessionControl.REQUEST_SEQUENCE_STATUS)

    @Slot(int)
    def readSensor(self, sensor_id: int) -> None:
        self._send(mcu.ReadCommand.READ_SENSOR, sensor_id & 0xFF)

    @Slot(str)
    def readSensorByName(self, sensor_name: str) -> None:
        normalized = str(sensor_name).strip().upper()
        normalized = normalized.replace(" ", "_")
        selector = getattr(mcu.SensorSelector, normalized, None)
        if selector is None:
            self.logger.warning(f"Unknown sensor name: {sensor_name}")
            return
        self._send(mcu.ReadCommand.READ_SENSOR, int(selector))

    @Slot(str)
    def setRingLight(self, color: str) -> None:
        normalized = str(color).strip().upper()
        selector = getattr(mcu.RingLightColor, normalized, None)
        if selector is None:
            self.logger.warning(f"Unknown ring light color: {color}")
            return
        self._send(mcu.DeviceControl.RING_LIGHT, int(selector))

    @Slot()
    def setRingLightRed(self) -> None:
        self._send(mcu.DeviceControl.RING_LIGHT, mcu.RingLightColor.RED)

    @Slot()
    def setRingLightGreen(self) -> None:
        self._send(mcu.DeviceControl.RING_LIGHT, mcu.RingLightColor.GREEN)

    @Slot()
    def setRingLightBlue(self) -> None:
        self._send(mcu.DeviceControl.RING_LIGHT, mcu.RingLightColor.BLUE)

    @Slot()
    def setRingLightYellow(self) -> None:
        self._send(mcu.DeviceControl.RING_LIGHT, mcu.RingLightColor.YELLOW)

    @Slot(str)
    def buzzer(self, pattern: str) -> None:
        normalized = str(pattern).strip().upper()
        selector = getattr(mcu.BuzzerPattern, normalized, None)
        if selector is None:
            self.logger.warning(f"Unknown buzzer pattern: {pattern}")
            return
        self._send(mcu.DeviceControl.BUZZER_BEEP, int(selector))

    @Slot()
    def buzzerSingle(self) -> None:
        self._send(mcu.DeviceControl.BUZZER_BEEP, mcu.BuzzerPattern.SINGLE)

    @Slot()
    def buzzerDouble(self) -> None:
        self._send(mcu.DeviceControl.BUZZER_BEEP, mcu.BuzzerPattern.DOUBLE)

    @Slot()
    def buzzerLong(self) -> None:
        self._send(mcu.DeviceControl.BUZZER_BEEP, mcu.BuzzerPattern.LONG)

    # ==================== DEV-MODE HARDWARE SIMULATION ====================

    def _dev_sim_start_session(self) -> None:
        """Simulate the full session start flow without a serial port."""
        self.logger.info("[DEV_SIM] sendNewUser -> simulating START_SESSION + gate open")
        self._start_session()  # creates session ID, sets stage
        self._session_stage = "await_gate_open"
        self._log_session_event(direction="STATE", event_name="dev_sim_start_session_sent")
        # Simulate gate opening after 500ms (production takes ~17s, but dev doesn't need to wait)
        QTimer.singleShot(500, self._dev_sim_gate_opened)

    def _dev_sim_gate_opened(self) -> None:
        if self._session_stage != "await_gate_open":
            return
        self.logger.info("[DEV_SIM] Gate opened (simulated) -> stage=active")
        self._session_stage = "active"
        self._gate_open = True
        self._log_session_event(direction="STATE", event_name="dev_sim_gate_open_confirmed")
        self.gateOpened.emit()
        self.ready.emit()

    def _dev_sim_accept(self, item_type: str) -> None:
        """Simulate ACCEPT_ITEM + ITEM_DROPPED without serial port."""
        if self._session_stage != "active":
            self.logger.warning(f"[DEV_SIM] Cannot accept {item_type} - stage is {self._session_stage}, not 'active'")
            return
        self.logger.info(f"[DEV_SIM] ACCEPT_ITEM({item_type}) -> simulating conveyor + sort")
        self._session_stage = "await_item_drop"
        self._log_session_event(direction="STATE", event_name=f"dev_sim_accept_{item_type}")
        # Simulate item drop after 300ms
        QTimer.singleShot(300, lambda: self._dev_sim_item_dropped(item_type))

    def _dev_sim_item_dropped(self, item_type: str) -> None:
        if self._session_stage != "await_item_drop":
            return
        self.logger.info(f"[DEV_SIM] ITEM_DROPPED ({item_type}) -> stage=active")
        self._session_stage = "active"
        self._log_session_event(direction="STATE", event_name=f"dev_sim_item_dropped_{item_type}")
        if item_type == "plastic":
            self.plasticAccepted.emit()
        elif item_type == "can":
            self.canAccepted.emit()
        self.conveyorDone.emit()

    def _dev_sim_reject(self) -> None:
        """Simulate REJECT_ITEM without serial port."""
        if self._session_stage != "active":
            self.logger.warning(f"[DEV_SIM] Cannot reject - stage is {self._session_stage}, not 'active'")
            return
        self.logger.info("[DEV_SIM] REJECT_ITEM -> simulating rejection")
        self._log_session_event(direction="STATE", event_name="dev_sim_reject")
        self.itemRejected.emit()

    def _dev_sim_end_session(self) -> None:
        """Simulate END_SESSION + gate close without serial port."""
        if self._session_stage in {"disconnected", "await_gate_close"}:
            self.logger.info(f"[DEV_SIM] END_SESSION ignored - stage already {self._session_stage}")
            return
        self.logger.info(f"[DEV_SIM] END_SESSION -> simulating gate close (stage was {self._session_stage})")
        self._session_stage = "await_gate_close"
        self._log_session_event(direction="STATE", event_name="dev_sim_end_session_sent")
        # Simulate gate closing after 300ms
        QTimer.singleShot(300, self._dev_sim_gate_closed)

    def _dev_sim_gate_closed(self) -> None:
        if self._session_stage != "await_gate_close":
            return
        self.logger.info("[DEV_SIM] Gate closed (simulated) -> session ended")
        self._gate_open = False
        self._log_session_event(direction="STATE", event_name="dev_sim_gate_close_confirmed")
        self.gateClosed.emit()
        self._end_session()

    @Slot(result=bool)
    def isProcessing(self) -> bool:
        return self._session_stage in {"await_item_drop", "await_gate_close"}

    # ==================== CLEANUP ====================

    def cleanup(self) -> None:
        self.scan_timer.stop()
        self.ping_timer.stop()
        self.bin_poll_timer.stop()
        self._credentials_timeout_timer.stop()
        self._command_timeout_timer.stop()

        if self.port.isOpen():
            if self._operation_active:
                self._send(mcu.SessionControl.END_SESSION)
            self.port.waitForBytesWritten(500)
            self.port.close()

        self.logger.info("AutoSerial cleaned up")
