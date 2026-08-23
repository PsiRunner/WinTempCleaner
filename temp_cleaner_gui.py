"""
WinTempCleaner — Minimalistic GUI (v3.0)

Front-end for temp_cleaner.py built with CustomTkinter.
Reuses all cleaning logic, reports and settings from the CLI module.
"""

import io
import os
import re
import sys
import glob
import json
import time
import ctypes
import threading
import collections
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import customtkinter as ctk
from tkinter import filedialog
from rich.console import Console

import temp_cleaner as tc
from icons import get_icon, SpinningIcon, NAV_ICONS, CARD_ICONS, MISC_ICONS

APP_NAME = "WinTempCleaner"
VERSION = tc.APP_VERSION

BG        = "#131316"
SURFACE   = "#1c1c20"
SURFACE2  = "#26262c"
BORDER    = "#2d2d34"
TEXT      = "#ececf1"
MUTED     = "#94949d"
ACCENT    = "#2dd4bf"
ACCENT_DK = "#0ea5a4"
ON_ACCENT = "#0b0b0c"
GREEN     = "#34d399"
AMBER     = "#fbbf24"
RED       = "#f87171"
RED_DK    = "#ef4444"

MODES = [
    ("quick",    "Quick Clean",     "Temp, browser caches, Recycle Bin",            "safe"),
    ("deep",     "Deep Clean",      "Everything safe — the full sweep",             "safe"),
    ("shaders",  "Shaders & Tiles", "GPU, thumbnail, icon & font caches",           "safe"),
    ("windows",  "Windows Files",   "Logs, dumps, Windows Update cache",            "safe"),
    ("apps",     "App Caches",      "Discord, Teams, Spotify, Slack, VSCode",       "safe"),
    ("dev",      "Dev Caches",      "npm, pip, NuGet, Gradle, Go, Cargo",           "safe"),
    ("games",    "Games & Launchers", "Steam client cache, crash dumps",           "safe"),
    ("extended", "Extended Clean",  "Game shaders, debug logs, junk sweep",         "caution"),
    ("maintenance", "System Maintenance", "WinSxS component cleanup (DISM)",       "caution"),
    ("analyze",  "Analyze Space",   "Scan only — see what is eating your disk",     "info"),
]
MODE_NAME = {k: n for k, n, _d, _t in MODES}
TAG_COLOR = {"safe": GREEN, "caution": AMBER, "info": MUTED}
TAG_TEXT  = {"safe": "SAFE", "caution": "CAUTION", "info": "SCAN"}

AGES = {"Off": 0, "1 day": 1, "3 days": 3, "7 days": 7, "30 days": 30}

REPO_PAGE = "https://github.com/PsiRunner/WinTempCleaner"
RELEASES_API = "https://api.github.com/repos/PsiRunner/WinTempCleaner/releases/latest"
API_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 300
DOWNLOAD_RETRIES = 3


def _version_tuple(s):
    nums = [int(n) for n in re.findall(r"\d+", s or "")][:5]
    return tuple(nums) if nums else (0,)


def is_newer_version(remote_tag, local_version=VERSION):
    a, b = _version_tuple(remote_tag), _version_tuple(local_version)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _gh_headers():
    return {"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/vnd.github+json"}


def fetch_latest_release(timeout=API_TIMEOUT):
    req = urllib.request.Request(RELEASES_API, headers=_gh_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {
        "tag": data.get("tag_name") or "",
        "title": data.get("name") or "",
        "notes": data.get("body") or "",
        "page": data.get("html_url") or REPO_PAGE,
        "assets": [
            {"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
             "size": a.get("size", 0)}
            for a in data.get("assets") or []
            if str(a.get("name", "")).lower().endswith(".exe")
        ],
    }


def pick_installer_asset(assets):
    exes = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    pref = [a for a in exes if "gui" in a["name"].lower()]
    pool = pref or exes
    return pool[0] if pool else None


def _download_once(url, dest, progress, timeout, chunk_size):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = resp.read(chunk_size)
            if not block:
                break
            f.write(block)
            done += len(block)
            if progress:
                progress(done, total)
    return done, time.time() - started


def download_to_file(url, dest, progress=None, timeout=DOWNLOAD_TIMEOUT,
                     chunk_size=65536, retries=DOWNLOAD_RETRIES):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return _download_once(url, dest, progress, timeout, chunk_size)
        except Exception as exc:
            last_exc = exc
            try:
                os.remove(dest)
            except OSError:
                pass
            if attempt < retries:
                time.sleep(min(2 ** attempt, 5))
    raise last_exc


def _deep_clean():
    total = tc.CleanStats()
    total += tc.clear_basics()
    total += tc.clear_shaders_thumbnails()
    total += tc.clear_windows_files()
    total += tc.clear_app_caches()
    total += tc.clear_dev_caches()
    total += tc.clear_game_caches()
    return total


RUNNERS = {
    "quick":   tc.clear_basics,
    "deep":    _deep_clean,
    "shaders": tc.clear_shaders_thumbnails,
    "windows": tc.clear_windows_files,
    "apps":    tc.clear_app_caches,
    "dev":     tc.clear_dev_caches,
    "extended": tc.clear_extended,
    "games":   tc.clear_game_caches,
    "maintenance": tc.clear_system_maintenance,
}

PREVIEW_NOTES = {
    "quick":    "+ Recycle Bin also gets emptied (not sized here)",
    "deep":     "+ Recycle Bin also gets emptied (not sized here)",
    "windows":  "+ Windows.old is asked at runtime (not sized here)",
    "extended": "+ junk-file sweep runs at runtime (not estimated)",
    "maintenance": "WinSxS isn't pre-scanned (slow) — space freed is measured "
                   "by free-disk-space delta after DISM runs",
}


def _mode_items(mode):
    if mode == "quick":
        return [
            ("User Temp", tc.TEMP, "core"),
            ("Windows Temp", r"C:\Windows\Temp", "system"),
            ("Prefetch", r"C:\Windows\Prefetch", "core"),
        ] + tc._browser_cache_items() + tc._firefox_cache_items()
    if mode == "deep":
        return (_mode_items("quick") + _mode_items("shaders") +
                _mode_items("windows") + _mode_items("apps") + _mode_items("dev") +
                _mode_items("games"))
    if mode == "shaders":
        return tc._cache_tile_items() + [
            ("Thumbnail Cache", os.path.join(tc.LOCAL, r"Microsoft\Windows\Explorer",
                                             "thumbcache_*.db"), "caches"),
            ("Icon Cache", os.path.join(tc.LOCAL, r"Microsoft\Windows\Explorer",
                                        "iconcache_*.db"), "caches"),
            ("IconCache.db", os.path.join(tc.LOCAL, "IconCache.db"), "caches"),
            ("Legacy WebCache", os.path.join(tc.LOCAL, r"Microsoft\Windows\WebCache",
                                             "WebCacheV01.dat"), "caches"),
        ]
    if mode == "windows":
        return [
            ("WU Download", r"C:\Windows\SoftwareDistribution\Download", "system"),
            ("Delivery Opt.", r"C:\Windows\SoftwareDistribution\DeliveryOptimization", "system"),
        ] + tc._system_items() + [("MEMORY.DMP", r"C:\Windows\MEMORY.DMP", "system")]
    if mode == "apps":
        return tc._app_cache_items()
    if mode == "dev":
        return tc._dev_cache_items()
    if mode == "extended":
        return tc._extended_items()
    if mode == "games":
        return tc._game_cache_items()
    if mode == "maintenance":
        return []   # WinSxS isn't pre-scanned — see PREVIEW_NOTES
    return []


def _scan_items(items):
    expanded = []
    groups = {}
    for label, path, g in items:
        groups.setdefault(label, g)
        if any(ch in path for ch in "*?["):
            for p in glob.glob(path):
                expanded.append((label, p))
        else:
            expanded.append((label, path))
    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(tc.calc_size, p): label for label, p in expanded}
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                sz = fut.result()
            except Exception:
                sz = 0
            results[label] = results.get(label, 0) + sz
    return {k: v for k, v in results.items() if v > 0}, groups


