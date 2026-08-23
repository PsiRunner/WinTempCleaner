"""
Windows Temp/Cache Cleaner — Professional Edition (Enhanced v3.0)

Rich CLI with styled menu, size tracking, interactive loop, and safety layers.
Auto-elevates via UAC when not admin.

Enhancements over v2.0:
  - Age limit: only files/dirs older than N days are deleted (default 1 day)
  - Recycle Bin mode: delete items to the Recycle Bin instead of permanently (undoable)
  - Long-path support (\\\\?\\ prefix) for trees deeper than 260 chars
  - Fast iterative size scanner (threaded across locations)
  - New SAFE categories: App Caches, Dev Caches, Icon/Font caches
  - New CAUTION category: Extended Clean (game shaders, debug logs, junk sweep)
  - Cleanup reports saved to Reports/ (CSV + JSON) and a report viewer
  - Persistent options via cleaner_config.ini

Dependencies: rich (pip install rich)
"""

import os
import sys
import csv
import json
import time
import glob
import ctypes
import ctypes.wintypes
import shutil
import stat
import fnmatch
import subprocess
import traceback
import configparser
from datetime import datetime
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Prompt, Confirm

APP_VERSION = "3.2"

console = Console()
ERROR_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleaner_error.log")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleaner_config.ini")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")

LOCAL = os.environ.get("LOCALAPPDATA", "")
APPDATA = os.environ.get("APPDATA", "")
TEMP = os.environ.get("TEMP", "")
USERPROFILE = os.environ.get("USERPROFILE", "")

# Known Chromium-based browsers and their User Data paths under %LOCALAPPDATA%
CHROMIUM_BROWSERS = [
    ("Chrome",  r"Google\Chrome\User Data"),
    ("Edge",    r"Microsoft\Edge\User Data"),
    ("Brave",   r"BraveSoftware\Brave-Browser\User Data"),
    ("Opera",   r"Opera Software\Opera Stable"),
    ("Opera GX", r"Opera Software\Opera GX Stable"),
    ("Vivaldi", r"Vivaldi\User Data"),
    ("Chromium", r"Chromium\User Data"),
]

FIREFOX_PROFILES = os.path.join(LOCAL, r"Mozilla\Firefox\Profiles")

# ---------------------------------------------------------------------------
# settings / config
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    age_days: int = 0          # 0 = off, else delete only items older than this
    use_recycle_bin: bool = False
    save_reports: bool = True
    excluded_paths: list = field(default_factory=list)   # never touched, no matter the mode


def load_settings() -> Settings:
    s = Settings()
    try:
        cp = configparser.ConfigParser()
        if cp.read(CONFIG_PATH) and "cleaner" in cp:
            sec = cp["cleaner"]
            s.age_days = sec.getint("age_days", fallback=0)
            s.use_recycle_bin = sec.getboolean("use_recycle_bin", fallback=False)
            s.save_reports = sec.getboolean("save_reports", fallback=True)
            raw = sec.get("excluded_paths", fallback="")
            s.excluded_paths = [p for p in raw.split(";;") if p]
    except Exception:
        pass
    return s


def save_settings(s: Settings):
    try:
        cp = configparser.ConfigParser()
        cp["cleaner"] = {
            "age_days": str(s.age_days),
            "use_recycle_bin": str(s.use_recycle_bin),
            "save_reports": str(s.save_reports),
            "excluded_paths": ";;".join(s.excluded_paths),
        }
        with open(CONFIG_PATH, "w") as f:
            cp.write(f)
    except Exception:
        pass


