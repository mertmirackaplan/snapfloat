"""System tray controller orchestrating the screenshot watcher, context menu, and floating card."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from snapfloat import __app_name__, __version__
from snapfloat.config import (
    AppSettings,
    get_temp_screenshots_dir,
    resolve_screenshot_directories,
)
from snapfloat.ui.icons import create_app_tray_icon
from snapfloat.ui.preview_card import PreviewCard
from snapfloat.utils.snipping_notifications import (
    is_snipping_notification_muted,
    set_snipping_notification_muted,
)
from snapfloat.utils.sound import ensure_shutter_wav_path, play_shutter_sound
from snapfloat.utils.startup import is_startup_enabled, set_startup_enabled
from snapfloat.watcher import ScreenshotWatcher

logger = logging.getLogger(__name__)


class SnapFloatTrayController(QObject):
    """
    Manages the QSystemTrayIcon, its context menu, the dual-trigger ScreenshotWatcher,
    and the lifecycle of the floating PreviewCard.
    """

    def __init__(self, app: QApplication, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._app = app
        self._settings = AppSettings.load()
        self._active_card: Optional[PreviewCard] = None

        # Pre-generate macOS shutter WAV and apply Snipping Tool toast suppression
        ensure_shutter_wav_path()
        if self._settings.mute_snipping_tool_notifications:
            set_snipping_notification_muted(True)

        # Initialize Dual-Trigger Watcher
        self._watcher = ScreenshotWatcher(paused=self._settings.monitoring_paused, parent=self)
        self._watcher.screenshot_ready.connect(self.show_preview)

        # Initialize System Tray Icon
        self._tray = QSystemTrayIcon(self)
        self._update_tray_appearance()
        self._build_context_menu()
        self._tray.activated.connect(self._on_tray_activated)

    def start(self) -> None:
        """Show the system tray icon and start the screenshot folder observer."""
        self._tray.show()
        self._watcher.start()
        logger.info("%s v%s started in system tray.", __app_name__, __version__)

    def shutdown(self) -> None:
        """Stop background monitoring, close any active preview card, and quit."""
        logger.info("Shutting down %s...", __app_name__)
        self._watcher.stop()
        if self._active_card is not None:
            self._active_card.dismiss_immediately()
            self._active_card = None
        self._tray.hide()
        self._app.quit()

    def _build_context_menu(self) -> None:
        """Construct the styled native dark-friendly tray context menu."""
        menu = QMenu()

        # 1. Test Preview
        self._act_test = QAction("Test Preview", menu)
        self._act_test.triggered.connect(self.trigger_test_preview)
        menu.addAction(self._act_test)

        menu.addSeparator()

        # 2. Pause / Resume Monitoring toggle
        self._act_pause = QAction(menu)
        self._act_pause.setCheckable(True)
        self._act_pause.setChecked(self._settings.monitoring_paused)
        self._update_pause_action_text()
        self._act_pause.triggered.connect(self._on_toggle_pause)
        menu.addAction(self._act_pause)

        # 3. macOS Shutter Sound toggle
        self._act_sound = QAction("macOS Shutter Sound", menu)
        self._act_sound.setCheckable(True)
        self._act_sound.setChecked(self._settings.sound_enabled)
        self._act_sound.triggered.connect(self._on_toggle_sound)
        menu.addAction(self._act_sound)

        # 4. Mute Snipping Tool Banner toggle
        self._act_mute_snip = QAction("Mute Snipping Tool Notification", menu)
        self._act_mute_snip.setCheckable(True)
        self._act_mute_snip.setChecked(self._settings.mute_snipping_tool_notifications)
        self._act_mute_snip.triggered.connect(self._on_toggle_mute_snip)
        menu.addAction(self._act_mute_snip)

        # 5. Start with Windows checkable toggle
        self._act_startup = QAction("Start with Windows", menu)
        self._act_startup.setCheckable(True)
        self._act_startup.setChecked(is_startup_enabled())
        self._act_startup.triggered.connect(self._on_toggle_startup)
        menu.addAction(self._act_startup)

        menu.addSeparator()

        # 6. Open Screenshots Folder
        self._act_open_folder = QAction("Open Screenshots Folder", menu)
        self._act_open_folder.triggered.connect(self._on_open_screenshots_folder)
        menu.addAction(self._act_open_folder)

        menu.addSeparator()

        # 7. Exit
        self._act_exit = QAction("Exit", menu)
        self._act_exit.triggered.connect(self.shutdown)
        menu.addAction(self._act_exit)

        self._menu = menu
        self._tray.setContextMenu(self._menu)

    def _update_pause_action_text(self) -> None:
        if self._settings.monitoring_paused:
            self._act_pause.setText("Resume Monitoring")
        else:
            self._act_pause.setText("Pause Monitoring")

    def _update_tray_appearance(self) -> None:
        paused = self._settings.monitoring_paused
        self._tray.setIcon(create_app_tray_icon(paused=paused))
        status_str = "Paused" if paused else "Active"
        self._tray.setToolTip(f"{__app_name__} v{__version__} ({status_str})")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Refresh registry state before menu display, or open test preview on double-click."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.trigger_test_preview()
        elif reason in (
            QSystemTrayIcon.ActivationReason.Context,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self._act_startup.setChecked(is_startup_enabled())
            self._act_mute_snip.setChecked(is_snipping_notification_muted())

    def _on_toggle_pause(self, checked: bool) -> None:
        self._settings.monitoring_paused = checked
        self._settings.save()
        self._watcher.set_paused(checked)
        self._update_pause_action_text()
        self._update_tray_appearance()

    def _on_toggle_sound(self, checked: bool) -> None:
        self._settings.sound_enabled = checked
        self._settings.save()
        if checked:
            play_shutter_sound()

    def _on_toggle_mute_snip(self, checked: bool) -> None:
        if set_snipping_notification_muted(checked):
            self._settings.mute_snipping_tool_notifications = checked
            self._settings.save()
        else:
            self._act_mute_snip.setChecked(is_snipping_notification_muted())

    def _on_toggle_startup(self, checked: bool) -> None:
        success = set_startup_enabled(checked)
        if not success:
            # Revert checkmark if registry write failed
            self._act_startup.setChecked(is_startup_enabled())

    def _on_open_screenshots_folder(self) -> None:
        folders = self._watcher.watched_directories or resolve_screenshot_directories()
        target: Path = folders[0] if folders else Path.home()
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def show_preview(self, file_path: str, pixmap: QPixmap) -> None:
        """
        Play macOS shutter sound and show the floating preview card for a newly
        captured screenshot, cleanly replacing any currently open preview card.
        """
        if pixmap.isNull():
            return

        if self._settings.sound_enabled:
            play_shutter_sound()

        if self._active_card is not None:
            try:
                self._active_card.closed.disconnect(self._on_card_closed)
            except (RuntimeError, TypeError):
                pass
            self._active_card.dismiss_immediately()
            self._active_card = None

        card = PreviewCard(
            file_path=file_path,
            pixmap=pixmap,
            auto_dismiss_ms=self._settings.auto_dismiss_ms,
            on_internal_copy=self._watcher.register_internal_clipboard_image,
        )
        card.closed.connect(self._on_card_closed)
        self._active_card = card
        card.show_animated()

    def _on_card_closed(self, card_obj: object) -> None:
        if self._active_card is card_obj:
            self._active_card = None

    def trigger_test_preview(self) -> None:
        """Generate a sleek synthetic screenshot in the system temp folder and preview it."""
        width, height = 800, 500
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Gradient background
        grad = QLinearGradient(QPointF(0.0, 0.0), QPointF(float(width), float(height)))
        grad.setColorAt(0.0, QColor("#0f172a"))
        grad.setColorAt(0.5, QColor("#1e1b4b"))
        grad.setColorAt(1.0, QColor("#311042"))
        painter.fillRect(0, 0, width, height, grad)

        # Mock window card inside test screenshot
        card_rect = QRectF(80.0, 65.0, 640.0, 370.0)
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.5))
        painter.setBrush(QColor(15, 23, 42, 210))
        painter.drawRoundedRect(card_rect, 16.0, 16.0)

        # Window traffic light dots
        dots = [("#ef4444", 110.0), ("#f59e0b", 132.0), ("#22c55e", 154.0)]
        painter.setPen(Qt.PenStyle.NoPen)
        for hex_color, cx in dots:
            painter.setBrush(QColor(hex_color))
            painter.drawEllipse(QPointF(cx, 95.0), 6.5, 6.5)

        # Title & subtitle text
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor("#f8fafc"))
        painter.drawText(
            QRectF(80.0, 155.0, 640.0, 50.0),
            Qt.AlignmentFlag.AlignCenter,
            "SnapFloat Test Capture",
        )

        sub_font = QFont("Segoe UI", 12, QFont.Weight.Normal)
        painter.setFont(sub_font)
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            QRectF(110.0, 215.0, 580.0, 65.0),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            "Drag this floating card into any app (Discord, Chrome, Explorer)\n"
            "or hover to Copy, Open, Show in Explorer, or Delete.",
        )

        # Accent pill at bottom of synthetic screenshot
        pill_rect = QRectF(285.0, 315.0, 230.0, 40.0)
        painter.setPen(QPen(QColor("#38bdf8"), 1.5))
        painter.setBrush(QColor(56, 189, 248, 35))
        painter.drawRoundedRect(pill_rect, 20.0, 20.0)

        badge_font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        painter.setFont(badge_font)
        painter.setPen(QColor("#e0f2fe"))
        timestamp_str = time.strftime("%H:%M:%S")
        painter.drawText(
            pill_rect,
            Qt.AlignmentFlag.AlignCenter,
            f"Captured at {timestamp_str}",
        )

        painter.end()

        temp_dir = get_temp_screenshots_dir()
        file_name = f"SnapFloat_Test_{int(time.time() * 1000)}.png"
        test_path = temp_dir / file_name
        pixmap.save(str(test_path), "PNG")

        logger.info("Generated test preview screenshot: %s", test_path)
        self.show_preview(str(test_path), pixmap)
