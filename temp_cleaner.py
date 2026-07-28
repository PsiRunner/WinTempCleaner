"""
Windows Temp/Cache Cleaner — Professional Edition

Rich CLI with styled menu, size tracking, and interactive loop.
Auto-elevates via UAC when not admin.

Dependencies: rich (pip install rich)
"""

import os
import sys
import ctypes
import shutil
import glob
import subprocess
import traceback
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Prompt, Confirm

console = Console()
ERROR_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleaner_error.log")

LOCAL = os.environ.get("LOCALAPPDATA", "")
TEMP = os.environ.get("TEMP", "")

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


def calc_size(path: str) -> int:
    total = 0
    try:
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except Exception:
                return 0
        try:
            entries = list(os.scandir(path))
        except Exception:
            return 0
        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += calc_size(entry.path)
            except Exception:
                continue
    except Exception:
        pass
    return total


def run_quiet(args):
    subprocess.run(args, capture_output=True, shell=False)


# ---------------------------------------------------------------------------
# stats accumulator
# ---------------------------------------------------------------------------

@dataclass
class CleanStats:
    deleted: int = 0
    skipped: int = 0
    bytes_freed: int = 0

    def reset(self):
        self.deleted = 0
        self.skipped = 0
        self.bytes_freed = 0

    def __iadd__(self, other: "CleanStats") -> "CleanStats":
        self.deleted += other.deleted
        self.skipped += other.skipped
        self.bytes_freed += other.bytes_freed
        return self


stats = CleanStats()


# ---------------------------------------------------------------------------
# cleaning primitives
# ---------------------------------------------------------------------------

def _result(label: str, s: CleanStats):
    icon = "[green]OK[/green]" if s.skipped == 0 else "[yellow]![/yellow]"
    console.print(
        f"  [{label}]  {icon}  "
        f"deleted [bold]{s.deleted}[/bold], "
        f"skipped [bold]{s.skipped}[/bold], "
        f"freed [bold]{fmt_size(s.bytes_freed)}[/bold]"
    )


def clear_folder(folder_path: str, label: str) -> CleanStats:
    s = CleanStats()
    if not folder_path or not os.path.isdir(folder_path):
        console.print(f"  [{label}]  [yellow]not found[/yellow]")
        return s

    try:
        entries = list(os.scandir(folder_path))
    except Exception:
        console.print(f"  [{label}]  [yellow]cannot list directory[/yellow]")
        return s

    for entry in entries:
        try:
            if entry.is_symlink() or entry.is_file():
                sz = entry.stat().st_size if entry.is_file() else 0
                os.remove(entry.path)
                s.deleted += 1
                s.bytes_freed += sz
            elif entry.is_dir():
                sz = calc_size(entry.path)
                shutil.rmtree(entry.path)
                s.deleted += 1
                s.bytes_freed += sz
        except Exception:
            s.skipped += 1

    _result(label, s)
    return s


def delete_matching(folder_path: str, pattern: str, label: str) -> CleanStats:
    s = CleanStats()
    if not folder_path or not os.path.isdir(folder_path):
        console.print(f"  [{label}]  [yellow]not found[/yellow]")
        return s
    for f in glob.glob(os.path.join(folder_path, pattern)):
        try:
            sz = os.path.getsize(f)
            os.remove(f)
            s.deleted += 1
            s.bytes_freed += sz
        except (PermissionError, OSError):
            s.skipped += 1
    _result(label, s)
    return s


def delete_file(path: str, label: str) -> CleanStats:
    s = CleanStats()
    if path and os.path.isfile(path):
        try:
            sz = os.path.getsize(path)
            os.remove(path)
            s.deleted = 1
            s.bytes_freed = sz
            console.print(f"  [{label}]  [green]OK[/green] deleted [bold]{fmt_size(sz)}[/bold]")
        except (PermissionError, OSError):
            s.skipped = 1
            console.print(f"  [{label}]  [yellow]![/yellow] locked, skipped")
    return s


def _chromium_cache_dirs():
    """Yield (label, path) for every profile cache folder found across Chromium browsers."""
    for name, rel_path in CHROMIUM_BROWSERS:
        base = os.path.join(LOCAL, rel_path)
        for cache_dir in glob.glob(os.path.join(base, "*", "Cache")):
            yield (f"{name} Cache", cache_dir)
        for cache_dir in glob.glob(os.path.join(base, "*", "Code Cache")):
            yield (f"{name} Code Cache", cache_dir)


def _firefox_cache_dirs():
    """Yield (label, path) for every Firefox profile cache2 folder found."""
    for cache_dir in glob.glob(os.path.join(FIREFOX_PROFILES, "*", "cache2")):
        yield ("Firefox Cache", cache_dir)


def empty_recycle_bin():
    SHERB_NOCONFIRMATION = 0x1
    SHERB_NOPROGRESSUI = 0x2
    SHERB_NOSOUND = 0x4
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    console.print("  [Recycle Bin]  [green]OK[/green] emptied")


