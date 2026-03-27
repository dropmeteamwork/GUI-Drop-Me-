#!/usr/bin/env python3
"""
DropMe MCU Simulator - Cross-Platform Protocol Tester (senior-grade)

Goals:
- Cross-platform keyboard controls (Windows + Linux/macOS)
- Logs EVERY frame RX (PC->MCU) and TX (MCU->PC) to console + JSONL
- Async scheduled responses (realistic behavior)
- Keeps protocol: SOF/SEQ/CMD/PAYLOAD/CRC (6 bytes)

Gate behavior:
- If GATE_CLOSE is blocked (h pressed), respond GATE_BLOCKED with same seq.
- When unblocked (u pressed), if a close is pending, resume and complete close
  with SAME seq (this is what your GUI needs).

Usage:
    python enhanced_mcu_simulator.py COM10
    (GUI connects to paired port COM11)

Controls (press key, no Enter):
    1 = SYS_READY
    2 = SYS_BUSY
    3 = SYS_IDLE
    4 = GATE_OPENED
    5 = GATE_CLOSED
    6 = CONVEYOR_DONE
    7 = SORT_DONE (PLASTIC)
    8 = SORT_DONE (CAN)
    9 = REJECT_DONE
    0 = REJECT_HOME_OK
    h = GATE_BLOCKED
    u = Gate obstruction OFF (resume pending close if any)
    w = WEIGHT_DATA (random)
    p = BIN_PLASTIC_FULL
    c = BIN_CAN_FULL
    r = BIN_REJECT_FULL
    t = ERR_GATE_TIMEOUT
    e = ERR_MOTOR_STALL
    f = ERR_SENSOR_FAIL
    b = ERR_BIN_FULL
    s = Show status
    q = Quit
"""

from __future__ import annotations

import sys
import time
import json
import heapq
import random
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

# -------------------- pyserial import guard --------------------
try:
    from serial import Serial, SerialException
except ImportError:
    _path0 = sys.path.pop(0) if sys.path else None
    sys.modules.pop("serial", None)
    try:
        from serial import Serial, SerialException
    except ImportError:
        print("Error: pyserial not installed")
        print("Install: pip install pyserial")
        sys.exit(1)
    finally:
        if _path0:
            sys.path.insert(0, _path0)

# ==================== PROTOCOL CONSTANTS ====================

SOF = 0xAA
FRAME_SIZE = 6
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF
DEFAULT_BAUD = 9600

# ==================== PROTOCOL ENUMS ====================

class SystemControl(IntEnum):
    SYS_INIT = 0x01
    SYS_RESET = 0x02
    SYS_PING = 0x03
    SYS_STOP_ALL = 0x04

class OperationControl(IntEnum):
    OP_NEW = 0x10
    OP_CANCEL = 0x11
    OP_END = 0x12

class MotionControl(IntEnum):
    GATE_OPEN = 0x20
    GATE_CLOSE = 0x21
    CONVEYOR_RUN = 0x22
    CONVEYOR_STOP = 0x23
    REJECT_ACTIVATE = 0x24
    REJECT_HOME = 0x25
    SORT_SET = 0x26

class Classification(IntEnum):
    ITEM_ACCEPT = 0x30
    ITEM_REJECT = 0x31

class StatusFeedback(IntEnum):
    SYS_READY = 0x40
    SYS_BUSY = 0x41
    SYS_IDLE = 0x42
    GATE_OPENED = 0x43
    GATE_CLOSED = 0x44
    GATE_BLOCKED = 0x45
    CONVEYOR_DONE = 0x46
    SORT_DONE = 0x47
    REJECT_DONE = 0x48
    REJECT_HOME_OK = 0x49

class SensorData(IntEnum):
    WEIGHT_DATA = 0xE0
    BIN_PLASTIC_FULL = 0xE1
    BIN_CAN_FULL = 0xE2
    BIN_REJECT_FULL = 0xE3

class ErrorFault(IntEnum):
    ERR_GATE_TIMEOUT = 0xF0
    ERR_MOTOR_STALL = 0xF1
    ERR_SENSOR_FAIL = 0xF2
    ERR_BIN_FULL = 0xF3

