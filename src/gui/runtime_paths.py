from __future__ import annotations

import os
import sys
from pathlib import Path


APP_VENDOR = "dropme"
APP_NAME = "gui"
DEFAULT_RELEASE_DIRNAME = "gui-v1.1.3"


def _env_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def home_dir() -> Path:
    return Path.home().resolve()


def data_root() -> Path:
    """
    Cross-platform runtime data directory.
    Priority:
      1) DROPME_DATA_DIR
      2) XDG_DATA_HOME/<vendor>/<app>
      3) Windows %LOCALAPPDATA%/<vendor>/<app>
      4) ~/.local/share/<vendor>/<app>
    """
    p = _env_path("DROPME_DATA_DIR")
    if p is not None:
        return p

    xdg_data_home = _env_path("XDG_DATA_HOME")
    if xdg_data_home is not None:
        return xdg_data_home / APP_VENDOR / APP_NAME

    if sys.platform.startswith("win"):
        local_app_data = _env_path("LOCALAPPDATA")
        if local_app_data is not None:
            return local_app_data / APP_VENDOR / APP_NAME

    return home_dir() / ".local" / "share" / APP_VENDOR / APP_NAME


def state_root() -> Path:
    """
    Cross-platform runtime state directory.
    Priority:
      1) DROPME_STATE_DIR
      2) XDG_STATE_HOME/<vendor>
      3) Windows %LOCALAPPDATA%/<vendor>/state
      4) ~/.local/state/<vendor>
    """
    p = _env_path("DROPME_STATE_DIR")
    if p is not None:
        return p

    xdg_state_home = _env_path("XDG_STATE_HOME")
    if xdg_state_home is not None:
        return xdg_state_home / APP_VENDOR

    if sys.platform.startswith("win"):
        local_app_data = _env_path("LOCALAPPDATA")
        if local_app_data is not None:
            return local_app_data / APP_VENDOR / "state"

    return home_dir() / ".local" / "state" / APP_VENDOR


def release_dirname() -> str:
    return os.getenv("DROPME_RELEASE_DIRNAME", DEFAULT_RELEASE_DIRNAME).strip() or DEFAULT_RELEASE_DIRNAME


def models_dir() -> Path:
    """
    Model directory.
    Priority:
      1) DROPME_MODELS_DIR
      2) <state_root>/<release>/src/gui/new_models
    """
    p = _env_path("DROPME_MODELS_DIR")
    if p is not None:
        return p
    return state_root() / release_dirname() / "src" / "gui" / "new_models"


def model_logs_dir() -> Path:
    return models_dir() / "log"


def captures_dir() -> Path:
    return data_root() / "captures"


def metadata_dir() -> Path:
    return data_root() / "metadata"


def upload_queue_dir() -> Path:
    return data_root() / "upload_queue"


def brand_cache_dir() -> Path:
    return data_root() / "brand_cache"

