# Fleet Scripts

## Files

- `next-machine-id.ps1`: allocates next available machine name (`RVM-00x`).
- `provision-rvm.ps1`: provisions a Windows target remotely from your laptop.
- `machines.csv`: local registry log of provisioned targets.
- `next_id.txt`: allocator counter.
- `secrets.example.ps1`: template for local secrets file.

## Setup

1. Copy `secrets.example.ps1` -> `secrets.local.ps1`.
2. Fill `secrets.local.ps1` values.
3. Ensure target machine has PowerShell remoting enabled and `uv` installed.

## Allocate next machine ID manually

```powershell
.\scripts\fleet\next-machine-id.ps1
```

## Provision a machine

```powershell
.\scripts\fleet\provision-rvm.ps1 `
  -Target 192.168.1.120 `
  -ModelsSource D:\models `
  -PromptForCredential `
  -RegisterStartupTask
```

Optional:
- `-RenameComputer` to set OS hostname to allocated `RVM-00x`.
- `-SkipDependencyInstall` if dependencies are already installed.

## Notes

- `MACHINE_NAME` is auto-assigned unless `-MachineName` is provided.
- Secrets are read from `secrets.local.ps1` and set remotely as machine env vars.
- Registry rows are appended to `machines.csv` with status (`provisioned`/`failed`).
