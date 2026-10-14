"""Global mouse tracking.

Primary backend is `pynput`, which installs a low-level Windows mouse hook and
so sees movement, wheel and clicks across every application. If it is missing or
the hook cannot be installed, we fall back to polling the cursor position with
`GetCursorPos`, which still measures distance (wheel and clicks are unavailable
that way).

No keyboard hook is installed — only mouse events — so nothing here records what
you type.
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time

IS_WINDOWS = sys.platform.startswith("win")

# Anything longer than this in a single event is a cursor warp (a game
# recentring the pointer, a remote-desktop jump), not a real hand movement.
TELEPORT_PX = 4000.0


class Tracker:
    """Feeds a Store from global mouse events."""

    def __init__(self, store, teleport_px: float = TELEPORT_PX):
        self.store = store
        self.teleport_px = float(teleport_px)
        self.backend = "none"
        self.error = None
        self._last = None
        self._listener = None
        self._poll_stop = threading.Event()
        self._poll_thread = None

    # ------------------------------------------------------------------ #
    def start(self) -> str:
        if self._start_pynput():
            self.backend = "pynput (global hook)"
        elif self._start_polling():
            self.backend = "cursor polling (movement only)"
        else:
            self.backend = "none"
        return self.backend

    def stop(self) -> None:
        self._poll_stop.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # pynput backend
    # ------------------------------------------------------------------ #
    def _start_pynput(self) -> bool:
        try:
            from pynput import mouse
        except Exception as exc:
            self.error = f"pynput unavailable: {exc}"
            return False
        try:
            self._listener = mouse.Listener(
                on_move=self._on_move,
                on_scroll=self._on_scroll,
                on_click=self._on_click,
            )
            self._listener.daemon = True
            self._listener.start()
            # Give the hook a moment to fail loudly if it is going to.
            self._listener.wait()
            if not self._listener.running:
                self.error = "pynput listener did not start"
                return False
            return True
        except Exception as exc:
            self.error = f"pynput hook failed: {exc}"
            self._listener = None
            return False

    def _on_move(self, x, y):
        prev, self._last = self._last, (x, y)
        if prev is None:
            return
        d = math.hypot(x - prev[0], y - prev[1])
        if 0 < d < self.teleport_px:
            self.store.add_distance(d)

    def _on_scroll(self, x, y, dx, dy):
        self.store.add_scroll(int(dy))
        if dx:
            # Horizontal wheel / tilt counts as scrolling too.
            self.store.add_scroll(int(abs(dx)))

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self.store.add_click(getattr(button, "name", "middle"))

    # ------------------------------------------------------------------ #
    # polling fallback
    # ------------------------------------------------------------------ #
    def _start_polling(self) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            ctypes.windll.user32.GetCursorPos
        except Exception:
            return False
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="cursor-poll", daemon=True)
        self._poll_thread.start()
        return True

    def _poll_loop(self):
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        get = ctypes.windll.user32.GetCursorPos
        while not self._poll_stop.wait(1 / 60):
            if not get(ctypes.byref(pt)):
                continue
            self._on_move(pt.x, pt.y)