class ItemType(IntEnum):
    PLASTIC = 0x01
    CAN = 0x02

MANUAL_CONTROL_LINES = [
    ("1", "SYS_READY"),
    ("2", "SYS_BUSY"),
    ("3", "SYS_IDLE"),
    ("4", "GATE_OPENED"),
    ("5", "GATE_CLOSED"),
    ("6", "CONVEYOR_DONE"),
    ("7", "SORT_DONE (PLASTIC)"),
    ("8", "SORT_DONE (CAN)"),
    ("9", "REJECT_DONE"),
    ("0", "REJECT_HOME_OK"),
    ("h", "Hand in gate (GATE_BLOCKED)"),
    ("u", "Unblock gate (resume pending close)"),
    ("w", "Weight sensor"),
    ("p", "Plastic bin FULL"),
    ("c", "Can bin FULL"),
    ("r", "Reject bin FULL"),
    ("t", "Error (gate timeout)"),
    ("e", "Error (motor stall)"),
    ("f", "Error (sensor fail)"),
    ("b", "Error (bin full)"),
    ("s", "Show status"),
    ("q", "Quit"),
]

# ==================== CRC / FRAME ====================

def calculate_crc(data: list[int]) -> int:
    crc = CRC_INIT
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc

@dataclass(frozen=True)
class Frame:
    seq: int
    cmd: int
    payload: int
    crc: int

    @staticmethod
    def build(seq: int, cmd: int, payload: int) -> "Frame":
        crc = calculate_crc([seq & 0xFF, cmd & 0xFF, payload & 0xFF])
        return Frame(seq & 0xFF, cmd & 0xFF, payload & 0xFF, crc)

    def to_bytes(self) -> bytes:
        return bytes([SOF, self.seq, self.cmd, self.payload, self.crc & 0xFF, (self.crc >> 8) & 0xFF])

    @staticmethod
    def try_parse(data: bytes) -> Optional["Frame"]:
        if len(data) != FRAME_SIZE or data[0] != SOF:
            return None
        seq, cmd, payload = data[1], data[2], data[3]
        crc_rcv = data[4] | (data[5] << 8)
        if calculate_crc([seq, cmd, payload]) != crc_rcv:
            return None
        return Frame(seq, cmd, payload, crc_rcv)

def get_cmd_name(cmd: int) -> str:
    for ec in (SystemControl, OperationControl, MotionControl, Classification, StatusFeedback, SensorData, ErrorFault):
        try:
            return ec(cmd).name
        except ValueError:
            pass
    return f"UNKNOWN_0x{cmd:02X}"

# ==================== LOGGING ====================

class ProtocolLogger:
    """Writes JSON Lines with full RX/TX details for replay/inspection."""
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.log_dir / f"mcu_sim_{stamp}.jsonl"

    @staticmethod
    def now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="milliseconds")

    def write(self, event: dict) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as f:
                json.dump(event, f, ensure_ascii=False)
                f.write("\n")
        except Exception:
            # Simulator must never crash because of logging
            pass

# ==================== SCHEDULER ====================

class Scheduler:
    """Tiny time-based scheduler (min-heap)."""
    def __init__(self):
        self._q: list[tuple[float, int, Callable[[], None]]] = []
        self._ctr = 0

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None:
        when = time.monotonic() + max(0.0, delay_s)
        self._ctr += 1
        heapq.heappush(self._q, (when, self._ctr, fn))

    def run_ready(self) -> None:
        now = time.monotonic()
        while self._q and self._q[0][0] <= now:
            _, __, fn = heapq.heappop(self._q)
            fn()

# ==================== CROSS-PLATFORM KEY INPUT ====================

class KeyReader:
    """
    Non-blocking single-key reader.
    - Windows: msvcrt
    - POSIX  : termios/tty + select (cbreak)
    """
    def __init__(self):
        self.is_windows = (os.name == "nt")
        self._fd = None
        self._old = None

        if self.is_windows:
            import msvcrt  # type: ignore
            self._msvcrt = msvcrt
        else:
            import termios
            import tty
            self._termios = termios
            self._tty = tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)

    def close(self) -> None:
        if not self.is_windows and self._fd is not None and self._old is not None:
            try:
                self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old)
            except Exception:
                pass

    def poll(self) -> Optional[str]:
        if self.is_windows:
            if self._msvcrt.kbhit():
                ch = self._msvcrt.getch()
                try:
                    s = ch.decode("utf-8", errors="ignore")
                except Exception:
                    return None
                return s if s else None
            return None
        else:
            import select
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                try:
                    s = sys.stdin.read(1)
                except Exception:
                    return None
                return s if s else None
            return None

