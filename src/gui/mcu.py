"""
DropMe Serial Communication Protocol - MCU Interface
Protocol Version: 1.0 (as per Serial_Command_Protocol.pdf)

FLOW SPECIFICATION:
==================

1. SYSTEM CONTROL:
   - SYS_PING: Periodic (every 10s), response = SYS_IDLE or SYS_BUSY
   - SYS_INIT: On system startup, response = SYS_READY
   - SYS_RESET: After ERR_GATE_TIMEOUT/ERR_MOTOR_STALL/ERR_SENSOR_FAIL, response = SYS_READY
   - SYS_STOP_ALL: Emergency (keep for future use)

2. USER FLOW:
   - User starts → selects language → PC sends OP_NEW
   - Cancel on numpad OR QR timeout (20s) → OP_CANCEL then SYS_RESET → back to main
   - Valid credentials → GATE_OPEN → MCU responds GATE_OPENED

3. RECYCLING FLOW:
   - User inserts item
   - GATE_BLOCKED check (async from MCU) - if blocked, show popup, DON'T process
   - If not blocked:
     * WEIGHT_DATA is received (log it, can be used by ML)
     * ML detects item:
       - ACCEPTED (plastic/can): CONVEYOR_RUN(50=5s) → wait CONVEYOR_DONE → SORT_SET → ITEM_ACCEPT → SORT_DONE
       - REJECTED: REJECT_ACTIVATE → wait REJECT_DONE → REJECT_HOME → wait REJECT_HOME_OK → ITEM_REJECT

4. END SESSION:
   - User presses End → OP_END
   - PC sends GATE_CLOSE
   - If GATE_BLOCKED during close → stop, wait for clear, retry
   - Response: GATE_CLOSED

5. BIN MONITORING:
   - BIN_PLASTIC_FULL, BIN_CAN_FULL, BIN_REJECT_FULL
   - Log to file, poll every 12 hours

Frame Format:
    SOF (0xAA) | SEQ (1 Byte) | CMD (1 Byte) | PAYLOAD (1 Byte) | CRC (2 Bytes)
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


# Protocol Constants
SOF = 0xAA
FRAME_SIZE = 6
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF
BAUD_RATE = 9600


class SystemControl(IntEnum):
    """PC → MCU: System Control Commands (0x01-0x0F)"""
    SYS_INIT = 0x01      # On startup → response: SYS_READY
    SYS_RESET = 0x02     # After errors → response: SYS_READY
    SYS_PING = 0x03      # Periodic (10s) → response: SYS_IDLE or SYS_BUSY
    SYS_STOP_ALL = 0x04  # Emergency stop (future use)


class OperationControl(IntEnum):
    """PC → MCU: Operation Control Commands (0x10-0x1F)"""
    OP_NEW = 0x10     # After language selection → response: SYS_READY
    OP_CANCEL = 0x11  # Cancel before recycling starts → then SYS_RESET
    OP_END = 0x12     # User presses End → then GATE_CLOSE


class MotionControl(IntEnum):
    """PC → MCU: Motion Control Commands (0x20-0x2F)"""
    GATE_OPEN = 0x20       # After valid credentials → response: GATE_OPENED
    GATE_CLOSE = 0x21      # After OP_END (only if not blocked) → response: GATE_CLOSED
    CONVEYOR_RUN = 0x22    # For accepted items (payload × 100ms) → response: CONVEYOR_DONE
    CONVEYOR_STOP = 0x23   # Stop conveyor → response: CONVEYOR_DONE
    REJECT_ACTIVATE = 0x24 # For rejected items → response: REJECT_DONE
    REJECT_HOME = 0x25     # Return reject arm → response: REJECT_HOME_OK
    SORT_SET = 0x26        # Set sort path (0x01=plastic, 0x02=can) → response: SORT_DONE


class Classification(IntEnum):
    """PC → MCU: Decision/Classification Commands (0x30-0x3F)"""
    ITEM_ACCEPT = 0x30  # Accept item (payload: 0x01=plastic, 0x02=can)
    ITEM_REJECT = 0x31  # Reject the item


class StatusFeedback(IntEnum):
    """MCU → PC: Status & Feedback Messages (0x40-0x5F)"""
    SYS_READY = 0x40      # System ready (response to SYS_INIT, SYS_RESET, OP_NEW)
    SYS_BUSY = 0x41       # System busy (response to SYS_PING when busy)
    SYS_IDLE = 0x42       # System idle (response to SYS_PING when idle)
    GATE_OPENED = 0x43    # Gate opened (response to GATE_OPEN)
    GATE_CLOSED = 0x44    # Gate closed (response to GATE_CLOSE)
    GATE_BLOCKED = 0x45   # Obstruction detected (ASYNC - can come anytime!)
    CONVEYOR_DONE = 0x46  # Conveyor finished (response to CONVEYOR_RUN/STOP)
    SORT_DONE = 0x47      # Sorting complete (response to SORT_SET, ITEM_ACCEPT)
    REJECT_DONE = 0x48    # Rejection complete (response to REJECT_ACTIVATE)
    REJECT_HOME_OK = 0x49 # Reject arm home (response to REJECT_HOME)


class SensorData(IntEnum):
    """MCU → PC: Sensor Data Messages (0xE0-0xEF) - ASYNC"""
    WEIGHT_DATA = 0xE0       # Item weight (0-255 grams) - log and pass to ML
    BIN_PLASTIC_FULL = 0xE1  # Plastic bin full - log, poll every 12h
    BIN_CAN_FULL = 0xE2      # Can bin full - log, poll every 12h
    BIN_REJECT_FULL = 0xE3   # Reject bin full - log, poll every 12h


class ErrorFault(IntEnum):
    """MCU → PC: Error & Fault Messages (0xF0-0xFF) - triggers SYS_RESET"""
    ERR_GATE_TIMEOUT = 0xF0  # Gate timeout → send SYS_RESET
    ERR_MOTOR_STALL = 0xF1   # Motor stall → send SYS_RESET
    ERR_SENSOR_FAIL = 0xF2   # Sensor fail → send SYS_RESET
    ERR_BIN_FULL = 0xF3      # Bin full error (future use)


class ItemType(IntEnum):
    """Payload values for sorting and classification"""
    PLASTIC = 0x01
    CAN = 0x02


class BinID(IntEnum):
    """Bin identifiers"""
    PLASTIC = 0x01
    CAN = 0x02
    REJECT = 0x03


# Timing constants (in payload units: value × 100ms)
CONVEYOR_TIME_ACCEPT = 50   # 5 seconds for accepted items
REJECT_TIME = 30            # 3 seconds for rejection


def calculate_crc(data: list) -> int:
    """
    Calculate CRC-16 CCITT as per protocol specification.
    """
    crc = CRC_INIT
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC_POLY
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def get_command_name(cmd: int) -> str:
    """Get human-readable command name for logging."""
    for enum_class in [SystemControl, OperationControl, MotionControl, 
                       Classification, StatusFeedback, SensorData, ErrorFault]:
        try:
            return enum_class(cmd).name
        except ValueError:
            continue
    return f"UNKNOWN_0x{cmd:02X}"


def get_payload_description(cmd: int, payload: int) -> str:
    """Get human-readable payload description for logging."""
    if cmd in [Classification.ITEM_ACCEPT, MotionControl.SORT_SET, StatusFeedback.SORT_DONE]:
        if payload == ItemType.PLASTIC:
            return "PLASTIC"
        elif payload == ItemType.CAN:
            return "CAN"
    
    if cmd == SensorData.WEIGHT_DATA:
        return f"{payload}g"
    
    if cmd == MotionControl.CONVEYOR_RUN:
        return f"{payload * 100}ms"
    
    return f"0x{payload:02X}" if payload else "0x00"


@dataclass
class Frame:
    """Serial communication frame."""
    seq: int
    cmd: int
    payload: int
    crc: Optional[int] = None

    def __post_init__(self):
        if self.crc is None:
            self.crc = calculate_crc([self.seq, self.cmd, self.payload])

    def to_bytes(self) -> bytes:
        """Serialize frame to bytes (CRC low byte first)."""
        return bytes([
            SOF,
            self.seq & 0xFF,
            self.cmd & 0xFF,
            self.payload & 0xFF,
            self.crc & 0xFF,
            (self.crc >> 8) & 0xFF
        ])

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional['Frame']:
        """Parse and validate frame from received bytes."""
        if len(data) != FRAME_SIZE:
            return None
        if data[0] != SOF:
            return None
            
        seq = data[1]
        cmd = data[2]
        payload = data[3]
        crc_received = data[4] | (data[5] << 8)
        
        crc_calculated = calculate_crc([seq, cmd, payload])
        if crc_calculated != crc_received:
            return None
            
        return cls(seq, cmd, payload, crc_received)

    def __str__(self) -> str:
        cmd_name = get_command_name(self.cmd)
        payload_desc = get_payload_description(self.cmd, self.payload)
        return f"Frame(SEQ={self.seq:02X}, CMD={cmd_name}, PL={payload_desc})"


class SequenceManager:
    """Manages sequence numbers for transmitted frames."""
    
    def __init__(self):
        self._seq = 0
    
    def next(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq
    
    def reset(self):
        self._seq = 0
    
    @property
    def current(self) -> int:
        return self._seq


# Expected response mapping
EXPECTED_RESPONSES = {
    SystemControl.SYS_INIT: [StatusFeedback.SYS_READY],
    SystemControl.SYS_RESET: [StatusFeedback.SYS_READY],
    SystemControl.SYS_PING: [StatusFeedback.SYS_IDLE, StatusFeedback.SYS_BUSY],
    SystemControl.SYS_STOP_ALL: [StatusFeedback.SYS_IDLE],
    OperationControl.OP_NEW: [StatusFeedback.SYS_READY],
    OperationControl.OP_CANCEL: [StatusFeedback.SYS_IDLE],
    OperationControl.OP_END: [StatusFeedback.SYS_IDLE],
    MotionControl.GATE_OPEN: [StatusFeedback.GATE_OPENED],
    MotionControl.GATE_CLOSE: [StatusFeedback.GATE_CLOSED, StatusFeedback.GATE_BLOCKED],
    MotionControl.CONVEYOR_RUN: [StatusFeedback.CONVEYOR_DONE],
    MotionControl.CONVEYOR_STOP: [StatusFeedback.CONVEYOR_DONE],
    MotionControl.REJECT_ACTIVATE: [StatusFeedback.REJECT_DONE],
    MotionControl.REJECT_HOME: [StatusFeedback.REJECT_HOME_OK],
    MotionControl.SORT_SET: [StatusFeedback.SORT_DONE],
    # ITEM_ACCEPT and ITEM_REJECT have no direct response
}