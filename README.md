<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-blue?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/build-PyInstaller-orange?style=flat-square" alt="Build">
  <br>
  <strong>Portable · No dependencies · ASCII-safe · UAC-aware</strong>
</p>

<h1 align="center">🧹 WinTempCleaner</h1>
<p align="center"><em>Portable Windows Temp &amp; Cache Cleaner — CLI</em></p>

---

## Overview

WinTempCleaner is a lightweight, portable Windows command-line tool that sweeps through common temporary file locations, browser caches, GPU shader caches, and system log files. It shows exactly how much space was freed and what remains — all from a clean interactive menu.

No installation, no dependencies, no background services. One `.exe`, double-click, done.

---

## Features

| Feature | Detail |
|---|---|
| **5 cleaning modes** | Quick Clean, Deep Clean, Shaders, System Files, or Analyze-only |
| **Size tracking** | Per-item and total freed/remaining displayed in KB / MB / GB |
| **Pre-scan estimates** | See how much is reclaimable before deleting anything |
| **Interactive loop** | Return to the menu or quit after every operation |
| **ASCII-safe UI** | Renders cleanly in any Windows terminal (CMD, PowerShell, Terminal) |
| **Portable single file** | No Python runtime or DLLs required |
| **Auto-elevation** | Prompts for administrator rights on launch (UAC) |
| **Locked-file safe** | Skipped files are reported — no Explorer popups, no crashes |

---

## Menu

```
┌─────────────────────────────────────────────────────────────┐
│  Windows Temp / Cache Cleaner                               │
│  Professional Edition                                       │
├─────────────────────────────────────── v2.0 ────────────────┤
│  Menu                                                       │
│   1  Quick Clean        - Temp, browser caches, Recycle Bin │
│   2  Deep Clean         - Everything (full system sweep)    │
│   3  Shaders & Tiles    - GPU shaders + thumbnail cache     │
│   4  Windows Files      - Logs, dumps, SoftwareDistribution │
│   5  Analyze Space      - Scan only, see what's taking room │
│                                                             │
│   Q  Quit                                                   │
├─────────────────────────────────────────────────────────────┤
│  Choice: _                                                   │
└─────────────────────────────────────────────────────────────┘
```

### What each option cleans

| Option | Scope |
|---|---|
| **1 · Quick Clean** | `%TEMP%`, `C:\Windows\Temp`, Prefetch, Chrome/Edge/Firefox caches, Recycle Bin |
| **2 · Deep Clean** | Everything in Quick + Shaders + System Files |
| **3 · Shaders & Tiles** | DirectX Shader Cache, NVIDIA DX/GL Cache, Windows Thumbnail Cache |
| **4 · Windows Files** | Windows Update cache, Panther/CBS logs, minidumps, WER reports, CrashDumps, MEMORY.DMP, Windows.old (prompts) |
| **5 · Analyze Space** | Scan-only — reports size per location without deleting anything |

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
== Basics ==
  [User Temp]       OK  deleted 456, skipped 2, freed 1.24 GB
  [Windows Temp]    OK  deleted 89,  skipped 0, freed 45.2 MB
  [Prefetch]        OK  deleted 124, skipped 0, freed 8.7 MB
  [Chrome Cache]    !   deleted 312, skipped 1, freed 892.1 MB
  [Edge Cache]      OK  deleted 0,   skipped 0, freed 0 B
  [Recycle Bin]     OK  emptied

          Cleanup Complete
+-----------------------------------+
| Metric                 |    Value |
|------------------------+----------|
| Items deleted          |      981 |
| Items skipped (locked) |        3 |
| Space freed            |   2.18 GB |
| Est. remaining         | 523.4 MB |
+-----------------------------------+
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

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center"><sub>Made with Python, Rich, and PyInstaller.</sub></p>