# ==================== SIMULATOR ====================

class MCUSimulator:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD, log_dir: Optional[Path] = None, time_scale: float = 1.0):
        self.serial = Serial(port, baud, timeout=0.0)
        self.rx_buffer = bytearray()
        self.running = True

        self.time_scale = max(0.05, float(time_scale))
        self.scheduler = Scheduler()

        # Log directory inside project folder (same folder as this script)
        project_root = Path(__file__).resolve().parent
        self.logger = ProtocolLogger(log_dir or (project_root / "dropme_protocol_logs"))

        self.keys = KeyReader()

        # State
        self.gate_blocked = False
        self.gate_open = False
        self.busy = False
        self.operation_active = False

        # Gate-close resume state (CRITICAL)
        self._close_requested = False
        self._pending_gate_close_seq: Optional[int] = None

        self._print_banner(port, baud)

    @staticmethod
    def ts_human() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _print_banner(self, port: str, baud: int) -> None:
        print("\n" + "=" * 70)
        print("  DropMe MCU Simulator (cross-platform, senior-grade)")
        print("=" * 70)
        print(f"  Port: {port} @ {baud} baud")
        print(f"  Log : {self.logger.path}")
        print("=" * 70)
        print("  Controls (press key, no Enter):")
        for key, description in MANUAL_CONTROL_LINES:
            print(f"    {key} = {description}")
        print("=" * 70)
        print("\n  Waiting for frames...\n")

    def _log_console(self, direction: str, frame: Frame, raw: bytes, note: str = "") -> None:
        cmd_name = get_cmd_name(frame.cmd)
        pl = frame.payload
        line = f"[{self.ts_human()}] {direction} {cmd_name:20s} PL:0x{pl:02X} | {raw.hex(' ')}"
        if note:
            line += f"    {note}"
        print(line)

    def _log_jsonl(self, direction: str, frame: Frame, raw: bytes, note: str = "") -> None:
        self.logger.write({
            "ts": self.logger.now_iso(),
            "direction": direction,  # "RX", "TX", "OP", etc.
            "seq": frame.seq,
            "cmd": frame.cmd,
            "cmd_name": get_cmd_name(frame.cmd),
            "payload": frame.payload,
            "crc": frame.crc,
            "raw_hex": raw.hex(" "),
            "state": {
                "gate_open": self.gate_open,
                "gate_blocked": self.gate_blocked,
                "busy": self.busy,
                "operation_active": self.operation_active,
                "close_requested": self._close_requested,
                "pending_gate_close_seq": self._pending_gate_close_seq,
            },
            "note": note,
        })

    def send(self, seq: int, cmd: int, payload: int = 0x00, note: str = "") -> None:
        frame = Frame.build(seq, cmd, payload)
        raw = frame.to_bytes()
        self.serial.write(raw)
        self._log_console("TX →", frame, raw, note)
        self._log_jsonl("TX", frame, raw, note)

    def send_async(self, cmd: int, payload: int = 0x00, note: str = "") -> None:
        # Async events use seq=0 (matches your current design)
        self.send(0, cmd, payload, note=note)

    def handle_rx(self, frame: Frame, raw: bytes) -> None:
        self._log_console("RX ←", frame, raw)
        self._log_jsonl("RX", frame, raw)

        cmd = frame.cmd
        seq = frame.seq
        pl = frame.payload

        # SYSTEM
        if cmd == SystemControl.SYS_INIT:
            self._set_busy(False)
            self.scheduler.call_later(self._scale(0.10), lambda: self.send(seq, StatusFeedback.SYS_READY, 0x00, "init ok"))
            return

        if cmd == SystemControl.SYS_RESET:
            self._reset_state()
            self.scheduler.call_later(self._scale(0.10), lambda: self.send(seq, StatusFeedback.SYS_READY, 0x00, "reset ok"))
            return

        if cmd == SystemControl.SYS_PING:
            resp = StatusFeedback.SYS_BUSY if self.busy else StatusFeedback.SYS_IDLE
            self.send(seq, resp, 0x00, "ping")
            return

        if cmd == SystemControl.SYS_STOP_ALL:
            self._set_busy(False)
            self.send(seq, StatusFeedback.SYS_IDLE, 0x00, "stop all")
            return

        # OPERATION
        if cmd == OperationControl.OP_NEW:
            self.operation_active = True
            self.send(seq, StatusFeedback.SYS_READY, 0x00, "op new")
            return

        if cmd == OperationControl.OP_CANCEL:
            self.operation_active = False
            self._set_busy(False)
            self.send(seq, StatusFeedback.SYS_IDLE, 0x00, "op cancel")
            return

        if cmd == OperationControl.OP_END:
            self.operation_active = False
            self._set_busy(False)
            self.send(seq, StatusFeedback.SYS_IDLE, 0x00, "op end")
            return

        # GATE OPEN
        if cmd == MotionControl.GATE_OPEN:
            def _do_open():
                self.gate_open = True
                self.gate_blocked = False
                self._close_requested = False
                self._pending_gate_close_seq = None
                self.send(seq, StatusFeedback.GATE_OPENED, 0x00, "gate opened")
            self.scheduler.call_later(self._scale(0.20), _do_open)
            return

        # GATE CLOSE (supports blocked-resume correctly)
        if cmd == MotionControl.GATE_CLOSE:
            self._close_requested = True

            def _do_close():
                if self.gate_blocked:
                    # Remember which close was blocked so "u" can complete it
                    self._pending_gate_close_seq = seq
                    self.send(seq, StatusFeedback.GATE_BLOCKED, 0x01, "blocked while closing")
                else:
                    self.gate_open = False
                    self._close_requested = False
                    self._pending_gate_close_seq = None
                    self.send(seq, StatusFeedback.GATE_CLOSED, 0x00, "gate closed")
            self.scheduler.call_later(self._scale(0.20), _do_close)
            return

        # CONVEYOR
        if cmd == MotionControl.CONVEYOR_RUN:
            duration_s = (pl * 0.1)
            self._set_busy(True)

            def _done():
                self._set_busy(False)
                self.send(seq, StatusFeedback.CONVEYOR_DONE, 0x00, f"conveyor done ({pl} units)")
            self.scheduler.call_later(self._scale(duration_s), _done)
            return

        if cmd == MotionControl.CONVEYOR_STOP:
            self._set_busy(False)
            self.send(seq, StatusFeedback.CONVEYOR_DONE, 0x00, "conveyor stopped")
            return

        # REJECT
        if cmd == MotionControl.REJECT_ACTIVATE:
            self._set_busy(True)

            def _rej_done():
                self._set_busy(False)
                self.send(seq, StatusFeedback.REJECT_DONE, 0x00, "reject done")
            self.scheduler.call_later(self._scale(0.30), _rej_done)
            return

        if cmd == MotionControl.REJECT_HOME:
            self.scheduler.call_later(self._scale(0.20), lambda: self.send(seq, StatusFeedback.REJECT_HOME_OK, 0x00, "reject homed"))
            return

        # SORT
        if cmd == MotionControl.SORT_SET:
            self.scheduler.call_later(self._scale(0.10), lambda: self.send(seq, StatusFeedback.SORT_DONE, pl, "sort done"))
            return

        # CLASSIFICATION (simulate weight)
        if cmd == Classification.ITEM_ACCEPT:
            weight = random.randint(15, 45) if pl == ItemType.PLASTIC else random.randint(10, 25)
            self.scheduler.call_later(self._scale(0.05), lambda: self.send_async(SensorData.WEIGHT_DATA, weight, "weight after accept"))
            return

        if cmd == Classification.ITEM_REJECT:
            weight = random.randint(20, 100)
            self.scheduler.call_later(self._scale(0.05), lambda: self.send_async(SensorData.WEIGHT_DATA, weight, "weight after reject"))
            return

        self._log_jsonl("WARN", frame, raw, note="unknown cmd received")

    def _finish_close_after_unblock(self, seq: int) -> None:
        # If blocked again before completion, report blocked again
        if self.gate_blocked:
            self._pending_gate_close_seq = seq
            self.send(seq, StatusFeedback.GATE_BLOCKED, 0x01, "blocked again while resuming close")
            return

        self.gate_open = False
        self._close_requested = False
        self._pending_gate_close_seq = None
        self.send(seq, StatusFeedback.GATE_CLOSED, 0x00, "close completed after unblock")

    def _send_manual_event(self, cmd: int, payload: int = 0x00, note: str = "") -> None:
        if cmd == StatusFeedback.SYS_READY:
            self._set_busy(False)
        elif cmd == StatusFeedback.SYS_BUSY:
            self._set_busy(True)
        elif cmd == StatusFeedback.SYS_IDLE:
            self._set_busy(False)
        elif cmd == StatusFeedback.GATE_OPENED:
            self.gate_open = True
            self.gate_blocked = False
            self._close_requested = False
            self._pending_gate_close_seq = None
        elif cmd == StatusFeedback.GATE_CLOSED:
            self.gate_open = False
            self.gate_blocked = False
            self._close_requested = False
            self._pending_gate_close_seq = None
        elif cmd == StatusFeedback.GATE_BLOCKED:
            self.gate_blocked = True
        elif cmd in (ErrorFault.ERR_GATE_TIMEOUT, ErrorFault.ERR_MOTOR_STALL, ErrorFault.ERR_SENSOR_FAIL):
            self._set_busy(False)
        self.send_async(cmd, payload, note)

    def handle_key(self, key: str) -> None:
        key = key.lower()

        if key == "1":
            self._send_manual_event(StatusFeedback.SYS_READY, 0x00, "operator: sys ready")
            return

        if key == "2":
            self._send_manual_event(StatusFeedback.SYS_BUSY, 0x00, "operator: sys busy")
            return

        if key == "3":
            self._send_manual_event(StatusFeedback.SYS_IDLE, 0x00, "operator: sys idle")
            return

        if key == "4":
            self._send_manual_event(StatusFeedback.GATE_OPENED, 0x00, "operator: gate opened")
            return

        if key == "5":
            self._send_manual_event(StatusFeedback.GATE_CLOSED, 0x00, "operator: gate closed")
            return

        if key == "6":
            self._send_manual_event(StatusFeedback.CONVEYOR_DONE, 0x00, "operator: conveyor done")
            return

        if key == "7":
            self._send_manual_event(StatusFeedback.SORT_DONE, ItemType.PLASTIC, "operator: sort done plastic")
            return

        if key == "8":
            self._send_manual_event(StatusFeedback.SORT_DONE, ItemType.CAN, "operator: sort done can")
            return

        if key == "9":
            self._send_manual_event(StatusFeedback.REJECT_DONE, 0x00, "operator: reject done")
            return

        if key == "0":
            self._send_manual_event(StatusFeedback.REJECT_HOME_OK, 0x00, "operator: reject home ok")
            return

        if key == "h":
            self._send_manual_event(StatusFeedback.GATE_BLOCKED, 0x01, "operator: hand in gate")
            self.logger.write({"ts": self.logger.now_iso(), "direction": "OP", "event": "BLOCK_GATE"})
            return

        if key == "u":
            was_blocked = self.gate_blocked
            self.gate_blocked = False
            print(f"[{self.ts_human()}] OPERATOR: gate unblocked")
            self.logger.write({"ts": self.logger.now_iso(), "direction": "OP", "event": "UNBLOCK_GATE"})

            # 1) If a close was pending, resume and complete it (same seq)
            if self._close_requested and self._pending_gate_close_seq is not None:
                pending = self._pending_gate_close_seq
                self.scheduler.call_later(self._scale(0.15), lambda: self._finish_close_after_unblock(pending))
                return

            # 2) If no close is pending, DO NOT force movement.
            #    Just report the current gate state so the PC clears its "blocked" latch.
            if was_blocked:
                if self.gate_open:
                    self.send_async(StatusFeedback.GATE_OPENED, 0x00, "operator: unblocked -> gate still open")
                else:
                    self.send_async(StatusFeedback.GATE_CLOSED, 0x00, "operator: unblocked -> gate still closed")
            return


        if key == "w":
            weight = random.randint(10, 200)
            self.send_async(SensorData.WEIGHT_DATA, weight, "operator: weight")
            return

        if key == "p":
            self._send_manual_event(SensorData.BIN_PLASTIC_FULL, 0x01, "operator: plastic bin full")
            return

        if key == "c":
            self._send_manual_event(SensorData.BIN_CAN_FULL, 0x01, "operator: can bin full")
            return

        if key == "r":
            self._send_manual_event(SensorData.BIN_REJECT_FULL, 0x01, "operator: reject bin full")
            return

        if key == "t":
            self._send_manual_event(ErrorFault.ERR_GATE_TIMEOUT, 0x01, "operator: gate timeout")
            return

        if key == "e":
            self._send_manual_event(ErrorFault.ERR_MOTOR_STALL, 0x01, "operator: motor stall")
            return

        if key == "f":
            self._send_manual_event(ErrorFault.ERR_SENSOR_FAIL, 0x01, "operator: sensor fail")
            return

        if key == "b":
            self._send_manual_event(ErrorFault.ERR_BIN_FULL, 0x01, "operator: bin full")
            return

        if key == "s":
            print(
                f"\n  Status: gate_open={self.gate_open}, blocked={self.gate_blocked}, "
                f"busy={self.busy}, op_active={self.operation_active}, "
                f"close_requested={self._close_requested}, pending_close_seq={self._pending_gate_close_seq}\n"
            )
            return

        if key == "q":
            print("\nQuitting...")
            self.running = False
            return

    def _reset_state(self) -> None:
        self.gate_blocked = False
        self.gate_open = False
        self.busy = False
        self.operation_active = False
        self._close_requested = False
        self._pending_gate_close_seq = None

    def _set_busy(self, value: bool) -> None:
        self.busy = bool(value)

    def _scale(self, seconds: float) -> float:
        return float(seconds) * self.time_scale

    def run(self) -> None:
        try:
            while self.running:
                waiting = self.serial.in_waiting
                if waiting:
                    self.rx_buffer.extend(self.serial.read(waiting))

                while len(self.rx_buffer) >= FRAME_SIZE:
                    sof_idx = self.rx_buffer.find(bytes([SOF]))
                    if sof_idx == -1:
                        self.rx_buffer.clear()
                        break
                    if sof_idx > 0:
                        del self.rx_buffer[:sof_idx]
                    if len(self.rx_buffer) < FRAME_SIZE:
                        break

                    chunk = bytes(self.rx_buffer[:FRAME_SIZE])
                    del self.rx_buffer[:FRAME_SIZE]

                    parsed = Frame.try_parse(chunk)
                    if parsed is None:
                        self.logger.write({"ts": self.logger.now_iso(), "direction": "RX_INVALID", "raw_hex": chunk.hex(" ")})
                        print(f"[{self.ts_human()}] RX ← INVALID_FRAME           | {chunk.hex(' ')}")
                        continue

                    self.handle_rx(parsed, chunk)

                self.scheduler.run_ready()

                k = self.keys.poll()
                if k and k.strip():
                    self.handle_key(k)

                time.sleep(0.005)

        except KeyboardInterrupt:
            print("\nInterrupted")
        finally:
            self.running = False
            try:
                self.keys.close()
            except Exception:
                pass
            try:
                self.serial.close()
            except Exception:
                pass
            print("Port closed")


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
    try:
        sim = MCUSimulator(port=port, baud=DEFAULT_BAUD)
        sim.run()
    except SerialException as e:
        print(f"\nError: Could not open {port}")
        print(f"Details: {e}")
        print("\nSetup tips:")
        print("  Windows:")
        print("    - Install com0com")
        print("    - Create paired ports: COM10 <-> COM11")
        print("    - Run: python enhanced_mcu_simulator.py COM10")
        print("    - GUI connects to COM11")
        print("  Linux:")
        print("    - Use socat to create PTYs (see header docstring)")
        sys.exit(1)


if __name__ == "__main__":
    main()
