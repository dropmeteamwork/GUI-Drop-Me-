#!/usr/bin/env python3
"""
DropMe MCU Simulator for the new RVM protocol.

Protocol:
    START (0xAA) | MSG_ID | LEN | PAYLOAD... | CRC_L | CRC_H

Usage:
    python src/gui/enhanced_mcu_simulator.py COM10
"""

from __future__ import annotations

import heapq
import json
import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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

from gui import mcu


DEFAULT_BAUD = mcu.BAUD_RATE

MANUAL_CONTROL_LINES = [
    ("o", "ACK OK"),
    ("k", "STATUS_OK event"),
    ("p", "ITEM_PLACED event"),
    ("d", "ITEM_DROPPED event"),
    ("b", "BASKET_STATUS event"),
    ("w", "DATA weight response"),
    ("1", "Basket 1 FULL"),
    ("2", "Basket 2 FULL"),
    ("3", "Basket 3 FULL"),
    ("h", "Gate alarm ON"),
    ("u", "Gate alarm OFF"),
    ("x", "Send bad-CRC frame"),
    ("s", "Show simulator state"),
    ("q", "Quit"),
]


def _payload_value(payload: bytes) -> int:
    return mcu.payload_to_int(payload)


def get_cmd_name(cmd: int) -> str:
    return mcu.get_command_name(cmd)


class ProtocolLogger:
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
            pass


class Scheduler:
    def __init__(self) -> None:
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


class KeyReader:
    def __init__(self) -> None:
        self.is_windows = os.name == "nt"
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

    def poll(self) -> str | None:
        if self.is_windows:
            if self._msvcrt.kbhit():
                ch = self._msvcrt.getch()
                try:
                    return ch.decode("utf-8", errors="ignore") or None
                except Exception:
                    return None
            return None

        import select

        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            return None
        try:
            return sys.stdin.read(1) or None
        except Exception:
            return None


@dataclass
class SimulatorState:
    operation_active: bool = False
    gate_open: bool = False
    gate_alarm: bool = False
    ring_light: int = int(mcu.RingLightColor.BLUE)
    basket_1_full: bool = False
    basket_2_full: bool = False
    basket_3_full: bool = False
    sort_plastic_active: bool = False
    sort_aluminum_active: bool = False
    reject_home: bool = True
    drop_sensor: bool = False
    exit_gate: bool = False
    last_weight_mg: int = 25000
    status_byte: int = 0x01


