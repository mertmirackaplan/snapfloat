"""Application configuration, constants, screenshot folder resolution, and JSON settings."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

from PySide6.QtCore import QStandardPaths

from snapfloat import __app_name__

logger = logging.getLogger(__name__)

# UI & Timing Constants
CARD_WIDTH: int = 280
CARD_HEIGHT: int = 185
CARD_MARGIN: int = 16
CARD_RADIUS: int = 12
AUTO_DISMISS_MS: int = 6000
SLIDE_IN_DURATION_MS: int = 260
FADE_OUT_DURATION_MS: int = 180

# Watcher & Deduplication Constants
CLIPBOARD_FALLBACK_DELAY_MS: int = 400
DEDUP_COOLDOWN_SEC: float = 2.0
FILE_POLL_INTERVAL_MS: int = 100
FILE_POLL_MAX_ATTEMPTS: int = 20
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# Single-instance server name
SINGLE_INSTANCE_KEY: str = "SnapFloat_SingleInstance_Server_v1"


def get_app_data_dir() -> Path:
    """Return and ensure the %APPDATA%/SnapFloat configuration directory exists."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata) / __app_name__
    else:
        base_dir = Path.home() / f".{__app_name__.lower()}"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_temp_screenshots_dir() -> Path:
    """Return and ensure the temporary folder for clipboard/test screenshots exists."""
    temp_dir = Path(tempfile.gettempdir()) / __app_name__
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def resolve_screenshot_directories() -> List[Path]:
    """
    Resolve all candidate Windows Screenshots directories, including standard
    Pictures/Screenshots and OneDrive fallbacks. Ensures at least the primary
    Pictures/Screenshots folder exists.
    """
    candidates: List[Path] = []

    # 1. Qt Standard PicturesLocation
    qt_pictures = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation
    )
    if qt_pictures:
        candidates.append(Path(qt_pictures) / "Screenshots")

    # 2. Environment OneDrive paths
    for env_key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        onedrive_root = os.environ.get(env_key)
        if onedrive_root:
            candidates.append(Path(onedrive_root) / "Pictures" / "Screenshots")

    # 3. Home directory fallbacks
    home = Path.home()
    candidates.append(home / "OneDrive" / "Pictures" / "Screenshots")
    candidates.append(home / "Pictures" / "Screenshots")

    resolved: List[Path] = []
    seen: set[str] = set()

    for folder in candidates:
        try:
            norm = os.path.normcase(os.path.abspath(str(folder)))
        except OSError:
            continue
        if norm in seen:
            continue
        if folder.exists() and folder.is_dir():
            seen.add(norm)
            resolved.append(folder)

    # If no Screenshots directory exists yet, create the primary one
    if not resolved and candidates:
        primary = candidates[0]
        try:
            primary.mkdir(parents=True, exist_ok=True)
            resolved.append(primary)
        except OSError as exc:
            logger.warning("Could not create primary Screenshots folder %s: %s", primary, exc)

    return resolved


@dataclass
class AppSettings:
    """Lightweight persistent user settings stored in %APPDATA%/SnapFloat/settings.json."""

    monitoring_paused: bool = False
    auto_dismiss_ms: int = AUTO_DISMISS_MS
    sound_enabled: bool = True
    mute_snipping_tool_notifications: bool = True
    start_with_windows: bool = True

    @classmethod
    def settings_path(cls) -> Path:
        """Return full path to the JSON settings file."""
        return get_app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> AppSettings:
        """Load settings from disk, falling back to defaults on missing or corrupt file."""
        path = cls.settings_path()
        if not path.exists():
            settings = cls()
            settings.save()
            return settings
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                monitoring_paused=bool(data.get("monitoring_paused", False)),
                auto_dismiss_ms=int(data.get("auto_dismiss_ms", AUTO_DISMISS_MS)),
                sound_enabled=bool(data.get("sound_enabled", True)),
                mute_snipping_tool_notifications=bool(
                    data.get("mute_snipping_tool_notifications", True)
                ),
                start_with_windows=bool(data.get("start_with_windows", True)),
            )
        except Exception as exc:
            logger.warning("Failed to read settings from %s, using defaults: %s", path, exc)
            return cls()

    def save(self) -> None:
        """Persist current settings to %APPDATA%/SnapFloat/settings.json."""
        path = self.settings_path()
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save settings to %s: %s", path, exc)
