# Changelog

All notable changes to WinTempCleaner from this round of work. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

## [3.2] - 2026-08-23

### Added

**UI / branding**
- `icons.py` — a small, cached icon loader (`get_icon()`) built on
  `ctkfontawesome`, used across the sidebar, stat cards, and buttons.
  Originally built on `pytablericons`, but that pulls in `pygame` at
  runtime for SVG rasterization, and `pygame` has no prebuilt wheel yet for
  newer Python releases — pip tried to compile it from source and failed.
  Swapped to `ctkfontawesome`, whose renderer needs only Pillow.
- `SpinningIcon` — a 12-frame rotating icon (pre-rendered with PIL, cycled
  via `.after()`) used as a lightweight in-progress indicator next to the
  Start button while a clean job runs.
- On-brand splash screen (`SplashScreen` class) shown while the app builds
  its UI. Reuses the app's own palette and the same `broom` icon the
  sidebar uses — no separate design. Progress and status text are tied to
  real init steps (building the interface, restoring last session,
  checking installers, checking permissions), not a fixed animation.

**New clean category — Games & Launchers** *(SAFE, included in Deep Clean)*
- Steam client cache, crash dumps, and web-view cache (`appcache`,
  `dumps`, `htmlcache`). Kept separate from the existing per-game shader
  cache in Extended Clean — that one causes shader recompile stutter on
  next launch, this one doesn't, so it's a different risk tier.

**New category — System Maintenance** *(CAUTION, manual-only, never bundled into Quick/Deep)*
- WinSxS component cleanup via the official
  `dism.exe /Online /Cleanup-Image /StartComponentCleanup` — no
  `/ResetBase`, so recently installed updates stay uninstallable. No manual
  file deletion happens here; DISM owns the whole operation.
- Space freed is reported via a free-disk-space delta (before/after),
  since walking `C:\Windows\WinSxS` directly to size it can be slow.
- Requires admin, has its own confirmation dialog with a duration warning,
  in both the CLI and the GUI.

**New safe items, folded into existing categories** *(no new UI needed — they just appear where you'd expect)*
- Dev Caches: Cargo registry cache, Go module download cache
  (`pkg/mod/cache/download` only — not all of `pkg/mod`, since that also
  holds extracted module source other projects reference directly).
- App Caches: `DawnCache` and `Service Worker\CacheStorage` added for
  Discord, Slack, Teams, VSCode, and Cursor.
- Windows Files: per-user WER reports (`%LOCALAPPDATA%...\WER`, distinct
  from the existing system-wide `ProgramData` one), per-package UWP
  `AC\Temp` folders, orphaned CHKDSK `FOUND.*` recovery folders across all
  drives.
- Shaders & Tiles: RDP bitmap cache, legacy `WebCacheV01.dat` (best-effort
  — it's often locked by IE/old Edge/Search Indexer, which just falls
  through to the existing "locked/skipped" bucket).

**Exclusion list (protected paths)**
- `Settings.excluded_paths`, checked before every single deletion, in
  every mode, regardless of age limit or Recycle Bin setting.
- Wired into `clear_folder`, `clear_matching`, `delete_file`, and
  `junk_sweep` (including pruning excluded folders out of the directory
  walk entirely, not just skipping matched files inside them).
- CLI: Options → `4` Exclusions (add/remove/list).
- GUI: new **Exclude** sidebar button — add a folder or file, remove any
  entry, all changes save immediately.

**Installers report** *(read-only — never deletes in bulk)*
- `find_old_installers()` — lists `.exe`/`.msi` files in Downloads older
  than 30 days, sorted by size.
- CLI: `I` menu option.
- GUI: new **Installers** sidebar button — each row has its own Delete
  button, which asks to confirm before removing anything.

### Changed
- `_app_cache_items()` refactored onto a shared `ELECTRON_CACHE_SUBDIRS` /
  `_electron_cache_items()` helper, so adding a new cache kind (like
  `DawnCache`) benefits every Electron app at once instead of needing
  per-app edits.
- `_system_items()` now composes the UWP-temp and CHKDSK-recovery scans
  in automatically — `clear_windows_files()`, `scan_all()`, and the GUI's
  preview all picked these up with no extra wiring.
- Deep Clean now includes Games & Launchers.
- Sidebar nav grew from 8 to 10 items, plus new full-width Installers and
  Exclude buttons. Window size increased from `1020x680` (min `880x620`) to
  `1020x780` (min `880x720`) so the sidebar has real headroom instead of
  sitting a few pixels from clipping.
- Age limit is now **off by default** (was `1 day`) — first-run cleans touch
  everything the mode covers; set a limit in the sidebar/Options for extra
  caution. Existing configs keep whatever they saved before.
- Version bumped to `3.2`.
- Splash/main-window hide-and-reveal changed from `withdraw()`/
  `deiconify()` to an alpha-fade (`attributes("-alpha", 0/1)`). There's a
  documented CustomTkinter issue with `withdraw`/`deiconify`/`focus_force`
  between a `CTk` root and a `CTkToplevel` misbehaving; the alpha approach
  keeps the window "mapped" the whole time, just invisible, which sidesteps it.
- `overrideredirect(True)` on the splash is now applied on a short delay
  on Windows specifically, rather than immediately in `__init__` — that
  immediate-call pattern is a known cause of blank/black-render races on
  Windows.
- After the admin-elevation relaunch, the main window now does a brief
  `topmost` pulse to force itself to the foreground — Windows' focus-
  stealing prevention often won't hand a freshly-elevated process's
  window the foreground automatically.

### Fixed
- `temp_cleaner.py` referenced `ctypes.wintypes.HWND` without ever
  explicitly importing `ctypes.wintypes`. Likely only worked before by
  luck of import order (some other import pulling it in first). Added the
  explicit `import ctypes.wintypes`.
- `_remove_path()` now retries past the Windows read-only file attribute
  (`_force_writable()` + `_rmtree_onerror()` as a `shutil.rmtree` hook)
  instead of just failing. This is what was silently blocking deletion of
  Go's module cache, which marks every file it stores read-only — a
  well-known Windows/Go gotcha. Also applied to the `Windows.old` removal
  path for the same robustness.

### Testing notes
- `temp_cleaner.py` only touches `ctypes.windll` inside function bodies,
  not at import time, so it could actually be imported and exercised on
  Linux rather than just read through. Ran real tests: exclusion matching
  (including a deliberate "GAMMA vs GAMMA2" lookalike-prefix case, where
  naive string matching would get it wrong), settings persistence
  round-trip, installer age-filtering, and read-only-file deletion (the
  exact Go-module-cache scenario) actually succeeding via the chmod-retry
  path.
- The GUI was run end-to-end through its own `--selftest` flag under a
  virtual display, using the real `mainloop()` — not a simulated one —
  with the grown 10-item sidebar and both new dialogs. Zero exceptions.
- Native Windows behavior (UAC elevation focus-stealing, DISM timing)
  couldn't be verified directly — flagged inline above wherever that
  applies.

### Deferred (not included this round)
- **Driver Store cleanup** — correctly identifying which driver versions
  are genuinely stale needs more certainty than could be verified blind;
  a wrong guess can break hardware. Not worth the risk for a cleaner
  billed as safe.
- **Scheduled auto-clean via Task Scheduler** and **CLI `--profile`/
  `--json` automation flags** — straightforward in principle, but Task
  Scheduler registration isn't something that could be tested with
  confidence from here. Open to building these next if wanted.
