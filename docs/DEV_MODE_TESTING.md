# Dev Mode Test Guide

Dev mode is now intended to be a parity harness, not a separate behavior path.

## Parity rules

- `--dev` only enables tooling and visibility.
- Real serial framing stays on.
- Real ML stays on unless you explicitly opt out.
- MCU-side events should come from the simulator so the GUI exercises the same RX path as operating mode.
- Local sensor shortcut buttons are disabled by default because they bypass the serial layer.

## Recommended setup

1. Create a virtual serial pair such as `COM10 <-> COM11`.
2. Start the simulator on one side:

```bash
python src/gui/enhanced_mcu_simulator.py COM10
```

3. Start the GUI on the other side:

```bash
uv run python -m gui.main --dev
```

## Optional dev-only escape hatches

- Skip ML on purpose:

```bash
set DROPME_DEV_SKIP_ML=1
uv run python -m gui.main --dev
```

- Re-enable local sensor shortcut buttons (non-parity path):

```bash
set DROPME_DEV_LOCAL_SENSOR_OVERRIDE=1
uv run python -m gui.main --dev
```

Use that override only for fast UI experiments. It is not a production-parity test.

## What the simulator now enforces

- Documented PC -> MCU requests must match the published reference bytes exactly.
- Bad CRC / malformed frames produce `NACK`.
- Reference-mismatched request bytes also produce `NACK`.

That means dev mode can now catch request framing drift instead of silently hiding it.

## Core validation flow

1. Connect the GUI to the simulator.
2. Confirm the initial ping succeeds.
3. Use the Protocol Test panel or the normal recycle flow.
4. Watch the simulator log and `src/dropme_protocol_logs/` artifacts.
5. Trigger MCU events from the simulator terminal and verify the GUI reacts correctly.

## High-value checks

### 1. Hand / gate blocking

1. Start a session.
2. Trigger gate alarm from the simulator.
3. Verify the hand-blocked UX appears and stays active.
4. Clear the alarm from the simulator.
5. Verify the popup clears and the flow resumes correctly.

### 2. Accept plastic / aluminum

1. Start a session.
2. Trigger plastic or aluminum from the GUI flow.
3. Verify the outgoing request bytes match the reference.
4. Verify the simulator emits `ITEM_DROPPED`.
5. Verify the GUI records the accepted item and starts exit-gate verification.

### 3. Reject path

1. Start a session.
2. Trigger reject from the GUI.
3. Verify `REJECT_ITEM` request bytes match the reference.
4. Verify the session remains stable and no fake success event is invented by the GUI.

### 4. End session

1. End the session from the GUI.
2. Verify `END_SESSION` matches the reference bytes.
3. Verify the simulator emits `BASKET_STATUS`.
4. Verify the GUI follows up with `GATE_CLOSED` polling and returns to connected/idle state.

### 5. CRC / protocol drift

1. Use the simulator `x` shortcut to send a bad-CRC frame.
2. Verify the GUI logs `crc_invalid` / malformed RX.
3. Temporarily change a request in code if you want to test strictness.
4. Verify the simulator returns `NACK` for a non-reference request frame.

## Runtime artifacts

The GUI writes parity evidence to:

- `src/dropme_protocol_logs/protocol_events.jsonl`
- `src/dropme_protocol_logs/session_events.csv`
- `src/dropme_protocol_logs/sensor_events.jsonl`
- `src/dropme_protocol_logs/sensor_snapshot.json`
- `src/dropme_protocol_logs/protocol_state.json`
