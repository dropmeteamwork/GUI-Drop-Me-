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

import csv
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QStandardPaths
from PySide6.QtQml import QmlElement
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from gui import mcu
from gui import logging

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


class ProcessingState:
    IDLE = None

    # Accept flow states
    ACCEPT_SORT = "ACCEPT_SORT"              # Waiting for SORT_DONE after SORT_SET
    ACCEPT_CONVEYOR = "ACCEPT_CONVEYOR"      # Waiting for CONVEYOR_DONE

    # Reject flow states
    REJECT_ACTIVATE = "REJECT_ACTIVATE"      # Waiting for REJECT_DONE
    REJECT_HOME = "REJECT_HOME"              # Waiting for REJECT_HOME_OK

    # Gate close flow
    CLOSING_GATE = "CLOSING_GATE"            # Waiting for GATE_CLOSED

    # End operation flow
    ENDING_OPERATION = "ENDING_OPERATION"    # Waiting for SYS_IDLE after OP_END


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

        # State machine for item processing
        self._processing_state = ProcessingState.IDLE
        self._pending_item_type: str | None = None  # "plastic" or "can" or "reject"

        # Gate close retry mechanism
        self._pending_gate_close = False
        self._gate_close_retry_count = 0
        self._max_gate_close_retries = 5

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

        # ==================== FILE PATHS ====================
        # Put logs in project folder (same repo) so Windows/Linux behave the same.
        # autoserial.py is usually .../<project>/gui/autoserial.py, so parent of "gui" is project root.
        project_root = Path(__file__).resolve().parents[1]

        self._protocol_log_dir = project_root / "dropme_protocol_logs"
        self._protocol_log_file = self._protocol_log_dir / "protocol_events.jsonl"

        self._weights_log_dir = project_root / "dropme_protocol_logs"
        self._weights_log_file = self._weights_log_dir / "weights.csv"
        self._init_weights_log()

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

    # ==================== LOG INIT ====================

    def _init_weights_log(self) -> None:
        try:
            self._weights_log_dir.mkdir(parents=True, exist_ok=True)
            if not self._weights_log_file.exists():
                with open(self._weights_log_file, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(["timestamp", "session_id", "weight_grams", "port"])
                self.logger.info(f"Created weights log: {self._weights_log_file}")
        except Exception as e:
            self.logger.warning(f"Failed to init weights log: {e}")

    def _log_weight(self, weight_grams: int) -> None:
        try:
            with open(self._weights_log_file, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    self._session_id or "no_session",
                    weight_grams,
                    self.connected_port_name or "unknown",
                ])
            self.logger.info(f"Logged weight: {weight_grams}g")
        except Exception as e:
            self.logger.warning(f"Failed to log weight: {e}")

    def _append_protocol_event(self, event: dict) -> None:
        try:
            if self._session_id and "session_id" not in event:
                event["session_id"] = self._session_id
            self._protocol_log_dir.mkdir(parents=True, exist_ok=True)
            with self._protocol_log_file.open("a", encoding="utf-8") as f:
                json.dump(event, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            self.logger.warning(f"Protocol log failed: {e}")

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

                frame = mcu.Frame(self.seq_manager.next(), mcu.SystemControl.SYS_INIT, 0x00)
                test_port.write(frame.to_bytes())

                if test_port.waitForReadyRead(1000):
                    data = test_port.readAll().data()
                    if len(data) >= mcu.FRAME_SIZE:
                        response = mcu.Frame.from_bytes(data[:mcu.FRAME_SIZE])
                        if response and response.cmd == mcu.StatusFeedback.SYS_READY:
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

        self._processing_state = ProcessingState.IDLE
        self._pending_item_type = None

        self._pending_gate_close = False
        self._gate_close_retry_count = 0

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

            frame = mcu.Frame.from_bytes(frame_bytes)
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

            if self._processing_state == ProcessingState.ENDING_OPERATION:
                self.logger.info("OP_END acknowledged, now closing gate")
                self._processing_state = ProcessingState.CLOSING_GATE
                self._pending_gate_close = True
                self._attempt_gate_close()

        # GATE STATUS
        elif cmd == mcu.StatusFeedback.GATE_OPENED:
            self._gate_open = True
            self._gate_blocked = False
            self.gateOpened.emit()
            self.logger.info("Gate opened")

        elif cmd == mcu.StatusFeedback.GATE_CLOSED:
            self._gate_open = False
            self._gate_blocked = False
            self._pending_gate_close = False
            self._gate_close_retry_count = 0
            self._gate_close_retry_timer.stop()

            self.gateClosed.emit()
            self.logger.info("Gate closed")

            if self._processing_state == ProcessingState.CLOSING_GATE:
                self._processing_state = ProcessingState.IDLE
                self.logger.info("End session sequence complete")

        elif cmd == mcu.StatusFeedback.GATE_BLOCKED:
            # Physical obstruction only
            self._gate_blocked = True
            self.logger.warning("GATE BLOCKED - obstruction detected!")
            self.gateBlocked.emit()
            self.handInGate.emit()

            if self._pending_gate_close:
                self.logger.info("Gate blocked during close - will retry")
                self._gate_close_retry_timer.start()

        # MOTION FEEDBACK
        elif cmd == mcu.StatusFeedback.SORT_DONE:
            self.sortDone.emit(frame.payload)

            if self._processing_state == ProcessingState.ACCEPT_SORT:
                self.logger.info("Sort path set, now running conveyor")
                self._processing_state = ProcessingState.ACCEPT_CONVEYOR
                self._send(mcu.MotionControl.CONVEYOR_RUN, mcu.CONVEYOR_TIME_ACCEPT)

        elif cmd == mcu.StatusFeedback.CONVEYOR_DONE:
            self.conveyorDone.emit()

            # FIX: check state BEFORE resetting it
            if self._processing_state == ProcessingState.ACCEPT_CONVEYOR:
                self.logger.info(f"Accept sequence COMPLETE for {self._pending_item_type}")
                if self._pending_item_type == "plastic":
                    self.plasticAccepted.emit()
                elif self._pending_item_type == "can":
                    self.canAccepted.emit()

                self._pending_item_type = None
                self._processing_state = ProcessingState.IDLE
            else:
                # Non-state-machine conveyor completion
                self._processing_state = ProcessingState.IDLE

        elif cmd == mcu.StatusFeedback.REJECT_DONE:
            self.rejectDone.emit()

            if self._processing_state == ProcessingState.REJECT_ACTIVATE:
                self.logger.info("Reject done, now homing reject arm")
                self._processing_state = ProcessingState.REJECT_HOME
                self._send(mcu.MotionControl.REJECT_HOME)

        elif cmd == mcu.StatusFeedback.REJECT_HOME_OK:
            self.rejectHomeOk.emit()

            if self._processing_state == ProcessingState.REJECT_HOME:
                self.logger.info("Reject sequence COMPLETE")
                self.itemRejected.emit()
                self._pending_item_type = None
                self._processing_state = ProcessingState.IDLE

        # SENSOR
        elif cmd == mcu.SensorData.WEIGHT_DATA:
            self._log_weight(frame.payload)
            self.weightReceived.emit(frame.payload)

        elif cmd == mcu.SensorData.BIN_PLASTIC_FULL:
            self.logger.warning("BIN FULL: Plastic")
            self.binFull.emit("Plastic")

        elif cmd == mcu.SensorData.BIN_CAN_FULL:
            self.logger.warning("BIN FULL: Can")
            self.binFull.emit("Can")

        elif cmd == mcu.SensorData.BIN_REJECT_FULL:
            self.logger.warning("BIN FULL: Reject")
            self.binFull.emit("Reject")

        # ERRORS
        elif cmd == mcu.ErrorFault.ERR_GATE_TIMEOUT:
            self.logger.error("ERROR: Gate timeout")
            self.errorOccurred.emit("ERR_GATE_TIMEOUT", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_MOTOR_STALL:
            self.logger.error(f"ERROR: Motor stall ({frame.payload})")
            self.errorOccurred.emit("ERR_MOTOR_STALL", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_SENSOR_FAIL:
            self.logger.error(f"ERROR: Sensor fail ({frame.payload})")
            self.errorOccurred.emit("ERR_SENSOR_FAIL", frame.payload)
            self._abort_processing()
            self.resetSystem()

        elif cmd == mcu.ErrorFault.ERR_BIN_FULL:
            self.logger.error(f"ERROR: Bin full ({frame.payload})")
            self.errorOccurred.emit("ERR_BIN_FULL", frame.payload)

    def _abort_processing(self) -> None:
        self.logger.warning(f"Aborting processing state: {self._processing_state}")
        self._processing_state = ProcessingState.IDLE
        self._pending_item_type = None
        self._pending_gate_close = False

    # ==================== GATE CLOSE RETRY ====================

    def _attempt_gate_close(self) -> None:
        if self._gate_blocked:
            self.logger.warning("Cannot close gate - blocked, will retry")
            self._gate_close_retry_timer.start()
            return

        if self._gate_close_retry_count >= self._max_gate_close_retries:
            self.logger.error("Max gate close retries reached!")
            self._pending_gate_close = False
            self._processing_state = ProcessingState.IDLE
            return

        self._gate_close_retry_count += 1
        self.logger.info(f"Attempting gate close (attempt {self._gate_close_retry_count})")
        self._send(mcu.MotionControl.GATE_CLOSE)

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
        self._abort_processing()
        self.errorOccurred.emit("COMMAND_TIMEOUT", 0)

    # ==================== TX ====================

    def _send(self, cmd: int, payload: int = 0x00) -> bool:
        if not self.port.isOpen():
            self.logger.warning("Cannot send - not connected")
            return False

        frame = mcu.Frame(self.seq_manager.next(), cmd, payload)
        raw = frame.to_bytes()
        written = self.port.write(raw)

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
        self._processing_state = ProcessingState.ENDING_OPERATION
        self._send(mcu.OperationControl.OP_END)
        self._end_session()

    # ==================== GATE CONTROL ====================

    @Slot()
    def openGate(self) -> None:
        self._credentials_timeout_timer.stop()
        self.logger.info("Opening gate")
        self._send(mcu.MotionControl.GATE_OPEN)

    @Slot()
    def closeGate(self) -> None:
        self._pending_gate_close = True
        self._gate_close_retry_count = 0
        self._processing_state = ProcessingState.CLOSING_GATE
        self._attempt_gate_close()

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
            return True
        return False

    def _start_accept_sequence(self, item_type: str) -> bool:
        if self._blocked_by_fraud_or_gate(f"accept {item_type}"):
            return False

        if self._processing_state != ProcessingState.IDLE:
            self.logger.warning(f"Cannot start accept - already processing: {self._processing_state}")
            return False

        self.logger.info(f"Starting accept sequence for {item_type}")
        self._pending_item_type = item_type
        payload = mcu.ItemType.PLASTIC if item_type == "plastic" else mcu.ItemType.CAN

        # Step 1: ITEM_ACCEPT (no response expected)
        self._send(mcu.Classification.ITEM_ACCEPT, payload)

        # Step 2: SORT_SET -> SORT_DONE
        self._processing_state = ProcessingState.ACCEPT_SORT
        self._send(mcu.MotionControl.SORT_SET, payload)
        return True

    def _start_reject_sequence(self) -> bool:
        if self._blocked_by_fraud_or_gate("reject item"):
            return False

        if self._processing_state != ProcessingState.IDLE:
            self.logger.warning(f"Cannot start reject - already processing: {self._processing_state}")
            return False

        self.logger.info("Starting reject sequence")
        self._pending_item_type = "reject"

        self._send(mcu.Classification.ITEM_REJECT, 0x00)

        self._processing_state = ProcessingState.REJECT_ACTIVATE
        self._send(mcu.MotionControl.REJECT_ACTIVATE)
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