class MCUSimulator:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD, log_dir: Path | None = None, time_scale: float = 1.0):
        self.serial = Serial(port, baud, timeout=0.0)
        self.rx_buffer = bytearray()
        self.running = True
        self.time_scale = max(0.05, float(time_scale))
        self.scheduler = Scheduler()
        self.keys = KeyReader()
        self.state = SimulatorState()

        project_root = Path(__file__).resolve().parent
        self.logger = ProtocolLogger(log_dir or (project_root / "dropme_protocol_logs"))

        self._print_banner(port, baud)

    @staticmethod
    def ts_human() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _print_banner(self, port: str, baud: int) -> None:
        print("\n" + "=" * 72)
        print("  DropMe MCU Simulator - New Protocol")
        print("=" * 72)
        print(f"  Port: {port} @ {baud} baud")
        print(f"  Log : {self.logger.path}")
        print("=" * 72)
        for key, description in MANUAL_CONTROL_LINES:
            print(f"    {key} = {description}")
        print("=" * 72)
        print("\n  Waiting for frames...\n")

    def _scale(self, seconds: float) -> float:
        return float(seconds) * self.time_scale

    def _log_console(self, direction: str, frame: mcu.Frame, raw: bytes, note: str = "") -> None:
        payload_desc = mcu.get_payload_description(frame.cmd, frame.payload)
        line = f"[{self.ts_human()}] {direction} {get_cmd_name(frame.cmd):18s} PL:{payload_desc:>12s} | {raw.hex(' ')}"
        if note:
            line += f"    {note}"
        print(line)

    def _log_jsonl(self, direction: str, frame: mcu.Frame, raw: bytes, note: str = "") -> None:
        self.logger.write(
            {
                "ts": self.logger.now_iso(),
                "direction": direction,
                "cmd": frame.cmd,
                "cmd_name": get_cmd_name(frame.cmd),
                "payload": _payload_value(frame.payload),
                "payload_hex": frame.payload.hex(" "),
                "raw_hex": raw.hex(" "),
                "state": self.state.__dict__,
                "note": note,
            }
        )

    def _write_frame(self, cmd: int, payload: bytes = b"", note: str = "") -> None:
        frame = mcu.Frame(cmd=cmd, payload=payload)
        raw = frame.to_bytes()
        self.serial.write(raw)
        self._log_console("TX ->", frame, raw, note)
        self._log_jsonl("TX", frame, raw, note)

    def _send_ack_ok(self, note: str = "") -> None:
        self._write_frame(mcu.ResponseCode.ACK, b"OK", note or "ack ok")

    def _send_nack(self, payload: bytes = b"\x01", note: str = "") -> None:
        self._write_frame(mcu.ResponseCode.NACK, payload, note or "nack")

    def _send_data(self, payload: bytes, note: str = "") -> None:
        self._write_frame(mcu.ResponseCode.DATA, payload, note)

    def _send_error(self, payload: bytes = b"\x01", note: str = "") -> None:
        self._write_frame(mcu.ResponseCode.ERROR, payload, note or "error")

    def _send_status_ok(self, note: str = "") -> None:
        self._write_frame(mcu.AsyncEvent.STATUS_OK, b"", note or "status ok")

    def _send_item_placed(self, note: str = "") -> None:
        payload = int(self.state.last_weight_mg).to_bytes(4, "little", signed=True)
        self._write_frame(mcu.AsyncEvent.ITEM_PLACED, payload, note or "item placed")

    def _send_item_dropped(self, note: str = "") -> None:
        self.state.drop_sensor = True
        self._write_frame(mcu.AsyncEvent.ITEM_DROPPED, b"", note or "item dropped")
        self.scheduler.call_later(self._scale(0.15), lambda: setattr(self.state, "drop_sensor", False))

    def _send_basket_status(self, note: str = "") -> None:
        mask = (
            (0x01 if self.state.basket_1_full else 0x00)
            | (0x02 if self.state.basket_2_full else 0x00)
            | (0x04 if self.state.basket_3_full else 0x00)
        )
        self._write_frame(mcu.AsyncEvent.BASKET_STATUS, bytes([mask]), note or "basket status")

    def _send_bad_crc(self) -> None:
        raw = bytearray(mcu.Frame(cmd=mcu.ResponseCode.ACK, payload=b"OK").to_bytes())
        raw[-1] ^= 0xFF
        self.serial.write(raw)
        print(f"[{self.ts_human()}] TX -> BAD_CRC_FRAME       | {bytes(raw).hex(' ')}")

    def _sensor_state(self, sensor_id: int) -> int:
        if sensor_id == int(mcu.SensorSelector.SORT_PLASTIC):
            return int(self.state.sort_plastic_active)
        if sensor_id == int(mcu.SensorSelector.SORT_ALUMINUM):
            return int(self.state.sort_aluminum_active)
        if sensor_id == int(mcu.SensorSelector.GATE_CLOSED):
            return int(not self.state.gate_open)
        if sensor_id == int(mcu.SensorSelector.GATE_OPENED):
            return int(self.state.gate_open)
        if sensor_id == int(mcu.SensorSelector.EXIT_GATE):
            return int(self.state.exit_gate)
        if sensor_id == int(mcu.SensorSelector.GATE_ALARM):
            return int(self.state.gate_alarm)
        if sensor_id == int(mcu.SensorSelector.REJECT_HOME):
            return int(self.state.reject_home)
        if sensor_id == int(mcu.SensorSelector.DROP_SENSOR):
            return int(self.state.drop_sensor)
        if sensor_id == int(mcu.SensorSelector.BASKET_1):
            return int(self.state.basket_1_full)
        if sensor_id == int(mcu.SensorSelector.BASKET_2):
            return int(self.state.basket_2_full)
        if sensor_id == int(mcu.SensorSelector.BASKET_3):
            return int(self.state.basket_3_full)
        return 0

    def handle_rx(self, frame: mcu.Frame, raw: bytes) -> None:
        self._log_console("RX <-", frame, raw)
        self._log_jsonl("RX", frame, raw)

        cmd = int(frame.cmd)
        payload = frame.payload

        if not mcu.matches_reference_request_bytes(cmd, payload, raw):
            expected = mcu.reference_tx_bytes(cmd, payload)
            note = f"reference mismatch expected={expected.hex(' ') if expected else 'n/a'}"
            self._send_nack(b"\x01", note)
            return

        if cmd == int(mcu.SystemControl.PING):
            self._send_ack_ok("ping")
            return

        if cmd == int(mcu.SystemControl.GET_MCU_STATUS):
            self._send_data(bytes([self.state.status_byte]), "status byte")
            return

        if cmd == int(mcu.SystemControl.SYSTEM_RESET):
            self.state = SimulatorState()
            return

        if cmd == int(mcu.ReadCommand.POLL_WEIGHT):
            payload_out = int(self.state.last_weight_mg).to_bytes(4, "little", signed=True)
            self._send_data(payload_out, "weight mg")
            return

        if cmd == int(mcu.ReadCommand.READ_SENSOR):
            sensor_id = payload[0] if payload else 0
            sensor_state = self._sensor_state(sensor_id)
            self._send_data(bytes([sensor_id, sensor_state]), f"sensor {mcu.get_payload_description(cmd, bytes([sensor_id]))}")
            return

        if cmd == int(mcu.DeviceControl.RING_LIGHT):
            self.state.ring_light = payload[0] if payload else int(mcu.RingLightColor.BLUE)
            return

        if cmd == int(mcu.DeviceControl.BUZZER_BEEP):
            return

        if cmd == int(mcu.SessionControl.REQUEST_SEQUENCE_STATUS):
            self.state.status_byte = 0x01
            self.scheduler.call_later(self._scale(0.10), lambda: self._send_status_ok("sequence status"))
            return

        if cmd == int(mcu.SessionControl.START_SESSION):
            self.state.operation_active = True
            self.state.gate_open = True
            self.state.ring_light = int(mcu.RingLightColor.BLUE)
            self.state.status_byte = 0x02
            return

        if cmd == int(mcu.SessionControl.ACCEPT_ITEM):
            item_type = payload[0] if payload else int(mcu.ItemType.PLASTIC)
            self.state.sort_plastic_active = item_type == int(mcu.ItemType.PLASTIC)
            self.state.sort_aluminum_active = item_type == int(mcu.ItemType.ALUMINUM)
            self.state.last_weight_mg = random.randint(10000, 45000)

            def _finish_drop() -> None:
                self.state.sort_plastic_active = False
                self.state.sort_aluminum_active = False
                self._send_item_dropped("accept item")

            self.scheduler.call_later(self._scale(0.30), _finish_drop)
            return

        if cmd == int(mcu.SessionControl.REJECT_ITEM):
            self.state.sort_plastic_active = False
            self.state.sort_aluminum_active = False
            self.state.reject_home = True
            self.state.ring_light = int(mcu.RingLightColor.BLUE)
            return

        if cmd == int(mcu.SessionControl.END_SESSION):
            self.state.operation_active = False
            self.state.gate_open = False
            self.state.status_byte = 0x01
            self.scheduler.call_later(self._scale(0.20), lambda: self._send_basket_status("end session"))
            return

        self._send_error(b"\xFF", "unknown command")

    def handle_key(self, key: str) -> None:
        key = key.lower()

        if key == "o":
            self._send_ack_ok("operator")
        elif key == "k":
            self._send_status_ok("operator")
        elif key == "p":
            self.state.last_weight_mg = random.randint(10000, 200000)
            self._send_item_placed("operator")
        elif key == "d":
            self._send_item_dropped("operator")
        elif key == "b":
            self._send_basket_status("operator")
        elif key == "w":
            self.state.last_weight_mg = random.randint(10000, 200000)
            self._send_data(self.state.last_weight_mg.to_bytes(4, "little", signed=True), "operator weight")
        elif key == "1":
            self.state.basket_1_full = not self.state.basket_1_full
        elif key == "2":
            self.state.basket_2_full = not self.state.basket_2_full
        elif key == "3":
            self.state.basket_3_full = not self.state.basket_3_full
        elif key == "h":
            self.state.gate_alarm = True
        elif key == "u":
            self.state.gate_alarm = False
        elif key == "x":
            self._send_bad_crc()
        elif key == "s":
            print(f"\n  State: {self.state}\n")
        elif key == "q":
            print("\nQuitting...")
            self.running = False

    def run(self) -> None:
        try:
            while self.running:
                waiting = self.serial.in_waiting
                if waiting:
                    self.rx_buffer.extend(self.serial.read(waiting))

                while self.rx_buffer:
                    frame, consumed = mcu.Frame.try_parse_from_buffer(self.rx_buffer)
                    if consumed == 0:
                        break

                    chunk = bytes(self.rx_buffer[:consumed])
                    del self.rx_buffer[:consumed]

                    if frame is None:
                        reference = mcu.parse_reference_request_bytes(chunk)
                        if reference is not None:
                            cmd, payload = reference
                            self.handle_rx(mcu.Frame(cmd=cmd, payload=payload), chunk)
                            continue
                        self.logger.write({"ts": self.logger.now_iso(), "direction": "RX_INVALID", "raw_hex": chunk.hex(" ")})
                        print(f"[{self.ts_human()}] RX <- INVALID_FRAME      | {chunk.hex(' ')}")
                        if chunk and chunk[0] == mcu.START_BYTE:
                            self._send_nack(b"\x01", "invalid crc/frame")
                        continue

                    self.handle_rx(frame, chunk)

                self.scheduler.run_ready()

                key = self.keys.poll()
                if key and key.strip():
                    self.handle_key(key)

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
    except SerialException as exc:
        print(f"\nError: Could not open {port}")
        print(f"Details: {exc}")
        print("\nSetup tips:")
        print("  Windows:")
        print("    - Install com0com")
        print("    - Create paired ports: COM10 <-> COM11")
        print("    - Run: python src/gui/enhanced_mcu_simulator.py COM10")
        print("    - GUI connects to COM11")
        sys.exit(1)


if __name__ == "__main__":
    main()
