# Fleet Deployment Playbook

This project is configured to run without per-machine code edits.

## 1) Prepare release from `master`

1. Ensure clean working tree.
2. Build/install dependencies with lockfile:
   - `uv sync --frozen`
3. Package project files (exclude caches, logs, local secrets).
4. Package models separately (or in release artifact):
   - `v8n_5classes_v2.pt`
   - `multihead_b3.pth`

## 2) Machine identity policy

- Machine names are `RVM-00x`.
- Set `MACHINE_NAME` per machine via environment variable.
- Do not hardcode machine names in code.

## 3) Required env vars per machine

- `MACHINE_NAME` (ex: `RVM-001`)
- `MACHINE_API_KEY`

Optional but recommended:
- `DROPME_SERVER_BASE_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_BUCKET_NAME`

Path overrides (optional):
- `DROPME_DATA_DIR`
- `DROPME_STATE_DIR`
- `DROPME_MODELS_DIR`
- `DROPME_RELEASE_DIRNAME`

## 4) Windows deployment (tomorrow machine)

1. Install Python 3.12 and `uv`.
2. Copy release to target path (example: `D:\dropme\gui`).
3. Set machine-level env vars (PowerShell as admin):

```powershell
[Environment]::SetEnvironmentVariable("MACHINE_NAME","RVM-001","Machine")
[Environment]::SetEnvironmentVariable("MACHINE_API_KEY","<api-key>","Machine")
[Environment]::SetEnvironmentVariable("AWS_ACCESS_KEY_ID","<aws-key>","Machine")
[Environment]::SetEnvironmentVariable("AWS_SECRET_ACCESS_KEY","<aws-secret>","Machine")
[Environment]::SetEnvironmentVariable("AWS_REGION","eu-central-1","Machine")
[Environment]::SetEnvironmentVariable("AWS_BUCKET_NAME","ai-data-001","Machine")
```

4. Set model location:
   - either set `DROPME_MODELS_DIR`
   - or copy models into default runtime state models folder.
5. Install deps and run:
   - `uv sync --frozen`
   - `uv run gui`

## 5) Linux deployment

1. Install Python 3.12 and `uv`.
2. Export same env vars for service/user.
3. Install deps and run:
   - `uv sync --frozen`
   - `uv run gui`

## 6) Dev vs Operating behavior

- `--dev`: dev tools + simulated predictions, ML inference skipped.
- Operating mode: no `--dev`; real ML path and production UX.

## 7) Automation direction (next step)

For 100+ machines, use a laptop provisioning script to:
1. allocate next `RVM-00x`,
2. set env vars remotely,
3. copy/update release,
4. start/restart app and verify health.
