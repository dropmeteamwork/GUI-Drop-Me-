# Serial Protocol Testing – All Commands & Proof

This describes how to test **every** PC↔MCU command and see **proof** that they work.

## 1. Automated E2E Test (Proof Report)

Runs all **PC → MCU** commands and checks that the **MCU → PC** response matches.

### Setup

- Use a **virtual serial pair** (e.g. com0com: COM10 ↔ COM11).
- Start the **MCU simulator** on one port (e.g. COM10):
  ```bash
  python src/gui/enhanced_mcu_simulator.py COM10
  ```
- Leave the **other port** (e.g. COM11) for the test.

### Run

From project root:

```bash
python -m src.gui.protocol_e2e_test COM11
```

### Output (Proof)

You get a report like:

```
======================================================================
PROTOCOL E2E TEST REPORT – PC → MCU commands & MCU → PC responses
======================================================================
Command                    Response               Result
----------------------------------------------------------------------
SYS_INIT                   SYS_READY               PASS
SYS_RESET                  SYS_READY               PASS
SYS_PING                   SYS_IDLE                PASS
...
----------------------------------------------------------------------
Total: 18/18 passed
======================================================================
```

Exit code **0** = all passed, **1** = at least one failed.

---

## 2. GUI Protocol Test View (All Commands in the Flow)

In **dev mode**, every command is available in the GUI and every TX/RX is logged.

### Run GUI in dev mode

```bash
python -m gui.main --dev
```

### Open Protocol Test

- Click the **"Protocol Test"** button (top-right, dev only).
- You get:
  - **Log area**: every **TX** (after you click a command) and every **RX** (from MCU) with timestamp.
  - **Buttons** for every command:
    - **System**: SYS_INIT, SYS_RESET, SYS_PING, SYS_STOP_ALL
    - **Operation**: OP_NEW, OP_CANCEL, OP_END
    - **Gate**: GATE_OPEN, GATE_CLOSE
    - **Conveyor**: CONVEYOR_RUN(10), CONVEYOR_STOP
    - **Reject**: REJECT_ACTIVATE, REJECT_HOME
    - **Sort**: SORT_SET(plastic), SORT_SET(can)
    - **Classification**: ITEM_ACCEPT(plastic), ITEM_ACCEPT(can), ITEM_REJECT

### Proof in the GUI

- **TX**: After each button click you see a line like `[time] TX: GATE_OPEN PL:0`.
- **RX**: When the simulator (or real MCU) replies, you see e.g. `[time] RX: GATE_OPENED`.
- **MCU-initiated** (sensor/error/status): Use simulator keys in the **simulator** window:
  - **1 / 2 / 3** -> `SYS_READY` / `SYS_BUSY` / `SYS_IDLE`.
  - **4 / 5 / h** -> `GATE_OPENED` / `GATE_CLOSED` / `GATE_BLOCKED`.
  - **6 / 7 / 8 / 9 / 0** -> `CONVEYOR_DONE` / `SORT_DONE(plastic)` / `SORT_DONE(can)` / `REJECT_DONE` / `REJECT_HOME_OK`.
  - **w** -> `WEIGHT_DATA` -> log shows `RX: WEIGHT_DATA Xg`.
  - **p / c / r** -> `BIN_*_FULL` -> log shows `RX: BIN_FULL Plastic/Can/Reject` and bin-full popup.
  - **t / e / f / b** -> `ERR_GATE_TIMEOUT` / `ERR_MOTOR_STALL` / `ERR_SENSOR_FAIL` / `ERR_BIN_FULL`.


---

## 3. Command ↔ Response Summary

| PC → MCU (CMD) | Expected MCU → PC response(s) |
|----------------|-------------------------------|
| SYS_INIT       | SYS_READY                     |
| SYS_RESET      | SYS_READY                     |
| SYS_PING       | SYS_IDLE                      |
| SYS_STOP_ALL   | SYS_IDLE                      |
| OP_NEW         | SYS_BUSY then SYS_READY       |
| OP_CANCEL      | SYS_IDLE                      |
| OP_END         | GATE_CLOSED                   |
| GATE_OPEN      | GATE_OPENED                   |
| GATE_CLOSE     | GATE_CLOSED                   |
| CONVEYOR_RUN   | CONVEYOR_DONE                 |
| CONVEYOR_STOP  | CONVEYOR_DONE                 |
| REJECT_ACTIVATE| REJECT_DONE                   |
| REJECT_HOME    | REJECT_HOME_OK                |
| SORT_SET(0x01/0x02) | SORT_DONE                |
| ITEM_ACCEPT(0x01/0x02) | SORT_DONE              |
| ITEM_REJECT    | REJECT_DONE                   |

**MCU → PC only** (no request from PC): SYS_READY, SYS_BUSY, SYS_IDLE, GATE_OPENED, GATE_CLOSED, GATE_BLOCKED, CONVEYOR_DONE, SORT_DONE, REJECT_DONE, REJECT_HOME_OK, WEIGHT_DATA, BIN_*_FULL, ERR_*.

---

## 4. Normal GUI Flow (Where Commands Are Used)

- **SYS_INIT**: Auto when GUI connects (port scan handshake).
- **SYS_PING**: Auto every 10 s keepalive.
- **OP_NEW**: Start recycle session (e.g. RecycleView `sendNewUser`).
- **OP_END / GATE_CLOSE**: End session, close gate (e.g. after hand-in-gate popup).
- **GATE_OPEN**: Maintenance “open door”.
- **SORT_SET / ITEM_ACCEPT / ITEM_REJECT**: After ML classification (plastic/can/other).
- **Bin full / hand in gate / weight / errors**: Shown via popups and log as above.

All other commands (SYS_RESET, SYS_STOP_ALL, OP_CANCEL, CONVEYOR_*, REJECT_*) are available in the **Protocol Test** view and in **AutoSerial** slots for integration when you add those flows.
