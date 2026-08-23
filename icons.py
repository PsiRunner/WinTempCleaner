"""
icons.py — Font Awesome icon loader for WinTempCleaner (CustomTkinter).

pip install "ctkfontawesome[images]"

Why this instead of pytablericons: pytablericons calls pygame internally to
rasterize its SVGs, and pygame has no prebuilt wheel yet for newer Python
releases, so pip tries to compile it from source and fails without SDL2 dev
tools. ctkfontawesome renders with bundled fonts + Pillow only — no pygame,
no Cairo, no GTK — so it installs cleanly on new Python versions too.

Icons are rendered once per (name, size, color) combo and cached, so calling
get_icon() repeatedly (e.g. inside a loop building nav buttons) is free.
"""

from functools import lru_cache

import customtkinter as ctk
from ctkfontawesome import icon_to_ctkimage, icon_to_pil


@lru_cache(maxsize=256)
def _raster(name, size, color):
    # Returns a raw PIL.Image (RGBA) — cached so repeated calls are free.
    return icon_to_pil(name, fill=color, scale_to_width=size)


def get_icon(name, size=18, color="#94949d"):
    """Return a CTkImage ready to pass to image= on any CTk widget."""
    img = _raster(name, size, color)
    return ctk.CTkImage(light_image=img, dark_image=img, size=img.size)


# --- one place to name every icon used in the app -------------------------
# (names verified against ctkfontawesome==0.8.0 / Font Awesome Free 6 set)
NAV_ICONS = {
    "quick":       "broom",
    "deep":        "droplet",
    "shaders":     "layer-group",
    "windows":     "windows",
    "apps":        "th-large",
    "dev":         "terminal",
    "extended":    "wand-magic-sparkles",
    "games":       "gamepad",
    "maintenance": "screwdriver-wrench",
    "analyze":     "chart-area",
}
CARD_ICONS = {
    "freed":   "database",
    "deleted": "trash",
    "locked":  "lock",
    "kept":    "clock",
}
MISC_ICONS = {
    "reports":    "file-lines",
    "updates":    "cloud-arrow-down",
    "start":      "play",
    "installers": "box-archive",
    "exclusions": "shield-halved",
    "spinner":    "arrows-rotate",   # used by the animated spinner below
}


class SpinningIcon(ctk.CTkLabel):
    """
    A small animated (rotating) icon for in-progress states — e.g. show it
    next to the Start button or log header while a clean/scan is running.

    usage:
        self._spinner = SpinningIcon(parent, size=16, color=ACCENT)
        self._spinner.pack(...)
        self._spinner.start()   # begins spinning
        ...
        self._spinner.stop()    # freezes it (call when the job finishes)
    """

    STEPS = 12          # frames per full rotation — 12 is smooth enough at small sizes
    INTERVAL_MS = 60    # ms between frames (~ full rotation every ~720ms)

    def __init__(self, master, size=16, color="#2dd4bf", **kwargs):
        super().__init__(master, text="", **kwargs)
        base = _raster(MISC_ICONS["spinner"], size, color)
        self._frames = [
            ctk.CTkImage(light_image=base.rotate(-360 * i / self.STEPS),
                         dark_image=base.rotate(-360 * i / self.STEPS),
                         size=base.size)
            for i in range(self.STEPS)
        ]
        self._i = 0
        self._running = False
        self.configure(image=self._frames[0])

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        self._i = (self._i + 1) % self.STEPS
        self.configure(image=self._frames[self._i])
        self.after(self.INTERVAL_MS, self._tick)
