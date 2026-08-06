<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/build-PyInstaller-orange?style=flat-square" alt="Build">
  <img src="https://img.shields.io/badge/version-v3.0-purple?style=flat-square" alt="Version">
  <br>
  <strong>Portable · No dependencies · ASCII-safe · UAC-aware · Safety-first</strong>
</p>

<h1 align="center">🧹 WinTempCleaner</h1>
<p align="center"><em>Portable Windows Temp &amp; Cache Cleaner — CLI (Enhanced Edition v3.0)</em></p>

---

## Overview

WinTempCleaner is a lightweight, portable Windows command-line tool that sweeps through common temporary file locations, browser caches, GPU shader caches, app caches, developer caches, and system log files. It shows exactly how much space was freed and what remains — all from a clean interactive menu.

No installation, no dependencies, no background services. One `.exe`, double-click, done.

---

## Features

| Feature | Detail |
|---|---|
| **5 safe cleaning modes + extras** | Quick, Deep, Shaders & Tiles, Windows Files, App Caches, Dev Caches, Analyze |
| **Extended Clean (caution)** | Game shader caches, debug logs, junk-file sweep — confirmed before deleting |
| **Age limit** | Only deletes files older than N days (1 / 3 / 7 / 30 or off) — keeps in-use & session files safe |
| **Recycle Bin mode** | Optional undoable deletions instead of permanent removal |
| **Long-path support** | Handles trees deeper than 260 characters (`\\?\` prefix) |
| **Fast threaded scan** | 50+ locations scanned in parallel; iterative walk, no recursion limits |
| **Size tracking** | Per-item and total freed/remaining displayed in KB / MB / GB |
| **Space analysis** | Grouped report with proportional size bars — see what's eating your drive |
| **Cleanup reports** | CSV + JSON saved after every run, with a built-in report viewer |
| **Interactive loop** | Return to the menu or quit after every operation |
| **ASCII-safe UI** | Renders cleanly in any Windows terminal (CMD, PowerShell, Terminal) |
| **Portable single file** | No Python runtime or DLLs required |
| **Auto-elevation** | Prompts for administrator rights on launch (UAC) |
| **Locked-file safe** | Skipped files are reported — no Explorer popups, no crashes |
| **Persistent options** | Age limit / Recycle Bin / reports stored in `cleaner_config.ini` |

---

## Menu

```
  Windows Temp / Cache Cleaner
  Professional Edition - Enhanced             v3.0

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

### What each option cleans

| Option | Scope |
|---|---|
| **1 · Quick Clean** | `%TEMP%`, `C:\Windows\Temp`, Prefetch, browser caches (Chrome, Edge, Brave, Opera, Vivaldi, Chromium, Firefox), Recycle Bin |
| **2 · Deep Clean** | Everything safe — Quick + Shaders & Tiles + Windows Files + App Caches + Dev Caches |
| **3 · Shaders & Tiles** | DirectX / NVIDIA shader caches, Thumbnail cache, Icon cache, Font cache |
| **4 · Windows Files** | Windows Update cache, Panther/CBS logs, minidumps, WER reports, CrashDumps, MEMORY.DMP, Windows.old (prompts) |
| **5 · App Caches** | Discord, Slack, Teams (classic + new), Spotify, VSCode, Cursor, Zoom logs |
| **6 · Dev Caches** | npm, pip, NuGet, Gradle, Go build caches |
| **7 · Extended Clean** *(caution, confirmed)* | Steam shader caches, LiveKernel / DISM / MoSetup debug logs, junk-file sweep (`*.tmp`, `~$*`, `*.bak`, `*-001.*`) |
| **8 · Analyze Space** | Scan-only — grouped report with size bars, nothing deleted |
| **9 · Options** | Set age limit, toggle Recycle Bin deletions, toggle auto-reports |
| **R · Reports** | Browse and view past cleanup reports |

### Safety model

Everything is split into tiers:

- **SAFE** — cleanable any time: temp dirs, browser/app/dev caches, icon & font caches, shader & thumbnail caches, system logs & dumps.
- **CAUTION** — cleanable only via **Extended Clean**, and only after an explicit confirmation: game shader caches (games recompile), system debug logs (diagnostics lost), junk-file sweep.

Two more safety layers apply to everything:

- **Age limit** (default 1 day) — recently-modified files are kept, so in-use/session files are never touched.
- **Recycle Bin mode** (off by default) — deletions become undoable. Note: Quick/Deep then skip emptying the Recycle Bin so you can recover items.

---

## Quick Start

### Binary (recommended)

1. Download `WindowsTempCleaner.exe` from the [Releases](../../releases) page.
2. Double-click — accept the UAC prompt when it appears.
3. Choose an option from the menu and press Enter.

### From source

```batch
pip install rich
python temp_cleaner.py
```

---

## Example Output

```
== Core Temp & Browser ==
  [User Temp]       OK  deleted 456 | locked 2 | 31 too new | freed 1.24 GB
  [Windows Temp]    OK  deleted 89  | locked 0 | freed 45.2 MB
  [Prefetch]        OK  deleted 124 | locked 0 | freed 8.7 MB
  [Chrome Cache]    !   deleted 312 | locked 1 | freed 892.1 MB
  [Edge Cache]      OK  deleted 0   | nothing to clean
  [Recycle Bin]     OK  emptied

== App Caches ==
  [Discord Cache]   OK  deleted 1,204 | locked 0 | freed 512.3 MB

          Cleanup Complete
+----------------------+-------------+
| Metric               |      Value |
+----------------------+-------------+
| Mode                 | Quick Clean |
| Duration             | 4.2s        |
| Items deleted        |       2,185 |
| Locked skipped       |           3 |
| Kept (too new)       |          31 |
| Space freed          |    2.18 GB  |
| Est. remaining       |   523.4 MB  |
| Deletion mode        | Permanent   |
| Age limit            | 1 day(s)    |
+----------------------+-------------+
Report saved: Reports\report_20260806_103015.csv
```

---

## Requirements

- **OS:** Windows 10 / 11 (x64)
- **Permission:** Administrator rights (the tool auto-prompts via UAC)
- **Source only:** Python 3.10+ and the `rich` package

---

## Building from Source

```batch
pip install pyinstaller rich
pyinstaller --onefile --console --uac-admin `
    --name "WindowsTempCleaner" `
    temp_cleaner.py
```

The `.exe` will be placed in the `dist/` folder.

---

## Files Created

| File / Folder | Purpose |
|---|---|
| `cleaner_config.ini` | Persisted options (age limit, recycle bin, reports) |
| `Reports/` | CSV + JSON reports for every cleanup run |
| `cleaner_error.log` | Written only on unexpected crashes |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center"><sub>Made with Python, Rich, and PyInstaller.</sub></p>
