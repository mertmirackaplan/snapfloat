"""Windows Registry helper to mute/unmute native Windows Snipping Tool notifications."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# Windows 10 & 11 Snipping Tool (ScreenSketch) AUMIDs under Notifications\Settings
SNIPPING_TOOL_AUMIDS: tuple[str, ...] = (
    "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "Microsoft.Windows.Shell.SnippingTool",
)

NOTIFICATIONS_BASE_KEY: str = (
    r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
)


def is_snipping_notification_muted() -> bool:
    """
    Return True if Windows Snipping Tool notifications are currently muted
    (Enabled=0 and ShowInActionCenter=0 in HKCU Notifications\\Settings).
    """
    if sys.platform != "win32":
        return False

    import winreg

    key_path = f"{NOTIFICATIONS_BASE_KEY}\\{SNIPPING_TOOL_AUMIDS[0]}"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_READ,
        ) as key:
            enabled_val, _ = winreg.QueryValueEx(key, "Enabled")
            return int(enabled_val) == 0
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_snipping_notification_muted(muted: bool) -> bool:
    """
    Suppress or restore native Windows 11 Snipping Tool toast banners and sounds
    so only SnapFloat's macOS-style preview card & shutter sound appear.
    """
    if sys.platform != "win32":
        return False

    import winreg

    dword_val = 0 if muted else 1
    success = False

    for aumid in SNIPPING_TOOL_AUMIDS:
        key_path = f"{NOTIFICATIONS_BASE_KEY}\\{aumid}"
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, "Enabled", 0, winreg.REG_DWORD, dword_val)
                winreg.SetValueEx(key, "ShowInActionCenter", 0, winreg.REG_DWORD, dword_val)
                winreg.SetValueEx(key, "SoundFile", 0, winreg.REG_SZ, "" if muted else "ms-winsoundevent:Notification.Default")
            success = True
        except OSError as exc:
            logger.warning(
                "Could not update notification registry key for %s: %s",
                aumid,
                exc,
            )

    if success:
        logger.info("Windows Snipping Tool native notifications muted=%s", muted)
    return success
