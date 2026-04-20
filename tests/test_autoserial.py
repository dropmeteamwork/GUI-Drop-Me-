from collections import deque

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


def test_item_placed_before_gate_open_is_ignored_until_gate_is_confirmed_open():
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

    assert serial._session_stage == "await_gate_open"
    assert serial._gate_open_deadline == 123.0
    assert serial._last_weight_grams == 16
    assert ready_hits == []


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


def test_gate_open_confirmed_waits_for_first_item_before_starting_idle_timeout():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "await_gate_open"
    serial._gate_open_deadline = 123.0

    serial._handle_gate_open_confirmed()

    assert serial._session_stage == "active"
    assert serial._awaiting_first_item_after_gate_open is True
    assert serial._session_idle_timer.isActive() is False


def test_ping_timeout_during_fresh_active_session_keeps_session_alive():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "active"
    serial._awaiting_first_item_after_gate_open = True
    serial._pending_requests.append(
        {
            "cmd": int(mcu.SystemControl.PING),
            "payload": b"",
            "expected": (int(mcu.ResponseCode.ACK),),
            "sent_at": 0.0,
            "deadline": 0.0,
            "stage": "active",
        }
    )

    serial._on_command_timeout()

    assert serial._session_stage == "active"
    assert serial._pending_requests == deque()


def test_reject_sequence_returns_to_active_immediately():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "active"
    serial._current_prediction = "other"
    serial._current_prediction_confidence = 1.0
    serial._last_weight_grams = 18

    sent = []
    reject_hits = []
    serial._send = lambda cmd, payload=b"": sent.append((cmd, payload)) or True
    serial.itemRejected.connect(lambda: reject_hits.append("rejected"))

    ok = serial._start_reject_sequence()

    assert ok is True
    assert sent == [(int(mcu.SessionControl.REJECT_ITEM), b"\x01")]
    assert serial._session_stage == "active"
    assert serial._current_prediction == ""
    assert serial._last_weight_grams == 0
    assert reject_hits == ["rejected"]


def test_accept_sequence_returns_to_active_immediately_when_item_dropped_disabled():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "active"

    sent = []
    plastic_hits = []
    conveyor_hits = []
    serial._send = lambda cmd, payload=b"": sent.append((cmd, payload)) or True
    serial.plasticAccepted.connect(lambda: plastic_hits.append("plastic"))
    serial.conveyorDone.connect(lambda: conveyor_hits.append("done"))

    ok = serial._start_accept_sequence("plastic")

    assert ok is True
    assert sent == [(int(mcu.SessionControl.ACCEPT_ITEM), bytes([int(mcu.ItemType.PLASTIC)]))]
    assert serial._session_stage == "active"
    assert plastic_hits == ["plastic"]
    assert conveyor_hits == ["done"]
    assert serial._pending_exit_verification is None


def test_exit_gate_verification_is_skipped_by_default():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._current_prediction = "aluminum"
    serial._current_prediction_confidence = 1.0
    serial._last_weight_grams = 20

    serial._start_exit_gate_verification("can")

    assert serial._pending_exit_verification is None
    assert serial._last_weight_grams == 0
    assert serial._current_prediction == ""


def test_weight_is_not_item_evidence_by_default():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._last_weight_grams = 25
    serial._current_prediction = ""

    assert serial._has_item_evidence() is False


def test_detection_allowed_ignores_gate_alarm_block():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "active"
    serial._gate_blocked = True
    serial._fraud_hold = False

    assert serial.isDetectionAllowed() is True


def test_reject_sequence_not_blocked_by_gate_alarm():
    _app()
    serial = AutoSerial()
    serial.scan_timer.stop()
    serial.ping_timer.stop()
    serial.bin_poll_timer.stop()
    serial._sensor_poll_timer.stop()

    serial._session_stage = "active"
    serial._gate_blocked = True

    sent = []
    serial._send = lambda cmd, payload=b"": sent.append((cmd, payload)) or True

    ok = serial._start_reject_sequence()

    assert ok is True
    assert sent == [(int(mcu.SessionControl.REJECT_ITEM), b"\x01")]