# ---------------------------------------------------------------------------
# category implementations
# ---------------------------------------------------------------------------

def clear_basics() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Basics ==[/bold cyan]")

    for label, path in [
        ("User Temp", TEMP),
        ("Windows Temp", r"C:\Windows\Temp"),
        ("Prefetch", r"C:\Windows\Prefetch"),
    ]:
        total += clear_folder(path, label)

    for label, path in _chromium_cache_dirs():
        total += clear_folder(path, label)

    for label, path in _firefox_cache_dirs():
        total += clear_folder(path, label)

    empty_recycle_bin()
    return total


def clear_shaders_thumbnails() -> CleanStats:
    total = CleanStats()
    console.print(f"\n[bold cyan]== Shaders & Thumbnails ==[/bold cyan]")

    for label, path in [
        ("DirectX Shader Cache", os.path.join(LOCAL, "D3DSCache")),
        ("NVIDIA DX Cache", os.path.join(LOCAL, r"NVIDIA\DXCache")),
        ("NVIDIA GL Cache", os.path.join(LOCAL, r"NVIDIA\GLCache")),
    ]:
        total += clear_folder(path, label)

    total += delete_matching(
        os.path.join(LOCAL, r"Microsoft\Windows\Explorer"),
        "thumbcache_*.db",
        "Thumbnail Cache",
    )
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

    for label, path in [
        ("Setup Logs", r"C:\Windows\Panther"),
        ("Servicing Logs", r"C:\Windows\Logs\CBS"),
        ("Minidumps", r"C:\Windows\Minidump"),
        ("Error Reporting", r"C:\ProgramData\Microsoft\Windows\WER"),
        ("Crash Dumps", os.path.join(LOCAL, "CrashDumps")),
    ]:
        total += clear_folder(path, label)

    total += delete_file(r"C:\Windows\MEMORY.DMP", "MEMORY.DMP")

    win_old = r"C:\Windows.old"
    if os.path.isdir(win_old):
        console.print(f"\n  [bold yellow]! Windows.old detected[/bold yellow] (can't roll back after deletion)")
        if Confirm.ask("  Delete Windows.old?", default=False):
            with console.status("[yellow]Removing Windows.old...[/yellow]", spinner="dots"):
                run_quiet(["takeown", "/f", win_old, "/r", "/d", "y"])
                run_quiet(["icacls", win_old, "/grant", "Administrators:F", "/t"])
                try:
                    sz = calc_size(win_old)
                    shutil.rmtree(win_old)
                    total.deleted += 1
                    total.bytes_freed += sz
                    console.print(f"  [Windows.old]  [green]OK[/green] deleted [bold]{fmt_size(sz)}[/bold]")
                except (PermissionError, OSError):
                    total.skipped += 1
                    console.print(f"  [Windows.old]  [yellow]![/yellow] could not be fully removed")
        else:
            console.print("  [Windows.old]  [dim]skipped[/dim]")

    return total


# ---------------------------------------------------------------------------
# scan / analyze
# ---------------------------------------------------------------------------

def scan_all() -> dict:
    locations = {}

    for label, path in [
        ("User Temp", TEMP),
        ("Windows Temp", r"C:\Windows\Temp"),
        ("Prefetch", r"C:\Windows\Prefetch"),
    ]:
        locations[label] = calc_size(path)

    for label, path in _chromium_cache_dirs():
        locations[label] = locations.get(label, 0) + calc_size(path)

    for label, path in _firefox_cache_dirs():
        locations[label] = locations.get(label, 0) + calc_size(path)

    for label, path in [
        ("DirectX Shader", os.path.join(LOCAL, "D3DSCache")),
        ("NVIDIA DX", os.path.join(LOCAL, r"NVIDIA\DXCache")),
        ("NVIDIA GL", os.path.join(LOCAL, r"NVIDIA\GLCache")),
    ]:
        locations[label] = calc_size(path)

    locations["Thumbnails"] = sum(
        calc_size(f) for f in glob.glob(
            os.path.join(LOCAL, r"Microsoft\Windows\Explorer", "thumbcache_*.db")
        )
    )

    for label, path in [
        ("WU Download", r"C:\Windows\SoftwareDistribution\Download"),
        ("Delivery Opt.", r"C:\Windows\SoftwareDistribution\DeliveryOptimization"),
        ("Setup Logs", r"C:\Windows\Panther"),
        ("CBS Logs", r"C:\Windows\Logs\CBS"),
        ("Minidumps", r"C:\Windows\Minidump"),
        ("Error Reporting", r"C:\ProgramData\Microsoft\Windows\WER"),
        ("Crash Dumps", os.path.join(LOCAL, "CrashDumps")),
    ]:
        locations[label] = calc_size(path)

    mem = calc_size(r"C:\Windows\MEMORY.DMP")
    if mem:
        locations["MEMORY.DMP"] = mem
    wo = calc_size(r"C:\Windows.old")
    if wo:
        locations["Windows.old"] = wo

    return {k: v for k, v in locations.items() if v > 0}


