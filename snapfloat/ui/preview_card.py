"""macOS-style floating screenshot preview card with animations, hover toolbar, and native QDrag."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDrag,
    QEnterEvent,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snapfloat.config import (
    AUTO_DISMISS_MS,
    CARD_HEIGHT,
    CARD_MARGIN,
    CARD_RADIUS,
    CARD_WIDTH,
    FADE_OUT_DURATION_MS,
    SLIDE_IN_DURATION_MS,
)
from snapfloat.ui.icons import (
    icon_check,
    icon_close,
    icon_copy,
    icon_delete,
    icon_folder,
    icon_open,
)

logger = logging.getLogger(__name__)

# Outer shadow padding around the card body
SHADOW_PADDING: int = 12


class _CardBody(QWidget):
    """Custom painted dark rounded card surface holding the screenshot thumbnail and countdown bar."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._hovered: bool = False
        self._progress: float = 1.0  # 1.0 -> 0.0 countdown

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def set_hovered(self, hovered: bool) -> None:
        if self._hovered != hovered:
            self._hovered = hovered
            self.update()

    def set_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        # Card dark background (#1e1e1e)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1e1e1e"))
        painter.drawPath(clip_path)

        # Inner clipped region for thumbnail, hover gradient, and countdown progress bar
        painter.save()
        painter.setClipPath(clip_path)

        # Draw aspect-ratio-preserved thumbnail centered inside padding
        if not self._pixmap.isNull():
            pad = 8.0
            avail_w = max(1, int(self.width() - pad * 2))
            avail_h = max(1, int(self.height() - pad * 2 - 4))
            scaled = self._pixmap.scaled(
                avail_w,
                avail_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) / 2.0
            y = (self.height() - 3.0 - scaled.height()) / 2.0
            thumb_rect = QRectF(x, y, float(scaled.width()), float(scaled.height()))

            thumb_clip = QPainterPath()
            thumb_clip.addRoundedRect(thumb_rect, 7.0, 7.0)
            painter.save()
            painter.setClipPath(thumb_clip)
            painter.drawPixmap(int(x), int(y), scaled)
            painter.restore()

            # Subtle inner frame around the thumbnail image
            thumb_pen = QPen(QColor(255, 255, 255, 24))
            thumb_pen.setWidthF(1.0)
            painter.setPen(thumb_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(thumb_rect, 7.0, 7.0)

        # Hover dark scrim at top and bottom so overlay action buttons pop clearly
        if self._hovered:
            top_grad = QLinearGradient(0.0, 0.0, 0.0, 48.0)
            top_grad.setColorAt(0.0, QColor(0, 0, 0, 145))
            top_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(top_grad)
            painter.drawRect(QRectF(0.0, 0.0, float(self.width()), 48.0))

            bot_grad = QLinearGradient(0.0, float(self.height() - 62), 0.0, float(self.height()))
            bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            bot_grad.setColorAt(1.0, QColor(0, 0, 0, 195))
            painter.setBrush(bot_grad)
            painter.drawRect(QRectF(0.0, float(self.height() - 62), float(self.width()), 62.0))

        # Thin countdown bar along the bottom edge
        bar_h = 3.0
        bar_y = self.height() - bar_h
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRect(QRectF(0.0, bar_y, float(self.width()), bar_h))

        bar_w = self.width() * self._progress
        if bar_w > 0:
            bar_grad = QLinearGradient(0.0, bar_y, float(self.width()), bar_y)
            bar_grad.setColorAt(0.0, QColor("#38bdf8"))
            bar_grad.setColorAt(1.0, QColor("#818cf8"))
            painter.setBrush(bar_grad)
            painter.drawRect(QRectF(0.0, bar_y, bar_w, bar_h))

        painter.restore()

        # Subtle 1px outer border
        border_color = QColor("#4b5563") if self._hovered else QColor("#333333")
        border_pen = QPen(border_color)
        border_pen.setWidthF(1.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        painter.end()


class PreviewCard(QWidget):
    """
    Frameless, non-activating macOS-style floating preview card positioned in the
    bottom-right corner of the primary screen. Supports hover actions and native QDrag.
    """

    closed = Signal(object)

    def __init__(
        self,
        file_path: str,
        pixmap: QPixmap,
        auto_dismiss_ms: int = AUTO_DISMISS_MS,
        on_internal_copy: Optional[Callable[[QPixmap], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._file_path: str = os.path.abspath(file_path)
        self._pixmap: QPixmap = pixmap
        self._auto_dismiss_ms: int = max(1000, auto_dismiss_ms)
        self._remaining_ms: int = self._auto_dismiss_ms
        self._on_internal_copy = on_internal_copy

        self._drag_start_pos: Optional[QPoint] = None
        self._is_dragging: bool = False
        self._is_closing: bool = False

        # Keep strong references to active animations to prevent Python GC
        self._slide_anim: Optional[QPropertyAnimation] = None
        self._fade_anim: Optional[QPropertyAnimation] = None

        self._configure_window()
        self._build_ui()
        self._setup_countdown_timer()

    def _configure_window(self) -> None:
        """Apply strict PySide6 non-activating floating tool window flags and attributes."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)

        total_w = CARD_WIDTH + SHADOW_PADDING * 2
        total_h = CARD_HEIGHT + SHADOW_PADDING * 2
        self.setFixedSize(total_w, total_h)

    def _build_ui(self) -> None:
        """Construct the inner card body, drop shadow, and hover overlay buttons."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(
            SHADOW_PADDING, SHADOW_PADDING, SHADOW_PADDING, SHADOW_PADDING
        )
        root_layout.setSpacing(0)

        self._body = _CardBody(self)
        self._body.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self._body.set_pixmap(self._pixmap)

        shadow = QGraphicsDropShadowEffect(self._body)
        shadow.setBlurRadius(24.0)
        shadow.setOffset(0.0, 6.0)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._body.setGraphicsEffect(shadow)

        root_layout.addWidget(self._body)

        # Overlay layout inside the card body
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(10, 10, 10, 12)
        body_layout.setSpacing(0)

        # Top row: Close (×) button on top-right
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch(1)

        self._btn_close = QPushButton(self._body)
        self._btn_close.setFixedSize(26, 26)
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setIcon(icon_close("#f8fafc", 14))
        self._btn_close.setIconSize(QSize(14, 14))
        self._btn_close.setToolTip("Dismiss")
        self._btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_close.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(24, 24, 27, 195);
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 13px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 220);
                border-color: rgba(255, 255, 255, 80);
            }
            """
        )
        self._btn_close.clicked.connect(self.dismiss_animated)
        top_row.addWidget(self._btn_close)
        body_layout.addLayout(top_row)

        body_layout.addStretch(1)

        # Bottom action bar container
        self._toolbar_widget = QWidget(self._body)
        self._toolbar_widget.setStyleSheet(
            """
            QWidget {
                background-color: rgba(24, 24, 27, 215);
                border: 1px solid rgba(255, 255, 255, 32);
                border-radius: 9px;
            }
            """
        )
        bar_layout = QHBoxLayout(self._toolbar_widget)
        bar_layout.setContentsMargins(6, 4, 6, 4)
        bar_layout.setSpacing(4)

        btn_style = """
            QPushButton {
                background-color: transparent;
                color: #f1f5f9;
                border: none;
                border-radius: 6px;
                padding: 4px 7px;
                font-family: "Segoe UI", sans-serif;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 28);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 42);
            }
        """
        del_btn_style = """
            QPushButton {
                background-color: transparent;
                color: #fca5a5;
                border: none;
                border-radius: 6px;
                padding: 4px 6px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 55);
            }
        """

        # 1. Copy button
        self._btn_copy = QPushButton("Copy", self._toolbar_widget)
        self._btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_copy.setIcon(icon_copy("#f1f5f9", 14))
        self._btn_copy.setIconSize(QSize(14, 14))
        self._btn_copy.setToolTip("Copy image to clipboard")
        self._btn_copy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_copy.setStyleSheet(btn_style)
        self._btn_copy.clicked.connect(self._action_copy)
        bar_layout.addWidget(self._btn_copy)

        # 2. Open button
        self._btn_open = QPushButton("Open", self._toolbar_widget)
        self._btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_open.setIcon(icon_open("#f1f5f9", 14))
        self._btn_open.setIconSize(QSize(14, 14))
        self._btn_open.setToolTip("Open in default image viewer")
        self._btn_open.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_open.setStyleSheet(btn_style)
        self._btn_open.clicked.connect(self._action_open)
        bar_layout.addWidget(self._btn_open)

        # 3. Show in Explorer button
        self._btn_explorer = QPushButton("Explorer", self._toolbar_widget)
        self._btn_explorer.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_explorer.setIcon(icon_folder("#f1f5f9", 14))
        self._btn_explorer.setIconSize(QSize(14, 14))
        self._btn_explorer.setToolTip("Show in File Explorer")
        self._btn_explorer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_explorer.setStyleSheet(btn_style)
        self._btn_explorer.clicked.connect(self._action_show_in_explorer)
        bar_layout.addWidget(self._btn_explorer)

        bar_layout.addStretch(1)

        # 4. Delete button
        self._btn_delete = QPushButton(self._toolbar_widget)
        self._btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete.setIcon(icon_delete("#fca5a5", 15))
        self._btn_delete.setIconSize(QSize(15, 15))
        self._btn_delete.setToolTip("Delete screenshot file")
        self._btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_delete.setStyleSheet(del_btn_style)
        self._btn_delete.clicked.connect(self._action_delete)
        bar_layout.addWidget(self._btn_delete)

        body_layout.addWidget(self._toolbar_widget)

        # Overlay controls start hidden until mouse hover
        self._set_overlay_visible(False)

    def _set_overlay_visible(self, visible: bool) -> None:
        self._btn_close.setVisible(visible)
        self._toolbar_widget.setVisible(visible)
        self._body.set_hovered(visible)

    def _setup_countdown_timer(self) -> None:
        """Configure the 30 ms tick timer driving the 6-second auto-dismiss progress bar."""
        self._tick_interval_ms = 30
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(self._tick_interval_ms)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

    def _on_countdown_tick(self) -> None:
        if self._is_closing or self._is_dragging:
            return
        self._remaining_ms -= self._tick_interval_ms
        progress = self._remaining_ms / float(self._auto_dismiss_ms)
        self._body.set_progress(progress)
        if self._remaining_ms <= 0:
            self._countdown_timer.stop()
            self.dismiss_animated()

    def update_screenshot(self, file_path: str, pixmap: QPixmap) -> None:
        """
        In-place update if a new screenshot arrives while the card is already visible,
        resetting the countdown timer smoothly.
        """
        self._file_path = os.path.abspath(file_path)
        self._pixmap = pixmap
        self._body.set_pixmap(pixmap)
        self._remaining_ms = self._auto_dismiss_ms
        self._body.set_progress(1.0)
        if not self._body._hovered and not self._countdown_timer.isActive():
            self._countdown_timer.start()

    def show_animated(self) -> None:
        """Position in the bottom-right above the taskbar and slide in from the right edge."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.show()
            return

        avail = screen.availableGeometry()
        # Account for transparent SHADOW_PADDING so the visible card edge sits at CARD_MARGIN (16 px)
        effective_margin = CARD_MARGIN - SHADOW_PADDING
        target_x = avail.right() - self.width() - effective_margin + 1
        target_y = avail.bottom() - self.height() - effective_margin + 1

        start_pos = QPoint(avail.right() + 20, target_y)
        end_pos = QPoint(target_x, target_y)

        self.move(start_pos)
        self.setWindowOpacity(1.0)
        self.show()

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(SLIDE_IN_DURATION_MS)
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim = anim
        anim.start()

        self._countdown_timer.start()

    def dismiss_animated(self) -> None:
        """Fade out smoothly and destroy the preview window."""
        if self._is_closing:
            return
        self._is_closing = True
        self._countdown_timer.stop()

        if self._slide_anim is not None and self._slide_anim.state() == QPropertyAnimation.State.Running:
            self._slide_anim.stop()

        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(FADE_OUT_DURATION_MS)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InQuad)
        anim.finished.connect(self._finalize_close)
        self._fade_anim = anim
        anim.start()

    def dismiss_immediately(self) -> None:
        """Close immediately without waiting for fade-out animation (used when replacing card)."""
        if self._is_closing:
            return
        self._is_closing = True
        self._countdown_timer.stop()
        if self._slide_anim is not None:
            self._slide_anim.stop()
        if self._fade_anim is not None:
            self._fade_anim.stop()
        self._finalize_close()

    def _finalize_close(self) -> None:
        self.closed.emit(self)
        self.close()

    # --- Hover Events ---

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._countdown_timer.stop()
        self._set_overlay_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._is_dragging and not self._is_closing:
            self._set_overlay_visible(False)
            self._countdown_timer.start()
        super().leaveEvent(event)

    # --- Mouse & Native Windows Drag-and-Drop ---

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_start_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and not self._is_dragging
        ):
            distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._start_native_drag()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def _start_native_drag(self) -> None:
        """
        Execute a native Windows QDrag populated with BOTH local file URL and image data
        so dropping works across Chrome, Discord, WhatsApp, Explorer, and image editors.
        """
        self._is_dragging = True
        self._countdown_timer.stop()
        self._drag_start_pos = None

        abs_path = os.path.abspath(self._file_path)
        if not os.path.exists(abs_path) and not self._pixmap.isNull():
            # Ensure backing file exists on disk if needed
            try:
                self._pixmap.save(abs_path, "PNG")
            except Exception as exc:
                logger.warning("Could not re-save missing drag file %s: %s", abs_path, exc)

        mime = QMimeData()
        if os.path.exists(abs_path):
            mime.setUrls([QUrl.fromLocalFile(abs_path)])
        if not self._pixmap.isNull():
            mime.setImageData(self._pixmap.toImage())

        drag = QDrag(self)
        drag.setMimeData(mime)

        drag_preview = self._create_drag_preview_pixmap()
        if not drag_preview.isNull():
            drag.setPixmap(drag_preview)
            drag.setHotSpot(QPoint(drag_preview.width() // 2, drag_preview.height() // 2))

        logger.info("Starting native QDrag for %s", abs_path)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

        self._is_dragging = False
        self.dismiss_animated()

    def _create_drag_preview_pixmap(self) -> QPixmap:
        """Render a scaled, rounded, semi-transparent thumbnail for drag cursor feedback."""
        if self._pixmap.isNull():
            return QPixmap()

        scaled = self._pixmap.scaled(
            160,
            110,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(scaled.size())
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(0.85)

        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height())),
            8.0,
            8.0,
        )
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, scaled)

        pen = QPen(QColor(255, 255, 255, 110))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
        return canvas

    # --- Action Button Handlers ---

    def _action_copy(self) -> None:
        """Copy the screenshot image to the Windows clipboard."""
        if self._pixmap.isNull():
            return
        if self._on_internal_copy is not None:
            self._on_internal_copy(self._pixmap)

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setPixmap(self._pixmap)
            logger.info("Copied screenshot to clipboard: %s", self._file_path)

        # Visual confirmation on button before closing
        self._btn_copy.setText("Copied")
        self._btn_copy.setIcon(icon_check("#4ade80", 14))
        QTimer.singleShot(350, self.dismiss_animated)

    def _action_open(self) -> None:
        """Open the screenshot in the default Windows image viewer."""
        if os.path.exists(self._file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._file_path))
            self.dismiss_animated()

    def _action_show_in_explorer(self) -> None:
        """Highlight the screenshot file inside Windows File Explorer."""
        norm_path = os.path.normpath(self._file_path)
        if os.path.exists(norm_path):
            try:
                subprocess.Popen(["explorer", f"/select,{norm_path}"])
            except OSError as exc:
                logger.error("Failed to launch explorer: %s", exc)
            self.dismiss_animated()

    def _action_delete(self) -> None:
        """Delete the screenshot file from disk and dismiss the preview card."""
        try:
            if os.path.exists(self._file_path):
                os.remove(self._file_path)
                logger.info("Deleted screenshot file: %s", self._file_path)
        except OSError as exc:
            logger.error("Failed to delete %s: %s", self._file_path, exc)
        self.dismiss_animated()
