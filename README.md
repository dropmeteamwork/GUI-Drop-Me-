# DropMe GUI

Cross-platform GUI for DropMe RVM machines (Windows/Linux), with:
- Qt/QML UI (`PySide6`)
- MCU serial protocol (`AutoSerial`)
- Optional ML prediction pipeline (`ultralytics`, `torch`)

## Runtime Modes

- Operating mode: `uv run gui`
  - Fullscreen kiosk behavior
  - Real serial + real ML path
- Dev mode: `uv run python -m gui.main --dev`
  - Dev controls visible in UI
  - ML prediction is intentionally skipped and can be simulated from dev buttons

## Cross-Platform Runtime Configuration

No code edits are needed per machine. Configure machines with environment variables.

### Required machine identity / API env

- `MACHINE_NAME` (example: `RVM-001`)
- `MACHINE_API_KEY`
- `DROPME_SERVER_BASE_URL` (optional, default: production URL)

### Optional storage path overrides

- `DROPME_DATA_DIR` (captures, metadata, queue, cache)
- `DROPME_STATE_DIR` (state root)
- `DROPME_MODELS_DIR` (model directory)
- `DROPME_RELEASE_DIRNAME` (default: `gui-v1.1.3`)

If not overridden, the app auto-selects OS-appropriate defaults.

### Optional AWS env

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (default `eu-central-1`)
- `AWS_BUCKET_NAME`

## Models

Expected model files in `DROPME_MODELS_DIR` (or default models path):
- `v8n_5classes_v2.pt`
- `multihead_b3.pth`

Optional:
- `v8n_5classes_v2_openvino_model/` for OpenVINO YOLO backend

## Install

```bash
uv sync --frozen
```

## Run

Operating mode:

```bash
uv run gui
```

Dev mode:

```bash
uv run python -m gui.main --dev
```

## Windows Quick Start (tomorrow machine)

1. Install Python 3.12 + `uv`.
2. Set machine env vars (`MACHINE_NAME=RVM-001`, API/AWS vars).
3. Place model files in `DROPME_MODELS_DIR` (or default state path).
4. Run `uv sync --frozen`.
5. Start with `uv run gui` (no `--dev`).

## Testing

```bash
pytest
```

Integration serial test requires paired virtual COM ports and env vars:
- `DROPME_SIM_PORT`
- `DROPME_GUI_PORT`
