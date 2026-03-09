# Dev Mode Test Guide (Parity + Protocol)

This guide ensures **dev mode behaves like operating mode** as closely as possible.

## 0) Core principle

- Run GUI with `--dev` for tooling/controls.
- Keep production behavior enabled (ML ON, serial protocol ON).
- Use simulator only to inject hardware events.

## 1) Start setup

1. Create virtual serial pair (example): `COM10 <-> COM11`.
2. Start simulator on one side:

```bash
python src/gui/enhanced_mcu_simulator.py COM10
```

3. Start GUI on the paired side:

```bash
python -m gui.main --dev
```

## 2) ML parity in dev mode

- Dev mode now keeps ML active by default (same as production path).
- Only skip ML intentionally with:

```bash
set DROPME_DEV_SKIP_ML=1
python -m gui.main --dev
```

## 3) Hardware/sensor event injection matrix

From simulator terminal:

- `h` -> `GATE_BLOCKED` (hand in gate)
- `u` -> gate clear (`GATE_OPENED` or `GATE_CLOSED`) for popup clear path
- `w` -> `WEIGHT_DATA`
- `p` -> `BIN_PLASTIC_FULL`
- `c` -> `BIN_CAN_FULL`
- `r` -> `BIN_REJECT_FULL`
- `e` -> `ERR_MOTOR_STALL`
- `s` -> print simulator state

From GUI dev panel (RecycleView):

- `sensor hand ON` / `sensor hand OFF`
- `bin plastic FULL` / `bin can FULL` / `clear bins`
- ML result buttons: `plastic`, `aluminum`, `other`, `hand`

## 4) Test cases (must pass)

### A) Hand popup persistence
1. Trigger hand sensor (`h` or `sensor hand ON`).
2. Verify hand popup appears and **does not disappear automatically** while blocked.
3. Clear sensor (`u` or `sensor hand OFF`).
4. Verify popup clears.

### B) Bin full visual + logic lock
1. Trigger plastic full (`p` or dev button).
2. Verify plastic full overlay appears.
3. Trigger plastic ML result.
4. Verify no plastic accept command is sent to MCU and count does not increment.
5. Repeat for can full (`c`).

### C) End flow responsiveness
1. Press End during recycle.
2. Verify immediate transition to finish behavior (no long wait for timer tick).
3. For phone flow with network down, verify offline finish fallback appears quickly.

### D) Protocol sanity
1. Use Protocol Test view for command coverage.
2. Verify TX/RX for system/op/gate/sort/reject commands.

## 5) Sensor telemetry files

All runtime sensor+status/error data is persisted under:

- `src/dropme_protocol_logs/protocol_events.jsonl` (all TX/RX protocol traffic)
- `src/dropme_protocol_logs/weights.csv` (weights)
- `src/dropme_protocol_logs/sensor_events.jsonl` (sensor/status/error events)
- `src/dropme_protocol_logs/sensor_snapshot.json` (latest sensor/system state)

## 6) Bin-full image assets (recommended names)

Add these four files to `images/`:

- `en-overlay-bin-full-plastic.png`
- `en-overlay-bin-full-can.png`
- `ar-overlay-bin-full-plastic.png`
- `ar-overlay-bin-full-can.png`

The code is already wired to these names via `MultilingualResource` in `RecycleView.qml`.
If a file is missing, fallback drawn overlay is used.
