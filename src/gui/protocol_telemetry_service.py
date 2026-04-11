from __future__ import annotations

import copy
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from gui import mcu


class ProtocolTelemetryService:
    """Persists protocol, sensor, and state telemetry independent of serial transport."""

    def __init__(self, logger, log_dir: Path, machine_name: str, telemetry_uploader=None) -> None:
        self.logger = logger
        self.log_dir = Path(log_dir)
        self.machine_name = str(machine_name)
        self.telemetry_uploader = telemetry_uploader

        self.protocol_log_file = self.log_dir / "protocol_events.jsonl"
        self.weights_log_file = self.log_dir / "weights.csv"
        self.sensor_events_file = self.log_dir / "sensor_events.jsonl"
        self.sensor_snapshot_file = self.log_dir / "sensor_snapshot.json"
        self.protocol_state_file = self.log_dir / "protocol_state.json"
        self.session_events_file = self.log_dir / "session_events.csv"

        self._protocol_state = self._build_initial_protocol_state()
        self._protocol_state_serialized = ""

    def initialize(self) -> None:
        self._init_weights_log()
        self._init_sensor_logs()
        self._init_session_events_log()
        self.write_protocol_state_if_changed(force=True)

    def log_weight(self, weight_grams: int, session_id: str | None, port_name: str | None) -> None:
        try:
            with self.weights_log_file.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    [
                        self._now_iso(),
                        session_id or "no_session",
                        int(weight_grams),
                        port_name or "unknown",
                    ]
                )
            self.logger.info(f"Logged weight: {weight_grams}g")
        except Exception as exc:
            self.logger.warning(f"Failed to log weight: {exc}")

    def append_protocol_event(self, event: dict[str, Any], session_id: str | None) -> None:
        try:
            row = dict(event)
            if session_id and "session_id" not in row:
                row["session_id"] = session_id
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with self.protocol_log_file.open("a", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False)
                f.write("\n")
        except Exception as exc:
            self.logger.warning(f"Protocol log failed: {exc}")

    def log_session_event(
        self,
        *,
        session_id: str | None,
        stage: str,
        direction: str,
        event_name: str,
        raw_hex: str = "",
        crc_valid: bool | None = None,
        payload_summary: str = "",
        prediction: str = "",
        confidence: float | None = None,
        weight_grams: int | None = None,
        sensors: dict[str, Any] | None = None,
        note: str = "",
    ) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            sensors_json = json.dumps(sensors or {}, ensure_ascii=False, sort_keys=True)
            with self.session_events_file.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    [
                        self._now_iso(),
                        session_id or "",
                        str(stage),
                        str(direction),
                        str(event_name),
                        str(raw_hex),
                        "" if crc_valid is None else int(bool(crc_valid)),
                        str(payload_summary),
                        str(prediction),
                        "" if confidence is None else float(confidence),
                        "" if weight_grams is None else int(weight_grams),
                        sensors_json,
                        str(note),
                    ]
                )
        except Exception as exc:
            self.logger.warning(f"Session event log failed: {exc}")

    def write_sensor_snapshot(self, snapshot: dict[str, Any]) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with self.sensor_snapshot_file.open("w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.logger.warning(f"Failed to write sensor snapshot: {exc}")

    def append_sensor_event(
        self,
        kind: str,
        payload: int,
        session_id: str | None,
        port_name: str | None,
        snapshot: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            event: dict[str, Any] = {
                "ts": self._now_iso(),
                "session_id": session_id or "",
                "port": port_name or "",
                "kind": str(kind),
                "payload": int(payload),
            }
            if extra:
                event.update(extra)
            with self.sensor_events_file.open("a", encoding="utf-8") as f:
                json.dump(event, f, ensure_ascii=False)
                f.write("\n")
        except Exception as exc:
            self.logger.warning(f"Sensor event log failed: {exc}")
        self.write_sensor_snapshot(snapshot)

    def sync_connection_state(self, connected: bool, port_name: str | None) -> None:
        conn = self._protocol_state["connection"]
        conn["connected"] = bool(connected)
        conn["port"] = port_name or ""
        if not connected:
            conn["last_disconnect_ts"] = self._now_iso()
        self.write_protocol_state_if_changed()

    def reduce_protocol_state(
        self,
        direction: str,
        frame: mcu.Frame,
        raw: bytes,
        connected: bool,
        port_name: str | None,
    ) -> None:
        ts = self._now_iso()
        cmd = int(frame.cmd)
        payload = mcu.payload_to_int(frame.payload)
        cmd_name = mcu.get_command_name(cmd)
        group = self._cmd_group(cmd)

        conn = self._protocol_state["connection"]
        conn["connected"] = bool(connected)
        conn["port"] = port_name or ""

        if direction == "RX":
            conn["last_rx_ts"] = ts
            conn["last_rx_seq"] = int(frame.seq) if frame.seq is not None else None
            conn["last_rx_raw"] = raw.hex(" ")
        else:
            conn["last_tx_ts"] = ts
            conn["last_tx_seq"] = int(frame.seq) if frame.seq is not None else None
            conn["last_tx_raw"] = raw.hex(" ")

        self._protocol_state["commands"][cmd_name] = {
            "cmd": cmd,
            "payload": payload,
            "direction": direction,
        }

        if group:
            section = self._protocol_state[group]
            if (
                section.get("last_cmd") != cmd_name
                or section.get("last_payload") != payload
                or section.get("last_direction") != direction
            ):
                section["last_cmd"] = cmd_name
                section["last_payload"] = payload
                section["last_direction"] = direction
                section["last_update"] = ts

        if cmd == mcu.ResponseCode.ACK:
            self._protocol_state["system_status"]["state"] = "ack"
        elif cmd == mcu.AsyncEvent.STATUS_OK:
            self._protocol_state["system_status"]["state"] = "ready"

        if cmd == mcu.SessionControl.START_SESSION and direction == "TX":
            self._protocol_state["operation"]["active"] = True
        elif cmd in (mcu.SystemControl.SYSTEM_RESET, mcu.SessionControl.END_SESSION) and direction == "TX":
            self._protocol_state["operation"]["active"] = False

        if cmd == mcu.ResponseCode.ERROR or cmd == mcu.ResponseCode.NACK:
            self._protocol_state["errors"]["last_error_cmd"] = cmd_name
            self._protocol_state["errors"]["last_error_payload"] = payload
            self._protocol_state["errors"]["last_direction"] = direction
            self._protocol_state["errors"]["last_update"] = ts

        self.write_protocol_state_if_changed()

    def write_protocol_state_if_changed(self, force: bool = False) -> None:
        try:
            fingerprint = self._protocol_state_fingerprint(self._protocol_state)
            if not force and fingerprint == self._protocol_state_serialized:
                return

            state_to_write = copy.deepcopy(self._protocol_state)
            state_to_write["updated_at"] = self._now_iso()
            self._write_json_atomic(self.protocol_state_file, state_to_write)

            self._protocol_state["updated_at"] = state_to_write["updated_at"]
            self._protocol_state_serialized = fingerprint

            try:
                if self.telemetry_uploader is not None:
                    self.telemetry_uploader.upload_serial_state(state_to_write)
            except Exception as upload_exc:
                self.logger.warning(f"Protocol state S3 mirror failed: {upload_exc}")
        except Exception as exc:
            self.logger.warning(f"Failed to persist protocol_state.json: {exc}")

    def _init_weights_log(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            if not self.weights_log_file.exists():
                with self.weights_log_file.open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(["timestamp", "session_id", "weight_grams", "port"])
                self.logger.info(f"Created weights log: {self.weights_log_file}")
        except Exception as exc:
            self.logger.warning(f"Failed to init weights log: {exc}")

    def _init_sensor_logs(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            if not self.sensor_snapshot_file.exists():
                self.write_sensor_snapshot({})
        except Exception as exc:
            self.logger.warning(f"Failed to init sensor logs: {exc}")

    def _init_session_events_log(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            if not self.session_events_file.exists():
                with self.session_events_file.open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(
                        [
                            "timestamp",
                            "session_id",
                            "stage",
                            "direction",
                            "event_name",
                            "raw_hex",
                            "crc_valid",
                            "payload_summary",
                            "prediction",
                            "confidence",
                            "weight_grams",
                            "sensors_json",
                            "note",
                        ]
                    )
        except Exception as exc:
            self.logger.warning(f"Failed to init session events log: {exc}")

    def _now_iso(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _build_known_commands_map(self) -> dict[str, dict[str, Any]]:
        commands: dict[str, dict[str, Any]] = {}
        for enum_class in (
            mcu.SystemControl,
            mcu.ReadCommand,
            mcu.DeviceControl,
            mcu.SessionControl,
            mcu.AsyncEvent,
            mcu.ResponseCode,
        ):
            for item in enum_class:
                commands[item.name] = {"cmd": int(item.value), "payload": None, "direction": ""}
        return commands

    def _build_initial_protocol_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "updated_at": "",
            "machine_name": self.machine_name,
            "connection": {
                "connected": False,
                "port": "",
                "last_rx_ts": "",
                "last_tx_ts": "",
                "last_disconnect_ts": "",
                "last_rx_seq": None,
                "last_tx_seq": None,
                "last_rx_raw": "",
                "last_tx_raw": "",
            },
            "system_status": {"state": "unknown", "last_cmd": "", "last_payload": 0, "last_direction": "", "last_update": ""},
            "operation": {"active": False, "last_cmd": "", "last_payload": 0, "last_direction": "", "last_update": ""},
            "motion": {
                "gate_open": False,
                "gate_blocked": False,
                "last_cmd": "",
                "last_payload": 0,
                "last_direction": "",
                "last_update": "",
            },
            "classification": {"last_cmd": "", "last_payload": 0, "last_direction": "", "last_update": ""},
            "sensor": {
                "weight_grams": None,
                "bin_plastic_full": False,
                "bin_can_full": False,
                "bin_reject_full": False,
                "last_cmd": "",
                "last_payload": 0,
                "last_direction": "",
                "last_update": "",
            },
            "errors": {"last_error_cmd": "", "last_error_payload": 0, "last_direction": "", "last_update": ""},
            "commands": self._build_known_commands_map(),
        }

    def _protocol_state_fingerprint(self, state: dict[str, Any]) -> str:
        stable = copy.deepcopy(state)
        stable["updated_at"] = ""
        conn = stable.get("connection", {})
        for key in ("last_rx_ts", "last_tx_ts", "last_disconnect_ts", "last_rx_seq", "last_tx_seq", "last_rx_raw", "last_tx_raw"):
            conn[key] = "" if "ts" in key or "raw" in key else None
        for group in ("system_status", "operation", "motion", "classification", "sensor", "errors"):
            if group in stable and isinstance(stable[group], dict):
                stable[group]["last_update"] = ""
        return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _cmd_group(self, cmd: int) -> str:
        if 0x01 <= cmd <= 0x0F or 0x70 <= cmd <= 0x7F or 0xA0 <= cmd <= 0xAF:
            return "system_status"
        if 0x10 <= cmd <= 0x1F:
            return "sensor"
        if 0x50 <= cmd <= 0x5F:
            return "motion"
        if 0x60 <= cmd <= 0x6F:
            return "operation"
        if cmd in (int(mcu.ResponseCode.NACK), int(mcu.ResponseCode.ERROR)):
            return "errors"
        return ""

    def _write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
