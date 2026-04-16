# Docker Setup for DropMe GUI Application

This project includes Docker and Docker Compose configurations for running the DropMe GUI application in containerized environments. Configurations are provided for Linux, macOS, and Windows systems.

## Quick Start

### Prerequisites
- Docker Desktop (version 20.10+) or Docker Engine
- Docker Compose (version 2.0+)
- X11 server (for GUI display on Linux/macOS)

### Build and Run

```bash
# Build the Docker image
docker-compose build

# Run the application
docker-compose up
```

## Platform Selection Guide

Choose the appropriate Docker Compose configuration for your platform:

| Platform | Use Case | Command |
|----------|----------|---------|
| **Windows 10/11 - Headless** | Server/CI/CD (no GUI) | `docker-compose -f docker-compose.yml -f docker-compose.windows.yml up` |
| **Windows 10/11 - WSL2 + X11** | Desktop with GUI display | `docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml up` |
| **Windows 10/11 - Development** | Development with code hot-reload | `docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml up` |
| **Linux/macOS** | Development/production with X11 | `docker-compose up` |
| **Linux/macOS - Development** | Development with live updates | `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up` |

## Detailed Usage

### Production Build

Build the optimized runtime image:

```bash
docker build -t dropme-gui:latest .
```

Run with X11 forwarding on Linux:

```bash
docker-compose up
```

### Development Mode

Use the development compose file for development workflow:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

This uses the `builder` stage and mounts the entire project for live code updates.

### Interactive Development

Enter the development container:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm dropme-gui bash
```

Run tests in container:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm dropme-gui pytest
```

## Docker Architecture

### Multi-stage Build

The `Dockerfile` uses a two-stage build process:

1. **Builder Stage**: Installs all dependencies and project packages
2. **Runtime Stage**: Contains only runtime dependencies for minimal image size

### Volumes

- `/app/src` - Application source code
- `/app/qml` - QML UI files
- `dropme-logs` - Application logs
- `dropme-data` - Persistent application data
- `/tmp/.X11-unix` - X11 socket for GUI display

### Networks

- `dropme-network` - Internal bridge network connecting services

## X11 Display Forwarding

For GUI display on Linux:

```bash
# Allow local connections
xhost +local:docker

# Run with display forwarding
DISPLAY=$DISPLAY docker-compose up
```

### macOS (using Docker Desktop)

For macOS, you'll need an X11 server like XQuartz:

```bash
# Install XQuartz if not present
brew install xquartz

# Start XQuartz and enable remote connections
open -a XQuartz
# In XQuartz Preferences > Security, enable "Allow connections from network clients"

# Run with socat for display forwarding
socat TCP-LISTEN:6000,reuseaddr,fork UNIX-CONNECT:$HOME/.X11-unix/X0 &
docker-compose up
```

### Windows 10/11 - Three Options

#### Option 1: Headless Mode (Recommended for Server/CI/CD)

No GUI display needed - run in headless mode:

```cmd
@REM Use the Windows-specific compose file
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up
```

This is ideal for:Linux/macOS only, auto-detected)
- `XAUTHORITY` - X11 authentication file (Linux/macOS only, defaults to `$HOME/.Xauthority`)
- `DROPME_DEV` - Enable development mode (0=production, 1=development)
- `PYTHONUNBUFFERED=1` - Ensure Python output is unbuffered
- `QT_QPA_PLATFORM` - Platform abstraction (xcb=X11, offscreen=headless/Windows)
- `LIBGL_ALWAYS_INDIRECT=1` - Use indirect OpenGL rendering (WSL2 only)
- Testing

#### Option 2: WSL2 with X11 Forwarding (GUI Display)

Requires VcXsrv or Xming X11 server on Windows:

1. **Install X11 server on Windows:**
   - Download VcXsrv from https://sourceforge.net/projects/vcxsrv/
   - Or Xming from https://xming.en.softonic.com/
   - Run the X11 server with these settings:
     - Multiple windows mode
     - Start no client
     - Disable native opengl
     - Enable remote sessions (for Docker)

2. **Run application with X11 forwarding:**

```cmd
@REM In PowerShell/Command Prompt
docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml up
```

#### Option 3: Development Mode (Live Code Editing)

For development with code hot-reload:

```cmd
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui bash
```

Once inside the container:

```bash
# Install in development mode
pip install -e .

# Run application
python -m gui.main

# Or run tests
pytest

# Or watch for changes
pytest-watch
```

## Environment Variables

