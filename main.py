"""SnapFloat application entry point with single-instance guard and logging setup."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from snapfloat import __app_name__, __version__
from snapfloat.config import SINGLE_INSTANCE_KEY, get_app_data_dir
from snapfloat.ui.tray import SnapFloatTrayController


def setup_logging() -> None:
    """Configure rotating file and console logging inside %APPDATA%/SnapFloat/snapfloat.log."""
    log_dir = get_app_data_dir()
    log_file = log_dir / "snapfloat.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Rotating file handler (1 MB max, 2 backups)
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1_048_576, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError:
        pass

    # Standard stream handler when attached to a console
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


class SingleInstanceGuard(QObject):
    """
    Ensures only one instance of SnapFloat runs at a time using QLocalServer / QLocalSocket.
    If a second instance is launched, it notifies the running instance and exits cleanly.
    """

    def __init__(self, key: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._server: Optional[QLocalServer] = None

    def try_acquire(self, on_secondary_ping=None) -> bool:
        """
        Attempt to claim the single-instance lock.
        Returns True if this is the primary instance, or False if another instance is active.
        """
        probe = QLocalSocket(self)
        probe.connectToServer(self._key)
        if probe.waitForConnected(250):
            probe.write(b"PING")
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            return False

        # Clean up any stale pipe from a previous crash before listening
        QLocalServer.removeServer(self._key)
        server = QLocalServer(self)
        if not server.listen(self._key):
            return False

        if on_secondary_ping is not None:
            server.newConnection.connect(lambda: self._handle_connection(on_secondary_ping))

        self._server = server
        return True

    def _handle_connection(self, callback) -> None:
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(150)
            conn.close()
        callback()

    def release(self) -> None:
        """Close the local server on exit."""
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._key)
            self._server = None


def main() -> int:
    """Bootstrap QApplication, enforce single-instance guard, and launch the tray controller."""
    setup_logging()
    logger = logging.getLogger(__name__)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    # Prevent closing the floating preview card from quitting the background tray app
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstanceGuard(SINGLE_INSTANCE_KEY, parent=app)
    controller: Optional[SnapFloatTrayController] = None

    def _on_secondary_instance() -> None:
        logger.info("Secondary launch detected; triggering test preview on active instance.")
        if controller is not None:
            controller.trigger_test_preview()

    if not guard.try_acquire(on_secondary_ping=_on_secondary_instance):
        logger.info("%s is already running. Exiting secondary process.", __app_name__)
        return 0

    controller = SnapFloatTrayController(app)
    app.aboutToQuit.connect(guard.release)
    controller.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
