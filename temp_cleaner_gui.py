"""
WinTempCleaner — Minimalistic GUI (v3.0)

Front-end for temp_cleaner.py built with CustomTkinter.
Reuses all cleaning logic, reports and settings from the CLI module.
"""

import io
import os
import sys
import glob
import json
import time
import ctypes
import threading
import collections

import customtkinter as ctk
from rich.console import Console

import temp_cleaner as tc

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
    ("dev",      "Dev Caches",      "npm, pip, NuGet, Gradle, Go",                  "safe"),
    ("extended", "Extended Clean",  "Game shaders, debug logs, junk sweep",         "caution"),
    ("analyze",  "Analyze Space",   "Scan only — see what is eating your disk",     "info"),
]
MODE_NAME = {k: n for k, n, _d, _t in MODES}
TAG_COLOR = {"safe": GREEN, "caution": AMBER, "info": MUTED}
TAG_TEXT  = {"safe": "SAFE", "caution": "CAUTION", "info": "SCAN"}

AGES = {"Off": 0, "1 day": 1, "3 days": 3, "7 days": 7, "30 days": 30}


def _deep_clean():
    total = tc.CleanStats()
    total += tc.clear_basics()
    total += tc.clear_shaders_thumbnails()
    total += tc.clear_windows_files()
    total += tc.clear_app_caches()
    total += tc.clear_dev_caches()
    return total


RUNNERS = {
    "quick":   tc.clear_basics,
    "deep":    _deep_clean,
    "shaders": tc.clear_shaders_thumbnails,
    "windows": tc.clear_windows_files,
    "apps":    tc.clear_app_caches,
    "dev":     tc.clear_dev_caches,
    "extended": tc.clear_extended,
}


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
        self.geometry("1020x680")
        self.minsize(880, 620)
        self.configure(fg_color=BG)

        self._mode = "quick"
        self._busy = False
        self._pulsing = False
        self._phase = 0.0
        self._pos = 0
        self._reclaim = 0
        self._btns = {}

        self._build_sidebar()
        self._build_main()
        self._select("quick")
        self._welcome()
        self._poll_log()
        self._check_admin()

    # ------------------------------------------------------------------ UI

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=234, corner_radius=0, fg_color=SURFACE)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(22, 8))
        ctk.CTkLabel(head, text=APP_NAME, font=("Segoe UI Semibold", 17),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text=f"v{VERSION} · minimal GUI", font=("Segoe UI", 11),
                     text_color=MUTED).pack(anchor="w")

        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="x", padx=12, pady=(6, 0))
        for key, name, _desc, _tag in MODES:
            b = ctk.CTkButton(nav, text=name, anchor="w", height=34, corner_radius=8,
                              font=("Segoe UI", 13), fg_color="transparent",
                              text_color=MUTED, hover_color=SURFACE2,
                              command=lambda k=key: self._select(k))
            b.pack(fill="x", pady=1)
            self._btns[key] = b

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=(14, 12))

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
        self._adm.pack(side="bottom", pady=(0, 16))

        rep = ctk.CTkButton(sb, text="Reports", anchor="w", height=32, corner_radius=8,
                            font=("Segoe UI", 12), fg_color="transparent",
                            text_color=MUTED, hover_color=SURFACE2,
                            command=self._open_reports)
        rep.pack(side="bottom", fill="x", padx=12, pady=2)

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
        self._start = ctk.CTkButton(head, text="Start", width=150, height=42, corner_radius=10,
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
            v = ctk.CTkLabel(f, text="—", font=("Segoe UI Semibold", 21), text_color=TEXT)
            v.pack(pady=(13, 1))
            ctk.CTkLabel(f, text=cap, font=("Segoe UI", 11),
                         text_color=MUTED).pack(pady=(0, 12))
            self._cards[key] = v

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

    def _welcome(self):
        self._log_line("Pick a mode on the left, then press Start.")
        self._log_line("Everything runs in the background — the log updates live.")
        self._log_line()

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
                        text_color=ACCENT if sel else MUTED)
        name, desc, tag = next((n, d, t) for k, n, d, t in MODES if k == key)
        self._title.configure(text=name)
        self._desc.configure(text=desc)
        self._tag.configure(text=TAG_TEXT[tag], text_color=TAG_COLOR[tag])
        self._start.configure(text="Run Analysis" if key == "analyze" else f"Start {name}")

    def _ask(self, title, msg, ok="Continue", danger=False):
        dlg = ctk.CTkToplevel(self, fg_color=SURFACE, corner_radius=14)
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
        elif mode in ("deep", "windows"):
            _answers.append(False)

        self._busy = True
        self._start.configure(state="disabled", text="Working…")
        for b in self._btns.values():
            b.configure(state="disabled")
        for c in self._cards.values():
            c.configure(text="—")
        _buf.reset()
        self._pos = 0
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
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
        for g in ("core", "browser", "caches", "apps", "dev", "system", "extended"):
            items = [(l, s) for l, s in rows if groups.get(l, "other") == g]
            if not items:
                continue
            tc.console.print(tc.GROUP_LABELS.get(g, g).upper())
            for label, size in items:
                lab = label if len(label) <= 26 else label[:25] + "…"
                filled = max(1, round(26 * size / total))
                bar = "█" * filled + "·" * (26 - filled)
                tc.console.print(f"  {lab:<26}{tc.fmt_size(size):>10}  {bar}  {100 * size / total:4.1f}%")
            tc.console.print()

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
                with open(path, encoding="utf-8") as f:
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
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                cap = f"{d.get('mode', '?')} · {tc.fmt_size(d.get('totals', {}).get('bytes_freed', 0))}"
            except Exception:
                cap = ""
            ctk.CTkButton(left, text=f"{os.path.basename(p)}\n{cap}", anchor="w",
                          justify="left", height=46, corner_radius=8,
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


def main():
    app = App()
    if "--selftest" in sys.argv:
        app.after(1600, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
