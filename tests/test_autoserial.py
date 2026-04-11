import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication

from gui import mcu
from gui.autoserial import AutoSerial


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_item_placed_promotes_session_when_gate_open_sensor_is_missing():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "await_gate_open"
    serial._gate_open_deadline = 123.0
    serial._gate_open = False
    serial._gate_blocked = False
    serial._sensor_states["gate_closed"] = 0
    serial._sensor_states["gate_opened"] = 0
    serial._sensor_states["gate_alarm"] = 0

    ready_hits = []
    serial.ready.connect(lambda: ready_hits.append(True))

    weight_mg = 16431
    frame = mcu.Frame(cmd=mcu.AsyncEvent.ITEM_PLACED, payload=weight_mg.to_bytes(4, "little", signed=True))
    serial._handle_frame(frame, frame.to_bytes())

    assert serial._session_stage == "active"
    assert serial._gate_open_deadline == 0.0
    assert serial._last_weight_grams == 16
    assert ready_hits == [True]


def test_item_placed_below_threshold_is_ignored():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "await_gate_open"
    serial._gate_open_deadline = 123.0
    serial._gate_open = False
    serial._gate_blocked = False
    serial._sensor_states["gate_closed"] = 0

    ready_hits = []
    serial.ready.connect(lambda: ready_hits.append(True))

    weight_mg = 9000
    frame = mcu.Frame(cmd=mcu.AsyncEvent.ITEM_PLACED, payload=weight_mg.to_bytes(4, "little", signed=True))
    serial._handle_frame(frame, frame.to_bytes())

    assert serial._session_stage == "await_gate_open"
    assert serial._gate_open_deadline == 123.0
    assert serial._last_weight_grams == 0
    assert ready_hits == []
