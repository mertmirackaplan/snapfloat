"""Dual-trigger screenshot watcher (watchdog folder observer + Qt clipboard listener)."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from snapfloat.config import (
    CLIPBOARD_FALLBACK_DELAY_MS,
    DEDUP_COOLDOWN_SEC,
    FILE_POLL_INTERVAL_MS,
    FILE_POLL_MAX_ATTEMPTS,
    SUPPORTED_EXTENSIONS,
    get_temp_screenshots_dir,
    resolve_screenshot_directories,
)

logger = logging.getLogger(__name__)


def compute_image_signature(image: QImage) -> str:
    """Compute a fast deterministic hash from image dimensions and downsampled pixels."""
    if image.isNull():
        return ""
    small = image.scaled(
        32,
        32,
        Qt_IgnoreAspectRatio := QImage_aspect_ignore(),
    ).convertToFormat(QImage.Format.Format_RGBA8888)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    small.save(buf, "PNG")
    buf.close()
    digest = hashlib.sha256(bytes(ba.data())).hexdigest()[:16]
    return f"{image.width()}x{image.height()}:{digest}"


def QImage_aspect_ignore():
    """Return scoped Qt.AspectRatioMode.IgnoreAspectRatio."""
    from PySide6.QtCore import Qt

    return Qt.AspectRatioMode.IgnoreAspectRatio


class _FolderEventHandler(FileSystemEventHandler):
    """Watchdog event handler that emits file paths over a thread-safe Qt Signal."""

    def __init__(self, notify_callback) -> None:
        super().__init__()
        self._notify = notify_callback

    def on_created(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            self._check_and_emit(str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            self._check_and_emit(str(event.dest_path))

    def _check_and_emit(self, path_str: str) -> None:
        ext = os.path.splitext(path_str)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            self._notify(path_str)


@dataclass
class _PollState:
    """Tracks non-blocking readiness polling for a newly created image file."""

    path: str
    attempts: int = 0
    last_size: int = -1


class ScreenshotWatcher(QObject):
    """
    Coordinates both folder monitoring (via watchdog) and clipboard image monitoring
    (via QClipboard.dataChanged) with safe file readiness polling and deduplication.
    """

    screenshot_ready = Signal(str, QPixmap)
    _raw_file_detected = Signal(str)

    def __init__(self, paused: bool = False, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._paused: bool = paused
        self._watched_dirs: List[Path] = resolve_screenshot_directories()
        self._observer: Optional[Observer] = None

        # Active file polling entries keyed by normalized path
        self._polling_files: Dict[str, _PollState] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(FILE_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll_tick)

        # Pending clipboard fallback timer
        self._pending_clip_image: Optional[QImage] = None
        self._pending_clip_sig: str = ""
        self._clip_timer = QTimer(self)
        self._clip_timer.setSingleShot(True)
        self._clip_timer.setInterval(CLIPBOARD_FALLBACK_DELAY_MS)
        self._clip_timer.timeout.connect(self._commit_pending_clipboard_image)

        # Deduplication state
        self._last_emit_time: float = 0.0
        self._last_emit_sig: str = ""
        self._last_emit_dims: tuple[int, int] = (0, 0)
        self._last_emit_path: str = ""
        self._internal_clipboard_sigs: set[str] = set()

        # Internal thread-safe bridge from watchdog thread -> Qt main thread
        self._raw_file_detected.connect(self._on_file_detected_main_thread)

        # Connect Qt clipboard listener
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    @property
    def watched_directories(self) -> List[Path]:
        """Return the list of directories currently monitored for new screenshots."""
        return list(self._watched_dirs)

    @property
    def is_paused(self) -> bool:
        """Return True if monitoring is currently paused."""
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Pause or resume screenshot detection."""
        self._paused = paused
        if paused:
            self._clip_timer.stop()
            self._pending_clip_image = None
            self._polling_files.clear()
            self._poll_timer.stop()
        logger.info("ScreenshotWatcher paused=%s", paused)

    def register_internal_clipboard_image(self, pixmap: QPixmap) -> None:
        """
        Mark a pixmap copied by SnapFloat's own 'Copy' button so the clipboard
        listener does not trigger a new floating preview card for it.
        """
        if not pixmap.isNull():
            sig = compute_image_signature(pixmap.toImage())
            if sig:
                self._internal_clipboard_sigs.add(sig)

    def start(self) -> None:
        """Start the background watchdog folder observer."""
        if self._observer is not None:
            return

        self._watched_dirs = resolve_screenshot_directories()
        observer = Observer()
        handler = _FolderEventHandler(self._raw_file_detected.emit)

        for folder in self._watched_dirs:
            try:
                observer.schedule(handler, str(folder), recursive=False)
                logger.info("Watching screenshots directory: %s", folder)
            except Exception as exc:
                logger.warning("Failed to watch folder %s: %s", folder, exc)

        observer.daemon = True
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        """Cleanly stop timers and terminate the watchdog observer thread."""
        self._clip_timer.stop()
        self._poll_timer.stop()
        self._polling_files.clear()

        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception as exc:
                logger.warning("Error stopping watchdog observer: %s", exc)
            finally:
                self._observer = None
            logger.info("Watchdog observer stopped.")

    def _on_file_detected_main_thread(self, file_path: str) -> None:
        """Slot executed on the Qt main thread when watchdog detects a new image file."""
        if self._paused:
            return

        norm_path = os.path.normcase(os.path.abspath(file_path))
        if norm_path in self._polling_files:
            return

        logger.debug("Detected new screenshot file candidate: %s", file_path)

        # If a clipboard capture is waiting for a matching saved file, cancel or delay it
        if self._clip_timer.isActive():
            self._clip_timer.stop()

        self._polling_files[norm_path] = _PollState(path=os.path.abspath(file_path))
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _on_poll_tick(self) -> None:
        """Poll pending files every 100 ms until size stabilizes and QPixmap loads cleanly."""
        if not self._polling_files:
            self._poll_timer.stop()
            return

        finished_keys: List[str] = []

        for key, state in list(self._polling_files.items()):
            state.attempts += 1
            try:
                if not os.path.exists(state.path):
                    if state.attempts >= FILE_POLL_MAX_ATTEMPTS:
                        finished_keys.append(key)
                    continue
                current_size = os.path.getsize(state.path)
            except OSError:
                if state.attempts >= FILE_POLL_MAX_ATTEMPTS:
                    finished_keys.append(key)
                continue

            if current_size > 0 and current_size == state.last_size:
                pixmap = QPixmap(state.path)
                if not pixmap.isNull():
                    finished_keys.append(key)
                    self._PendingClipCancelIfMatches(pixmap)
                    self._emit_if_not_duplicate(state.path, pixmap)
                    continue

            state.last_size = current_size
            if state.attempts >= FILE_POLL_MAX_ATTEMPTS:
                logger.warning("Timed out waiting for file to stabilize: %s", state.path)
                finished_keys.append(key)

        for key in finished_keys:
            self._polling_files.pop(key, None)

        if not self._polling_files:
            self._poll_timer.stop()
            # If a pending clipboard image never matched any saved file, flush it
            if self._pending_clip_image is not None and not self._clip_timer.isActive():
                self._commit_pending_clipboard_image()

    def _PendingClipCancelIfMatches(self, file_pixmap: QPixmap) -> None:
        """Discard any pending clipboard image if a folder screenshot just arrived."""
        if self._pending_clip_image is None:
            return
        file_w, file_h = file_pixmap.width(), file_pixmap.height()
        clip_w, clip_h = self._pending_clip_image.width(), self._pending_clip_image.height()
        if (file_w, file_h) == (clip_w, clip_h):
            logger.debug("Matched folder file with pending clipboard image; suppressing temp save.")
            self._pending_clip_image = None
            self._pending_clip_sig = ""
            self._clip_timer.stop()

    def _on_clipboard_changed(self) -> None:
        """Handle QClipboard.dataChanged for newly copied screenshot images."""
        if self._paused:
            return

        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return

        mime = clipboard.mimeData()
        if mime is None or not mime.hasImage():
            return

        image = clipboard.image()
        if image.isNull():
            return

        sig = compute_image_signature(image)
        if not sig:
            return

        # Ignore clipboard updates triggered by our own 'Copy' action
        if sig in self._internal_clipboard_sigs:
            self._internal_clipboard_sigs.discard(sig)
            return

        # Ignore if identical to recently emitted screenshot within cooldown
        now = time.monotonic()
        dims = (image.width(), image.height())
        if (now - self._last_emit_time) <= DEDUP_COOLDOWN_SEC:
            if sig == self._last_emit_sig or dims == self._last_emit_dims:
                logger.debug("Clipboard image deduplicated against recent file screenshot.")
                return

        # Hold clipboard image for 400 ms to see if Snipping Tool also writes a file
        self._pending_clip_image = image
        self._pending_clip_sig = sig
        self._clip_timer.start()

    def _commit_pending_clipboard_image(self) -> None:
        """Save clipboard-only image to a temp PNG so native file drag-and-drop works."""
        if self._paused or self._pending_clip_image is None:
            return

        # If a file is actively polling right now, wait for polling to finish first
        if self._polling_files:
            return

        image = self._pending_clip_image
        sig = self._pending_clip_sig
        self._pending_clip_image = None
        self._pending_clip_sig = ""

        now = time.monotonic()
        dims = (image.width(), image.height())
        if (now - self._last_emit_time) <= DEDUP_COOLDOWN_SEC:
            if sig == self._last_emit_sig or dims == self._last_emit_dims:
                return

        temp_dir = get_temp_screenshots_dir()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        ms = int((time.time() % 1) * 1000)
        temp_path = temp_dir / f"SnapFloat_{timestamp}_{ms:03d}.png"

        if image.save(str(temp_path), "PNG"):
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                logger.info("Saved clipboard screenshot to temp file: %s", temp_path)
                self._emit_if_not_duplicate(str(temp_path), pixmap, precomputed_sig=sig)

    def _emit_if_not_duplicate(
        self,
        file_path: str,
        pixmap: QPixmap,
        precomputed_sig: Optional[str] = None,
    ) -> None:
        """Perform final cooldown + signature/dimension deduplication before emitting."""
        now = time.monotonic()
        dims = (pixmap.width(), pixmap.height())
        sig = precomputed_sig or compute_image_signature(pixmap.toImage())
        norm_path = os.path.normcase(os.path.abspath(file_path))

        if (now - self._last_emit_time) <= DEDUP_COOLDOWN_SEC:
            if (
                norm_path == self._last_emit_path
                or (sig and sig == self._last_emit_sig)
                or dims == self._last_emit_dims
            ):
                logger.debug("Suppressed duplicate screenshot popup for %s", file_path)
                return

        self._last_emit_time = now
        self._last_emit_sig = sig
        self._last_emit_dims = dims
        self._last_emit_path = norm_path

        logger.info("Screenshot ready: %s (%dx%d)", file_path, dims[0], dims[1])
        self.screenshot_ready.emit(os.path.abspath(file_path), pixmap)
