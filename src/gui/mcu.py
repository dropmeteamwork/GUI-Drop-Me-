"""
DropMe Serial Communication Protocol - MCU Interface.

Authoritative wire format:
    START (0xAA) | MSG_ID | LEN | PAYLOAD... | CRC_L | CRC_H

CRC:
    CRC16/Modbus over the entire frame prefix before the CRC bytes:
    START + MSG_ID + LEN + PAYLOAD
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


START_BYTE = 0xAA
SOF = START_BYTE
MIN_FRAME_SIZE = 5
CRC_POLY = 0xA001
CRC_INIT = 0xFFFF
BAUD_RATE = 115200


class SystemControl(IntEnum):
    PING = 0x01
    GET_MCU_STATUS = 0x02
    SYSTEM_RESET = 0x03

    SYS_PING = PING
    SYS_RESET = SYSTEM_RESET


class ReadCommand(IntEnum):
    READ_SENSOR = 0x11
    POLL_WEIGHT = 0x12


class DeviceControl(IntEnum):
    RING_LIGHT = 0x50
    BUZZER_BEEP = 0x51


class SessionControl(IntEnum):
    REQUEST_SEQUENCE_STATUS = 0x60
    START_SESSION = 0x61
    ACCEPT_ITEM = 0x62
    REJECT_ITEM = 0x63
    END_SESSION = 0x64


class MaintenanceDoorControl(IntEnum):
    OPEN_DOOR_1 = 0x65
    OPEN_DOOR_2 = 0x66
    OPEN_DOOR_3 = 0x67


class AsyncEvent(IntEnum):
    STATUS_OK = 0x70
    ITEM_PLACED = 0x71
    ITEM_DROPPED = 0x72
    BASKET_STATUS = 0x73


class ResponseCode(IntEnum):
    ACK = 0xA0
    NACK = 0xA1
    DATA = 0xA2
    ERROR = 0xA3


class SensorSelector(IntEnum):
    SORT_PLASTIC = 0x00
    SORT_ALUMINUM = 0x01
    GATE_CLOSED = 0x02
    GATE_OPENED = 0x03
    EXIT_GATE = 0x04
    GATE_ALARM = 0x05
    REJECT_HOME = 0x06
    DROP_SENSOR = 0x07
    BASKET_1 = 0x08
    BASKET_2 = 0x09
    BASKET_3 = 0x0A


class RingLightColor(IntEnum):
    OFF = 0x00
    RED = 0x01
    GREEN = 0x02
    BLUE = 0x03
    YELLOW = 0x04
    CYAN = 0x05
    MAGENTA = 0x06
    WHITE = 0x07


class BuzzerPattern(IntEnum):
    SINGLE = 0x01
    DOUBLE = 0x02
    LONG = 0x03


class ItemType(IntEnum):
    PLASTIC = 0x00
    ALUMINUM = 0x01
    CAN = ALUMINUM


class BinID(IntEnum):
    PLASTIC = 0x01
    CAN = 0x02
    REJECT = 0x03


def normalize_payload(payload: int | bytes | bytearray | Iterable[int] | None = None) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, int):
        return bytes([payload & 0xFF])
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    return bytes(int(part) & 0xFF for part in payload)


def payload_to_int(payload: int | bytes | bytearray | None, default: int = 0) -> int:
    if payload is None:
        return default
    if isinstance(payload, int):
        return payload
    if len(payload) == 0:
        return default
    if len(payload) == 1:
        return int(payload[0])
    return int.from_bytes(bytes(payload), "little", signed=False)


def calculate_crc(data: Iterable[int]) -> int:
    crc = CRC_INIT
    for byte in data:
        crc ^= int(byte) & 0xFF
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ CRC_POLY
            else:
                crc >>= 1
            crc &= 0xFFFF
    return crc


def build_frame_bytes(cmd: int, payload: int | bytes | bytearray | Iterable[int] | None = None) -> bytes:
    payload_bytes = normalize_payload(payload)
    frame_prefix = bytes([START_BYTE, int(cmd) & 0xFF, len(payload_bytes) & 0xFF, *payload_bytes])
    crc = calculate_crc(frame_prefix)
    return frame_prefix + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def reference_tx_bytes(cmd: int, payload: int | bytes | bytearray | Iterable[int] | None = None) -> bytes | None:
    return build_frame_bytes(cmd, payload)


def is_reference_request(cmd: int, payload: int | bytes | bytearray | Iterable[int] | None = None) -> bool:
    return True


def matches_reference_request_bytes(
    cmd: int,
    payload: int | bytes | bytearray | Iterable[int] | None,
    raw: bytes,
) -> bool:
    return bytes(raw) == build_frame_bytes(cmd, payload)


def parse_reference_request_bytes(data: bytes) -> tuple[int, bytes] | None:
    frame = Frame.from_bytes(data)
    if frame is None:
        return None
    return int(frame.cmd), bytes(frame.payload)


def validate_frame_bytes(data: bytes) -> bool:
    if len(data) < MIN_FRAME_SIZE:
        return False
    if data[0] != START_BYTE:
        return False
    payload_len = data[2]
    expected_size = 1 + 1 + 1 + payload_len + 2
    if len(data) != expected_size:
        return False
    crc_received = data[-2] | (data[-1] << 8)
    crc_calculated = calculate_crc(data[:-2])
    return crc_received == crc_calculated


def get_command_name(cmd: int) -> str:
    for enum_class in [
        SystemControl,
        ReadCommand,
        DeviceControl,
        SessionControl,
        MaintenanceDoorControl,
        AsyncEvent,
        ResponseCode,
    ]:
        try:
            return enum_class(cmd).name
        except ValueError:
            continue
    return f"UNKNOWN_0x{int(cmd):02X}"


def get_payload_description(cmd: int, payload: int | bytes | bytearray | None) -> str:
    payload_bytes = normalize_payload(payload)
    payload_int = payload_to_int(payload_bytes)

    if int(cmd) == int(ReadCommand.READ_SENSOR) and len(payload_bytes) == 1:
        try:
            return SensorSelector(payload_int).name
        except ValueError:
            pass

    if int(cmd) == int(DeviceControl.RING_LIGHT) and len(payload_bytes) == 1:
        try:
            return RingLightColor(payload_int).name
        except ValueError:
            pass

    if int(cmd) == int(DeviceControl.BUZZER_BEEP) and len(payload_bytes) == 1:
        try:
            return BuzzerPattern(payload_int).name
        except ValueError:
            pass

    if int(cmd) == int(SessionControl.ACCEPT_ITEM) and len(payload_bytes) == 1:
        try:
            return ItemType(payload_int).name
        except ValueError:
            pass

    if int(cmd) == int(AsyncEvent.ITEM_PLACED) and len(payload_bytes) >= 4:
        weight_mg = int.from_bytes(payload_bytes[:4], "little", signed=True)
        return f"{weight_mg} mg"

    if int(cmd) == int(AsyncEvent.BASKET_STATUS) and len(payload_bytes) >= 1:
        mask = payload_bytes[0]
        return f"mask=0x{mask:02X}"

    if len(payload_bytes) == 0:
        return "(none)"
    if len(payload_bytes) == 1:
        return f"0x{payload_int:02X}"
    return payload_bytes.hex(" ")


@dataclass
class Frame:
    seq: int = 0
    cmd: int = 0
    payload: bytes = b""
    crc: int | None = None
    crc_valid: bool = True

    def __post_init__(self) -> None:
        self.payload = normalize_payload(self.payload)
        if self.crc is None:
            self.crc = calculate_crc([START_BYTE, self.cmd & 0xFF, len(self.payload) & 0xFF, *self.payload])

    @property
    def payload_len(self) -> int:
        return len(self.payload)

    @property
    def payload_int(self) -> int:
        return payload_to_int(self.payload)

    def to_bytes(self) -> bytes:
        assert self.crc is not None
        return bytes([
            START_BYTE,
            self.cmd & 0xFF,
            self.payload_len & 0xFF,
            *self.payload,
            self.crc & 0xFF,
            (self.crc >> 8) & 0xFF,
        ])

    @classmethod
    def from_bytes(cls, data: bytes) -> Frame | None:
        if not validate_frame_bytes(data):
            return None
        cmd = data[1]
        payload_len = data[2]
        payload = bytes(data[3:3 + payload_len])
        crc_received = data[-2] | (data[-1] << 8)
        return cls(seq=0, cmd=cmd, payload=payload, crc=crc_received, crc_valid=True)

    @classmethod
    def try_parse_from_buffer(cls, data: bytes | bytearray) -> tuple[Frame | None, int]:
        if len(data) < 1:
            return None, 0

        if data[0] != START_BYTE:
            try:
                next_start = bytes(data).index(START_BYTE)
            except ValueError:
                return None, len(data)
            return None, next_start

        if len(data) < MIN_FRAME_SIZE:
            return None, 0

        payload_len = data[2]
        total_len = 1 + 1 + 1 + payload_len + 2
        if len(data) < total_len:
            return None, 0

        frame_bytes = bytes(data[:total_len])
        frame = cls.from_bytes(frame_bytes)
        return frame, total_len

    def __str__(self) -> str:
        return f"Frame(MSG_ID=0x{self.cmd:02X} {get_command_name(self.cmd)}, PL={get_payload_description(self.cmd, self.payload)})"


class SequenceManager:
    def __init__(self) -> None:
        self._seq = 0

    def next(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def reset(self) -> None:
        self._seq = 0

    @property
    def current(self) -> int:
        return self._seq


KNOWN_TX_FRAMES: dict[tuple[int, bytes], bytes] = {
    (int(SystemControl.PING), b""): build_frame_bytes(SystemControl.PING),
    (int(SystemControl.GET_MCU_STATUS), b""): build_frame_bytes(SystemControl.GET_MCU_STATUS),
    (int(SystemControl.SYSTEM_RESET), b""): build_frame_bytes(SystemControl.SYSTEM_RESET),
    (int(ReadCommand.POLL_WEIGHT), b""): build_frame_bytes(ReadCommand.POLL_WEIGHT),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.OFF)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.OFF)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.RED)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.RED)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.GREEN)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.GREEN)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.BLUE)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.BLUE)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.YELLOW)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.YELLOW)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.CYAN)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.CYAN)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.MAGENTA)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.MAGENTA)])),
    (int(DeviceControl.RING_LIGHT), bytes([int(RingLightColor.WHITE)])): build_frame_bytes(DeviceControl.RING_LIGHT, bytes([int(RingLightColor.WHITE)])),
    (int(DeviceControl.BUZZER_BEEP), bytes([int(BuzzerPattern.SINGLE)])): build_frame_bytes(DeviceControl.BUZZER_BEEP, bytes([int(BuzzerPattern.SINGLE)])),
    (int(DeviceControl.BUZZER_BEEP), bytes([int(BuzzerPattern.DOUBLE)])): build_frame_bytes(DeviceControl.BUZZER_BEEP, bytes([int(BuzzerPattern.DOUBLE)])),
    (int(DeviceControl.BUZZER_BEEP), bytes([int(BuzzerPattern.LONG)])): build_frame_bytes(DeviceControl.BUZZER_BEEP, bytes([int(BuzzerPattern.LONG)])),
    (int(SessionControl.REQUEST_SEQUENCE_STATUS), b""): build_frame_bytes(SessionControl.REQUEST_SEQUENCE_STATUS),
    (int(SessionControl.START_SESSION), b""): build_frame_bytes(SessionControl.START_SESSION),
    (int(SessionControl.ACCEPT_ITEM), bytes([int(ItemType.PLASTIC)])): build_frame_bytes(SessionControl.ACCEPT_ITEM, bytes([int(ItemType.PLASTIC)])),
    (int(SessionControl.ACCEPT_ITEM), bytes([int(ItemType.ALUMINUM)])): build_frame_bytes(SessionControl.ACCEPT_ITEM, bytes([int(ItemType.ALUMINUM)])),
    (int(SessionControl.REJECT_ITEM), b"\x01"): build_frame_bytes(SessionControl.REJECT_ITEM, b"\x01"),
    (int(SessionControl.END_SESSION), b""): build_frame_bytes(SessionControl.END_SESSION),
    (int(MaintenanceDoorControl.OPEN_DOOR_1), b""): build_frame_bytes(MaintenanceDoorControl.OPEN_DOOR_1),
    (int(MaintenanceDoorControl.OPEN_DOOR_2), b""): build_frame_bytes(MaintenanceDoorControl.OPEN_DOOR_2),
    (int(MaintenanceDoorControl.OPEN_DOOR_3), b""): build_frame_bytes(MaintenanceDoorControl.OPEN_DOOR_3),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.SORT_PLASTIC)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.SORT_PLASTIC)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.SORT_ALUMINUM)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.SORT_ALUMINUM)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.GATE_CLOSED)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.GATE_CLOSED)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.GATE_OPENED)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.GATE_OPENED)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.EXIT_GATE)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.EXIT_GATE)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.GATE_ALARM)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.GATE_ALARM)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.REJECT_HOME)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.REJECT_HOME)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.DROP_SENSOR)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.DROP_SENSOR)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.BASKET_1)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.BASKET_1)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.BASKET_2)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.BASKET_2)])),
    (int(ReadCommand.READ_SENSOR), bytes([int(SensorSelector.BASKET_3)])): build_frame_bytes(ReadCommand.READ_SENSOR, bytes([int(SensorSelector.BASKET_3)])),
}
