from gui import mcu


def test_frame_roundtrip_valid_crc():
    frame = mcu.Frame(seq=0x12, cmd=mcu.SystemControl.SYS_PING, payload=0x34)
    parsed = mcu.Frame.from_bytes(frame.to_bytes())

    assert parsed is not None
    assert parsed.seq == 0x12
    assert parsed.cmd == int(mcu.SystemControl.SYS_PING)
    assert parsed.payload == 0x34


def test_frame_invalid_crc_rejected():
    frame = mcu.Frame(seq=1, cmd=mcu.SystemControl.SYS_INIT, payload=0)
    raw = bytearray(frame.to_bytes())
    raw[-1] ^= 0xFF

    assert mcu.Frame.from_bytes(bytes(raw)) is None


def test_sequence_manager_wraps():
    seq = mcu.SequenceManager()
    for _ in range(256):
        seq.next()
    assert seq.next() == 0


def test_expected_responses_cover_core_commands():
    assert mcu.SystemControl.SYS_INIT in mcu.EXPECTED_RESPONSES
    assert mcu.MotionControl.GATE_OPEN in mcu.EXPECTED_RESPONSES
    assert mcu.MotionControl.SORT_SET in mcu.EXPECTED_RESPONSES
