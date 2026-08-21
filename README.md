<p align="center">
  <img src="Icon.ico" width="96" alt="WinTempCleaner logo">
</p>

<h1 align="center">🧹 WinTempCleaner</h1>
<p align="center"><strong>Portable Windows Temp &amp; Cache Cleaner — CLI + GUI</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/version-v3.1-purple?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/build-PyInstaller-orange?style=flat-square" alt="Build">
  <br>
  <sub>Portable · No dependencies · UAC-aware · Safety-first · Self-updating</sub>
</p>

---

## Overview

WinTempCleaner sweeps temporary files, browser caches, GPU shader caches, app caches, developer caches and system logs — then shows exactly how much space was freed.

- **Two ways to use it:** a minimalistic **dark GUI** or the classic **interactive CLI**.
- **One file, no install.** Download the `.exe`, double-click, accept UAC, done.
- **Self-updating:** the GUI checks GitHub Releases on demand and installs new versions in one click — no background polling, no spam.

<br />

<p align="center">
  <img src="screenshots/main.png" width="820" alt="WinTempCleaner GUI dashboard">
</p>

---

## ✨ Screenshots

### Analyze Space — see what is eating your disk

<p align="center">
  <img src="screenshots/analyze.png" width="820" alt="Analyze Space view with size bars">
</p>

### Built-in updater — one click to update

<p align="center">
  <img src="screenshots/update.png" width="640" alt="Update available dialog with release notes">
</p>

---

## 🧭 Cleaning modes

| Mode | Scope | Safety |
|---|---|---|
| **Quick Clean** | `%TEMP%`, `C:\Windows\Temp`, Prefetch, Chromium/Firefox caches, Recycle Bin | SAFE |
| **Deep Clean** | Everything safe: Quick + Shaders & Tiles + Windows Files + App Caches + Dev Caches | SAFE |
| **Shaders & Tiles** | DirectX / NVIDIA shader caches, thumbnail, icon & font caches | SAFE |
| **Windows Files** | Windows Update cache, Panther/CBS logs, minidumps, WER reports, CrashDumps, MEMORY.DMP | SAFE |
| **App Caches** | Discord, Slack, Teams (classic + new), Spotify, VSCode, Cursor, Zoom logs | SAFE |
| **Dev Caches** | npm, pip, NuGet, Gradle, Go build caches | SAFE |
| **Extended Clean** | Steam shader caches, LiveKernel / DISM / MoSetup debug logs, junk-file sweep (`*.tmp`, `~$*`, `*.bak`) | ⚠️ CAUTION |
| **Analyze Space** | Scan-only report of 50+ locations — nothing is deleted | SCAN |

The same modes are available in both interfaces:

| GUI | CLI menu |
|---|---|
| sidebar buttons | `1`–`9` keys, plus `R` for reports and `Q` to quit |

---

## 🛡️ Safety model

Everything is split into tiers:

- **SAFE** — cleanable any time: temp dirs, browser/app/dev caches, icon & font caches, shader & thumbnail caches, system logs & dumps.
- **CAUTION** — only via **Extended Clean**, after an explicit confirmation: game shader caches (games recompile on next launch), system debug logs (diagnostics are lost), profile-wide junk-file sweep.

Two more safety layers apply everywhere:

| Layer | Default | Detail |
|---|---|---|
| **Age limit** | 1 day | Only files older than *N* days (1 / 3 / 7 / 30) are deleted — in-use and session files are never touched. Set to `Off` to disable. |
| **Recycle Bin mode** | Off | Deletions become undoable via the Recycle Bin. Note: Quick/Deep then skip emptying the bin so items stay recoverable. |

Locked files (in use by running apps) are skipped and reported — no Explorer popups, no crashes.

---

## 🚀 Quick start

### GUI (recommended)

1. Grab `WindowsTempCleanerGUI.exe` from [Releases](../../releases/latest).
2. Double-click → accept the UAC prompt.
3. Pick a mode on the left, press **Start**.

### CLI

1. Grab `WindowsTempCleaner.exe` from [Releases](../../releases/latest).
2. Double-click → choose an option from the menu.

