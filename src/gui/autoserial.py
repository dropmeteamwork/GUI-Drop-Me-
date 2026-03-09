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
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QStandardPaths
from PySide6.QtQml import QmlElement
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from gui import mcu
from gui import logging
from gui.aws_uploader import AWSUploader
from gui.machine_controller import MachineController, ProcessingState, ControllerResult
from gui.protocol_telemetry_service import ProtocolTelemetryService
from gui.stm_interface import QtStmInterface

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


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
        self.seq_manager = mcu.SequenceManager()
        self.rx_buffer = bytearray()
        self.last_response_time = 0.0

        # ==================== STATE TRACKING ====================
        self._session_id: str | None = None
        self._gate_blocked = False          # physical obstruction (MCU)
        self._gate_open = False
        self._operation_active = False
        self._system_busy = False

        # Fraud prevention hold (PC-side, from ML hand detection)
        self._fraud_hold = False

        # Core workflow controller (business logic)
        self._machine_controller = MachineController(max_gate_close_retries=5)

        # Serial transport abstraction
        self._stm_interface = QtStmInterface()

        # ==================== TIMERS ====================
        self._credentials_timeout_timer = QTimer(self)
        self._credentials_timeout_timer.setSingleShot(True)
        self._credentials_timeout_timer.setInterval(20000)
        self._credentials_timeout_timer.timeout.connect(self._on_credentials_timeout)

        self._gate_close_retry_timer = QTimer(self)
        self._gate_close_retry_timer.setSingleShot(True)
        self._gate_close_retry_timer.setInterval(2000)
        self._gate_close_retry_timer.timeout.connect(self._retry_gate_close)

        self._command_timeout_timer = QTimer(self)
        self._command_timeout_timer.setSingleShot(True)
        self._command_timeout_timer.setInterval(15000)
        self._command_timeout_timer.timeout.connect(self._on_command_timeout)

        # ==================== Telemetry Service ====================
        project_root = Path(__file__).resolve().parents[1]
        telemetry_dir = project_root / "dropme_protocol_logs"

        self._telemetry = ProtocolTelemetryService(
            logger=self.logger,
            log_dir=telemetry_dir,
            machine_name=os.environ.get("MACHINE_NAME", "maadi_club"),
            telemetry_uploader=AWSUploader(),
        )

        self._bin_plastic_full = False
        self._bin_can_full = False
        self._bin_reject_full = False
        self._last_weight_grams = None
        self._last_error = ""

        self._telemetry.initialize()
        self._write_sensor_snapshot()
        # ==================== Port scanning timer ====================
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self._scan_ports)
        self.scan_timer.start(2000)

        # Keep-alive ping timer
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self._send_ping)
        self.ping_timer.setInterval(10000)

        # Bin poll timer (log only)
        self.bin_poll_timer = QTimer(self)
        self.bin_poll_timer.timeout.connect(self._poll_bin_status)
        self.bin_poll_timer.setInterval(43200000)

        self.logger.info("AutoSerial initialized (using QtSerialPort) - State machine enabled")

    @property
    def _processing_state(self):
        return self._machine_controller.processing_state

    @_processing_state.setter
    def _processing_state(self, value):
        self._machine_controller.processing_state = value

    @property
    def _pending_item_type(self):
        return self._machine_controller.pending_item_type

    @_pending_item_type.setter
    def _pending_item_type(self, value):
        self._machine_controller.pending_item_type = value

    @property
    def _pending_gate_close(self):
        return self._machine_controller.pending_gate_close

    @_pending_gate_close.setter
    def _pending_gate_close(self, value):
        self._machine_controller.pending_gate_close = bool(value)

    @property
    def _gate_close_retry_count(self):
        return self._machine_controller.gate_close_retry_count

    @_gate_close_retry_count.setter
    def _gate_close_retry_count(self, value):
        self._machine_controller.gate_close_retry_count = int(value)

    @property
    def _max_gate_close_retries(self):
        return self._machine_controller.max_gate_close_retries

    @_max_gate_close_retries.setter
    def _max_gate_close_retries(self, value):
        self._machine_controller.max_gate_close_retries = int(value)

    def _dispatch_controller_commands(self, result: ControllerResult) -> None:
        for command in result.commands:
            self._send(command.cmd, command.payload)

    def _apply_controller_result(self, result: ControllerResult) -> None:
        self._dispatch_controller_commands(result)

        if result.start_gate_retry_timer:
            self._gate_close_retry_timer.start()
        if result.stop_gate_retry_timer:
            self._gate_close_retry_timer.stop()

        if result.emit_plastic_accepted:
            self.plasticAccepted.emit()
        if result.emit_can_accepted:
            self.canAccepted.emit()
        if result.emit_item_rejected:
            self.itemRejected.emit()

    # ==================== LOG INIT ====================

    def _sensor_snapshot_data(self) -> dict:
        return {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "port": self.connected_port_name or "",
            "session_id": self._session_id or "",
            "system": {
                "busy": self._system_busy,
                "operation_active": self._operation_active,
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

    # ==================== CONNECTION MANAGEMENT ====================

    def _scan_ports(self) -> None:
        if self.port.isOpen():
            return

        for info in QSerialPortInfo.availablePorts():
            port_name = info.portName()
            self.logger.info(f"Trying port: {port_name}")

            test_port = QSerialPort(info)
            try:
                if not test_port.open(QSerialPort.ReadWrite):
                    continue

                test_port.setBaudRate(mcu.BAUD_RATE)
                test_port.setDataBits(QSerialPort.Data8)
                test_port.setParity(QSerialPort.NoParity)
                test_port.setStopBits(QSerialPort.OneStop)

                if self._stm_interface.probe_ready(test_port, self.seq_manager.next()):
                    self.port = test_port
                    self.port.readyRead.connect(self._read_data)
                    self.connected_port_name = port_name
                    self.last_response_time = time.time()

                    self.scan_timer.stop()
                    self.ping_timer.start()
                    self.bin_poll_timer.start()

                    self.logger.info(f"Connected to {port_name}")
                    self.connectionEstablished.emit(port_name)
                    self.systemReady.emit()
                    self.ready.emit()
                    self._sync_connection_state(True)
                    return

            except Exception as e:
                self.logger.error(f"Error testing {port_name}: {e}")
            finally:
                if self.port != test_port and test_port.isOpen():
                    test_port.close()

    def _send_ping(self) -> None:
        if self.port.isOpen():
            self._send(mcu.SystemControl.SYS_PING)
            if self.last_response_time > 0 and (time.time() - self.last_response_time) > 30:
                self.logger.warning("Connection timeout")
                self._handle_disconnect()

    def _poll_bin_status(self) -> None:
        self.logger.info("Bin status poll (12h interval)")
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "BIN_POLL",
            "note": "12-hour bin status check"
        })

    def _handle_disconnect(self) -> None:
        if self.port.isOpen():
            self.port.close()
        self.connected_port_name = None
        self._sync_connection_state(False)
        self._reset_state()
        self.ping_timer.stop()
        self.bin_poll_timer.stop()
        self.scan_timer.start()
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

        self._machine_controller.reset()

        self._credentials_timeout_timer.stop()
        self._gate_close_retry_timer.stop()
        self._command_timeout_timer.stop()

    # ==================== SESSION ====================

    def _start_session(self) -> None:
        self._session_id = uuid.uuid4().hex
        self._operation_active = True
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "SESSION_START"
        })
        self.logger.info(f"Session started: {self._session_id}")

    def _end_session(self) -> None:
        if self._session_id is None:
            return
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "SESSION_END"
        })
        self.logger.info(f"Session ended: {self._session_id}")
        self._session_id = None
        self._operation_active = False

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

    @Slot(result=bool)
    def isFraudHold(self) -> bool:
        return self._fraud_hold

    # ==================== RX ====================

    def _read_data(self) -> None:
        self.rx_buffer.extend(self.port.readAll().data())

        while len(self.rx_buffer) >= mcu.FRAME_SIZE:
            sof_idx = self.rx_buffer.find(mcu.SOF)
            if sof_idx == -1:
                self.rx_buffer.clear()
                break
            if sof_idx > 0:
                del self.rx_buffer[:sof_idx]
            if len(self.rx_buffer) < mcu.FRAME_SIZE:
                break

            frame_bytes = bytes(self.rx_buffer[:mcu.FRAME_SIZE])
            del self.rx_buffer[:mcu.FRAME_SIZE]

            frame = self._stm_interface.decode_frame(frame_bytes)
            if frame:
                self._handle_frame(frame, frame_bytes)
            else:
                self.logger.warning(f"Invalid frame: {frame_bytes.hex(' ')}")
                self._append_protocol_event({
                    "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "direction": "RX_INVALID",
                    "raw": frame_bytes.hex(" "),
                })

    def _handle_frame(self, frame: mcu.Frame, raw: bytes) -> None:
        self.last_response_time = time.time()
        self._command_timeout_timer.stop()

        cmd = frame.cmd
        cmd_name = mcu.get_command_name(cmd)

        self.logger.debug(f"RX: {cmd_name} PL=0x{frame.payload:02X} STATE={self._processing_state}")

        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "RX",
            "cmd": cmd_name,
            "payload": frame.payload,
            "state": self._processing_state,
            "raw": raw.hex(" ")
        })
        self._reduce_protocol_state("RX", frame, raw)

        # SYSTEM STATUS
        if cmd == mcu.StatusFeedback.SYS_READY:
            self._system_busy = False
            self.systemReady.emit()
            self.ready.emit()

        elif cmd == mcu.StatusFeedback.SYS_BUSY:
            self._system_busy = True
            self.systemBusy.emit()

        elif cmd == mcu.StatusFeedback.SYS_IDLE:
            self._system_busy = False
            self.systemIdle.emit()

            result = self._machine_controller.on_system_idle(self._gate_blocked)
            self._apply_controller_result(result)

        # GATE STATUS
        elif cmd == mcu.StatusFeedback.GATE_OPENED:
            self._gate_open = True
            self._gate_blocked = False
            self.gateOpened.emit()
            self._append_sensor_event("GATE_OPENED")
            self.logger.info("Gate opened")

        elif cmd == mcu.StatusFeedback.GATE_CLOSED:
            self._gate_open = False
            self._gate_blocked = False

            self.gateClosed.emit()
            self._append_sensor_event("GATE_CLOSED")
            self.logger.info("Gate closed")

            result = self._machine_controller.on_gate_closed()
            self._apply_controller_result(result)
            if result.end_sequence_complete:
                self.logger.info("End session sequence complete")

        elif cmd == mcu.StatusFeedback.GATE_BLOCKED:
            # Physical obstruction only
            self._gate_blocked = True
            self.logger.warning("GATE BLOCKED - obstruction detected!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)

            result = self._machine_controller.on_gate_blocked()
            self._apply_controller_result(result)
            if result.start_gate_retry_timer:
                self.logger.info("Gate blocked during close - will retry")

        # MOTION FEEDBACK
        elif cmd == mcu.StatusFeedback.SORT_DONE:
            self.sortDone.emit(frame.payload)

            result = self._machine_controller.on_sort_done()
            self._apply_controller_result(result)
            if result.commands:
                self.logger.info("Sort path set, now running conveyor")

        elif cmd == mcu.StatusFeedback.CONVEYOR_DONE:
            self.conveyorDone.emit()

            pending_item = self._pending_item_type
            result = self._machine_controller.on_conveyor_done()
            self._apply_controller_result(result)
            if result.emit_plastic_accepted or result.emit_can_accepted:
                self.logger.info(f"Accept sequence COMPLETE for {pending_item}")

        elif cmd == mcu.StatusFeedback.REJECT_DONE:
            self.rejectDone.emit()

            result = self._machine_controller.on_reject_done()
            self._apply_controller_result(result)
            if result.commands:
                self.logger.info("Reject done, now homing reject arm")

        elif cmd == mcu.StatusFeedback.REJECT_HOME_OK:
            self.rejectHomeOk.emit()

            result = self._machine_controller.on_reject_home_ok()
            self._apply_controller_result(result)
            if result.emit_item_rejected:
                self.logger.info("Reject sequence COMPLETE")

        # SENSOR
        elif cmd == mcu.SensorData.WEIGHT_DATA:
            self._last_weight_grams = int(frame.payload)
            self._log_weight(frame.payload)
            self.weightReceived.emit(frame.payload)
            self._append_sensor_event("WEIGHT_DATA", frame.payload)

        elif cmd == mcu.SensorData.BIN_PLASTIC_FULL:
            self._bin_plastic_full = True
            self.logger.warning("BIN FULL: Plastic")
            self.binFull.emit("Plastic")
            self._append_sensor_event("BIN_PLASTIC_FULL", frame.payload)

        elif cmd == mcu.SensorData.BIN_CAN_FULL:
            self._bin_can_full = True
            self.logger.warning("BIN FULL: Can")
            self.binFull.emit("Can")
            self._append_sensor_event("BIN_CAN_FULL", frame.payload)

        elif cmd == mcu.SensorData.BIN_REJECT_FULL:
            self._bin_reject_full = True
            self.logger.warning("BIN FULL: Reject")
            self.binFull.emit("Reject")
            self._append_sensor_event("BIN_REJECT_FULL", frame.payload)

        # ERRORS
        elif cmd == mcu.ErrorFault.ERR_GATE_TIMEOUT:
            self.logger.error("ERROR: Gate timeout")
            self._last_error = "ERR_GATE_TIMEOUT"
            self.errorOccurred.emit("ERR_GATE_TIMEOUT", frame.payload)
            self._append_sensor_event("ERR_GATE_TIMEOUT", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_MOTOR_STALL:
            self.logger.error(f"ERROR: Motor stall ({frame.payload})")
            self._last_error = "ERR_MOTOR_STALL"
            self.errorOccurred.emit("ERR_MOTOR_STALL", frame.payload)
            self._append_sensor_event("ERR_MOTOR_STALL", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_SENSOR_FAIL:
            self.logger.error(f"ERROR: Sensor fail ({frame.payload})")
            self._last_error = "ERR_SENSOR_FAIL"
            self.errorOccurred.emit("ERR_SENSOR_FAIL", frame.payload)
            self._append_sensor_event("ERR_SENSOR_FAIL", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_BIN_FULL:
            self.logger.error(f"ERROR: Bin full ({frame.payload})")
            self._last_error = "ERR_BIN_FULL"
            self.errorOccurred.emit("ERR_BIN_FULL", frame.payload)
            self._append_sensor_event("ERR_BIN_FULL", frame.payload)

    def _abort_processing(self) -> None:
        self.logger.warning(f"Aborting processing state: {self._processing_state}")
        result = self._machine_controller.abort_processing()
        self._apply_controller_result(result)

    # ==================== GATE CLOSE RETRY ====================

    def _attempt_gate_close(self) -> None:
        result = self._machine_controller.attempt_gate_close(self._gate_blocked)
        if result.start_gate_retry_timer:
            self.logger.warning("Cannot close gate - blocked, will retry")
        if result.dropped:
            self.logger.error("Max gate close retries reached!")
        elif result.commands:
            self.logger.info(f"Attempting gate close (attempt {self._gate_close_retry_count})")
        self._apply_controller_result(result)

    def _retry_gate_close(self) -> None:
        if self._pending_gate_close:
            self._attempt_gate_close()

    def _on_command_timeout(self) -> None:
        self.logger.error(f"COMMAND TIMEOUT in state: {self._processing_state}")
        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "TIMEOUT",
            "state": self._processing_state,
            "note": "MCU did not respond in time"
        })
        result = self._machine_controller.on_command_timeout()
        self._apply_controller_result(result)
        self.errorOccurred.emit("COMMAND_TIMEOUT", 0)

    # ==================== TX ====================

    def _send(self, cmd: int, payload: int = 0x00) -> bool:
        if not self.port.isOpen():
            self.logger.warning("Cannot send - not connected")
            return False

        frame, raw, written = self._stm_interface.write_command(self.port, self.seq_manager.next(), cmd, payload)

        cmd_name = mcu.get_command_name(cmd)
        self.logger.debug(f"TX: {cmd_name} PL=0x{payload:02X}")

        self._append_protocol_event({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "direction": "TX",
            "cmd": cmd_name,
            "payload": payload,
            "state": self._processing_state,
            "raw": raw.hex(" ")
        })
        self.commandSent.emit(cmd_name, payload)
        self._reduce_protocol_state("TX", frame, raw)

        commands_without_timeout = [
            mcu.SystemControl.SYS_PING,
            mcu.Classification.ITEM_ACCEPT,
            mcu.Classification.ITEM_REJECT,
        ]
        if cmd not in commands_without_timeout:
            self._command_timeout_timer.start()

        return written == mcu.FRAME_SIZE

    # ==================== STATE QUERIES ====================

    @Slot(result=bool)
    def isGateBlocked(self) -> bool:
        return self._gate_blocked

    @Slot(result=bool)
    def isGateOpen(self) -> bool:
        return self._gate_open

    @Slot(result=bool)
    def isConnected(self) -> bool:
        return self.port.isOpen()

    @Slot(result=str)
    def getPortName(self) -> str:
        return self.connected_port_name or ""

    @Slot(result=bool)
    def isProcessing(self) -> bool:
        return self._processing_state != ProcessingState.IDLE

    @Slot()
    def clearGateBlocked(self) -> None:
        self._gate_blocked = False
        self.logger.info("Gate blocked cleared")
        if self._pending_gate_close:
            self._attempt_gate_close()

    # ==================== SYSTEM CONTROL ====================

    @Slot()
    def initSystem(self) -> None:
        self._send(mcu.SystemControl.SYS_INIT)

    @Slot()
    def resetSystem(self) -> None:
        self._reset_state()
        self._send(mcu.SystemControl.SYS_RESET)

    @Slot()
    def pingSystem(self) -> None:
        self._send(mcu.SystemControl.SYS_PING)

    @Slot()
    def stopAll(self) -> None:
        self._abort_processing()
        self._send(mcu.SystemControl.SYS_STOP_ALL)

    # ==================== OPERATION CONTROL ====================

    @Slot()
    def startOperation(self) -> None:
        self._send(mcu.OperationControl.OP_NEW)
        self._start_session()

    @Slot()
    def cancelOperation(self) -> None:
        self.logger.info("Cancelling operation")
        self._credentials_timeout_timer.stop()
        self._send(mcu.OperationControl.OP_CANCEL)
        self._end_session()
        QTimer.singleShot(200, self.resetSystem)

    @Slot()
    def endOperation(self) -> None:
        self.logger.info("Ending operation")
        self._credentials_timeout_timer.stop()
        result = self._machine_controller.request_end_operation()
        self._apply_controller_result(result)
        self._end_session()

    # ==================== GATE CONTROL ====================

    @Slot()
    def openGate(self) -> None:
        self._credentials_timeout_timer.stop()
        self.logger.info("Opening gate")
        self._send(mcu.MotionControl.GATE_OPEN)

    @Slot()
    def closeGate(self) -> None:
        result = self._machine_controller.request_close_gate(self._gate_blocked)
        self._apply_controller_result(result)

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

    def _start_accept_sequence(self, item_type: str) -> bool:
        result = self._machine_controller.request_accept_sequence(item_type, self._gate_blocked, self._fraud_hold)

        if result.blocked_by_fraud:
            self.logger.warning(f"FRAUD PREVENTION: accept {item_type} - hand detected (fraud hold)!")
            return False

        if result.blocked_by_gate:
            self.logger.warning(f"Cannot accept {item_type} - gate physically blocked!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)
            return False

        if result.blocked_by_busy:
            self.logger.warning(f"Cannot start accept - already processing: {self._processing_state}")
            return False

        self.logger.info(f"Starting accept sequence for {item_type}")
        self._apply_controller_result(result)
        return True

    def _start_reject_sequence(self) -> bool:
        result = self._machine_controller.request_reject_sequence(self._gate_blocked, self._fraud_hold)

        if result.blocked_by_fraud:
            self.logger.warning("FRAUD PREVENTION: reject item - hand detected (fraud hold)!")
            return False

        if result.blocked_by_gate:
            self.logger.warning("Cannot reject item - gate physically blocked!")
            self.gateBlocked.emit()
            self.handInGate.emit()
            self._append_sensor_event("GATE_BLOCKED", 0)
            return False

        if result.blocked_by_busy:
            self.logger.warning(f"Cannot start reject - already processing: {self._processing_state}")
            return False

        self.logger.info("Starting reject sequence")
        self._apply_controller_result(result)
        return True

    # ==================== High-level QML methods ====================

    @Slot()
    def sendNewUser(self) -> None:
        self.startOperation()

    @Slot()
    def sendPlastic(self) -> None:
        self._start_accept_sequence("plastic")

    @Slot()
    def sendCan(self) -> None:
        self._start_accept_sequence("can")

    @Slot()
    def sendOther(self) -> None:
        self._start_reject_sequence()

    @Slot()
    def sendSignOut(self) -> None:
        self.endOperation()

    @Slot()
    def sendOpenDoor(self) -> None:
        self.openGate()

    @Slot()
    def closeDoor(self) -> None:
        self.closeGate()

    @Slot(int)
    def doorToggle(self, door_id: int) -> None:
        self.logger.info(f"Door toggle: {door_id}")
        self._send(mcu.MotionControl.GATE_OPEN, door_id & 0xFF)

    @Slot()
    def getDoorStatus(self) -> None:
        self.pingSystem()

    # ==================== CLEANUP ====================

    def cleanup(self) -> None:
        self.scan_timer.stop()
        self.ping_timer.stop()
        self.bin_poll_timer.stop()
        self._credentials_timeout_timer.stop()
        self._gate_close_retry_timer.stop()
        self._command_timeout_timer.stop()

        if self.port.isOpen():
            if self._operation_active:
                self._send(mcu.OperationControl.OP_END)
            self.port.waitForBytesWritten(500)
            self.port.close()

        self.logger.info("AutoSerial cleaned up")




