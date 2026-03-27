# DropMe GUI

Cross-platform GUI for DropMe RVM machines (Windows/Linux), with:
- Qt/QML UI (`PySide6`)
- MCU serial protocol (`AutoSerial`)
- Optional ML prediction pipeline (`ultralytics`, `torch`)

## Production First (What you need for machines)

Use this section for real RVM deployment.  
You do **not** need `pytest`, simulator ports, or dev mode to run production.

### 1) Required environment variables (per machine)

- `MACHINE_NAME` (example: `RVM-001`)
- `MACHINE_API_KEY`

Optional:
- `DROPME_SERVER_BASE_URL` (defaults to production URL)
- AWS vars only if you use cloud upload:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION` (default `eu-central-1`)
  - `AWS_BUCKET_NAME`

### 2) Model files (required for operating mode)

Place model files in `DROPME_MODELS_DIR` (or default models path):
- `v8n_5classes_v2.pt`
- `multihead_b3.pth`

Optional:
- `v8n_5classes_v2_openvino_model/` (OpenVINO YOLO backend)

### 3) Install and run (operating mode)

```bash
uv sync --frozen
uv run gui
```

That is the production command path.  
Do **not** use `--dev` on deployed RVMs.

### 4) Optional path overrides

- `DROPME_DATA_DIR` (captures, metadata, queue, cache)
- `DROPME_STATE_DIR` (state root)
- `DROPME_MODELS_DIR` (model directory)
- `DROPME_RELEASE_DIRNAME` (default: `gui-v1.1.3`)

If not set, app auto-selects OS-appropriate defaults.

## Runtime Modes (Reference)

- Operating mode: `uv run gui`
  - Fullscreen kiosk behavior
  - Real serial + real ML path
- Dev mode: `uv run python -m gui.main --dev`
  - Dev controls visible in UI
  - ML prediction is intentionally skipped and can be simulated from dev buttons

## Windows Quick Start (tomorrow machine)

1. Install Python 3.12 + `uv`.
2. Set machine env vars (`MACHINE_NAME=RVM-001`, API/AWS vars).
3. Place model files in `DROPME_MODELS_DIR` (or default state path).
4. Run `uv sync --frozen`.
5. Start with `uv run gui` (no `--dev`).

## Testing

Developer-only. Not required for production deployment.

```bash
pytest
```

Integration serial test requires paired virtual COM ports and env vars:
- `DROPME_SIM_PORT`
- `DROPME_GUI_PORT`
