"""Programmatically rendered high-DPI vector icons using QPainter (zero external assets)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def create_app_tray_icon(paused: bool = False, size: int = 64) -> QIcon:
    """Draw the SnapFloat rounded gradient camera/crop badge icon for the system tray."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(4.0, 4.0, size - 8.0, size - 8.0)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    if paused:
        grad.setColorAt(0.0, QColor("#64748b"))
        grad.setColorAt(1.0, QColor("#475569"))
    else:
        grad.setColorAt(0.0, QColor("#38bdf8"))
        grad.setColorAt(0.5, QColor("#6366f1"))
        grad.setColorAt(1.0, QColor("#8b5cf6"))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, 15.0, 15.0)

    # Inner subtle floating frame brackets
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(4.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    m = 16.0
    b = 9.0
    # Top-left corner
    painter.drawLine(QPointF(m, m + b), QPointF(m, m))
    painter.drawLine(QPointF(m, m), QPointF(m + b, m))
    # Top-right corner
    painter.drawLine(QPointF(size - m - b, m), QPointF(size - m, m))
    painter.drawLine(QPointF(size - m, m), QPointF(size - m, m + b))
    # Bottom-left corner
    painter.drawLine(QPointF(m, size - m - b), QPointF(m, size - m))
    painter.drawLine(QPointF(m, size - m), QPointF(m + b, size - m))
    # Bottom-right corner
    painter.drawLine(QPointF(size - m - b, size - m), QPointF(size - m, size - m))
    painter.drawLine(QPointF(size - m, size - m), QPointF(size - m, size - m - b))

    # Center capture dot
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    center = size / 2.0
    painter.drawEllipse(QPointF(center, center), 5.0, 5.0)

    painter.end()
    return QIcon(pixmap)


def _new_canvas(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def _stroke_pen(color: str, width: float = 1.7) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def icon_close(color: str = "#f1f5f9", size: int = 16) -> QIcon:
    """Draw a crisp '×' close icon."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 1.8))
    m = 4.2
    painter.drawLine(QPointF(m, m), QPointF(size - m, size - m))
    painter.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    painter.end()
    return QIcon(pixmap)


def icon_copy(color: str = "#f1f5f9", size: int = 16) -> QIcon:
    """Draw an overlapping clipboard/copy sheets icon."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Back sheet
    path = QPainterPath()
    path.moveTo(10.5, 5.0)
    path.lineTo(10.5, 3.5)
    path.quadTo(10.5, 2.5, 9.5, 2.5)
    path.lineTo(3.5, 2.5)
    path.quadTo(2.5, 2.5, 2.5, 3.5)
    path.lineTo(2.5, 10.5)
    path.quadTo(2.5, 11.5, 3.5, 11.5)
    path.lineTo(5.0, 11.5)
    painter.drawPath(path)

    # Front sheet
    painter.drawRoundedRect(QRectF(5.5, 5.2, 8.0, 8.3), 1.6, 1.6)
    painter.end()
    return QIcon(pixmap)


def icon_check(color: str = "#4ade80", size: int = 16) -> QIcon:
    """Draw a checkmark icon for copy confirmation feedback."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 2.0))
    path = QPainterPath()
    path.moveTo(3.2, 8.5)
    path.lineTo(6.6, 11.8)
    path.lineTo(12.8, 4.5)
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def icon_open(color: str = "#f1f5f9", size: int = 16) -> QIcon:
    """Draw an external-open box with north-east arrow."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Box frame
    path = QPainterPath()
    path.moveTo(7.5, 3.5)
    path.lineTo(4.0, 3.5)
    path.quadTo(2.8, 3.5, 2.8, 4.7)
    path.lineTo(2.8, 12.0)
    path.quadTo(2.8, 13.2, 4.0, 13.2)
    path.lineTo(11.3, 13.2)
    path.quadTo(12.5, 13.2, 12.5, 12.0)
    path.lineTo(12.5, 8.5)
    painter.drawPath(path)

    # Diagonal arrow
    painter.drawLine(QPointF(7.2, 8.8), QPointF(13.2, 2.8))
    painter.drawLine(QPointF(9.5, 2.8), QPointF(13.2, 2.8))
    painter.drawLine(QPointF(13.2, 2.8), QPointF(13.2, 6.5))
    painter.end()
    return QIcon(pixmap)


def icon_folder(color: str = "#f1f5f9", size: int = 16) -> QIcon:
    """Draw a sleek folder outline icon for 'Show in Explorer'."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    path = QPainterPath()
    path.moveTo(2.2, 4.5)
    path.quadTo(2.2, 3.3, 3.4, 3.3)
    path.lineTo(6.2, 3.3)
    path.lineTo(7.6, 5.0)
    path.lineTo(12.6, 5.0)
    path.quadTo(13.8, 5.0, 13.8, 6.2)
    path.lineTo(13.8, 11.8)
    path.quadTo(13.8, 13.0, 12.6, 13.0)
    path.lineTo(3.4, 13.0)
    path.quadTo(2.2, 13.0, 2.2, 11.8)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def icon_delete(color: str = "#fca5a5", size: int = 16) -> QIcon:
    """Draw a minimal trash can icon."""
    pixmap, painter = _new_canvas(size)
    painter.setPen(_stroke_pen(color, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Lid & handle
    painter.drawLine(QPointF(3.0, 4.2), QPointF(13.0, 4.2))
    painter.drawLine(QPointF(6.2, 2.6), QPointF(9.8, 2.6))

    # Bin body
    body = QPainterPath()
    body.moveTo(4.4, 4.5)
    body.lineTo(5.0, 12.4)
    body.quadTo(5.1, 13.4, 6.1, 13.4)
    body.lineTo(9.9, 13.4)
    body.quadTo(10.9, 13.4, 11.0, 12.4)
    body.lineTo(11.6, 4.5)
    painter.drawPath(body)

    # Inner vertical ribs
    painter.drawLine(QPointF(6.8, 6.8), QPointF(6.8, 11.0))
    painter.drawLine(QPointF(9.2, 6.8), QPointF(9.2, 11.0))
    painter.end()
    return QIcon(pixmap)
