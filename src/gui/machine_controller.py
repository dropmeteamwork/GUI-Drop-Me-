from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from gui import mcu


class ProcessingState:
    IDLE = None

    ACCEPT_SORT = "ACCEPT_SORT"
    ACCEPT_CONVEYOR = "ACCEPT_CONVEYOR"

    REJECT_ACTIVATE = "REJECT_ACTIVATE"
    REJECT_HOME = "REJECT_HOME"

    CLOSING_GATE = "CLOSING_GATE"
    ENDING_OPERATION = "ENDING_OPERATION"


@dataclass(slots=True)
class Command:
    cmd: int
    payload: int = 0x00


@dataclass(slots=True)
class ControllerResult:
    commands: list[Command] = field(default_factory=list)
    emit_plastic_accepted: bool = False
    emit_can_accepted: bool = False
    emit_item_rejected: bool = False
    end_sequence_complete: bool = False
    start_gate_retry_timer: bool = False
    stop_gate_retry_timer: bool = False
    blocked_by_gate: bool = False
    blocked_by_fraud: bool = False
    blocked_by_busy: bool = False
    dropped: bool = False


class MachineController:
    """Core machine workflow controller decoupled from Qt/serial transport."""

    def __init__(self, max_gate_close_retries: int = 5) -> None:
        self.max_gate_close_retries = int(max_gate_close_retries)
        self.processing_state = ProcessingState.IDLE
        self.pending_item_type: Optional[str] = None
        self.pending_gate_close = False
        self.gate_close_retry_count = 0

    def reset(self) -> None:
        self.processing_state = ProcessingState.IDLE
        self.pending_item_type = None
        self.pending_gate_close = False
        self.gate_close_retry_count = 0

    def is_processing(self) -> bool:
        return self.processing_state != ProcessingState.IDLE

    def abort_processing(self) -> ControllerResult:
        self.processing_state = ProcessingState.IDLE
        self.pending_item_type = None
        self.pending_gate_close = False
        return ControllerResult(stop_gate_retry_timer=True)

    def request_end_operation(self) -> ControllerResult:
        self.processing_state = ProcessingState.ENDING_OPERATION
        return ControllerResult(commands=[Command(mcu.OperationControl.OP_END)])

    def request_close_gate(self, gate_blocked: bool) -> ControllerResult:
        self.pending_gate_close = True
        self.gate_close_retry_count = 0
        self.processing_state = ProcessingState.CLOSING_GATE
        return self.attempt_gate_close(gate_blocked)

    def attempt_gate_close(self, gate_blocked: bool) -> ControllerResult:
        if not self.pending_gate_close:
            return ControllerResult()

        if gate_blocked:
            return ControllerResult(start_gate_retry_timer=True)

        if self.gate_close_retry_count >= self.max_gate_close_retries:
            self.pending_gate_close = False
            self.processing_state = ProcessingState.IDLE
            return ControllerResult(stop_gate_retry_timer=True, dropped=True)

        self.gate_close_retry_count += 1
        return ControllerResult(commands=[Command(mcu.MotionControl.GATE_CLOSE)])

    def on_system_idle(self, gate_blocked: bool) -> ControllerResult:
        if self.processing_state != ProcessingState.ENDING_OPERATION:
            return ControllerResult()

        self.processing_state = ProcessingState.CLOSING_GATE
        self.pending_gate_close = True
        return self.attempt_gate_close(gate_blocked)

    def on_gate_closed(self) -> ControllerResult:
        self.pending_gate_close = False
        self.gate_close_retry_count = 0

        done = self.processing_state == ProcessingState.CLOSING_GATE
        if done:
            self.processing_state = ProcessingState.IDLE

        return ControllerResult(end_sequence_complete=done, stop_gate_retry_timer=True)

    def on_gate_blocked(self) -> ControllerResult:
        if self.pending_gate_close:
            return ControllerResult(start_gate_retry_timer=True)
        return ControllerResult()

    def on_sort_done(self) -> ControllerResult:
        if self.processing_state != ProcessingState.ACCEPT_SORT:
            return ControllerResult()

        self.processing_state = ProcessingState.ACCEPT_CONVEYOR
        return ControllerResult(commands=[Command(mcu.MotionControl.CONVEYOR_RUN, mcu.CONVEYOR_TIME_ACCEPT)])

    def on_conveyor_done(self) -> ControllerResult:
        if self.processing_state != ProcessingState.ACCEPT_CONVEYOR:
            self.processing_state = ProcessingState.IDLE
            self.pending_item_type = None
            return ControllerResult()

        result = ControllerResult()
        if self.pending_item_type == "plastic":
            result.emit_plastic_accepted = True
        elif self.pending_item_type == "can":
            result.emit_can_accepted = True

        self.pending_item_type = None
        self.processing_state = ProcessingState.IDLE
        return result

    def on_reject_done(self) -> ControllerResult:
        if self.processing_state != ProcessingState.REJECT_ACTIVATE:
            return ControllerResult()

        self.processing_state = ProcessingState.REJECT_HOME
        return ControllerResult(commands=[Command(mcu.MotionControl.REJECT_HOME)])

    def on_reject_home_ok(self) -> ControllerResult:
        if self.processing_state != ProcessingState.REJECT_HOME:
            return ControllerResult()

        self.pending_item_type = None
        self.processing_state = ProcessingState.IDLE
        return ControllerResult(emit_item_rejected=True)

    def on_error(self) -> ControllerResult:
        return self.abort_processing()

    def on_command_timeout(self) -> ControllerResult:
        return self.abort_processing()

    def request_accept_sequence(self, item_type: str, gate_blocked: bool, fraud_hold: bool) -> ControllerResult:
        if fraud_hold:
            return ControllerResult(blocked_by_fraud=True)

        if gate_blocked:
            return ControllerResult(blocked_by_gate=True)

        if self.processing_state != ProcessingState.IDLE:
            return ControllerResult(blocked_by_busy=True)

        payload = mcu.ItemType.PLASTIC if item_type == "plastic" else mcu.ItemType.CAN
        self.pending_item_type = item_type
        self.processing_state = ProcessingState.ACCEPT_SORT
        return ControllerResult(
            commands=[
                Command(mcu.Classification.ITEM_ACCEPT, payload),
                Command(mcu.MotionControl.SORT_SET, payload),
            ]
        )

    def request_reject_sequence(self, gate_blocked: bool, fraud_hold: bool) -> ControllerResult:
        if fraud_hold:
            return ControllerResult(blocked_by_fraud=True)

        if gate_blocked:
            return ControllerResult(blocked_by_gate=True)

        if self.processing_state != ProcessingState.IDLE:
            return ControllerResult(blocked_by_busy=True)

        self.pending_item_type = "reject"
        self.processing_state = ProcessingState.REJECT_ACTIVATE
        return ControllerResult(
            commands=[
                Command(mcu.Classification.ITEM_REJECT, 0x00),
                Command(mcu.MotionControl.REJECT_ACTIVATE),
            ]
        )