```
  Windows Temp / Cache Cleaner
  Professional Edition - Enhanced             v3.1

  Menu
   1  Quick Clean        - Temp, browser caches, Recycle Bin      SAFE
   2  Deep Clean         - Everything safe (full sweep)           SAFE
   3  Shaders & Tiles    - GPU, thumbnail, icon & font caches     SAFE
   4  Windows Files      - Logs, dumps, update cache              SAFE
   5  App Caches         - Discord, Teams, Spotify, Slack, VSCode SAFE
   6  Dev Caches         - npm, pip, NuGet, Gradle, Go            SAFE
   7  Extended Clean     - Game shaders, debug logs, junk sweep   CAUTION
   8  Analyze Space      - Scan only, detailed report             SAFE
   9  Options            - Age limit, Recycle Bin, reports
   R  Reports            - View past cleanup reports
   Q  Quit
```

### From source

```batch
pip install customtkinter rich
python temp_cleaner_gui.py
```

---

## 🔄 Auto-update (GUI)

Press **Check for Updates** in the sidebar:

- The app compares your version against the latest GitHub Release.
- If a newer version exists you get release notes and a **Download & Install** button.
- The installer swaps itself in place and relaunches — done.
- Checks happen **only when you click**; there are no background timers or notifications.
- Running from source instead? The button opens the releases page.

---

## 📊 Example output

```
== Core Temp & Browser ==
  [User Temp]       OK  deleted 456 | locked 2 | 31 too new | freed 1.24 GB
  [Windows Temp]    OK  deleted 89  | locked 0 | freed 45.2 MB
  [Prefetch]        OK  deleted 124 | locked 0 | freed 8.7 MB
  [Chrome Cache]    !   deleted 312 | locked 1 | freed 892.1 MB
  [Edge Cache]      OK  deleted 0   | nothing to clean
  [Recycle Bin]     OK  emptied

          Cleanup Complete
  Space freed ................. 2.18 GB
  Duration .................... 4.2s
  Items deleted ............... 2,185
```

Every run can save CSV + JSON reports to `Reports/` (viewable inside both apps).

---

## 📦 Requirements

| What | Detail |
|---|---|
| OS | Windows 10 / 11 (x64) |
| Permission | Administrator rights (auto-prompted via UAC) |
| From source only | Python 3.10+, `customtkinter`, `rich` |

## 🔨 Building from source

CLI:

```batch
pip install pyinstaller rich
pyinstaller --onefile --console --uac-admin --icon "Icon.ico" ^
    --name "WindowsTempCleaner" ^
    temp_cleaner.py
```

GUI:

```batch
pip install pyinstaller customtkinter rich
pyinstaller --onefile --noconsole --uac-admin --icon "Icon.ico" ^
    --collect-all customtkinter ^
    --exclude-module PyQt5 --exclude-module PyQt6 ^
    --exclude-module PySide2 --exclude-module PySide6 ^
    --exclude-module numpy --exclude-module pandas --exclude-module scipy ^
    --exclude-module matplotlib --exclude-module PIL ^
    --exclude-module IPython --exclude-module jedi --exclude-module parso ^
    --exclude-module jupyter --exclude-module notebook ^
    --exclude-module pythonnet --exclude-module clr ^
    --name "WindowsTempCleanerGUI" ^
    temp_cleaner_gui.py
```

> The `--exclude-module` flags stop PyInstaller from bundling unrelated packages
> installed in your global Python environment (~80 MB → ~17 MB).

## 🗂️ Files created at runtime

| File / Folder | Purpose |
|---|---|
| `cleaner_config.ini` | Persisted options (age limit, recycle bin mode, auto-reports) |
| `Reports/` | CSV + JSON reports for every cleanup run |
| `cleaner_error.log` | Written only on unexpected crashes (CLI) |

## 📄 License

Licensed under the MIT License — see [LICENSE](LICENSE).

---

<p align="center"><sub>Made with Python, CustomTkinter, Rich, and PyInstaller.</sub></p>
