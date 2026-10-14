"""JSON settings, stored next to the app."""
from __future__ import annotations

import json
import os
from pathlib import Path

# Bump when DEFAULTS["chips"] gains an entry, so an existing config.json picks
# up the new chips instead of pinning the list it was first written with.
SCHEMA = 3

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_DATA_PATH = APP_DIR / "data" / "odometer.json"

ALL_CHIPS = [
    "dist_today", "dist_session", "dist_total",
    "scroll_today", "scroll_session", "scroll_total",
    "roll_today", "roll_session", "roll_total",
    "page_today", "page_session", "page_total",
    "clicks_today", "clicks_session", "clicks_total",
    "active_today",
]

DEFAULTS = {
    "schema": SCHEMA,
    "mouse_dpi": 800,
    "pointer_scale": 1.0,
    "wheel_diameter_mm": 20.0,
    "wheel_detents": 24,
    "screen_dpi": 96,
    "lines_per_notch": 3,
    "px_per_line": 20.0,
    "refresh": 1.0,
    "autosave": 30.0,
    "teleport_px": 4000,
    "opacity": 0.93,
    "font_size": 11,
    "window_layer": "top",   # "top" | "normal" | "bottom"
    "always_on_top": True,   # legacy; migrated into window_layer
    "click_through": False,
    "show_sparklines": True,
    "history": 60,
    "data_path": "",
    "chips": ["dist_today", "dist_total", "scroll_today", "scroll_total",
              "roll_total", "page_total", "clicks_today"],
    "position": {"x": None, "y": None},
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    stored_schema = SCHEMA
    user_keys: set[str] = set()
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                stored_schema = int(user.get("schema", 1))
                user_keys = set(user)
                cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except Exception:
            pass

    cfg["chips"] = [c for c in cfg.get("chips", []) if c in ALL_CHIPS] or \
        list(DEFAULTS["chips"])

    # Older configs only had the on/off flag.
    if "window_layer" not in user_keys:
        cfg["window_layer"] = "top" if cfg.get("always_on_top", True) else "normal"
    if cfg["window_layer"] not in ("top", "normal", "bottom"):
        cfg["window_layer"] = "top"

    if stored_schema < SCHEMA:
        cfg["chips"] = _migrate_chips(cfg["chips"])
        cfg["schema"] = SCHEMA
        save(cfg)
    return cfg


def _migrate_chips(chips: list[str]) -> list[str]:
    """Add chips that are new in this version, keeping the user's own order.

    A saved chips list would otherwise pin the app to whatever metrics existed
    when config.json was first written.
    """
    missing = [c for c in DEFAULTS["chips"] if c not in chips]
    if not missing:
        return chips
    merged = list(chips)
    for c in missing:
        # Slot each new chip where it sits in the canonical order.
        target = ALL_CHIPS.index(c)
        pos = len(merged)
        for i, existing in enumerate(merged):
            if ALL_CHIPS.index(existing) > target:
                pos = i
                break
        merged.insert(pos, c)
    return merged


def save(cfg: dict) -> None:
    try:
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass


def data_path(cfg: dict) -> Path:
    p = (cfg.get("data_path") or "").strip()
    return Path(p) if p else DEFAULT_DATA_PATH
