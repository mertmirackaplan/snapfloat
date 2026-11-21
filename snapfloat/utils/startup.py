"""Windows Registry helper to toggle 'Start with Windows' in HKCU Run."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from snapfloat import __app_name__

logger = logging.getLogger(__name__)

RUN_REGISTRY_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_startup_command() -> str:
    """Build the command string used to launch SnapFloat at Windows login."""
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller standalone executable
        exe_path = Path(sys.executable).resolve()
        return f'"{exe_path}"'

    # Running from Python source; prefer pythonw.exe to suppress console window
    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    interpreter = pythonw_exe if pythonw_exe.exists() else python_exe
    main_script = (Path(__file__).resolve().parents[2] / "main.py").resolve()
    return f'"{interpreter}" "{main_script}"'


def is_startup_enabled() -> bool:
    """Return True if SnapFloat is registered in HKCU\\...\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_REGISTRY_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, __app_name__)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Unable to query startup registry key: %s", exc)
        return False


def set_startup_enabled(enabled: bool) -> bool:
    """
    Enable or disable 'Start with Windows' in HKCU\\...\\CurrentVersion\\Run.
    Returns True if the operation succeeded.
    """
    if sys.platform != "win32":
        logger.warning("Windows Registry startup toggle is only supported on win32.")
        return False

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_REGISTRY_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                cmd = get_startup_command()
                winreg.SetValueEx(key, __app_name__, 0, winreg.REG_SZ, cmd)
                logger.info("Registered '%s' in Windows startup: %s", __app_name__, cmd)
            else:
                try:
                    winreg.DeleteValue(key, __app_name__)
                    logger.info("Removed '%s' from Windows startup.", __app_name__)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        logger.error("Failed to update Windows startup registry entry: %s", exc)
        return False