def _bar_row(label, size, total, width=26):
    lab = label if len(label) <= width else label[:width - 1] + "…"
    if not total:
        return f"  {lab:<26}{tc.fmt_size(size):>10}"
    filled = max(1, round(width * size / total))
    bar = "█" * filled + "·" * (width - filled)
    return f"  {lab:<26}{tc.fmt_size(size):>10}  {bar}  {100 * size / total:4.1f}%"


class _Buffer(io.StringIO):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def write(self, s):
        with self._lock:
            return super().write(s)

    def snapshot(self):
        with self._lock:
            return super().getvalue()

    def reset(self):
        with self._lock:
            self.seek(0)
            self.truncate(0)

    def maybe_reset(self, limit=150_000):
        with self._lock:
            if self.tell() > limit:
                self.seek(0)
                self.truncate(0)
                return True
            return False


_buf = _Buffer()
tc.console = Console(file=_buf, width=96, highlight=False)

_answers = collections.deque()


class _Confirm:
    @staticmethod
    def ask(*_a, **_k):
        return _answers.popleft() if _answers else False


tc.Confirm = _Confirm


class SplashScreen(ctk.CTkToplevel):
    """
    Minimal on-brand splash shown while App() builds its UI. Frameless,
    centered, matches the app's own dark/teal palette exactly (same BG/
    SURFACE2/BORDER/ACCENT constants — not a separate design).

    usage:
        splash = SplashScreen(self)
        splash.set_status("Building interface…", 0.4)
        ... do real init work ...
        splash.close()
    """

    WIDTH, HEIGHT = 440, 260
    MIN_STEP_MS = 120   # floor per status update so progress is perceptible,
                         # not a hard delay — real work exceeding this just runs

    def __init__(self, master):
        super().__init__(master)
        # Hide via alpha, NOT overrideredirect/withdraw — setting overrideredirect
        # synchronously on a brand-new Toplevel is a known cause of blank/black
        # renders on Windows (the window gets mapped mid-configure). Same for
        # withdraw()/deiconify() on a CTk root — see TomSchimansky/CustomTkinter#59.
        self.attributes("-alpha", 0)
        self.configure(fg_color=BORDER)  # 1px "border" via padding trick below

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - self.WIDTH) // 2
        y = (sh - self.HEIGHT) // 2
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        card = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        ring = ctk.CTkFrame(card, width=56, height=56, corner_radius=28,
                            fg_color="transparent", border_width=2, border_color=ACCENT)
        ring.pack(pady=(42, 16))
        ring.pack_propagate(False)
        ctk.CTkLabel(ring, text="",
                    image=get_icon(NAV_ICONS["quick"], size=24, color=ACCENT)).pack(expand=True)

        word = ctk.CTkFrame(card, fg_color="transparent")
        word.pack()
        ctk.CTkLabel(word, text="WinTemp", font=("Segoe UI Semibold", 21),
                    text_color=TEXT).pack(side="left")
        ctk.CTkLabel(word, text="Cleaner", font=("Segoe UI Semibold", 21),
                    text_color=ACCENT).pack(side="left")

        ctk.CTkLabel(card, text=f"v{VERSION}", font=("Segoe UI", 11),
                    text_color=MUTED).pack(pady=(2, 0))

        self._bar = ctk.CTkProgressBar(card, height=3, corner_radius=2,
                                       progress_color=ACCENT, fg_color=SURFACE2)
        self._bar.pack(fill="x", padx=32, pady=(32, 0))
        self._bar.set(0)

        self._status = ctk.CTkLabel(card, text="Starting…", font=("Segoe UI", 11),
                                    text_color=MUTED)
        self._status.pack(pady=(10, 0))

        self.update_idletasks()
        self.update()

        # Frameless + on-top are applied only after the window is fully built
        # and positioned, then we fade it in. This ordering is what avoids the
        # Windows blank-render race mentioned above.
        if sys.platform.startswith("win"):
            self.after(30, lambda: self.overrideredirect(True))
        else:
            self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.after(60, lambda: self.attributes("-alpha", 1))
        self.update()

    def set_status(self, text, progress):
        self._status.configure(text=text)
        self._bar.set(progress)
        self.update()
        time.sleep(self.MIN_STEP_MS / 1000)

    def close(self):
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(APP_NAME)
        self._icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Icon.ico")
        if os.path.isfile(self._icon):
            try:
                self.iconbitmap(self._icon)
            except Exception:
                pass
        self.geometry("1020x780")
        self.minsize(880, 720)
        self.configure(fg_color=BG)

        self.attributes("-alpha", 0)   # hide without withdraw() — see SplashScreen note
        splash = SplashScreen(self)

        self._mode = "quick"
        self._busy = False
        self._updating = False
        self._pulsing = False
        self._phase = 0.0
        self._pos = 0
        self._reclaim = 0
        self._preview_seq = 0
        self._btns = {}
        self._card_caps = {}

        splash.set_status("Building interface…", 0.35)
        self._build_sidebar()
        self._build_main()
        splash.set_status("Restoring last session…", 0.6)
        self._select("quick")
        self._poll_log()
        splash.set_status("Checking installers…", 0.8)
        self._cleanup_stale_installers()
        splash.set_status("Checking permissions…", 0.95)
        self._check_admin()

        splash.set_status("Ready", 1.0)
        splash.close()
        self.attributes("-alpha", 1)
        self.lift()
        self.focus_force()
        # Windows' focus-stealing prevention often keeps a freshly-elevated
        # process's window behind everything else even after focus_force().
        # A brief topmost pulse forces it in front regardless.
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))

    # ------------------------------------------------------------------ UI

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=234, corner_radius=0, fg_color=SURFACE)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18, 8))
        ctk.CTkLabel(head, text=APP_NAME, font=("Segoe UI Semibold", 17),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text=f"v{VERSION} · minimal GUI", font=("Segoe UI", 11),
                     text_color=MUTED).pack(anchor="w")

        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="x", padx=12, pady=(6, 0))
        for key, name, _desc, _tag in MODES:
            b = ctk.CTkButton(nav, text=name, anchor="w", height=34, corner_radius=8,
                              image=get_icon(NAV_ICONS[key], size=17, color=MUTED),
                              compound="left", font=("Segoe UI", 13), fg_color="transparent",
                              text_color=MUTED, hover_color=SURFACE2,
                              command=lambda k=key: self._select(k))
            b.pack(fill="x", pady=1)
            self._btns[key] = b

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=(10, 10))

        opts = ctk.CTkFrame(sb, fg_color="transparent")
        opts.pack(fill="x", padx=20)
        ctk.CTkLabel(opts, text="AGE LIMIT", font=("Segoe UI", 10, "bold"),
                     text_color=MUTED, anchor="w").pack(fill="x")
        self._age = ctk.CTkOptionMenu(
            opts, values=list(AGES), command=self._set_age, height=28,
            fg_color=SURFACE2, button_color=SURFACE2, button_hover_color=BORDER,
            text_color=TEXT, font=("Segoe UI", 12), dropdown_fg_color=SURFACE2,
            dropdown_hover_color=BORDER, dropdown_text_color=TEXT, anchor="w")
        self._age.set(self._age_label())
        self._age.pack(fill="x", pady=(4, 12))

        self._sw_bin = ctk.CTkSwitch(opts, text="Recycle Bin (undoable)",
                                     command=lambda: self._toggle("use_recycle_bin", self._sw_bin),
                                     progress_color=ACCENT, font=("Segoe UI", 12),
                                     text_color=TEXT)
        if tc.settings.use_recycle_bin:
            self._sw_bin.select()
        self._sw_bin.pack(anchor="w", pady=(0, 8))

        self._sw_rep = ctk.CTkSwitch(opts, text="Save reports",
                                     command=lambda: self._toggle("save_reports", self._sw_rep),
                                     progress_color=ACCENT, font=("Segoe UI", 12),
                                     text_color=TEXT)
        if tc.settings.save_reports:
            self._sw_rep.select()
        self._sw_rep.pack(anchor="w")

        self._adm = ctk.CTkLabel(sb, text="", font=("Segoe UI", 11), text_color=MUTED)
        self._adm.pack(side="bottom", pady=(0, 12))

        rep = ctk.CTkButton(sb, text="Reports", anchor="w", height=32, corner_radius=8,
                            image=get_icon(MISC_ICONS["reports"], size=15, color=MUTED),
                            compound="left", font=("Segoe UI", 12), fg_color="transparent",
                            text_color=MUTED, hover_color=SURFACE2,
                            command=self._open_reports)
        rep.pack(side="bottom", fill="x", padx=12, pady=2)

        self._upd_btn = ctk.CTkButton(sb, text="Check for Updates", anchor="w", height=32,
                                      corner_radius=8,
                                      image=get_icon(MISC_ICONS["updates"], size=15, color=MUTED),
                                      compound="left", font=("Segoe UI", 12),
                                      fg_color="transparent", text_color=MUTED,
                                      hover_color=SURFACE2, command=self._check_updates)
        self._upd_btn.pack(side="bottom", fill="x", padx=12)

        # Installers + Exclusions: identical full-width rows packed straight
        # into the sidebar (an intermediate frame can end up clipping its
        # children — CTk height propagation quirk), with even 4px gaps.
        ctk.CTkButton(sb, text="Installers", anchor="w", height=32, corner_radius=8,
                      image=get_icon(MISC_ICONS["installers"], size=15, color=MUTED),
                      compound="left", font=("Segoe UI", 12), fg_color="transparent",
                      hover_color=SURFACE2, text_color=MUTED,
                      command=self._open_installers).pack(side="bottom", fill="x",
                                                          padx=12, pady=(2, 4))
        ctk.CTkButton(sb, text="Exclude", anchor="w", height=32, corner_radius=8,
                      image=get_icon(MISC_ICONS["exclusions"], size=15, color=MUTED),
                      compound="left", font=("Segoe UI", 12), fg_color="transparent",
                      hover_color=SURFACE2, text_color=MUTED,
                      command=self._open_exclusions).pack(side="bottom", fill="x",
                                                          padx=12, pady=(0, 4))

    def _build_main(self):
        m = ctk.CTkFrame(self, fg_color="transparent")
        m.pack(side="left", fill="both", expand=True)
        m.grid_columnconfigure(0, weight=1)
        m.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(m, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 0))
        self._title = ctk.CTkLabel(head, text="", font=("Segoe UI Semibold", 24),
                                   text_color=TEXT)
        self._title.pack(side="left")
        self._tag = ctk.CTkLabel(head, text="", font=("Segoe UI", 10, "bold"),
                                 fg_color=SURFACE2, corner_radius=6, width=70, height=22,
                                 text_color=GREEN)
        self._tag.pack(side="left", padx=(12, 0), pady=(9, 0))
        self._spinner = SpinningIcon(head, size=18, color=ACCENT)
        # not packed yet — shown only while a job is running (see _run/_done)

        self._start = ctk.CTkButton(head, text="Start", width=150, height=42, corner_radius=10,
                                    image=get_icon(MISC_ICONS["start"], size=14, color=ON_ACCENT),
                                    compound="left",
                                    font=("Segoe UI Semibold", 14), fg_color=ACCENT,
                                    hover_color=ACCENT_DK, text_color=ON_ACCENT,
                                    command=self._run)
        self._start.pack(side="right")

        self._desc = ctk.CTkLabel(m, text="", font=("Segoe UI", 12), text_color=MUTED,
                                  anchor="w")
        self._desc.grid(row=1, column=0, sticky="ew", padx=30, pady=(4, 0))

        cards = ctk.CTkFrame(m, fg_color="transparent")
        cards.grid(row=2, column=0, sticky="ew", padx=28, pady=(18, 14))
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1, uniform="card")
        self._cards = {}
        caps = [("freed", "space freed"), ("deleted", "items deleted"),
                ("locked", "locked / skipped"), ("kept", "kept (too new)")]
        for i, (key, cap) in enumerate(caps):
            f = ctk.CTkFrame(cards, fg_color=SURFACE, corner_radius=12,
                             border_width=1, border_color=BORDER)
            f.grid(row=0, column=i, sticky="ew",
                   padx=(0 if i == 0 else 10, 0 if i == 3 else 0))
            ctk.CTkLabel(f, text="", image=get_icon(CARD_ICONS[key], size=15, color=MUTED)
                        ).pack(pady=(12, 0))
            v = ctk.CTkLabel(f, text="—", font=("Segoe UI Semibold", 21), text_color=TEXT)
            v.pack(pady=(2, 1))
            cap_lbl = ctk.CTkLabel(f, text=cap, font=("Segoe UI", 11), text_color=MUTED)
            cap_lbl.pack(pady=(0, 12))
            self._cards[key] = v
            self._card_caps[key] = cap_lbl

        self._log = ctk.CTkTextbox(m, font=("Consolas", 12), fg_color=SURFACE,
                                   text_color=TEXT, corner_radius=12, border_width=1,
                                   border_color=BORDER, wrap="none")
        self._log.grid(row=3, column=0, sticky="nsew", padx=28, pady=(0, 12))
        self._log.configure(state="disabled")

        self._bar = ctk.CTkProgressBar(m, height=4, corner_radius=2,
                                       progress_color=ACCENT, fg_color=SURFACE2)
        self._bar.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 18))
        self._bar.set(0)

    # ------------------------------------------------------------- helpers

    def _log_line(self, s=""):
        self._log.configure(state="normal")
        self._log.insert("end", s + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        _buf.reset()
        self._pos = 0
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _poll_log(self):
        val = _buf.snapshot()
        if len(val) > self._pos:
            self._log.configure(state="normal")
            self._log.insert("end", val[self._pos:])
            self._log.see("end")
            self._log.configure(state="disabled")
            self._pos = len(val)
        if _buf.maybe_reset():
            self._pos = 0
        self.after(80, self._poll_log)

    def _pulse_loop(self):
        if not self._pulsing:
            return
        self._phase = (self._phase + 0.03) % 1.0
        p = self._phase
        self._bar.set(p if p <= 0.5 else 1 - p)
        self.after(30, self._pulse_loop)

    # ------------------------------------------------------------ previews

    def _start_preview(self, key):
        if self._busy or self._updating:
            return
        seq = self._preview_seq + 1
        self._preview_seq = seq
        name = MODE_NAME[key]
        note = PREVIEW_NOTES.get(key, "")
        self._clear_log()
        self._log_line(f"Estimating {name}…")
        if note:
            self._log_line(note)
        self._pulsing = True
        self._pulse_loop()

        def work():
            data, groups = {}, {}
            try:
                if key == "analyze":
                    data, groups = tc.scan_all()
                else:
                    data, groups = _scan_items(_mode_items(key))
            except Exception as exc:
                self.after(0, lambda: self._preview_done(key, seq, None, str(exc)))
                return
            self.after(0, lambda: self._preview_done(key, seq, (data, groups), ""))

        threading.Thread(target=work, daemon=True).start()

    def _preview_done(self, key, seq, payload, err):
        if seq != self._preview_seq or self._busy:
            return
        self._pulsing = False
        self._bar.set(0)
        name = MODE_NAME[key]
        if err:
            self._log_line(f"Estimate unavailable: {err}")
            return
        data, groups = payload
        total = sum(data.values())
        if not data:
            self._log_line("Nothing found to clean here — you're clean.")
            return
        tc.console.print()
        tc.console.print(f"Estimated freeable: ~{tc.fmt_size(total)}")
        tc.console.print()
        rows = sorted(data.items(), key=lambda x: -x[1])
        for g in ("core", "browser", "caches", "apps", "dev", "games", "system", "extended"):
            items = [(l, s) for l, s in rows if groups.get(l, "other") == g]
            if not items:
                continue
            tc.console.print(tc.GROUP_LABELS.get(g, g).upper())
            for label, size in items:
                tc.console.print(_bar_row(label, size, total))
            tc.console.print()
        self._cards["freed"].configure(text=f"~{tc.fmt_size(total)}")
        cap = self._card_caps["freed"]
        if key == "analyze":
            cap.configure(text="total reclaimable")
        else:
            cap.configure(text="estimated freeable")

    def _age_label(self):
        return next(k for k, v in AGES.items() if v == tc.settings.age_days)

    def _set_age(self, label):
        tc.settings.age_days = AGES[label]
        tc.save_settings(tc.settings)

    def _toggle(self, attr, sw):
        setattr(tc.settings, attr, bool(sw.get()))
        tc.save_settings(tc.settings)

    def _select(self, key):
        self._mode = key
        for k, b in self._btns.items():
            sel = k == key
            b.configure(fg_color=SURFACE2 if sel else "transparent",
                        text_color=ACCENT if sel else MUTED,
                        image=get_icon(NAV_ICONS[k], size=17, color=ACCENT if sel else MUTED))
        name, desc, tag = next((n, d, t) for k, n, d, t in MODES if k == key)
        self._title.configure(text=name)
        self._desc.configure(text=desc)
        self._tag.configure(text=TAG_TEXT[tag], text_color=TAG_COLOR[tag])
        self._start.configure(text="Run Analysis" if key == "analyze" else f"Start {name}")
        self._start_preview(key)

    def _ask(self, title, msg, ok="Continue", danger=False):
        dlg = ctk.CTkToplevel(self, fg_color=SURFACE)
        dlg.title(title)
        w, h = 440, 230
        dlg.resizable(False, False)
        dlg.transient(self)
        x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_y() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.attributes("-topmost", True)
        res = {"v": False}

        def _ok():
            res["v"] = True
            dlg.destroy()

        ctk.CTkLabel(dlg, text=title, font=("Segoe UI Semibold", 16),
                     text_color=TEXT).pack(pady=(26, 8))
        ctk.CTkLabel(dlg, text=msg, font=("Segoe UI", 12), text_color=MUTED,
                     wraplength=380, justify="left").pack(padx=30)
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=20)
        ctk.CTkButton(row, text=ok, width=120, command=_ok, corner_radius=8,
                      fg_color=RED if danger else ACCENT,
                      hover_color=RED_DK if danger else ACCENT_DK,
                      text_color=ON_ACCENT,
                      font=("Segoe UI Semibold", 12)).pack(side="right")
        ctk.CTkButton(row, text="Cancel", width=96, command=dlg.destroy, corner_radius=8,
                      fg_color=SURFACE2, hover_color=BORDER, text_color=TEXT,
                      font=("Segoe UI", 12)).pack(side="right", padx=(0, 10))
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.wait_window()
        return res["v"]

    # ------------------------------------------------------------ actions

    def _run(self):
        if self._busy:
            return
        mode = self._mode
        _answers.clear()
        if mode == "extended":
            if not self._ask(
                "Extended Clean",
                "This removes game shader caches, system debug logs and\n"
                "junk files (*.tmp, ~$*, *.bak, *-001.*).\n\n"
                "Games recompile shaders on next launch and diagnostics\n"
                "are lost. Continue?",
                ok="Run Extended", danger=True):
                return
            _answers.append(True)
        elif mode == "maintenance":
            if not self._ask(
                "System Maintenance",
                "Runs Windows' official WinSxS component cleanup (DISM).\n"
                "Only removes component versions Windows has already\n"
                "marked safe to discard — recent updates stay uninstallable.\n\n"
                "Requires admin and can take several minutes. Continue?",
                ok="Run Cleanup", danger=True):
                return
            _answers.append(True)
        elif mode in ("deep", "windows"):
            _answers.append(False)

        self._busy = True
        self._preview_seq += 1
        self._start.configure(state="disabled", text="Working…")
        self._spinner.pack(side="right", padx=(0, 10))
        self._spinner.start()
        for b in self._btns.values():
            b.configure(state="disabled")
        for c in self._cards.values():
            c.configure(text="—")
        cap = self._card_caps["freed"]
        if mode == "analyze":
            cap.configure(text="total reclaimable")
        else:
            cap.configure(text="space freed")
        self._clear_log()
        self._pulsing = True
        self._pulse_loop()
        threading.Thread(target=self._worker, args=(mode,), daemon=True).start()

    def _worker(self, mode):
        res = {"mode": mode, "ok": True, "err": "", "pre": None}
        t0 = time.time()
        tc.RUN_DETAIL.clear()
        try:
            if mode == "analyze":
                data, groups = tc.scan_all()
                self._render_analysis(data, groups)
                res["reclaim"] = sum(data.values())
            else:
                try:
                    res["pre"], _g = tc.scan_all()
                except Exception:
                    res["pre"] = None
                total = RUNNERS[mode]()
                tc.stats = total
                res.update(freed=total.bytes_freed, deleted=total.deleted,
                           locked=total.skipped, kept=total.skipped_new)
                tc.save_report(MODE_NAME[mode], time.time() - t0)
        except Exception as exc:
            res["ok"] = False
            res["err"] = str(exc)
        res["elapsed"] = time.time() - t0
        self.after(0, lambda: self._done(res))

    def _done(self, res):
        self._pulsing = False
        self._bar.set(0)
        self._busy = False
        self._spinner.stop()
        self._spinner.pack_forget()
        self._start.configure(state="normal", text="Run Analysis" if self._mode == "analyze"
                              else f"Start {MODE_NAME[self._mode]}")
        for b in self._btns.values():
            b.configure(state="normal")

        if not res["ok"]:
            self._log_line(f"Error: {res['err']}")
            return

        if res["mode"] == "analyze":
            self._cards["freed"].configure(text=tc.fmt_size(res.get("reclaim", 0)))
            self._log_line(f"Scan finished in {res['elapsed']:.1f}s")
        else:
            self._cards["freed"].configure(text=tc.fmt_size(res["freed"]))
            self._cards["deleted"].configure(text=f"{res['deleted']:,}")
            self._cards["locked"].configure(text=f"{res['locked']:,}")
            self._cards["kept"].configure(text=f"{res['kept']:,}")
            self._log_line(f"Done in {res['elapsed']:.1f}s — {tc.fmt_size(res['freed'])} freed")
            pre = res.get("pre")
            if pre:
                rem = max(0, sum(pre.values()) - res["freed"])
                self._log_line(f"Estimated remaining: {tc.fmt_size(rem)}")
            if tc.settings.use_recycle_bin and res["freed"]:
                self._log_line("Recycle Bin mode: empty the bin to reclaim the space.")
        self._log_line()

    def _render_analysis(self, data, groups):
        total = sum(data.values())
        if not data:
            tc.console.print()
            tc.console.print("No significant temp data found — you're clean.")
            return
        tc.console.print()
        tc.console.print(f"{len(data)} locations · {tc.fmt_size(total)} reclaimable")
        tc.console.print()
        rows = sorted(data.items(), key=lambda x: -x[1])
        for g in ("core", "browser", "caches", "apps", "dev", "games", "system", "extended"):
            items = [(l, s) for l, s in rows if groups.get(l, "other") == g]
            if not items:
                continue
            tc.console.print(tc.GROUP_LABELS.get(g, g).upper())
            for label, size in items:
                tc.console.print(_bar_row(label, size, total))
            tc.console.print()

    # ------------------------------------------------------------ updates

    def _cleanup_stale_installers(self):
        if getattr(sys, "frozen", False):
            for p in (sys.executable + ".old", sys.executable + ".update"):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    def _check_updates(self):
        if self._busy or self._updating:
            return
        self._upd_btn.configure(state="disabled", text="Checking…")
        self._log_line("Checking GitHub for a new release…")

        def work():
            rel, err = None, ""
            try:
                rel = fetch_latest_release()
            except urllib.error.HTTPError as exc:
                err = {404: "no published release on GitHub yet",
                       403: "GitHub rate limit — try again later"}.get(exc.code,
                                                                      f"HTTP {exc.code}")
            except Exception as exc:
                err = str(exc) or type(exc).__name__
            self.after(0, lambda: self._updates_checked(rel, err))

        threading.Thread(target=work, daemon=True).start()

    def _updates_checked(self, rel, err):
        self._upd_btn.configure(state="normal", text="Check for Updates")
        if rel is None:
            self._log_line(f"Update check failed: {err}")
            return
        if not is_newer_version(rel["tag"]):
            self._log_line(f"You're up to date — v{VERSION} (latest release {rel['tag']})")
            return
        asset = pick_installer_asset(rel["assets"])
        self._log_line(f"Update available: {rel['tag']}  (current v{VERSION})")
        if self._show_update_dialog(rel, asset) != "install":
            return
        if not asset:
            self._log_line("No installer attached to the release — opening the page.")
            try:
                os.startfile(rel["page"])
            except Exception:
                pass
        elif getattr(sys, "frozen", False):
            self._install_update(asset)
        else:
            self._log_line("Running from source — opening the releases page instead.")
            try:
                os.startfile(rel["page"])
            except Exception:
                pass

    def _show_update_dialog(self, rel, asset):
        dlg = ctk.CTkToplevel(self, fg_color=SURFACE)
        dlg.title("Update available")
        w, h = 480, 410
        dlg.resizable(False, False)
        dlg.transient(self)
        x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_y() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.attributes("-topmost", True)
        res = {"v": None}

        head = ctk.CTkFrame(dlg, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(22, 2))
        ctk.CTkLabel(head, text=f"{rel['tag']} is available",
                     font=("Segoe UI Semibold", 17), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text=f"you have v{VERSION}", font=("Segoe UI", 11),
                     text_color=MUTED).pack(side="right", pady=(6, 0))
        size = f"  ·  {asset['size'] / 1024 ** 2:.1f} MB installer" if asset else ""
        ctk.CTkLabel(dlg, text=(rel.get("title") or "New version") + size,
                     font=("Segoe UI", 11), text_color=MUTED,
                     anchor="w").pack(fill="x", padx=26)

        box = ctk.CTkTextbox(dlg, font=("Consolas", 11), fg_color=SURFACE2,
                             text_color=MUTED, corner_radius=10, wrap="word", height=180)
        box.pack(fill="both", expand=True, padx=24, pady=(12, 8))
        box.insert("1.0", (rel.get("notes") or "No release notes.").strip()[:4000])
        box.configure(state="disabled")

        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=(0, 18))

        def done(v):
            res["v"] = v
            dlg.destroy()

        ctk.CTkButton(row, text="Download & Install", width=150, corner_radius=8,
                      command=lambda: done("install"), fg_color=ACCENT,
                      hover_color=ACCENT_DK, text_color=ON_ACCENT,
                      font=("Segoe UI Semibold", 12)).pack(side="right")
        ctk.CTkButton(row, text="GitHub page", width=110, corner_radius=8,
                      command=lambda: done("page"), fg_color=SURFACE2,
                      hover_color=BORDER, text_color=TEXT,
                      font=("Segoe UI", 12)).pack(side="right", padx=(0, 8))
        ctk.CTkButton(row, text="Later", width=80, corner_radius=8,
                      command=lambda: done(None), fg_color="transparent",
                      hover_color=SURFACE2, text_color=MUTED,
                      border_width=1, border_color=BORDER,
                      font=("Segoe UI", 12)).pack(side="right")
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.wait_window()
        if res["v"] == "page":
            try:
                os.startfile(rel["page"])
            except Exception:
                pass
        return res["v"]

    def _install_update(self, asset):
        self._busy = True
        self._updating = True
        self._pulsing = False
        self._upd_btn.configure(state="disabled", text="Downloading…")
        self._start.configure(state="disabled")
        for b in self._btns.values():
            b.configure(state="disabled")
        exe = sys.executable
        tmp = exe + ".update"

        def prog(done, total):
            frac = min(1.0, done / float(total)) if total else 0.0
            self.after(0, lambda fr=frac: self._bar.set(fr))

        def work():
            ok, msg = True, ""
            try:
                _, secs = download_to_file(asset["url"], tmp, progress=prog)
                self.after(0, lambda s=secs: self._bar.set(1.0))
                self._log_line_safe(f"Downloaded {asset['name']} in {s:.1f}s — installing…")
            except Exception as exc:
                ok, msg = False, f"download failed ({exc})"
            if ok:
                try:
                    old = exe + ".old"
                    if os.path.exists(old):
                        os.remove(old)
                    os.rename(exe, old)
                    try:
                        os.replace(tmp, exe)
                    except OSError:
                        os.rename(old, exe)
                        raise
                except PermissionError:
                    ok, msg = False, ("cannot write next to the running exe — "
                                      "move the app to a writable folder and retry")
                except Exception as exc:
                    ok, msg = False, str(exc) or type(exc).__name__
            if not ok:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            self.after(0, lambda: self._update_finished(ok, msg, asset))

        threading.Thread(target=work, daemon=True).start()

    def _log_line_safe(self, s):
        self.after(0, lambda: self._log_line(s))

    def _update_finished(self, ok, msg, asset):
        self._busy = False
        self._updating = False
        self._bar.set(0)
        self._start.configure(state="normal", text="Run Analysis" if self._mode == "analyze"
                              else f"Start {MODE_NAME[self._mode]}")
        for b in self._btns.values():
            b.configure(state="normal")
        if not ok:
            self._upd_btn.configure(state="normal", text="Check for Updates")
            self._log_line(f"Update failed: {msg}")
            return
        self._log_line(f"Installed {asset['name']} — restarting…")
        try:
            subprocess.Popen([sys.executable], cwd=os.path.dirname(sys.executable),
                             close_fds=True)
        except Exception as exc:
            self._log_line(f"Restart failed: {exc} — start the app manually.")
            self._upd_btn.configure(state="normal", text="Check for Updates")
            return
        self.after(250, self.destroy)

    # ------------------------------------------------------------- admin

    def _check_admin(self):
        if tc.is_admin():
            self._adm.configure(text="●  Administrator", text_color=GREEN)
        else:
            self._adm.configure(text="●  No admin rights", text_color=AMBER)
            if "--selftest" not in sys.argv:
                self.after(700, self._offer_elevate)

    def _offer_elevate(self):
        if not self._ask(
            "Administrator rights",
            "System locations (Windows Temp, Prefetch, Update cache)\n"
            "need admin rights to clean.\n\nRelaunch as administrator?",
            ok="Elevate"):
            return
        try:
            if getattr(sys, "frozen", False):
                exe, args = sys.executable, ""
            else:
                exe, args = sys.executable, f'"{os.path.abspath(__file__)}"'
            h = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
        except Exception:
            h = 0
        if h > 32:
            self.after(150, self.destroy)

    # ----------------------------------------------------------- reports

    def _open_reports(self):
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title("Cleanup Reports")
        win.geometry("740x480")
        win.transient(self)
        win.grid_columnconfigure(1, weight=1)
        win.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(win, width=260, fg_color=SURFACE, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsw", padx=(16, 8), pady=16)

        box = ctk.CTkTextbox(win, font=("Consolas", 11), fg_color=SURFACE, text_color=TEXT,
                             corner_radius=12, border_width=1, border_color=BORDER,
                             wrap="none")
        box.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        box.configure(state="disabled")

        def show(path):
            try:
                with open(path, encoding="utf-8-sig") as f:
                    txt = json.dumps(json.load(f), indent=2, ensure_ascii=False)
            except Exception as exc:
                txt = f"Could not read report: {exc}"
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", txt)
            box.configure(state="disabled")

        files = sorted(glob.glob(os.path.join(tc.REPORTS_DIR, "*.json")), reverse=True)[:20]
        if not files:
            ctk.CTkLabel(left, text="No reports yet", font=("Segoe UI", 12),
                         text_color=MUTED).pack(padx=16, pady=16)
        for p in files:
            try:
                with open(p, encoding="utf-8-sig") as f:
                    d = json.load(f)
                cap = f"{d.get('mode', '?')} · {tc.fmt_size(d.get('totals', {}).get('bytes_freed', 0))}"
            except Exception:
                cap = ""
            ctk.CTkButton(left, text=f"{os.path.basename(p)}\n{cap}", anchor="w",
                          height=46, corner_radius=8,
                          fg_color="transparent", hover_color=SURFACE2,
                          text_color=TEXT, font=("Segoe UI", 11),
                          command=lambda pp=p: show(pp)).pack(fill="x", pady=1)
        if files:
            show(files[0])
        try:
            ctk.CTkButton(left, text="Open folder", height=30, corner_radius=8,
                          font=("Segoe UI", 11), fg_color=SURFACE2,
                          hover_color=BORDER, text_color=MUTED,
                          command=lambda: os.startfile(tc.REPORTS_DIR)).pack(fill="x", pady=(8, 0))
        except Exception:
            pass

    def _open_installers(self):
        """Read-only review of old installers in Downloads. Nothing here is
        ever deleted in bulk — each row has its own Delete button, and each
        delete asks to confirm first. This is deliberately manual: an
        installer sitting in Downloads might still be wanted."""
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title("Old Installers")
        win.geometry("560x460")
        win.transient(self)

        header = ctk.CTkFrame(win, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(header, text="Old Installers in Downloads",
                    font=("Segoe UI Semibold", 15), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(header, text="Informational only — review and delete one at a time. "
                                  "Older than 30 days.",
                    font=("Segoe UI", 11), text_color=MUTED, wraplength=500,
                    justify="left").pack(anchor="w", pady=(2, 0))

        body = ctk.CTkScrollableFrame(win, fg_color=SURFACE, corner_radius=12)
        body.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        def refresh():
            for w in body.winfo_children():
                w.destroy()
            items = tc.find_old_installers(30)
            if not items:
                ctk.CTkLabel(body, text="No installers older than 30 days found — clean.",
                            font=("Segoe UI", 12), text_color=MUTED).pack(padx=16, pady=16)
                return
            for it in items:
                row = ctk.CTkFrame(body, fg_color=SURFACE2, corner_radius=8)
                row.pack(fill="x", pady=3, padx=2)
                info = ctk.CTkFrame(row, fg_color="transparent")
                info.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=8)
                ctk.CTkLabel(info, text=it["name"], font=("Segoe UI", 12),
                            text_color=TEXT, anchor="w").pack(fill="x")
                ctk.CTkLabel(info, text=f"{tc.fmt_size(it['size'])} · {it['age_days']}d old",
                            font=("Segoe UI", 10), text_color=MUTED, anchor="w").pack(fill="x")

                def do_delete(path=it["path"], name=it["name"], size=it["size"]):
                    if self._ask("Delete Installer",
                                 f"Delete {name} ({tc.fmt_size(size)})?\n\n"
                                 "This is permanent unless Recycle Bin mode is on.",
                                 ok="Delete", danger=True):
                        tc.delete_file(path, name)
                        refresh()

                ctk.CTkButton(row, text="Delete", width=72, height=28, corner_radius=6,
                             fg_color=RED, hover_color=RED_DK, text_color=ON_ACCENT,
                             font=("Segoe UI", 11), command=do_delete
                             ).pack(side="right", padx=(6, 12), pady=8)

        refresh()

    def _open_exclusions(self):
        """Manage protected paths — anything listed here is skipped by every
        clean mode, unconditionally, regardless of age limit or mode."""
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title("Protected Paths")
        win.geometry("560x460")
        win.transient(self)

        header = ctk.CTkFrame(win, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(header, text="Protected Paths",
                    font=("Segoe UI Semibold", 15), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(header, text="Never touched by any clean mode — checked before every "
                                  "single deletion.",
                    font=("Segoe UI", 11), text_color=MUTED, wraplength=500,
                    justify="left").pack(anchor="w", pady=(2, 0))

        body = ctk.CTkScrollableFrame(win, fg_color=SURFACE, corner_radius=12)
        body.pack(fill="both", expand=True, padx=20, pady=(10, 10))

        def refresh():
            for w in body.winfo_children():
                w.destroy()
            if not tc.settings.excluded_paths:
                ctk.CTkLabel(body, text="No protected paths yet.",
                            font=("Segoe UI", 12), text_color=MUTED).pack(padx=16, pady=16)
                return
            for p in list(tc.settings.excluded_paths):
                row = ctk.CTkFrame(body, fg_color=SURFACE2, corner_radius=8)
                row.pack(fill="x", pady=3, padx=2)
                ctk.CTkLabel(row, text=p, font=("Segoe UI", 11), text_color=TEXT,
                            anchor="w", wraplength=380, justify="left"
                            ).pack(side="left", fill="x", expand=True, padx=(12, 6), pady=8)

                def do_remove(path=p):
                    tc.settings.excluded_paths = [
                        x for x in tc.settings.excluded_paths if tc._norm(x) != tc._norm(path)
                    ]
                    tc.save_settings(tc.settings)
                    refresh()

                ctk.CTkButton(row, text="Remove", width=76, height=28, corner_radius=6,
                             fg_color="transparent", hover_color=BORDER, text_color=MUTED,
                             font=("Segoe UI", 11), command=do_remove
                             ).pack(side="right", padx=(6, 12), pady=8)

        def add_folder():
            p = filedialog.askdirectory(title="Choose a folder to protect", parent=win)
            if p:
                _add_path(p)

        def add_file():
            p = filedialog.askopenfilename(title="Choose a file to protect", parent=win)
            if p:
                _add_path(p)

        def _add_path(p):
            existing = [tc._norm(x) for x in tc.settings.excluded_paths]
            if tc._norm(p) not in existing:
                tc.settings.excluded_paths.append(os.path.abspath(p))
                tc.save_settings(tc.settings)
                refresh()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkButton(btn_row, text="+ Add Folder", height=32, corner_radius=8,
                     fg_color=SURFACE2, hover_color=BORDER, text_color=TEXT,
                     font=("Segoe UI", 12), command=add_folder
                     ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(btn_row, text="+ Add File", height=32, corner_radius=8,
                     fg_color=SURFACE2, hover_color=BORDER, text_color=TEXT,
                     font=("Segoe UI", 12), command=add_file
                     ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        refresh()


def main():
    app = App()
    if "--selftest" in sys.argv:
        app.after(int(os.environ.get("WTC_SELFTEST_MS", "1600")), app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
