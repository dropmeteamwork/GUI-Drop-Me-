from gui.machine_controller import MachineController, ProcessingState
from gui import mcu


def test_accept_sequence_happy_path():
    c = MachineController()

    req = c.request_accept_sequence("plastic", gate_blocked=False, fraud_hold=False)
    assert [cmd.cmd for cmd in req.commands] == [mcu.Classification.ITEM_ACCEPT, mcu.MotionControl.SORT_SET]
    assert c.processing_state == ProcessingState.ACCEPT_SORT

    sort_done = c.on_sort_done()
    assert [cmd.cmd for cmd in sort_done.commands] == [mcu.MotionControl.CONVEYOR_RUN]
    assert c.processing_state == ProcessingState.ACCEPT_CONVEYOR

    conv_done = c.on_conveyor_done()
    assert conv_done.emit_plastic_accepted is True
    assert c.processing_state == ProcessingState.IDLE


def test_reject_sequence_happy_path():
    c = MachineController()

    req = c.request_reject_sequence(gate_blocked=False, fraud_hold=False)
    assert [cmd.cmd for cmd in req.commands] == [mcu.Classification.ITEM_REJECT, mcu.MotionControl.REJECT_ACTIVATE]
    assert c.processing_state == ProcessingState.REJECT_ACTIVATE

    rej_done = c.on_reject_done()
    assert [cmd.cmd for cmd in rej_done.commands] == [mcu.MotionControl.REJECT_HOME]
    assert c.processing_state == ProcessingState.REJECT_HOME

    home_ok = c.on_reject_home_ok()
    assert home_ok.emit_item_rejected is True
    assert c.processing_state == ProcessingState.IDLE


def test_end_flow_transitions_to_gate_close():
    c = MachineController()

    end_req = c.request_end_operation()
    assert [cmd.cmd for cmd in end_req.commands] == [mcu.OperationControl.OP_END]
    assert c.processing_state == ProcessingState.ENDING_OPERATION

    idle = c.on_system_idle(gate_blocked=False)
    assert [cmd.cmd for cmd in idle.commands] == [mcu.MotionControl.GATE_CLOSE]
    assert c.processing_state == ProcessingState.CLOSING_GATE

    closed = c.on_gate_closed()
    assert closed.end_sequence_complete is True
    assert c.processing_state == ProcessingState.IDLE


def test_gate_close_retry_drop_after_max_attempts():
    c = MachineController(max_gate_close_retries=1)

    blocked = c.request_close_gate(gate_blocked=True)
    assert blocked.start_gate_retry_timer is True

    first = c.attempt_gate_close(gate_blocked=False)
    assert [cmd.cmd for cmd in first.commands] == [mcu.MotionControl.GATE_CLOSE]

    drop = c.attempt_gate_close(gate_blocked=False)
    assert drop.dropped is True
    assert c.processing_state == ProcessingState.IDLE


def test_blocked_states():
    c = MachineController()

    fraud = c.request_accept_sequence("can", gate_blocked=False, fraud_hold=True)
    assert fraud.blocked_by_fraud is True

    gate = c.request_reject_sequence(gate_blocked=True, fraud_hold=False)
    assert gate.blocked_by_gate is True
