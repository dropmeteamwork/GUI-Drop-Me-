# Protocol Testing

This project now treats the provided RVM PC-to-MCU table as the request-frame source of truth.

## What is verified

- GUI request bytes match the published reference request hex exactly.
- MCU responses and async events are parsed with CRC16/CCITT-FALSE over `MSG_ID + LEN + PAYLOAD`.
- The simulator rejects malformed or non-reference request frames with `NACK`, so protocol drift is visible during development.

## Automated checks

Run the unit suite:

```bash
pytest tests/test_mcu.py
```

That suite verifies:

- all documented request examples serialize exactly as expected
- helper validation rejects non-reference request bytes
- CRC16 response parsing still accepts `ACK OK`
- bad CRC responses are rejected

## Integration check with simulator

1. Create a virtual serial pair such as `COM10 <-> COM11`.
2. Start the simulator:

```bash
python src/gui/enhanced_mcu_simulator.py COM10
```

3. Run the integration test against the paired port:

```bash
set DROPME_SIM_PORT=COM10
set DROPME_GUI_PORT=COM11
pytest tests/test_protocol_integration.py
```

## Manual parity check

Use the Protocol Test view in `--dev` mode. Every button now maps to a real supported command from the current protocol:

- `PING`
- `GET STATUS`
- `RESET`
- `REQ STATUS`
- `POLL WEIGHT`
- sensor reads
- ring light colors
- buzzer patterns
- `START FLOW`
- `OPEN / START`
- `ACCEPT PLASTIC`
- `ACCEPT AL`
- `REJECT`
- `END`
- `CLOSE / END`

For async MCU -> PC events, use the simulator terminal. That keeps manual testing on the same RX path used in operating mode.
