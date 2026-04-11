from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from PySide6.QtSerialPort import QSerialPort

from gui import mcu


@dataclass(slots=True)
class DecodedFrame:
    frame: Optional[mcu.Frame]
    raw: bytes


class StmInterface(ABC):
    """Transport abstraction for STM communication."""

    @abstractmethod
    def encode_command(self, seq: int, cmd: int, payload: int | bytes = b"") -> bytes:
        raise NotImplementedError

    @abstractmethod
    def decode_frame(self, data: bytes) -> Optional[mcu.Frame]:
        raise NotImplementedError

    @abstractmethod
    def write_command(self, port: QSerialPort, seq: int, cmd: int, payload: int | bytes = b"") -> tuple[mcu.Frame, bytes, int]:
        raise NotImplementedError


class QtStmInterface(StmInterface):
    """QtSerialPort-backed STM interface implementation."""

    def encode_command(self, seq: int, cmd: int, payload: int | bytes = b"") -> bytes:
        frame = mcu.Frame(seq, cmd, payload)
        return frame.to_bytes()

    def decode_frame(self, data: bytes) -> Optional[mcu.Frame]:
        return mcu.Frame.from_bytes(data)

    def write_command(self, port: QSerialPort, seq: int, cmd: int, payload: int | bytes = b"") -> tuple[mcu.Frame, bytes, int]:
        frame = mcu.Frame(seq, cmd, payload)
        raw = frame.to_bytes()
        written = port.write(raw)
        return frame, raw, written

    def probe_ready(self, port: QSerialPort, seq: int) -> bool:
        # Clear any stale bytes before probing so we do not parse leftover noise
        # from a previous device interaction as the ping response.
        try:
            port.clear(QSerialPort.AllDirections)
        except Exception:
            pass
        while port.bytesAvailable() > 0:
            port.readAll()

        raw = self.encode_command(seq, mcu.SystemControl.PING)
        written = port.write(raw)
        if written != len(raw):
            return False
        if not port.waitForBytesWritten(250):
            return False

        deadline = time.monotonic() + 2.0
        data = bytearray()
        while time.monotonic() < deadline:
            if not port.waitForReadyRead(150):
                continue

            chunk = port.readAll().data()
            if chunk:
                data.extend(chunk)

            frame, _ = mcu.Frame.try_parse_from_buffer(data)
            if frame is None:
                continue

            return bool(
                (frame.cmd == int(mcu.ResponseCode.ACK) and frame.payload == b"OK")
                or frame.cmd == int(mcu.ResponseCode.NACK)
            )

        return False
