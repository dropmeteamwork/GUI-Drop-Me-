# Multi-stage build for DropMe GUI Application
# Stage 1: Builder - Install dependencies and build
FROM python:3.12-slim as builder

WORKDIR /build

# Install system dependencies needed for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libfontconfig1 \
    libxext6 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY qml/ ./qml/

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -e ".[dev]"

# Stage 2: Runtime - Minimal image for running the application
FROM python:3.12-slim as runtime

WORKDIR /app

# Install only runtime dependencies (including X11 libraries for GUI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libfontconfig1 \
    libxext6 \
    libsm6 \
    libxrender1 \
    libxkbcommon0 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkb1 \
    libxcb-util1 \
    libxcb-image0 \
    libharfbuzz0b \
    libfreetype6 \
    libpng16-16 \
    libffi-dev \
    libjpeg62-turbo \
    libxcb-shape0 \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /build/src ./src
COPY --from=builder /build/qml ./qml
COPY --from=builder /build/pyproject.toml /build/README.md ./

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:$PYTHONPATH \
    LIBVA_DRIVER_NAME=dummy \
    LD_PRELOAD= \
    QT_QPA_PLATFORM=offscreen \
    # Windows compatibility: Allow GUI via X11 or offscreen rendering
    XDG_RUNTIME_DIR=/tmp/runtime-appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import gui; print('OK')" || exit 1

# Default command
CMD ["python", "-m", "gui.main"]