- `DISPLAY` - X11 display socket (auto-detected on Linux)
- `XAUTHORITY` - X11 authentication file (defaults to `$HOME/.Xauthority`)
- `DROPME_DEV` - Enable development mode (0=production, 1=development)
- `PYTHONUNBUFFERED=1` - Ensure Python output is unbuffered

## Optional Services

### PostgreSQL Database (Development)

Include the optional database service:

```bash
docker-compose --profile dev up
```

This includes a PostgreSQL service on port 5432:
- User: `dropme`
- Password: `dropme_dev`
- Database: `dropme_db`

## TWindows: Container exits immediately

**Check logs:**

```cmd
docker-compose -f docker-compose.yml -f docker-compose.windows.yml logs -f
```

**Common causes:**
- Entry point not found
- Missing dependencies
- Python script errors

**Solution:**

```cmd
@REM Start with interactive bash to debug
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui bash
```

### Windows: X11 not connecting (WSL2 mode)

**Verify X11 server is running:**
- Check VcXsrv is running in system tray
- Ensure "Remote sessions" is enabled

**Check display:**

```cmd
echo %DISPLAY%
```

Should show something like `host.docker.internal:0`

**Restart X11 server:**
- Stop VcXsrv/Xming
- Close Docker container
- Restart X11 server
- Restart container

### Windows: Permission denied on volumes

**Solution:**

```cmd
@REM Reset directory permissions
icacls . /grant:r %USERNAME%:F /t

@REM Or use Docker with elevated permissions
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up
```

### Linux/macOS: GUI not displaying

1. Check X11 forwarding is working:
   ```bash
   xhost
   ```

2. Verify DISPLAY variable:
   ```bash
   echo $DISPLAY
   ```

3. Check X11 socket:
   ```bash
   ls -l /tmp/.X11-unix/
   ```

### Permission denied on X11 socket (Linux)

```bash
sudo chmod 666 /tmp/.X11-unix/X0
```

### High memory usage (All platforms)

Adjust resource limits in respective compose file:

```yaml
deploy:
  resources:
    limits:
      memory: 4G
```

### Windows: Docker Compose file not found

Use forward slashes in Windows Command Prompt:

```cmd
@REM Correct
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up

@REM Wrong (backslashes not recognized)
docker-compose -f docker-compose.yml -f docker-compose\windows.yml up
    limits:
      memory: 4G
```

## Performance Optimization

### Volume Mounts

- Use `cached` option for source mounts on Docker Desktop for macOS
- Use `delegated` for even faster mounts (may cause sync delays)

### Layer Caching

Dockerfile is optimized for layer caching:
1. System dependencies installed first
2. Project dependencies installed next
3. Application code copied last

## Security Considerations

- Non-root user (`appuser`) runs the application
- `no-new-privileges` security option enabled
- Capability dropping for network operations
- Resource limits enforced

## Building for Different Architectures

### Linux ARM64 (Raspberry Pi, etc.)

```bash
docker buildx build --platform linux/arm64 -t dropme-gui:latest .
```

### Multi-architecture build

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t dropme-gui:latest .
```

## Cleanup

Remove containers and volumes:

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (data loss)
docker-compose down -v

# Remove dangling images
docker image prune

# Full cleanup
docker system prune -a --volumes
```Platform-Specific Commands

### Linux/macOS

```bash
# Build and run (with X11 display)
docker-compose up

# Development mode
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Run tests
docker-compose run --rm dropme-gui pytest

# Stop services
docker-compose down
```

### Windows 10/11 - Headless Mode

```cmd
# Build and run (no GUI)
docker-compose -f docker-compose.yml -f docker-compose.windows.yml up

# Development mode with code editing
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml up

# Run tests
docker-compose -f docker-compose.yml -f docker-compose.windows-dev.yml run --rm dropme-gui pytest

# Stop services
docker-compose down

# View logs
docker-compose logs -f
```

### Windows 10/11 - WSL2 with X11 (GUI)

```cmd
# Ensure X11 server is running first!
# Then start the application
docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml up

# Run tests
docker-compose -f docker-compose.yml -f docker-compose.windows-wsl2.yml run --rm dropme-gui pytest

# Stop services
docker-compose down
```

### General Commands (All Platforms)

```bash
# View logs
docker-compose logs -f

# Enter container shell
docker-compose exec dropme-gui bash

# Rebuild image
docker-compose build --no-cache

# View service status
docker-compose ps

# Stop services
docker-compose down

# Clean up volumes (removes data)
docker-compose down -v

# Clean all Docker resources
docker system prune -a --volume
# View service status
docker-compose ps
```

## Support

For issues or questions, refer to the main README.md or open an issue on GitHub.