def show_analysis(data: dict):
    total = sum(data.values())
    table = Table(box=box.ASCII, title="[bold]Space Analysis[/bold]", title_justify="center")
    table.add_column("Location", style="cyan")
    table.add_column("Size", justify="right")

    for label, size in sorted(data.items(), key=lambda x: x[1], reverse=True):
        table.add_row(label, fmt_size(size))

    table.add_row("", "", style="dim")
    table.add_row("[bold]Total reclaimable[/bold]", f"[bold]{fmt_size(total)}[/bold]", style="bold")
    console.print()
    console.print(table)
    console.print()

    if total == 0:
        console.print("[yellow]No significant temp data found.[/yellow]")
    else:
        console.print(f"[dim]Est. reclaimable: ~{fmt_size(total)} (some items may be locked)[/dim]")


# ---------------------------------------------------------------------------
# results & menu
# ---------------------------------------------------------------------------

def show_results(pre_scan=None):
    table = Table(box=box.ASCII, title="[bold]Cleanup Complete[/bold]", title_justify="center")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Items deleted", str(stats.deleted))
    table.add_row("Items skipped (locked)", str(stats.skipped))
    table.add_row("Space freed", fmt_size(stats.bytes_freed))

    if pre_scan:
        pre_total = sum(pre_scan.values())
        remaining = max(0, pre_total - stats.bytes_freed)
        table.add_row("Est. remaining", fmt_size(remaining), style="dim")

    console.print()
    console.print(table)
    console.print()


def show_menu() -> str:
    os.system("cls")
    console.clear()

    title = Panel(
        "[bold cyan]Windows Temp / Cache Cleaner[/bold cyan]\n"
        "[dim]Professional Edition[/dim]",
        box=box.ASCII,
        style="bold white",
        subtitle="[dim]v2.0[/dim]",
    )
    console.print(title)

    menu_table = Table.grid(padding=(0, 2))
    menu_table.add_column(style="bold cyan", justify="right")
    menu_table.add_column(style="white")

    menu_table.add_row(" 1", "Quick Clean        - Temp, browser caches, Recycle Bin")
    menu_table.add_row(" 2", "Deep Clean         - Everything (full system sweep)")
    menu_table.add_row(" 3", "Shaders & Tiles    - GPU shaders + thumbnail cache")
    menu_table.add_row(" 4", "Windows Files      - Logs, dumps, SoftwareDistribution, .old")
    menu_table.add_row(" 5", "Analyze Space      - Scan only, see what's taking room")
    menu_table.add_row("", "")
    menu_table.add_row(" Q", "[bold red]Quit[/bold red]")

    console.print(Panel(menu_table, box=box.ASCII, title="[bold]Menu[/bold]"))
    console.print()

    while True:
        choice = Prompt.ask("[bold]Choice[/bold]").strip().lower()
        if choice in ("1", "2", "3", "4", "5", "q"):
            return choice
        console.print("[red]Invalid choice. Enter 1-5 or Q.[/red]")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def press_enter(label="continue"):
    """Reliable pause that works in all terminals. Fallback to plain input if rich fails."""
    try:
        Prompt.ask(f"[dim]Press Enter to {label}[/dim]", default="")
    except Exception:
        input(f"Press Enter to {label}...")


def main():
    global stats
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

            stats.reset()
            pre_scan = None

            if choice == "5":
                try:
                    with console.status("[green]Scanning temp locations...[/green]", spinner="dots"):
                        data = scan_all()
                    show_analysis(data)
                except Exception as exc:
                    console.print(f"[red]Scan failed: {exc}[/red]")
                press_enter("continue")
                continue

            try:
                with console.status("[green]Pre-scanning...[/green]", spinner="dots"):
                    pre_scan = scan_all()
            except Exception as exc:
                console.print(f"[red]Pre-scan failed (continuing anyway): {exc}[/red]")

            try:
                if choice == "1":
                    stats += clear_basics()
                elif choice == "2":
                    stats += clear_basics()
                    stats += clear_shaders_thumbnails()
                    stats += clear_windows_files()
                elif choice == "3":
                    stats += clear_shaders_thumbnails()
                elif choice == "4":
                    stats += clear_windows_files()
            except Exception as exc:
                console.print(f"\n[bold red]Error during cleaning:[/bold red] {exc}")
                traceback.print_exc()

            show_results(pre_scan)
            press_enter("return to menu")

    except Exception:
        console.print("[bold red]Unexpected error - see log for details[/bold red]")
        with open(ERROR_LOG, "w") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        press_enter("exit")


if __name__ == "__main__":
    main()