settings = load_settings()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    script = os.path.abspath(sys.argv[0])
    params = " ".join([f'"{script}"'] + sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit()


def fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


def ext(p: str) -> str:
    """Return an extended-length path so very deep trees can be handled."""
    ap = os.path.abspath(p)
    if len(ap) > 240 and not ap.startswith("\\\\?\\"):
        return "\\\\?\\" + ap
    return p


def calc_size(path: str) -> int:
    """Iterative size calculation (no recursion-depth issues)."""
    total = 0
    try:
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except Exception:
                return 0
    except Exception:
        return 0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(ext(p)) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat().st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except Exception:
                        continue
        except Exception:
            continue
    return total


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def is_excluded(path: str) -> bool:
    """True if `path` is (or is inside) a user-protected exclusion path.
    Checked before every single deletion — regardless of mode, age limit,
    or Recycle Bin setting, an excluded path is never touched."""
    if not settings.excluded_paths or not path:
        return False
    try:
        norm = _norm(path)
    except Exception:
        return False
    for ex in settings.excluded_paths:
        try:
            ex_norm = _norm(ex)
        except Exception:
            continue
        if norm == ex_norm or norm.startswith(ex_norm + os.sep):
            return True
    return False


def run_quiet(args):
    subprocess.run(args, capture_output=True, shell=False)


def press_enter(label="continue"):
    """Reliable pause that works in all terminals. Fallback to plain input if rich fails."""
    try:
        Prompt.ask(f"[dim]Press Enter to {label}[/dim]", default="")
    except Exception:
        input(f"Press Enter to {label}...")


def clear_screen():
    """Hard-clear the terminal so new screens never overlap old text."""
    os.system("cls")
    console.clear()


# ---------------------------------------------------------------------------
# stats accumulator
# ---------------------------------------------------------------------------

@dataclass
class CleanStats:
    deleted: int = 0
    skipped: int = 0
    skipped_new: int = 0
    bytes_freed: int = 0

    def reset(self):
        self.deleted = 0
        self.skipped = 0
        self.skipped_new = 0
        self.bytes_freed = 0

    def __iadd__(self, other: "CleanStats") -> "CleanStats":
        self.deleted += other.deleted
        self.skipped += other.skipped
        self.skipped_new += other.skipped_new
        self.bytes_freed += other.bytes_freed
        return self


stats = CleanStats()
RUN_DETAIL = []  # list of (label, dict(stats)) for reports


# ---------------------------------------------------------------------------
# deletion primitives (permanent or Recycle Bin)
# ---------------------------------------------------------------------------

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _recycle_batch(paths):
    """Move a batch of paths to the Recycle Bin (batched for speed / path limits)."""
    if not paths:
        return
    FO_DELETE = 3
    FOF_SILENT = 0x4
    FOF_NOCONFIRMATION = 0x10
    FOF_ALLOWUNDO = 0x40
    FOF_NOERRORUI = 0x400
    flags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    func = ctypes.windll.shell32.SHFileOperationW

    batch, size = [], 0

    def flush():
        nonlocal batch, size
        if not batch:
            return
        src = "\0".join(batch) + "\0\0"
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = src
        op.fFlags = flags
        func(ctypes.byref(op))
        batch, size = [], 0

    for p in paths:
        if size + len(p) + 2 > 30000:
            flush()
        batch.append(p)
        size += len(p) + 1
    flush()


def _force_writable(path: str):
    """Clear the Windows read-only file attribute (os.chmod maps
    stat.S_IWRITE to FILE_ATTRIBUTE_READONLY on Windows). This is the
    standard fix for caches that mark their own files read-only —
    Go's module download cache does this for every file it stores."""
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass


def _rmtree_onerror(func, path, exc_info):
    """shutil.rmtree onerror hook: clear read-only, retry once, else give up
    quietly — the caller checks os.path.exists() afterwards regardless, so
    a failed retry here is correctly reported as skipped/locked, not crashed."""
    _force_writable(path)
    try:
        func(path)
    except Exception:
        pass


def _remove_path(p: str, is_dir: bool, recycle: bool) -> bool:
    """Delete (or recycle) a single file/dir. Returns True on success.
    Never called on an excluded path — callers filter before reaching here,
    but this is deliberately dumb/unconditional: the exclusion check lives
    once, at the call sites, so it can't be silently bypassed by a new
    caller forgetting to check."""
    if recycle:
        _recycle_batch([p])
        return not os.path.lexists(p)
    try:
        if is_dir:
            shutil.rmtree(ext(p), onerror=_rmtree_onerror)
            return not os.path.exists(ext(p))
        try:
            os.remove(ext(p))
        except PermissionError:
            _force_writable(ext(p))
            os.remove(ext(p))
        return True
    except (PermissionError, OSError):
        return False


def _older_than(entry, min_age_seconds: int) -> bool:
    if min_age_seconds <= 0:
        return True
    try:
        return (time.time() - entry.stat().st_mtime) >= min_age_seconds
    except Exception:
        return True


def _result(label: str, s: CleanStats, found: bool = True, concise: bool = False):
    if not found:
        console.print(f"  [{label}]  [dim]not found[/dim]")
        return
    if concise and not (s.deleted or s.skipped or s.skipped_new):
        console.print(f"  [{label}]  [dim]nothing to clean[/dim]")
        return
    parts = [f"deleted [bold]{s.deleted}[/bold]"]
    if s.skipped:
        parts.append(f"locked [bold]{s.skipped}[/bold]")
    if s.skipped_new:
        parts.append(f"[dim]{s.skipped_new} too new[/dim]")
    parts.append(f"freed [bold]{fmt_size(s.bytes_freed)}[/bold]")
    icon = "[green]OK[/green]" if not s.skipped else "[yellow]![/yellow]"
    console.print(f"  [{label}]  {icon}  " + " | ".join(parts))


def _track(label: str, s: CleanStats) -> CleanStats:
    RUN_DETAIL.append((label, asdict(s)))
    return s


def clear_folder(path: str, label: str, min_age=None, quiet: bool = False,
                 concise: bool = False) -> CleanStats:
    """Delete everything inside a folder, honouring the age limit."""
    s = CleanStats()
    if min_age is None:
        min_age = settings.age_days * 86400
    if not path or not os.path.isdir(path):
        if not quiet:
            _result(label, s, found=False)
        return s
    try:
        entries = list(os.scandir(ext(path)))
    except Exception:
        if not quiet:
            console.print(f"  [{label}]  [yellow]cannot list directory[/yellow]")
        return s

    for entry in entries:
        try:
            if is_excluded(entry.path):
                continue
            if not _older_than(entry, min_age):
                s.skipped_new += 1
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            sz = calc_size(entry.path) if is_dir else entry.stat().st_size
            if _remove_path(entry.path, is_dir, settings.use_recycle_bin):
                s.deleted += 1
                s.bytes_freed += sz
            else:
                s.skipped += 1
        except Exception:
            s.skipped += 1

    _track(label, s)
    if not quiet:
        _result(label, s, concise=concise)
    return s


def clear_matching(folder: str, pattern: str, label: str, min_age: int = 0,
                   concise: bool = False) -> CleanStats:
    """Delete matching entries inside a folder (case-insensitive fnmatch)."""
    s = CleanStats()
    if not folder or not os.path.isdir(folder):
        _result(label, s, found=False)
        return s
    try:
        entries = list(os.scandir(ext(folder)))
    except Exception:
        console.print(f"  [{label}]  [yellow]cannot list directory[/yellow]")
        return s

    for entry in entries:
        try:
            if not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                continue
            if is_excluded(entry.path):
                continue
            if not _older_than(entry, min_age):
                s.skipped_new += 1
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            sz = calc_size(entry.path) if is_dir else entry.stat().st_size
            if _remove_path(entry.path, is_dir, settings.use_recycle_bin):
                s.deleted += 1
                s.bytes_freed += sz
            else:
                s.skipped += 1
        except Exception:
            s.skipped += 1

    _track(label, s)
    _result(label, s, concise=concise)
    return s


def delete_file(path: str, label: str) -> CleanStats:
    s = CleanStats()
    if path and os.path.isfile(path) and not is_excluded(path):
        if _remove_path(path, False, settings.use_recycle_bin):
            s.deleted = 1
            s.bytes_freed = os.path.getsize(path)
            _track(label, s)
            console.print(f"  [{label}]  [green]OK[/green] deleted [bold]{fmt_size(s.bytes_freed)}[/bold]")
        else:
            s.skipped = 1
            _track(label, s)
            console.print(f"  [{label}]  [yellow]![/yellow] locked, skipped")
    return s


def empty_recycle_bin():
    SHERB_NOCONFIRMATION = 0x1
    SHERB_NOPROGRESSUI = 0x2
    SHERB_NOSOUND = 0x4
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    console.print("  [Recycle Bin]  [green]OK[/green] emptied")


# ---------------------------------------------------------------------------
# location builders  (label, path, group)
# ---------------------------------------------------------------------------

def _browser_cache_items():
    out = []
    for name, rel in CHROMIUM_BROWSERS:
        base = os.path.join(LOCAL, rel)
        for c in glob.glob(os.path.join(base, "*", "Cache")):
            out.append((f"{name} Cache", c, "browser"))
        for c in glob.glob(os.path.join(base, "*", "Code Cache")):
            out.append((f"{name} Code Cache", c, "browser"))
    return out


def _firefox_cache_items():
    out = []
    for c in glob.glob(os.path.join(FIREFOX_PROFILES, "*", "cache2")):
        out.append(("Firefox Cache", c, "browser"))
    return out


def _cache_tile_items():
    return [
        ("DirectX Shader Cache", os.path.join(LOCAL, "D3DSCache"), "caches"),
        ("NVIDIA DX Cache", os.path.join(LOCAL, r"NVIDIA\DXCache"), "caches"),
        ("NVIDIA GL Cache", os.path.join(LOCAL, r"NVIDIA\GLCache"), "caches"),
        ("Font Cache", os.path.join(LOCAL, r"Microsoft\Windows\Fonts"), "caches"),
        ("RDP Bitmap Cache", os.path.join(LOCAL, r"Microsoft\Terminal Server Client\Cache"), "caches"),
    ]


# Every Electron app (Discord, Slack, Teams, VSCode, Cursor, ...) uses the
# same Chromium-derived cache layout under its data folder. One shared list
# means adding a new cache kind (e.g. DawnCache) benefits every app at once
# instead of needing per-app edits.
ELECTRON_CACHE_SUBDIRS = (
    "Cache", "Code Cache", "GPUCache", "DawnCache",
    os.path.join("Service Worker", "CacheStorage"),
)


def _electron_cache_items(display: str, base: str):
    return [(f"{display} {os.path.basename(sub)}", os.path.join(base, sub), "apps")
            for sub in ELECTRON_CACHE_SUBDIRS]


def _app_cache_items():
    items = []
    items += _electron_cache_items("Discord", os.path.join(APPDATA, "discord"))
    items += _electron_cache_items("Slack", os.path.join(APPDATA, "slack"))
    items += _electron_cache_items("Teams", os.path.join(APPDATA, "Microsoft", "Teams"))
    for base in glob.glob(os.path.join(LOCAL, "Packages", "MicrosoftTeams_*",
                                       "LocalCache", "Microsoft", "Teams", "*")):
        name = os.path.basename(base)
        if name in ("Cache", "Code Cache", "GPUCache", "DawnCache", "blob_storage"):
            items.append((f"Teams (new) {name}", base, "apps"))
    items.append(("Spotify Data", os.path.join(LOCAL, "Spotify", "Data"), "apps"))
    vsc = os.path.join(APPDATA, "Code")
    items += _electron_cache_items("VSCode", vsc)
    items.append(("VSCode CachedData", os.path.join(vsc, "CachedData"), "apps"))
    cur = os.path.join(APPDATA, "Cursor")
    items += _electron_cache_items("Cursor", cur)
    items.append(("Cursor CachedData", os.path.join(cur, "CachedData"), "apps"))
    items.append(("Zoom Logs", os.path.join(APPDATA, "Zoom", "logs"), "apps"))
    return items


def _go_mod_cache_download_dir():
    """~/go/pkg/mod/cache/download by default, GOPATH-aware. Deliberately
    scoped to just the download/ subfolder (the re-downloadable HTTP cache
    of module zips), NOT all of pkg/mod — that also holds extracted module
    source that other projects reference directly; wiping it forces a full
    re-resolve of every dependency in every project, which is a much bigger
    action than clearing a cache and shouldn't happen from a cache cleaner."""
    gopath = os.environ.get("GOPATH") or os.path.join(USERPROFILE, "go")
    return os.path.join(gopath, "pkg", "mod", "cache", "download")


def _dev_cache_items():
    home = USERPROFILE
    return [
        ("npm Cache", os.path.join(LOCAL, "npm-cache"), "dev"),
        ("pip Cache", os.path.join(LOCAL, "pip", "cache"), "dev"),
        ("NuGet v3", os.path.join(LOCAL, "NuGet", "v3-cache"), "dev"),
        ("NuGet v4", os.path.join(LOCAL, "NuGet", "v4-cache"), "dev"),
        ("NuGet http", os.path.join(LOCAL, "NuGet", "http-cache"), "dev"),
        ("Gradle Caches", os.path.join(home, ".gradle", "caches"), "dev"),
        ("Go Build", os.path.join(LOCAL, "go-build"), "dev"),
        ("Go Module Download Cache", _go_mod_cache_download_dir(), "dev"),
        ("Cargo Registry Cache", os.path.join(home, ".cargo", "registry", "cache"), "dev"),
    ]


def _uwp_temp_items():
    """Per-package sandboxed temp folders for installed Store/UWP apps —
    each app gets its own AC\\Temp, and nothing ever cleans these up
    automatically. Safe: it's the same kind of scratch space as User Temp,
    just sandboxed per-package instead of shared."""
    items = []
    for t in glob.glob(os.path.join(LOCAL, "Packages", "*", "AC", "Temp")):
        pkg_name = os.path.basename(os.path.dirname(os.path.dirname(t)))
        items.append((f"UWP Temp: {pkg_name}", t, "system"))
    return items


def _chkdsk_recovery_items():
    """Orphaned FOUND.NNN / *.CHK folders CHKDSK leaves at drive roots after
    recovering lost clusters. Zero risk — these are already-disconnected
    fragments nothing references; almost nobody knows to clear them."""
    items = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        bitmask = 0
    for i in range(26):
        if not (bitmask & (1 << i)):
            continue
        drive = f"{chr(65 + i)}:\\"
        for d in glob.glob(os.path.join(drive, "FOUND.*")):
            if os.path.isdir(d):
                items.append((f"CHKDSK Recovery ({os.path.basename(d)} on {drive[:2]})", d, "system"))
    return items


def _system_items():
    items = [
        ("Setup Logs", r"C:\Windows\Panther", "system"),
        ("Servicing Logs", r"C:\Windows\Logs\CBS", "system"),
        ("Minidumps", r"C:\Windows\Minidump", "system"),
        ("Error Reporting", r"C:\ProgramData\Microsoft\Windows\WER", "system"),
        ("Error Reporting (user)", os.path.join(LOCAL, r"Microsoft\Windows\WER"), "system"),
        ("Crash Dumps", os.path.join(LOCAL, "CrashDumps"), "system"),
    ]
    items += _uwp_temp_items()
    items += _chkdsk_recovery_items()
    return items


def _steam_install_dirs():
    return [d for d in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam")
            if os.path.isdir(d)]


def _game_cache_items():
    """Steam CLIENT caches — its own UI/browser cache, crash dumps, and web
    view cache. These are a different, lower-risk thing than per-game shader
    caches (which stay in Extended Clean): deleting them doesn't cause any
    in-game recompile stutter, they're just Steam's own regenerable cache,
    same risk tier as a browser cache."""
    items = []
    for steam in _steam_install_dirs():
        for sub, label in (("appcache", "Steam App Cache"),
                           ("dumps", "Steam Crash Dumps"),
                           ("htmlcache", "Steam Web Cache")):
            items.append((label, os.path.join(steam, sub), "games"))
    return items


def _extended_items():
    items = []
    for root in (r"C:\Program Files (x86)\Steam\steamapps\shadercache",
                 r"C:\Program Files\Steam\steamapps\shadercache"):
        for d in glob.glob(os.path.join(root, "*")):
            items.append(("Steam Shader Cache", d, "extended"))
    for label, path in [
        ("LiveKernel Reports", r"C:\Windows\LiveKernelReports"),
        ("DISM Logs", r"C:\Windows\Logs\DISM"),
        ("MoSetup Logs", r"C:\Windows\Logs\MoSetup"),
    ]:
        items.append((label, path, "extended"))
    return items


def _all_scan_items():
    items = [
        ("User Temp", TEMP, "core"),
        ("Windows Temp", r"C:\Windows\Temp", "system"),
        ("Prefetch", r"C:\Windows\Prefetch", "core"),
    ]
    items += _browser_cache_items()
    items += _firefox_cache_items()
    items += _cache_tile_items()
    items.append(("Thumbnail Cache", os.path.join(LOCAL, r"Microsoft\Windows\Explorer", "thumbcache_*.db"), "caches"))
    items.append(("Icon Cache", os.path.join(LOCAL, r"Microsoft\Windows\Explorer", "iconcache_*.db"), "caches"))
    items.append(("IconCache.db", os.path.join(LOCAL, "IconCache.db"), "caches"))
    items += _app_cache_items()
    items += _dev_cache_items()
    items += _game_cache_items()
    items.append(("Legacy WebCache", os.path.join(LOCAL, r"Microsoft\Windows\WebCache",
                                                   "WebCacheV01.dat"), "caches"))
    items += [
        ("WU Download", r"C:\Windows\SoftwareDistribution\Download", "system"),
        ("Delivery Opt.", r"C:\Windows\SoftwareDistribution\DeliveryOptimization", "system"),
    ]
    items += _system_items()
    items.append(("MEMORY.DMP", r"C:\Windows\MEMORY.DMP", "system"))
    items += _extended_items()
    items.append(("Windows.old", r"C:\Windows.old", "extended"))
    return items


GROUP_LABELS = {
    "core": "Temp & Browser",
    "browser": "Temp & Browser",
    "caches": "Caches (GPU / Tiles / Icons)",
    "apps": "Apps",
    "dev": "Developer",
    "games": "Games & Launchers",
    "system": "Windows System",
    "extended": "Extended (caution)",
}


# ---------------------------------------------------------------------------
# category implementations
# ---------------------------------------------------------------------------

def clear_basics() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Core Temp & Browser ==[/bold cyan]")

    for label, path in [
        ("User Temp", TEMP),
        ("Windows Temp", r"C:\Windows\Temp"),
        ("Prefetch", r"C:\Windows\Prefetch"),
    ]:
        total += clear_folder(path, label)

    for label, path, _g in _browser_cache_items():
        total += clear_folder(path, label, quiet=True, concise=True)
    for label, path, _g in _firefox_cache_items():
        total += clear_folder(path, label, quiet=True, concise=True)

    if settings.use_recycle_bin:
        console.print("  [Recycle Bin]  [dim]skipped — recycle mode keeps items undoable[/dim]")
    else:
        empty_recycle_bin()
    return total


def clear_shaders_thumbnails() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== GPU, Thumbnail, Icon & Font Caches ==[/bold cyan]")

    for label, path, _g in _cache_tile_items():
        total += clear_folder(path, label, quiet=True, concise=True)

    total += clear_matching(
        os.path.join(LOCAL, r"Microsoft\Windows\Explorer"),
        "thumbcache_*.db", "Thumbnail Cache",
    )
    total += clear_matching(
        os.path.join(LOCAL, r"Microsoft\Windows\Explorer"),
        "iconcache_*.db", "Icon Cache",
    )
    total += delete_file(os.path.join(LOCAL, "IconCache.db"), "IconCache.db")
    total += delete_file(os.path.join(LOCAL, r"Microsoft\Windows\WebCache", "WebCacheV01.dat"),
                         "Legacy WebCache (IE / old Edge)")
    return total


def clear_windows_files() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Windows System Files ==[/bold cyan]")

    console.print("  [dim]Stopping Windows Update / BITS services...[/dim]")
    run_quiet(["net", "stop", "wuauserv"])
    run_quiet(["net", "stop", "bits"])

    total += clear_folder(r"C:\Windows\SoftwareDistribution\Download", "WU Download")
    total += clear_folder(r"C:\Windows\SoftwareDistribution\DeliveryOptimization", "Delivery Opt.")

    console.print("  [dim]Restarting Windows Update / BITS services...[/dim]")
    run_quiet(["net", "start", "wuauserv"])
    run_quiet(["net", "start", "bits"])

    for label, path, _g in _system_items():
        total += clear_folder(path, label, quiet=True, concise=True)

    total += delete_file(r"C:\Windows\MEMORY.DMP", "MEMORY.DMP")

    win_old = r"C:\Windows.old"
    if os.path.isdir(win_old) and is_excluded(win_old):
        console.print("  [Windows.old]  [dim]protected by exclusion list, skipped[/dim]")
    elif os.path.isdir(win_old):
        console.print(f"\n  [bold yellow]! Windows.old detected[/bold yellow] (can't roll back after deletion)")
        if Confirm.ask("  Delete Windows.old?", default=False):
            with console.status("[yellow]Removing Windows.old...[/yellow]", spinner="dots"):
                run_quiet(["takeown", "/f", win_old, "/r", "/d", "y"])
                run_quiet(["icacls", win_old, "/grant", "Administrators:F", "/t"])
                try:
                    sz = calc_size(win_old)
                    shutil.rmtree(ext(win_old), onerror=_rmtree_onerror)
                    if os.path.exists(ext(win_old)):
                        raise OSError("could not be fully removed")
                    total.deleted += 1
                    total.bytes_freed += sz
                    console.print(f"  [Windows.old]  [green]OK[/green] deleted [bold]{fmt_size(sz)}[/bold]")
                except (PermissionError, OSError):
                    total.skipped += 1
                    console.print(f"  [Windows.old]  [yellow]![/yellow] could not be fully removed")
        else:
            console.print("  [Windows.old]  [dim]skipped[/dim]")
    return total


def clear_app_caches() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== App Caches ==[/bold cyan]")
    found = 0
    for label, path, _g in _app_cache_items():
        s = clear_folder(path, label, quiet=True, concise=True)
        if s.deleted or s.skipped or s.skipped_new:
            found += 1
        total += s
    if found == 0:
        console.print("  [dim]No app caches found.[/dim]")
    return total


def clear_dev_caches() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Developer Caches ==[/bold cyan]")
    found = 0
    for label, path, _g in _dev_cache_items():
        s = clear_folder(path, label, quiet=True, concise=True)
        if s.deleted or s.skipped or s.skipped_new:
            found += 1
        total += s
    if found == 0:
        console.print("  [dim]No developer caches found.[/dim]")
    return total


def clear_game_caches() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Games & Launchers ==[/bold cyan]")
    found = 0
    for label, path, _g in _game_cache_items():
        s = clear_folder(path, label, quiet=True, concise=True)
        if s.deleted or s.skipped or s.skipped_new:
            found += 1
        total += s
    if found == 0:
        console.print("  [dim]No game launcher caches found.[/dim]")
    return total


def clear_system_maintenance() -> CleanStats:
    """
    Runs the official, Microsoft-sanctioned WinSxS component cleanup:
    `dism.exe /Online /Cleanup-Image /StartComponentCleanup`.

    This only removes component versions Windows Servicing has already
    marked superseded and safe to discard — it never touches active files
    directly (no manual deletion happens here at all, DISM owns the whole
    operation), and deliberately does NOT pass /ResetBase, so the ability
    to uninstall recently installed updates is preserved.

    Space freed is measured via a free-disk-space delta rather than scanning
    C:\\Windows\\WinSxS directly — that folder can be tens of GB and slow to
    walk, and the delta is what the user actually cares about anyway.
    """
    total = CleanStats()
    console.print()
    console.print(Panel(
        "[bold yellow]! System Maintenance — WinSxS Component Cleanup[/bold yellow]\n\n"
        "  Runs the official Windows servicing cleanup (DISM). Only removes\n"
        "  component versions Windows has already marked safe to discard.\n"
        "  Does NOT use /ResetBase, so recently installed updates stay\n"
        "  uninstallable.\n\n"
        "[dim]Requires administrator rights. Can take several minutes.\n"
        "Safe, but not something you need to run every day.[/dim]",
        box=box.ASCII, style="bold",
    ))
    console.print()
    if not Confirm.ask("[bold yellow]Run WinSxS component cleanup now?[/bold yellow]", default=False):
        console.print("  [dim]System Maintenance cancelled.[/dim]")
        return total

    if not is_admin():
        console.print("  [System Maintenance]  [yellow]![/yellow] requires administrator rights, skipped")
        total.skipped = 1
        _track("System Maintenance (WinSxS)", total)
        return total

    drive = os.environ.get("SystemDrive", "C:") + "\\"
    try:
        before = shutil.disk_usage(drive).free
    except Exception:
        before = None

    console.print("  [dim]Running DISM component cleanup — this can take several minutes...[/dim]")
    ok = False
    try:
        proc = subprocess.run(
            ["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            capture_output=True, shell=False, timeout=1800,
        )
        ok = proc.returncode == 0
    except Exception as exc:
        console.print(f"  [System Maintenance]  [red]failed[/red] {exc}")

    if ok:
        try:
            after = shutil.disk_usage(drive).free
        except Exception:
            after = before
        freed = max(0, (after or 0) - (before or 0)) if before is not None else 0
        total.deleted = 1
        total.bytes_freed = freed
        _track("System Maintenance (WinSxS)", total)
        console.print(f"  [System Maintenance]  [green]OK[/green] freed "
                      f"[bold]{fmt_size(freed)}[/bold] (approx., by free-space delta)")
    else:
        total.skipped = 1
        _track("System Maintenance (WinSxS)", total)
        console.print("  [System Maintenance]  [yellow]![/yellow] DISM did not complete successfully")
    return total


# ---------------------------------------------------------------------------
# installers report (read-only — never deletes automatically)
# ---------------------------------------------------------------------------

INSTALLER_EXTS = (".exe", ".msi")


def find_old_installers(days: int = 30):
    """
    Installer-looking files sitting in Downloads older than `days`. Purely
    informational — this never deletes anything itself. Individual items
    are only ever removed one at a time, by explicit user action, through
    show_installers_menu() (CLI) or the Installers dialog (GUI).
    """
    out = []
    downloads = os.path.join(USERPROFILE, "Downloads") if USERPROFILE else ""
    if not downloads or not os.path.isdir(downloads):
        return out
    cutoff = time.time() - days * 86400
    try:
        with os.scandir(downloads) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                    if not entry.name.lower().endswith(INSTALLER_EXTS):
                        continue
                    st = entry.stat()
                    if st.st_mtime > cutoff:
                        continue
                    out.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size": st.st_size,
                        "age_days": int((time.time() - st.st_mtime) / 86400),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    out.sort(key=lambda d: -d["size"])
    return out


JUNK_PATTERNS = ("*.tmp", "~$*", "*.bak", "*-001.*")
JUNK_SKIP_DIRS = {
    "AppData", "Windows", "Program Files", "Program Files (x86)", ".git",
    ".gradle", ".cache", ".npm", "node_modules", "__pycache__", "Temp",
    "Cache", "Code Cache", "GPUCache", "CachedData", "Data", "shadercache",
    "npm-cache", "NuGet", "pip", "go-build", "D3DSCache", "Dist",
}


def junk_sweep() -> CleanStats:
    s = CleanStats()
    age = settings.age_days * 86400
    if not USERPROFILE:
        _result("Junk Sweep", s, found=False)
        return s
    with console.status("[yellow]Sweeping profile for junk files...[/yellow]", spinner="dots"):
        for root, dirs, files in os.walk(USERPROFILE):
            dirs[:] = [d for d in dirs
                       if d not in JUNK_SKIP_DIRS and not d.startswith(".")
                       and not is_excluded(os.path.join(root, d))]
            for name in files:
                if not any(fnmatch.fnmatch(name.lower(), p) for p in JUNK_PATTERNS):
                    continue
                path = os.path.join(root, name)
                if is_excluded(path):
                    continue
                try:
                    if age > 0 and (time.time() - os.path.getmtime(path)) < age:
                        s.skipped_new += 1
                        continue
                    sz = os.path.getsize(path)
                    if _remove_path(path, False, settings.use_recycle_bin):
                        s.deleted += 1
                        s.bytes_freed += sz
                    else:
                        s.skipped += 1
                except Exception:
                    s.skipped += 1
    _track("Junk Sweep", s)
    _result("Junk Sweep", s)
    return s


def clear_extended() -> CleanStats:
    console.print()
    console.print(Panel(
        "[bold yellow]! Extended Clean — items that may have side effects[/bold yellow]\n\n"
        "  - [bold]Game shader caches[/bold] — games will recompile shaders on next launch\n"
        "  - [bold]System debug logs[/bold] (LiveKernel / DISM / MoSetup) — lose crash & kernel diagnostics\n"
        "  - [bold]Junk file sweep[/bold] — removes *.tmp, ~$*, *.bak, *-001.* from your profile\n\n"
        "[dim]Safe for everyday use, but not recommended as a routine daily clean.[/dim]",
        box=box.ASCII, style="bold",
    ))
    console.print()
    if not Confirm.ask("[bold yellow]Continue with Extended Clean?[/bold yellow]", default=False):
        console.print("  [dim]Extended clean cancelled.[/dim]")
        return CleanStats()

    total = CleanStats()
    console.print(f"\n[bold yellow]== Extended Clean (caution) ==[/bold yellow]")
    for label, path, _g in _extended_items():
        total += clear_folder(path, label, quiet=True, concise=True)
    total += junk_sweep()
    return total


# ---------------------------------------------------------------------------
# scan / analyze
# ---------------------------------------------------------------------------

def scan_all():
    """Threaded scan across all tracked locations. Returns (data, groups)."""
    items = _all_scan_items()
    expanded = []
    groups = {}
    for label, path, group in items:
        groups.setdefault(label, group)
        if any(ch in path for ch in "*?["):
            for p in glob.glob(path):
                expanded.append((label, p))
        else:
            expanded.append((label, path))

    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(calc_size, p): label for label, p in expanded}
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                sz = fut.result()
            except Exception:
                sz = 0
            results[label] = results.get(label, 0) + sz

    data = {k: v for k, v in results.items() if v > 0}
    return data, groups


def show_analysis(data: dict, groups: dict):
    total = sum(data.values())
    console.print()
    console.print(Panel(
        f"[bold]Space Analysis[/bold]\n[dim]{len(data)} locations | {fmt_size(total)} reclaimable[/dim]",
        box=box.ASCII, style="bold white",
    ))
    if total == 0:
        console.print("[yellow]No significant temp data found.[/yellow]")
        return

    table = Table(box=box.ASCII, header_style="bold cyan")
    table.add_column("Group")
    table.add_column("Location")
    table.add_column("Size", justify="right")
    table.add_column("Share", justify="right")

    rows = sorted(data.items(), key=lambda x: x[1], reverse=True)
    last_group = None
    for label, size in rows:
        group = groups.get(label, "other")
        if group != last_group:
            table.add_row(f"[bold]{GROUP_LABELS.get(group, group)}[/bold]", "", "", "", style="bold")
            last_group = group
        bar_len = max(1, round(20 * size / total))
        table.add_row("", label, fmt_size(size), "#" * bar_len)

    table.add_row("", "", "", "")
    table.add_row("[bold]Total reclaimable[/bold]", "", f"[bold]{fmt_size(total)}[/bold]", "")
    console.print()
    console.print(table)
    console.print(f"[dim]Est. reclaimable: ~{fmt_size(total)} — some items may be locked or newer than the age limit.[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# results & reports
# ---------------------------------------------------------------------------

def show_results(pre_scan, elapsed: float, mode: str):
    table = Table(box=box.ASCII, title="[bold]Cleanup Complete[/bold]", title_justify="center")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Mode", mode)
    table.add_row("Duration", f"{elapsed:.1f}s")
    table.add_row("Items deleted", str(stats.deleted))
    table.add_row("Locked skipped", str(stats.skipped))
    if stats.skipped_new:
        table.add_row("Kept (too new)", str(stats.skipped_new))
    table.add_row("Space freed", fmt_size(stats.bytes_freed))
    if pre_scan:
        remaining = max(0, sum(pre_scan.values()) - stats.bytes_freed)
        table.add_row("Est. remaining", fmt_size(remaining), style="dim")
    table.add_row("Deletion mode",
                  "[green]Recycle Bin (undoable)[/green]" if settings.use_recycle_bin
                  else "[red]Permanent[/red]")
    table.add_row("Age limit",
                  f"[cyan]{settings.age_days} day(s)[/cyan]" if settings.age_days else "[dim]off[/dim]")

    console.print()
    console.print(table)
    if settings.use_recycle_bin and stats.bytes_freed:
        console.print("[dim]Space freed is pending — empty the Recycle Bin to actually reclaim it.[/dim]")
    console.print()


def save_report(mode: str, elapsed: float):
    if not settings.save_reports:
        return
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        data = {
            "app": "WinTempCleaner",
            "version": APP_VERSION,
            "mode": mode,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "age_days": settings.age_days,
            "recycle_bin": settings.use_recycle_bin,
            "duration_sec": round(elapsed, 2),
            "totals": asdict(stats),
            "categories": [{"label": lbl} | d for lbl, d in RUN_DETAIL],
        }
        base = os.path.join(REPORTS_DIR, f"report_{ts}")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["category", "deleted", "locked_skipped", "too_new_kept", "freed_bytes", "freed_size"])
            for lbl, d in RUN_DETAIL:
                w.writerow([lbl, d["deleted"], d["skipped"], d["skipped_new"],
                            d["bytes_freed"], fmt_size(d["bytes_freed"])])
        console.print(f"[dim]Report saved: {base}.csv[/dim]")
    except Exception:
        pass


def _view_report(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        console.print(f"[red]Could not read report: {exc}[/red]")
        return

    console.print()
    console.print(Panel(
        f"[bold]Report[/bold]  [cyan]{data.get('mode', '?')}[/cyan]\n"
        f"[dim]{data.get('timestamp', '?')} · age limit {data.get('age_days')}d · "
        f"duration {data.get('duration_sec', 0)}s[/dim]",
        box=box.ASCII, style="bold white",
    ))
    table = Table(box=box.ASCII, header_style="bold cyan")
    table.add_column("Category")
    table.add_column("Deleted", justify="right")
    table.add_column("Locked", justify="right")
    table.add_column("Too new", justify="right")
    table.add_column("Freed", justify="right")

    for cat in data.get("categories", []):
        table.add_row(cat.get("label", "?"),
                      str(cat.get("deleted", 0)),
                      str(cat.get("skipped", 0)),
                      str(cat.get("skipped_new", 0)),
                      fmt_size(cat.get("bytes_freed", 0)))

    t = data.get("totals", {})
    table.add_row("", "", "", "", "")
    table.add_row("[bold]Total[/bold]",
                  str(t.get("deleted", 0)),
                  str(t.get("skipped", 0)),
                  str(t.get("skipped_new", 0)),
                  f"[bold]{fmt_size(t.get('bytes_freed', 0))}[/bold]")
    console.print(table)
    console.print()


def show_reports_menu():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json")), reverse=True)
    if not files:
        console.print("[yellow]No reports yet.[/yellow]")
        press_enter("continue")
        return
    clear_screen()
    console.print(Panel("[bold]Cleanup Reports[/bold]", box=box.ASCII, style="bold white"))
    for i, f in enumerate(files[:20], 1):
        console.print(f"  {i:>2}  [cyan]{os.path.basename(f)}[/cyan]")
    console.print("   Q  Back")
    console.print()
    while True:
        c = Prompt.ask("[bold]Report[/bold]").strip().lower()
        if c == "q":
            return
        if c.isdigit() and 1 <= int(c) <= min(len(files), 20):
            _view_report(files[int(c) - 1])
            press_enter("continue")
            return
        console.print("[red]Invalid choice.[/red]")


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------

def _manage_exclusions():
    while True:
        clear_screen()
        console.print(Panel("[bold]Protected Paths[/bold]\n"
                            "[dim]Never touched by any clean mode, regardless of age limit.[/dim]",
                            box=box.ASCII, style="bold white"))
        if not settings.excluded_paths:
            console.print("  [dim]No protected paths yet.[/dim]")
        for i, p in enumerate(settings.excluded_paths, 1):
            console.print(f"  {i:>2}  {p}")
        console.print()
        console.print("   A  Add a path")
        console.print("   R  Remove a path")
        console.print("   B  Back")
        console.print()
        c = Prompt.ask("[bold]Option[/bold]").strip().lower()
        if c == "b":
            save_settings(settings)
            return
        if c == "a":
            p = Prompt.ask("  Path to protect").strip().strip('"')
            if p and os.path.exists(p):
                existing = [_norm(x) for x in settings.excluded_paths]
                if _norm(p) not in existing:
                    settings.excluded_paths.append(os.path.abspath(p))
                    console.print("[green]Added.[/green]")
                else:
                    console.print("[yellow]Already protected.[/yellow]")
            else:
                console.print("[red]Path does not exist.[/red]")
            press_enter("continue")
        elif c == "r":
            if not settings.excluded_paths:
                continue
            v = Prompt.ask("  Number to remove").strip()
            if v.isdigit() and 1 <= int(v) <= len(settings.excluded_paths):
                removed = settings.excluded_paths.pop(int(v) - 1)
                console.print(f"[green]Removed:[/green] {removed}")
            press_enter("continue")


def show_options_menu():
    while True:
        clear_screen()
        console.print(Panel("[bold]Options[/bold]", box=box.ASCII, style="bold white"))
        age_str = f"[cyan]{settings.age_days}[/cyan] day(s)" if settings.age_days else "[cyan]off[/cyan]"
        console.print(f"   1  Age limit ......... {age_str}   (only delete files older than this)")
        console.print(f"   2  Recycle Bin ....... [cyan]{'On' if settings.use_recycle_bin else 'Off'}[/cyan]   (undoable deletions)")
        console.print(f"   3  Auto-report ....... [cyan]{'On' if settings.save_reports else 'Off'}[/cyan]   (save CSV/JSON after each clean)")
        console.print(f"   4  Exclusions ....... [cyan]{len(settings.excluded_paths)}[/cyan] protected path(s)")
        console.print("   B  Back (settings saved)")
        console.print()
        c = Prompt.ask("[bold]Option[/bold]").strip().lower()
        if c == "b":
            save_settings(settings)
            console.print("[dim]Settings saved.[/dim]")
            press_enter("continue")
            return
        if c == "1":
            console.print("   New age limit: [bold]0[/bold]=off, [bold]1[/bold], [bold]3[/bold], [bold]7[/bold] or [bold]30[/bold] days")
            v = Prompt.ask("[bold]Limit[/bold]", default=str(settings.age_days)).strip()
            try:
                n = int(v)
                if n in (0, 1, 3, 7, 30):
                    settings.age_days = n
                    console.print(f"[green]Age limit set to {n} day(s).[/green]")
                else:
                    console.print("[red]Pick 0, 1, 3, 7 or 30.[/red]")
            except ValueError:
                console.print("[red]Invalid number.[/red]")
        elif c == "2":
            settings.use_recycle_bin = not settings.use_recycle_bin
            console.print(f"[green]Recycle Bin {'On' if settings.use_recycle_bin else 'Off'}.[/green]")
        elif c == "3":
            settings.save_reports = not settings.save_reports
            console.print(f"[green]Auto-report {'On' if settings.save_reports else 'Off'}.[/green]")
        elif c == "4":
            _manage_exclusions()
            continue
        else:
            console.print("[red]Invalid choice.[/red]")
        press_enter("continue")


def show_installers_menu():
    items = find_old_installers(30)
    clear_screen()
    console.print(Panel("[bold]Old Installers in Downloads[/bold]\n"
                        "[dim]Informational only — nothing is deleted automatically. "
                        "Older than 30 days.[/dim]",
                        box=box.ASCII, style="bold white"))
    if not items:
        console.print("[dim]No installers older than 30 days found.[/dim]")
        press_enter("continue")
        return
    for i, it in enumerate(items, 1):
        console.print(f"  {i:>2}  {it['name']:<42} {fmt_size(it['size']):>10}   {it['age_days']}d old")
    console.print()
    console.print("   #  Delete that installer (asks to confirm first)")
    console.print("   B  Back")
    console.print()
    while True:
        c = Prompt.ask("[bold]Option[/bold]").strip().lower()
        if c == "b":
            return
        if c.isdigit() and 1 <= int(c) <= len(items):
            it = items[int(c) - 1]
            if Confirm.ask(f"  Delete [bold]{it['name']}[/bold] ({fmt_size(it['size'])})?", default=False):
                delete_file(it["path"], it["name"])
            press_enter("continue")
            return
        console.print("[red]Invalid choice.[/red]")


# ---------------------------------------------------------------------------
# menu
# ---------------------------------------------------------------------------

def show_menu() -> str:
    clear_screen()

    title = Panel(
        "[bold cyan]Windows Temp / Cache Cleaner[/bold cyan]\n"
        "[dim]Professional Edition — Enhanced[/dim]",
        box=box.ASCII,
        style="bold white",
        subtitle=f"[dim]v{APP_VERSION}[/dim]",
    )
    console.print(title)

    menu = Table.grid(padding=(0, 2))
    menu.add_column(style="bold cyan", justify="right")
    menu.add_column(style="white")
    menu.add_column(style="dim", justify="right")

    rows = [
        (" 1", "Quick Clean        - Temp, browser caches, Recycle Bin", "SAFE"),
        (" 2", "Deep Clean         - Everything safe (full sweep)", "SAFE"),
        (" 3", "Shaders & Tiles    - GPU, thumbnail, icon & font caches", "SAFE"),
        (" 4", "Windows Files      - Logs, dumps, update cache", "SAFE"),
        (" 5", "App Caches         - Discord, Teams, Spotify, Slack, VSCode", "SAFE"),
        (" 6", "Dev Caches         - npm, pip, NuGet, Gradle, Go, Cargo", "SAFE"),
        (" 7", "Extended Clean     - Game shaders, debug logs, junk sweep", "CAUTION"),
        (" G", "Games & Launchers  - Steam client cache, crash dumps", "SAFE"),
        (" 8", "Analyze Space      - Scan only, detailed report", "SAFE"),
        (" M", "System Maintenance - WinSxS component cleanup (DISM)", "CAUTION"),
        (" I", "Installers         - Old installers in Downloads (review)", ""),
        (" 9", "Options            - Age limit, Recycle Bin, exclusions", ""),
        (" R", "Reports            - View past cleanup reports", ""),
        ("", "", ""),
        (" Q", "[bold red]Quit[/bold red]", ""),
    ]
    for num, desc, tag in rows:
        if tag == "CAUTION":
            tag_str = "[bold yellow]CAUTION[/bold yellow]"
        elif tag == "SAFE":
            tag_str = "[green]SAFE[/green]"
        else:
            tag_str = ""
        menu.add_row(num, desc, tag_str)

    console.print(Panel(menu, box=box.ASCII, title="[bold]Menu[/bold]"))
    console.print()

    while True:
        choice = Prompt.ask("[bold]Choice[/bold]").strip().lower()
        if choice in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "g", "m", "i", "r", "q"):
            return choice
        console.print("[red]Invalid choice. Enter 1-9, G, M, I, R or Q.[/red]")


MODES = {
    "1": "Quick Clean",
    "2": "Deep Clean",
    "3": "Shaders & Tiles",
    "4": "Windows Files",
    "5": "App Caches",
    "6": "Dev Caches",
    "7": "Extended Clean",
    "g": "Games & Launchers",
    "m": "System Maintenance",
}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global stats, RUN_DETAIL
    try:
        if not is_admin():
            console.print("[yellow]Not running as admin. Relaunching with elevation...[/yellow]")
            relaunch_as_admin()
            return

        while True:
            choice = show_menu()

            if choice == "q":
                console.print("[dim]Goodbye![/dim]")
                break

            if choice == "8":
                try:
                    with console.status("[green]Scanning temp locations...[/green]", spinner="dots"):
                        data, groups = scan_all()
                    show_analysis(data, groups)
                except Exception as exc:
                    console.print(f"[red]Scan failed: {exc}[/red]")
                press_enter("continue")
                continue

            if choice == "9":
                show_options_menu()
                continue

            if choice == "r":
                show_reports_menu()
                continue

            if choice == "i":
                show_installers_menu()
                continue

            stats.reset()
            RUN_DETAIL.clear()
            mode = MODES.get(choice, choice)

            pre_scan = None
            try:
                with console.status("[green]Pre-scanning...[/green]", spinner="dots"):
                    pre_scan, _ = scan_all()
            except Exception as exc:
                console.print(f"[red]Pre-scan failed (continuing anyway): {exc}[/red]")

            start = time.time()
            try:
                if choice == "1":
                    stats += clear_basics()
                elif choice == "2":
                    stats += clear_basics()
                    stats += clear_shaders_thumbnails()
                    stats += clear_windows_files()
                    stats += clear_app_caches()
                    stats += clear_dev_caches()
                    stats += clear_game_caches()
                elif choice == "3":
                    stats += clear_shaders_thumbnails()
                elif choice == "4":
                    stats += clear_windows_files()
                elif choice == "5":
                    stats += clear_app_caches()
                elif choice == "6":
                    stats += clear_dev_caches()
                elif choice == "7":
                    stats += clear_extended()
                elif choice == "g":
                    stats += clear_game_caches()
                elif choice == "m":
                    stats += clear_system_maintenance()
            except Exception as exc:
                console.print(f"\n[bold red]Error during cleaning:[/bold red] {exc}")
                traceback.print_exc()

            elapsed = time.time() - start
            show_results(pre_scan, elapsed, mode)
            save_report(mode, elapsed)
            press_enter("return to menu")

    except Exception:
        console.print("[bold red]Unexpected error - see log for details[/bold red]")
        with open(ERROR_LOG, "w") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        press_enter("exit")


if __name__ == "__main__":
    main()
