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


def _read_frame(ser, timeout=2.0):
    from gui import mcu

    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        chunk = ser.read(64)
        if chunk:
            buf.extend(chunk)
            frame, consumed = mcu.Frame.try_parse_from_buffer(buf)
            if frame is not None and consumed > 0:
                return frame
            if consumed > 0:
                del buf[:consumed]
    return None


def test_simulator_protocol_flow_ping_status_sensor():
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
        with serial_mod.Serial(gui_port, mcu.BAUD_RATE, timeout=0.2) as ser:
            ser.write(mcu.Frame(cmd=mcu.SystemControl.PING, payload=b"").to_bytes())
            frame = _read_frame(ser)
            assert frame is not None
            assert frame.cmd == int(mcu.ResponseCode.ACK)
            assert frame.payload == b"OK"

            ser.write(mcu.Frame(cmd=mcu.SystemControl.GET_MCU_STATUS, payload=b"").to_bytes())
            frame = _read_frame(ser)
            assert frame is not None
            assert frame.cmd == int(mcu.ResponseCode.DATA)
            assert len(frame.payload) == 1

            ser.write(mcu.Frame(cmd=mcu.ReadCommand.READ_SENSOR, payload=bytes([int(mcu.SensorSelector.GATE_CLOSED)])).to_bytes())
            frame = _read_frame(ser)
            assert frame is not None
            assert frame.cmd == int(mcu.ResponseCode.DATA)
            assert frame.payload[0] == int(mcu.SensorSelector.GATE_CLOSED)
    finally:
        sim_proc.terminate()
        try:
            sim_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            sim_proc.kill()
