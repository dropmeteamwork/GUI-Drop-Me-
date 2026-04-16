# Docker Setup Guide for Windows 10/11

This guide walks you through setting up and running the DropMe GUI application on Windows 10 or Windows 11 using Docker.

## Prerequisites

### Required Software

1. **Windows 10/11** (with WSL2 support)
   - Windows 10 version 1909 or later
   - Windows 11 any version

2. **Docker Desktop for Windows**
   - Download from: https://www.docker.com/products/docker-desktop
   - Version 20.10 or later
   - Enable WSL2 backend during installation

3. **Git (optional but recommended)**
   - Download from: https://git-scm.com/download/win

### Installation Steps

#### Step 1: Install Docker Desktop

1. Download Docker Desktop from https://www.docker.com/products/docker-desktop
2. Run the installer and follow the prompts
3. Enable the following options:
   - ✅ "Install required Windows components for WSL2"
   - ✅ "Use WSL2 instead of Hyper-V"
4. Restart your computer when prompted
5. Launch Docker Desktop from Start menu

#### Step 2: Verify Docker Installation

Open PowerShell and run:

```powershell
docker --version
docker-compose --version
```

Both should show version information.

## Running the Application

### Option 1: Headless Mode (Recommended for Most Users)

This runs the application without a GUI display. Use this if you only need the backend services.

```powershell
cd C:\path\to\dropme\gui-final

# Build the Docker image
docker-compose build

# Run the application
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up

# View logs
docker-compose logs -f

# Stop the application (press Ctrl+C in the terminal, or in another PowerShell window):
docker-compose down
```

### Option 2: WSL2 with X11 GUI Display

This allows the QML UI to display graphically on your Windows desktop.

#### Setup X11 Server (One-time setup)

1. Download **VcXsrv** from: https://sourceforge.net/projects/vcxsrv/
   - Or alternative: Xming from https://xming.en.softonic.com/

2. Install VcXsrv with default settings

3. Configure VcXsrv:
   - Launch "XLaunch" from Start menu
   - Select "Multiple windows"
   - Click "Next" through all dialogs
   - On final screen, check ✅ "Save configuration"
   - Save as `config.xlaunch` in an easy location

4. Create a batch file `start-xserver.bat` to quickly launch X11:

```batch
@echo off
REM Add VcXsrv to PATH or specify full path
"C:\Program Files\VcXsrv\xlaunch.exe" -run C:\path\to\config.xlaunch
```

#### Run with GUI Display

```powershell
cd C:\path\to\dropme\gui-final

# Start X11 server first (in a separate terminal)
# Or use: start-xserver.bat

# Build and run with X11 forwarding
docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml up

# In another PowerShell window, view the UI logs
docker-compose logs -f

# Stop the application
docker-compose down
```

**Note:** The GUI window should appear on your Windows desktop once the container starts.

### Option 3: Development Mode

For developers who want live code editing with automatic container reloads.

```powershell
cd C:\path\to\dropme\gui-final

# Start development container
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui bash

# Inside the container:
pip install -e .                    # Install in editable mode
python -m gui.main                  # Run the app
pytest                              # Run all tests
pytest tests/test_mcu.py            # Run specific test
```

## Common Tasks

### View Application Logs

```powershell
# View all logs
docker-compose logs -f

# View logs from specific service
docker-compose logs -f dropme-gui

# View logs from last 100 lines
docker-compose logs -f --tail 100
```

### Run Tests

**Headless mode:**
```powershell
docker-compose -f docker-compose.yml -f docker-compose.windows.yml run --rm dropme-gui pytest
```

**Development mode:**
```powershell
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui pytest tests/
```

### Access Container Shell

```powershell
# Interactive bash shell
docker-compose exec dropme-gui bash

# Or in dev mode
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui bash
```

### Rebuild Docker Image

```powershell
# Full rebuild without cache
docker-compose build --no-cache

# Then run normally
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up
```

### Check Services Status

```powershell
docker-compose ps
```

Output should show:
```
NAME              COMMAND                 SERVICE     STATUS      PORTS
dropme-gui-app    python -m gui.main      dropme-gui  running     
dropme-db         postgres:16-alpine      dropme-db   exited      5432/tcp
```

### Clean Up

```powershell
# Stop all services
docker-compose down

# Stop and remove volumes (careful: removes data!)
docker-compose down -v

# Remove unused Docker images
docker image prune

# Full cleanup
docker system prune -a --volumes
```

## Troubleshooting

### Docker Desktop Won't Start

**Error:** "Docker Desktop stopped running"

**Solution:**
1. Open PowerShell as Administrator
2. Run: `wsl --list -v` to check WSL2 status
3. If WSL2 not installed: Enable it in Windows Features
4. Restart Docker Desktop

### Container Exits Immediately

**Error:** Container starts then stops

**Solution:**
1. Check logs:
```powershell
docker-compose logs
```

2. Look for Python error messages or module import failures

3. Rebuild the image:
```powershell
docker-compose build --no-cache
```

### X11 Not Connecting (GUI Mode)

**Error:** "Cannot connect to display"

**Solution:**
1. Verify VcXsrv is running (check system tray)
2. Restart VcXsrv
3. Ensure firewall allows Docker access to X11
4. Try headless mode instead:
```powershell
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up
```

### Port Already in Use

**Error:** "Port 5432 is already in use"

**Solution:**
```powershell
# Find process using the port
netstat -ano | findstr :5432

# Stop the sitting process or use a different port in compose file
```

### Permission Denied / Access Issues

**Error:** "Access denied" or "Permission denied"

**Solution:**
1. Run PowerShell as Administrator
2. Clear Docker cache:
```powershell
docker system prune -a
```

3. Rebuild images:
```powershell
docker-compose build --no-cache
```

### Out of Disk Space

**Error:** "no space left on device"

**Solution:**
```powershell
# Check Docker disk usage
docker system df

# Clean up unused images/containers
docker system prune -a --volumes

# If needed, expand Docker disk in Docker Desktop settings
```

## Performance Tips

### Windows Defender Exclusion (Faster Build Times)

Add Docker volumes folder to Windows Defender exclusions:

1. Windows Defender app → Virus & threat protection
2. Manage settings → Add exclusions
3. Add folder: `C:\Users\<YourUsername>\AppData\Local\Docker`

### WSL2 Memory Limit

If experiencing slow performance, limit WSL2 memory in `C:\Users\<YourUsername>\.wslconfig`:

```ini
[wsl2]
memory=4GB
processors=4
swap=2GB
```

### Mount Volume Optimization

The Windows compose files use `:cached` mount option for better performance:
```yaml
volumes:
  - .:/app:cached
```

This prioritizes host performance over container consistency.

## Next Steps

1. **For Server Deployment:** Use Option 1 (Headless mode) for production
2. **For Development:** Use Option 3 (Development mode) for live code editing
3. **For GUI Testing:** Use Option 2 (WSL2 with X11) to see the UI in action

## Getting Help

If you encounter issues:

1. Check the main [DOCKER_README.md](DOCKER_README.md)
2. Review logs: `docker-compose logs -f`
3. Restart Docker Desktop from system tray
4. For WSL2 issues: https://docs.microsoft.com/en-us/windows/wsl/
5. For Docker issues: https://docs.docker.com/desktop/windows/troubleshoot/

## Additional Resources

- Docker Documentation: https://docs.docker.com/
- WSL2 Documentation: https://docs.microsoft.com/en-us/windows/wsl/
- VcXsrv Documentation: https://sourceforge.net/projects/vcxsrv/
- DropMe Project: See main README.md
