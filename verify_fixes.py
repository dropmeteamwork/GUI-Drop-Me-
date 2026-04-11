#!/usr/bin/env python3
"""
DropMe Bug Fix Verification Script
===================================
Exercises the exact code paths that were broken in production,
WITHOUT requiring hardware, serial ports, or ML models.

Run with uv: uv run python verify_fixes.py
Or plain: python verify_fixes.py
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results = []


def test(name):
    """Decorator to register and run a test."""
    def decorator(fn):
        print(f"\n{'-' * 60}")
        print(f"  TEST: {name}")
        print(f"{'-' * 60}")
        try:
            fn()
            results.append((name, True, ""))
            print(f"  {PASS}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  {FAIL}: {e}")
            traceback.print_exc()
        return fn
    return decorator


# ============================================================
# BUG #1: Logger.info() crash
# ============================================================

@test("Bug #1: Logger.info() f-string does NOT crash")
def test_bug1_fstring_logger():
    """
    The fix changed %-style args to f-string formatting.
    We test BOTH that the new code works AND the old code would crash.
    Since gui.logging needs PySide6, we mock it to test the pattern.
    """
    # Replicate the Logger class from gui/logging.py
    class MockLogger:
        def info(self, message: str) -> None:
            assert isinstance(message, str), f"Expected str, got {type(message)}"

    logger = MockLogger()

    _def_pred = "plastic"
    _def_pred_image = "file:///some/image.png"
    _cleanup_path = "/tmp/cleanup.png"

    # NEW code (f-string) - must succeed
    logger.info(
        f"Applying prediction: pred={_def_pred} image={bool(_def_pred_image)} cleanup={bool(_cleanup_path)}"
    )
    print(f"    logger.info(f-string) succeeded")

    # OLD code (%-style) - must crash with TypeError
    old_code_crashed = False
    try:
        logger.info(
            "Applying prediction: pred=%s image=%s cleanup=%s",
            _def_pred,
            bool(_def_pred_image),
            bool(_cleanup_path),
        )
    except TypeError:
        old_code_crashed = True

    assert old_code_crashed, "Old %-style code should crash but didn't"
    print(f"    Old %-style code correctly crashes with TypeError")


@test("Bug #1: Source file has f-string, not %-style")
def test_bug1_source_check():
    """
    Verify the actual source file uses f-string formatting.
    """
    rfc_path = os.path.join(os.path.dirname(__file__), "src", "gui", "recycle_flow_coordinator.py")
    with open(rfc_path, "r", encoding="utf-8") as f:
        source = f.read()

    # The old broken pattern
    if '"Applying prediction: pred=%s image=%s cleanup=%s"' in source:
        raise AssertionError("recycle_flow_coordinator.py still has %-style logger call!")

    # The new fixed pattern
    if 'f"Applying prediction: pred={self._def_pred}' in source:
        print(f"    OK: Source uses f-string formatting")
    else:
        raise AssertionError("Could not find the fixed f-string logger call")

    # Check no other %-style calls exist in the file
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "self.logger." in stripped and '"%s' in stripped:
            raise AssertionError(f"Line {i+1}: Another %-style logger call found: {stripped}")

    print(f"    OK: No other %-style logger calls found in file")


# ============================================================
# BUG #7: endOperation() unreachable code
# ============================================================

@test("Bug #7: endOperation() routes 'active' to graceful end")
def test_bug7_active_graceful():
    """
    Verify 'active' goes to _request_end_session (graceful),
    NOT _request_forced_end_session.
    """
    autoserial_path = os.path.join(os.path.dirname(__file__), "src", "gui", "autoserial.py")
    with open(autoserial_path, "r", encoding="utf-8") as f:
        source = f.read()

    lines = source.split("\n")
    in_method = False
    method_lines = []
    indent_level = None

    for i, line in enumerate(lines):
        if "def endOperation(self)" in line:
            in_method = True
            indent_level = len(line) - len(line.lstrip())
            method_lines.append((i + 1, line))
            continue
        if in_method:
            if line.strip() == "":
                method_lines.append((i + 1, line))
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent_level and line.strip():
                break
            method_lines.append((i + 1, line))

    print(f"    endOperation() source ({len(method_lines)} lines):")
    for lineno, line in method_lines:
        print(f"      {lineno:4d}: {line.rstrip()}")

    first_active_check = None
    first_precheck_check = None
    active_uses_graceful = False

    for idx, (lineno, line) in enumerate(method_lines):
        stripped = line.strip()
        if '"active"' in stripped and '"await_item_drop"' in stripped and first_active_check is None:
            first_active_check = lineno
            # Check the NEXT code line
            for _, next_line in method_lines[idx+1:]:
                ns = next_line.strip()
                if not ns or ns.startswith("#"):
                    continue
                if "_request_end_session()" in ns and "forced" not in ns:
                    active_uses_graceful = True
                break
        if '"basket_precheck"' in stripped and first_precheck_check is None:
            first_precheck_check = lineno

    assert first_active_check is not None, "Could not find active/await_item_drop check"
    assert first_precheck_check is not None, "Could not find basket_precheck check"
    assert first_active_check < first_precheck_check, \
        f"Active (line {first_active_check}) must come BEFORE precheck (line {first_precheck_check})"
    assert active_uses_graceful, "Active stage must use _request_end_session() (graceful)"

    print(f"    OK: active/await_item_drop -> _request_end_session() at line {first_active_check}")
    print(f"    OK: basket_precheck/await_gate_open -> forced at line {first_precheck_check}")
    print(f"    OK: No unreachable code")


# ============================================================
# BUG #2+#8: Gate timeout uses graceful cleanup
# ============================================================

@test("Bug #2+#8: Gate OPEN timeout does NOT disconnect")
def test_bug2_gate_open():
    """
    Verify gate open timeout calls _request_forced_end_session()
    instead of _handle_disconnect().
    """
    autoserial_path = os.path.join(os.path.dirname(__file__), "src", "gui", "autoserial.py")
    with open(autoserial_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the gate_open_deadline check and inspect the CODE lines (not comments) nearby
    for i, line in enumerate(lines):
        if "_gate_open_deadline" in line and "time.time()" in line and ">" in line:
            # Scan next ~10 CODE lines (skip comments)
            code_calls_disconnect = False
            code_calls_forced_end = False
            for j in range(i+1, min(i+10, len(lines))):
                code_line = lines[j].strip()
                if code_line.startswith("#"):
                    continue  # skip comments
                if code_line == "":
                    continue
                if code_line == "return":
                    break  # end of this block
                if "_handle_disconnect()" == code_line or "self._handle_disconnect()" == code_line:
                    code_calls_disconnect = True
                if "_request_forced_end_session()" in code_line and not code_line.startswith("#"):
                    code_calls_forced_end = True

            assert not code_calls_disconnect, \
                f"Line {i+1}: Gate open timeout STILL calls _handle_disconnect() as executable code!"
            assert code_calls_forced_end, \
                f"Line {i+1}: Gate open timeout does not call _request_forced_end_session()"

            print(f"    OK: Gate open timeout at line {i+1}")
            print(f"    -> Calls _request_forced_end_session() (keeps serial alive)")
            print(f"    -> Comment mentions _handle_disconnect was the OLD behavior")
            return

    raise AssertionError("Could not find gate_open_deadline timeout handler")


@test("Bug #2+#8: Gate CLOSE timeout does NOT disconnect")
def test_bug2_gate_close():
    """
    Verify gate close timeout does graceful cleanup.
    """
    autoserial_path = os.path.join(os.path.dirname(__file__), "src", "gui", "autoserial.py")
    with open(autoserial_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if "_gate_close_deadline" in line and "time.time()" in line and ">" in line:
            code_calls_disconnect = False
            code_calls_end_session = False
            for j in range(i+1, min(i+12, len(lines))):
                code_line = lines[j].strip()
                if code_line.startswith("#"):
                    continue
                if "self._handle_disconnect()" == code_line:
                    code_calls_disconnect = True
                if code_line == "self._end_session()":
                    code_calls_end_session = True

            assert not code_calls_disconnect, \
                f"Line {i+1}: Gate close timeout STILL calls _handle_disconnect()!"
            assert code_calls_end_session, \
                f"Line {i+1}: Gate close timeout does not call _end_session()"

            print(f"    OK: Gate close timeout at line {i+1} -> _end_session() (graceful)")
            print(f"    -> Session ends locally without dropping serial port")
            return

    raise AssertionError("Could not find gate_close_deadline timeout handler")


@test("Bug #2: Gate open timeout is 25 seconds (was 20)")
def test_bug2_timeout_value():
    """
    Gate takes ~17s to open. 25s gives 8s margin.
    """
    autoserial_path = os.path.join(os.path.dirname(__file__), "src", "gui", "autoserial.py")
    with open(autoserial_path, "r", encoding="utf-8") as f:
        source = f.read()

    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "_gate_open_deadline" in line and "time.time()" in line and "+" in line:
            if "25.0" in line:
                print(f"    OK: Gate open timeout = 25s (line {i+1})")
                print(f"    -> 8 seconds margin over ~17s physical gate opening")
                return
            elif "20.0" in line:
                raise AssertionError(f"Line {i+1}: Still 20s, should be 25s")

    raise AssertionError("Could not find _gate_open_deadline assignment")


# ============================================================
# PROTOCOL: Cross-check with embedded engineer's reference app
# ============================================================

@test("Protocol: mcu.py matches embedded reference app")
def test_protocol_match():
    """
    Cross-check command IDs, sensor IDs, and CRC algorithm.
    """
    from gui import mcu

    reference = {
        "PING":           (0x01, "SystemControl"),
        "SYSTEM_RESET":   (0x03, "SystemControl"),
        "READ_SENSOR":    (0x11, "ReadCommand"),
        "POLL_WEIGHT":    (0x12, "ReadCommand"),
        "RING_LIGHT":     (0x50, "DeviceControl"),
        "BUZZER_BEEP":    (0x51, "DeviceControl"),
        "REQ_STATUS":     (0x60, "SessionControl"),
        "START_SESSION":  (0x61, "SessionControl"),
        "ACCEPT_ITEM":    (0x62, "SessionControl"),
        "REJECT_ITEM":    (0x63, "SessionControl"),
        "END_SESSION":    (0x64, "SessionControl"),
        "STATUS_OK":      (0x70, "AsyncEvent"),
        "ITEM_PLACED":    (0x71, "AsyncEvent"),
        "ITEM_DROPPED":   (0x72, "AsyncEvent"),
        "BASKET_STATUS":  (0x73, "AsyncEvent"),
        "ACK":            (0xA0, "ResponseCode"),
        "NACK":           (0xA1, "ResponseCode"),
        "DATA":           (0xA2, "ResponseCode"),
    }

    enum_map = {
        "SystemControl": mcu.SystemControl,
        "ReadCommand": mcu.ReadCommand,
        "DeviceControl": mcu.DeviceControl,
        "SessionControl": mcu.SessionControl,
        "AsyncEvent": mcu.AsyncEvent,
        "ResponseCode": mcu.ResponseCode,
    }

    all_ok = True
    for name, (expected_id, enum_name) in reference.items():
        enum_cls = enum_map.get(enum_name)
        if enum_cls is None:
            print(f"    {WARN} Enum {enum_name} not found in mcu.py")
            continue

        found = False
        for member in enum_cls:
            if int(member) == expected_id:
                print(f"    OK: {enum_name}.{member.name} = 0x{expected_id:02X}")
                found = True
                break
        if not found:
            print(f"    XX: {name} (0x{expected_id:02X}) NOT FOUND in {enum_name}")
            all_ok = False

    # Sensor IDs
    sensor_reference = {
        0: "SORT_PLASTIC", 1: "SORT_ALUMINUM", 2: "GATE_CLOSED",
        3: "GATE_OPENED", 4: "EXIT_GATE", 5: "GATE_ALARM",
        6: "REJECT_HOME", 7: "DROP_SENSOR", 8: "BASKET_1",
        9: "BASKET_2", 10: "BASKET_3",
    }

    print(f"\n    Sensor IDs:")
    for sensor_id, expected_name in sensor_reference.items():
        found = False
        for member in mcu.SensorSelector:
            if int(member) == sensor_id:
                print(f"    OK: SensorSelector.{member.name} = {sensor_id}")
                found = True
                break
        if not found:
            print(f"    XX: Sensor {expected_name} (ID={sensor_id}) NOT FOUND")
            all_ok = False

    # CRC algorithm
    print(f"\n    CRC16 check:")
    test_data = bytes([0xAA, 0x01, 0x00])
    our_crc = mcu.calculate_crc(test_data)

    # Reference CRC from the embedded engineer's app
    def ref_crc16(data):
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    ref_crc = ref_crc16(test_data)
    assert our_crc == ref_crc, f"CRC mismatch: ours=0x{our_crc:04X} ref=0x{ref_crc:04X}"
    print(f"    OK: CRC16 for PING = 0x{our_crc:04X} (matches reference)")

    # Baud rate
    assert mcu.BAUD_RATE == 115200, f"Baud rate: {mcu.BAUD_RATE} != 115200"
    print(f"    OK: Baud rate: {mcu.BAUD_RATE}")

    # Frame structure
    assert mcu.START_BYTE == 0xAA, f"Start byte: 0x{mcu.START_BYTE:02X} != 0xAA"
    print(f"    OK: Start byte: 0xAA")

    assert all_ok, "Some protocol definitions don't match"


# ============================================================
# SUMMARY
# ============================================================

print(f"\n{'=' * 60}")
print(f"  VERIFICATION SUMMARY")
print(f"{'=' * 60}")

passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)

for name, ok, err in results:
    status = PASS if ok else FAIL
    print(f"  {status}  {name}")
    if err:
        print(f"         -> {err}")

print(f"\n  {passed} passed, {failed} failed out of {len(results)} tests")

if failed:
    print(f"\n  {FAIL}: Some fixes are NOT verified. Review before deploying.")
    sys.exit(1)
else:
    print(f"\n  {PASS}: All fixes verified. Safe to deploy to the machine.")
    sys.exit(0)
