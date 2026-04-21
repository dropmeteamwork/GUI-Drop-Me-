import pytest

from gui import mcu


def test_frame_roundtrip_valid_crc_for_response_frames():
    frame = mcu.Frame(seq=0x12, cmd=mcu.ResponseCode.ACK, payload=b"OK")
    parsed = mcu.Frame.from_bytes(frame.to_bytes())

    assert parsed is not None
    assert parsed.seq == 0
    assert parsed.cmd == int(mcu.ResponseCode.ACK)
    assert parsed.payload == b"OK"
    assert parsed.payload_int == int.from_bytes(b"OK", "little")


def test_frame_invalid_start_rejected():
    frame = mcu.Frame(seq=1, cmd=mcu.ResponseCode.ACK, payload=b"OK")
    raw = bytearray(frame.to_bytes())
    raw[0] = 0x00

    assert mcu.Frame.from_bytes(bytes(raw)) is None


def test_sequence_manager_wraps():
    seq = mcu.SequenceManager()
    for _ in range(256):
        seq.next()
    assert seq.next() == 0


def test_payload_description_for_single_byte_commands():
    assert mcu.get_payload_description(mcu.DeviceControl.RING_LIGHT, b"\x03") == "BLUE"
    assert mcu.get_payload_description(mcu.ReadCommand.READ_SENSOR, b"\x08") == "BASKET_1"


def test_request_frames_match_reference_table_exactly():
    for (cmd, payload), expected in mcu.KNOWN_TX_FRAMES.items():
        frame = mcu.Frame(cmd=cmd, payload=payload)
        assert frame.to_bytes() == expected, f"Mismatch for {mcu.get_command_name(cmd)} payload={payload.hex(' ')}"


def test_reference_request_match_helper_rejects_wrong_bytes():
    expected = mcu.Frame(cmd=mcu.SystemControl.PING, payload=b"").to_bytes()
    wrong = bytes.fromhex("aa 01 00 3e 2e")

    assert mcu.matches_reference_request_bytes(mcu.SystemControl.PING, b"", expected)
    assert not mcu.matches_reference_request_bytes(mcu.SystemControl.PING, b"", wrong)


def test_parse_reference_request_bytes_accepts_documented_request_example():
    parsed = mcu.parse_reference_request_bytes(bytes.fromhex("aa 01 00 50 70"))
    assert parsed is not None
    cmd, payload = parsed
    assert cmd == int(mcu.SystemControl.PING)
    assert payload == b""


def test_crc16_modbus_matches_ack_ok_response():
    frame = mcu.Frame.from_bytes(bytes.fromhex("aa a0 02 4f 4b cb df"))
    assert frame is not None
    assert frame.cmd == int(mcu.ResponseCode.ACK)
    assert frame.payload == b"OK"


def test_invalid_crc_response_rejected():
    frame = mcu.Frame.from_bytes(bytes.fromhex("aa a0 02 4f 4b 00 00"))
    assert frame is None


@pytest.mark.parametrize(
    ("cmd", "payload", "expected_hex"),
    [
        (mcu.SystemControl.PING, b"", "aa 01 00 50 70"),
        (mcu.SystemControl.GET_MCU_STATUS, b"", "aa 02 00 50 80"),
        (mcu.ReadCommand.POLL_WEIGHT, b"", "aa 12 00 5d 40"),
        (mcu.SessionControl.ACCEPT_ITEM, bytes([int(mcu.ItemType.ALUMINUM)]), "aa 62 01 01 40 72"),
        (mcu.SessionControl.END_SESSION, b"", "aa 64 00 7b 20"),
        (mcu.MaintenanceDoorControl.OPEN_DOOR_1, b"", "aa 65 00 7a b0"),
        (mcu.MaintenanceDoorControl.OPEN_DOOR_2, b"", "aa 66 00 7a 40"),
        (mcu.MaintenanceDoorControl.OPEN_DOOR_3, b"", "aa 67 00 7b d0"),
    ],
)
def test_selected_reference_examples(cmd, payload, expected_hex):
    assert mcu.Frame(cmd=cmd, payload=payload).to_bytes().hex(" ") == expected_hex
