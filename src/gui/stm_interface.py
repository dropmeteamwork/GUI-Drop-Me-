from __future__ import annotations

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
    def encode_command(self, seq: int, cmd: int, payload: int = 0x00) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def decode_frame(self, data: bytes) -> Optional[mcu.Frame]:
        raise NotImplementedError

    @abstractmethod
    def write_command(self, port: QSerialPort, seq: int, cmd: int, payload: int = 0x00) -> tuple[mcu.Frame, bytes, int]:
        raise NotImplementedError


class QtStmInterface(StmInterface):
    """QtSerialPort-backed STM interface implementation."""

    def encode_command(self, seq: int, cmd: int, payload: int = 0x00) -> bytes:
        frame = mcu.Frame(seq, cmd, payload)
        return frame.to_bytes()

    def decode_frame(self, data: bytes) -> Optional[mcu.Frame]:
        return mcu.Frame.from_bytes(data)

    def write_command(self, port: QSerialPort, seq: int, cmd: int, payload: int = 0x00) -> tuple[mcu.Frame, bytes, int]:
        frame = mcu.Frame(seq, cmd, payload)
        raw = frame.to_bytes()
        written = port.write(raw)
        return frame, raw, written

    def probe_ready(self, port: QSerialPort, seq: int) -> bool:
        raw = self.encode_command(seq, mcu.SystemControl.SYS_INIT, 0x00)
        port.write(raw)
        if not port.waitForReadyRead(1000):
            return False

        data = port.readAll().data()
        if len(data) < mcu.FRAME_SIZE:
            return False

        response = self.decode_frame(data[:mcu.FRAME_SIZE])
        return bool(response and response.cmd == mcu.StatusFeedback.SYS_READY)
