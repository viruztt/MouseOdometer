"""Turning raw counters into numbers a person can read."""
from __future__ import annotations

import math

INCH_M = 0.0254

# Windows scrolls 3 lines per wheel notch by default; a text line is ~20 px.
LINES_PER_NOTCH = 3
PX_PER_LINE = 20.0

# Physical wheel: a typical mouse wheel is ~20 mm across with 24 detents per
# turn, so one notch rolls about 2.6 mm of rim past your finger.
WHEEL_DIAMETER_MM = 20.0
WHEEL_DETENTS = 24

# Nominal screen density, used to express scrolled document as a real length.
SCREEN_DPI = 96


def px_to_metres(px: float, mouse_dpi: int = 800, pointer_scale: float = 1.0) -> float:
    """Screen pixels -> how far the mouse actually moved on the desk.

    `pointer_scale` corrects for the Windows pointer-speed slider: at the default
    (6/11) it is 1.0; at higher settings the cursor covers more pixels per inch
    of desk, so the raw pixel count overstates real movement.
    """
    dpi = max(1, int(mouse_dpi))
    scale = pointer_scale if pointer_scale > 0 else 1.0
    return (px / scale) / dpi * INCH_M


def wheel_rolled_metres(notches: float, diameter_mm: float = WHEEL_DIAMETER_MM,
                        detents: int = WHEEL_DETENTS) -> float:
    """How far the wheel's rim has physically rolled under your finger."""
    detents = max(1, int(detents))
    circumference_m = math.pi * max(0.1, float(diameter_mm)) / 1000.0
    return notches * circumference_m / detents


def page_scrolled_metres(notches: float, screen_dpi: int = SCREEN_DPI,
                         lines_per_notch: int = LINES_PER_NOTCH,
                         px_per_line: float = PX_PER_LINE) -> float:
    """How much document has flowed past, as if the page were paper."""
    px = notches * max(1, int(lines_per_notch)) * max(1.0, float(px_per_line))
    return px / max(1, int(screen_dpi)) * INCH_M


def fmt_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.2f} km"
    if metres >= 10:
        return f"{metres:.0f} m"
    if metres >= 1:
        return f"{metres:.1f} m"
    return f"{metres * 100:.0f} cm"


def fmt_count(n: float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 10_000:
        return f"{n / 1000:.1f}k"
    return f"{n:,}"


def scroll_notches(row: dict) -> int:
    return int(row.get("su", 0)) + int(row.get("sd", 0))


def scroll_pixels(notches: float) -> float:
    return notches * LINES_PER_NOTCH * PX_PER_LINE


def scroll_screens(notches: float, screen_h: int = 1080) -> float:
    return scroll_pixels(notches) / max(1, screen_h)


def clicks_total(row: dict) -> int:
    return int(row.get("l", 0)) + int(row.get("r", 0)) + int(row.get("m", 0))


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"
