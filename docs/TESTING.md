# Testing

## Quick command

```bash
pytest
```

## Unit tests

- `tests/test_mcu.py`
- `tests/test_machine_controller.py`
- `tests/test_ui_coordinator.py`

## Integration test (simulator)

- `tests/test_protocol_integration.py` is marked `integration`.
- Requires paired virtual serial ports and `pyserial`.

Example setup variables:

```bash
set DROPME_SIM_PORT=COM10
set DROPME_GUI_PORT=COM11
pytest -m integration
```

Without these env vars, integration test is skipped.
