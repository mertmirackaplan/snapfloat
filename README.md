# SnapFloat

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform Windows 11](https://img.shields.io/badge/Platform-Windows%2011-0078D4?logo=windows11&logoColor=white)
![UI PySide6](https://img.shields.io/badge/UI-PySide6%20(Qt6)-41CD52?logo=qt&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-8b5cf6)

**SnapFloat** is a lightweight, open-source Windows 11 utility that brings the macOS floating screenshot thumbnail experience to Windows. Whenever you take a screenshot using `Win + Shift + S` (Snipping Tool) or `PrtScn`, a sleek, non-intrusive preview card slides into the bottom-right corner of your screen—ready to be dragged and dropped directly into any app.

---

## Key Features

- **Dual-Trigger Detection (`watchdog` + Qt Clipboard)**
  Monitors both your `Pictures/Screenshots` folders (including OneDrive locations) and the Windows clipboard (`QGuiApplication.clipboard().dataChanged`). Works seamlessly whether Windows 11 Snipping Tool auto-save is enabled or disabled.
- **Smart Deduplication & Safe Readiness Polling**
  Prevents double popups when Snipping Tool writes to the clipboard and disk simultaneously. Uses non-blocking `QTimer` size-stability and `QPixmap` validation checks instead of brittle `time.sleep()` delays.
- **Zero Focus Stealing**
  Built with `FramelessWindowHint | WindowStaysOnTopHint | Tool | WindowDoesNotAcceptFocus` and `WA_ShowWithoutActivating` so it never interrupts active full-screen applications, IDE typing, or games.
- **True Native Windows Drag-and-Drop**
  Populates `QMimeData` with **both** local file URLs (`setUrls`) and raw image data (`setImageData`), allowing instant drag-and-drop into Chrome, Discord, WhatsApp, Slack, Notion, File Explorer, and image editors.
- **Hover Action Overlay & Countdown Bar**
  Auto-dismisses after 6 seconds with a smooth progress bar along the bottom edge. Hovering pauses the countdown and reveals quick actions: **Copy**, **Open**, **Show in Explorer**, and **Delete**.
- **macOS Shutter Sound & Native Snipping Tool Toast Suppression**
  Synthesizes a crisp two-stage macOS camera shutter sound effect (`.wav`) and automatically mutes Windows 11 Snipping Tool's native toast banner (`Microsoft.ScreenSketch_8wekyb3d8bbwe!App`) so you only get SnapFloat's floating card and shutter sound. Both can be toggled anytime from the system tray menu.
- **Zero External Asset Dependencies**
  All tray icons, toolbar icons, and the macOS camera shutter audio waveform are generated programmatically at runtime.

---

## Project Structure

```text
snapfloat/
├── README.md
├── LICENSE                  # MIT License
├── .gitignore               # Python, venv, PyInstaller, and IDE ignores
├── requirements.txt         # PySide6 & watchdog dependencies
├── main.py                  # Entry point, single-instance guard, rotating logs
└── snapfloat/
    ├── __init__.py          # Package version and metadata
    ├── config.py            # Constants, folder resolution, %APPDATA% JSON settings
    ├── watcher.py           # Dual folder + clipboard listener & deduplication
    ├── utils/
    │   ├── __init__.py
    │   ├── snipping_notifications.py # Mutes Windows Snipping Tool native toast banners
    │   ├── sound.py         # Synthesizes & plays macOS camera shutter sound
    │   └── startup.py       # HKCU\...\Run registry toggle for "Start with Windows"
    └── ui/
        ├── __init__.py
        ├── icons.py         # Programmatic vector icons rendered via QPainter
        ├── preview_card.py  # Floating card UI, animations, hover bar, native QDrag
        └── tray.py          # System tray icon, context menu, and orchestration
```

---

## Quick Start

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.10+**

### 2. Installation

```powershell
git clone https://github.com/mertmirackaplan/snapfloat.git
cd snapfloat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Running SnapFloat

Run with a console attached (useful for seeing log output):

```powershell
python main.py
```

Or run silently in the background without a console window:

```powershell
pythonw main.py
```

Once running, right-click the **SnapFloat** icon in your Windows System Tray and click **Test Preview** to try out the floating card immediately.

---

## Building a Standalone `.exe` with PyInstaller

You can package SnapFloat into a single, dependency-free Windows executable:

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name SnapFloat main.py
```

The standalone executable will be generated at `dist\SnapFloat.exe`. When you toggle **Start with Windows** from the tray menu while running `SnapFloat.exe`, it automatically registers the standalone executable in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

---

## Troubleshooting

- **Preview card doesn't appear after `Win + Shift + S`**:
  1. Check the system tray icon to make sure monitoring is not set to **Paused**.
  2. Click **Test Preview** in the tray menu to verify the card renders on your primary display.
  3. Inspect the log file located at `%APPDATA%\SnapFloat\snapfloat.log`.
- **Where are clipboard-only screenshots stored?**:
  When Snipping Tool only copies to the clipboard without saving a file to `Pictures/Screenshots`, SnapFloat automatically writes a temporary `.png` file to `%TEMP%\SnapFloat\` so file-based drag-and-drop works in all desktop and web apps.
- **Resetting preferences**:
  Delete `%APPDATA%\SnapFloat\settings.json` and restart the application.

---

## License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for full details.
