"""Persistent counters: lifetime totals plus a per-day log.

The file is small JSON, written atomically (temp file + os.replace) with one
rolling backup, so a power cut can cost at most the last autosave interval —
never the whole history.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

VERSION = 1
KEEP_DAYS = 1095  # three years of daily rows


def today_key() -> str:
    return date.today().isoformat()


def _blank_day() -> dict:
    return {"px": 0.0, "su": 0, "sd": 0, "l": 0, "r": 0, "m": 0, "sec": 0}


class Store:
    """Thread-safe counters. Every mutation also lands in today's row."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.dirty = False
        self._last_active_sec = 0

        # Counters accumulated since this process started.
        self.session = _blank_day()
        self.session["start"] = time.time()

        self.data = {
            "version": VERSION,
            "created": datetime.now().isoformat(timespec="seconds"),
            "totals": _blank_day(),
            "days": {},
        }
        self.load()

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        for candidate in (self.path, self.path.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict) or "totals" not in raw:
                continue
            with self.lock:
                self.data["created"] = raw.get("created", self.data["created"])
                totals = _blank_day()
                totals.update({k: v for k, v in (raw.get("totals") or {}).items()
                               if k in totals})
                self.data["totals"] = totals
                days = {}
                for k, v in (raw.get("days") or {}).items():
                    row = _blank_day()
                    row.update({kk: vv for kk, vv in (v or {}).items() if kk in row})
                    days[k] = row
                self.data["days"] = days
            return

    def save(self, force: bool = False) -> bool:
        with self.lock:
            if not (self.dirty or force):
                return False
            self._prune()
            payload = json.dumps(self.data, separators=(",", ":"))
            self.dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    os.replace(self.path, self.path.with_suffix(".json.bak"))
                except Exception:
                    pass
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except Exception:
            with self.lock:
                self.dirty = True
            return False

    def _prune(self) -> None:
        days = self.data["days"]
        if len(days) > KEEP_DAYS:
            for k in sorted(days)[:len(days) - KEEP_DAYS]:
                days.pop(k, None)

    # ------------------------------------------------------------------ #
    # mutation
    # ------------------------------------------------------------------ #
    def _day_row(self) -> dict:
        key = today_key()
        row = self.data["days"].get(key)
        if row is None:
            row = _blank_day()
            self.data["days"][key] = row
        return row

    def _bump(self, field: str, amount) -> None:
        if not amount:
            return
        with self.lock:
            self.data["totals"][field] += amount
            self._day_row()[field] += amount
            self.session[field] += amount
            self.dirty = True
            self._mark_active()

    def _mark_active(self) -> None:
        """Count each wall-clock second that saw at least one input event."""
        sec = int(time.time())
        if sec != self._last_active_sec:
            self._last_active_sec = sec
            self.data["totals"]["sec"] += 1
            self._day_row()["sec"] += 1
            self.session["sec"] += 1

    def add_distance(self, px: float) -> None:
        self._bump("px", float(px))

    def add_scroll(self, dy: int) -> None:
        if dy > 0:
            self._bump("su", int(dy))
        elif dy < 0:
            self._bump("sd", int(-dy))

    def add_click(self, button: str) -> None:
        self._bump({"left": "l", "right": "r", "middle": "m"}.get(button, "m"), 1)

    def reset(self, scope: str = "all") -> None:
        """scope: 'all' wipes history, 'today' clears today's row only."""
        with self.lock:
            if scope == "all":
                self.data["totals"] = _blank_day()
                self.data["days"] = {}
                self.data["created"] = datetime.now().isoformat(timespec="seconds")
            elif scope == "today":
                row = self._day_row()
                for k in row:
                    self.data["totals"][k] -= row[k]
                    if self.data["totals"][k] < 0:
                        self.data["totals"][k] = 0
                self.data["days"][today_key()] = _blank_day()
            self.session = _blank_day()
            self.session["start"] = time.time()
            self.dirty = True
        self.save(force=True)
        if scope == "all":
            # Drop the rolling backup too, so a reset is actually final.
            try:
                self.path.with_suffix(".json.bak").unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "today": dict(self._day_row()),
                "total": dict(self.data["totals"]),
                "session": dict(self.session),
                "created": self.data["created"],
                "day_count": len(self.data["days"]),
            }

    def recent_days(self, n: int = 30) -> list[tuple[str, dict]]:
        """Last n calendar days ending today, gaps filled with zeros."""
        with self.lock:
            days = dict(self.data["days"])
            days.setdefault(today_key(), self._day_row())
        end = date.today()
        out = []
        for i in range(n - 1, -1, -1):
            d = date.fromordinal(end.toordinal() - i)
            key = d.isoformat()
            out.append((key, days.get(key, _blank_day())))
        return out


class AutoSaver(threading.Thread):
    """Flushes the store every `interval` seconds."""

    def __init__(self, store: Store, interval: float = 30.0):
        super().__init__(name="autosave", daemon=True)
        self.store = store
        self.interval = interval
        self._stop = threading.Event()

    def run(self):
        while not self._stop.wait(self.interval):
            self.store.save()

    def stop(self):
        self._stop.set()
        self.store.save(force=True)
