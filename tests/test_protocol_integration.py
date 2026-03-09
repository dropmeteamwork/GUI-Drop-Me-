import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.integration


def _try_import_serial():
    try:
        import serial  # type: ignore
        return serial
    except Exception:
        return None


def _read_frame(ser, size=6, timeout=2.0):
    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline and len(buf) < size:
        chunk = ser.read(size - len(buf))
        if chunk:
            buf.extend(chunk)
    return bytes(buf)


def test_simulator_protocol_flow_sys_init_ping_gate_open():
    serial_mod = _try_import_serial()
    if serial_mod is None:
        pytest.skip("pyserial is not installed")

    sim_port = os.getenv("DROPME_SIM_PORT")
    gui_port = os.getenv("DROPME_GUI_PORT")
    if not sim_port or not gui_port:
        pytest.skip("Set DROPME_SIM_PORT and DROPME_GUI_PORT to a paired virtual serial ports")

    from gui import mcu

    sim_proc = subprocess.Popen(
        [sys.executable, "src/gui/enhanced_mcu_simulator.py", sim_port],
        cwd=os.getcwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        time.sleep(1.2)
        with serial_mod.Serial(gui_port, 9600, timeout=0.2) as ser:
            # SYS_INIT -> SYS_READY
            ser.write(mcu.Frame(1, mcu.SystemControl.SYS_INIT, 0).to_bytes())
            raw = _read_frame(ser)
            frame = mcu.Frame.from_bytes(raw)
            assert frame is not None
            assert frame.cmd == int(mcu.StatusFeedback.SYS_READY)

            # SYS_PING -> SYS_IDLE or SYS_BUSY
            ser.write(mcu.Frame(2, mcu.SystemControl.SYS_PING, 0).to_bytes())
            raw = _read_frame(ser)
            frame = mcu.Frame.from_bytes(raw)
            assert frame is not None
            assert frame.cmd in (int(mcu.StatusFeedback.SYS_IDLE), int(mcu.StatusFeedback.SYS_BUSY))

            # GATE_OPEN -> GATE_OPENED
            ser.write(mcu.Frame(3, mcu.MotionControl.GATE_OPEN, 0).to_bytes())
            raw = _read_frame(ser)
            frame = mcu.Frame.from_bytes(raw)
            assert frame is not None
            assert frame.cmd == int(mcu.StatusFeedback.GATE_OPENED)
    finally:
        sim_proc.terminate()
        try:
            sim_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            sim_proc.kill()
