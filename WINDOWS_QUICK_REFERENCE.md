# Windows Docker Quick Reference

## Quick Commands

### Headless Mode (No GUI)
```powershell
# Start
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up

# Stop (in another terminal)
docker-compose down

# View logs
docker-compose logs -f
```

### GUI Mode with X11 (WSL2)
```powershell
# Start VcXsrv FIRST in separate terminal
# Then start container
docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml up

# Stop
docker-compose down
```

### Development Mode
```powershell
# Start interactive shell
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui bash

# Inside container:
pip install -e .                    # Install editable
python -m gui.main                  # Run app
pytest                              # Run tests
```

## Diagnostics

```powershell
# Check Docker status
docker ps

# View service status
docker-compose ps

# View logs
docker-compose logs -f

# Rebuild image
docker-compose build --no-cache

# Enter container shell
docker-compose exec dropme-gui bash

# Run specific test
docker-compose run --rm dropme-gui pytest tests/test_mcu.py
```

## Cleanup

```powershell
# Stop services
docker-compose down

# Remove images
docker image prune

# Full cleanup (careful!)
docker system prune -a --volumes
```

## File Paths Used

- **Headless compose:** `docker-compose.windows.yml`
- **X11 compose:** `docker-compose.windows-wsl2.yml`
- **Dev compose:** `docker-compose.windows-dev.yml`
- **Dockerfile:** Works for all platforms
- **Setup guide:** `WINDOWS_SETUP.md` (full instructions)
- **Docker docs:** `DOCKER_README.md` (comprehensive)

## Project Location

```
C:\path\to\dropme\gui-final\
├── Dockerfile
├── docker-compose.yml
├── docker-compose.windows.yml
├── docker-compose.windows-wsl2.yml
├── docker-compose.windows-dev.yml
├── DOCKER_README.md
├── WINDOWS_SETUP.md
└── src/
```

## Environment Variables

| Variable | Value | Mode | Notes |
|----------|-------|------|-------|
| `DROPME_DEV` | 0 | Headless | Production |
| `DROPME_DEV` | 1 | Dev | Development mode |
| `QT_QPA_PLATFORM` | offscreen | Headless | No GUI |
| `QT_QPA_PLATFORM` | xcb | X11 | Display UI |
| `DISPLAY` | :99 | Headless | Dummy display |
| `DISPLAY` | host.docker.internal:0 | X11 | Windows X11 server |

## Common Issues & Fixes

| Problem | Solution |
|---------|----------|
| Container exits immediately | `docker-compose logs` to see error |
| X11 not connecting | Start VcXsrv first, then container |
| Port 5432 already in use | Stop other services or restart Docker |
| Permission denied | Run PowerShell as Administrator |
| Out of disk space | `docker system prune -a --volumes` |
| Slow performance | Enable Windows Defender exclusion, see WINDOWS_SETUP.md |

## File Structure After Build

```
container filesystem/
├── /app
│   ├── src/                    (application code)
│   ├── qml/                    (QML UI files)
│   ├── logs/                   (application logs)
│   ├── data/                   (persistent data)
│   └── pyproject.toml
├── /usr/local/lib/python3.12/  (Python packages)
└── /tmp/
```

## References

- Full DOCKER README: [DOCKER_README.md](DOCKER_README.md)
- Detailed Windows Setup: [WINDOWS_SETUP.md](WINDOWS_SETUP.md)
- Docker Docs: https://docs.docker.com/
- WSL2 Docs: https://docs.microsoft.com/en-us/windows/wsl/
