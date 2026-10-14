"""The floating odometer bar."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QMenu, QMessageBox,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QRectF

from . import config as cfg_mod
from . import units
from .chips import BG, Chip
from .statswindow import StatsWindow

ACCENT_DIST = "#3FC1E0"
ACCENT_SCROLL = "#56D07A"
ACCENT_CLICK = "#E0A03F"
ACCENT_TIME = "#7C6CE8"
ACCENT_ROLL = "#7C6CE8"
ACCENT_PAGE = "#E04FB0"

# key -> (label, accent, scope, metric, reserve, per-second norm for sparkline)
SPEC = {
    "dist_today":     ("Mouse Today",   ACCENT_DIST,   "today",   "dist",   "000.00 km", 0.5),
    "dist_session":   ("Mouse Session", ACCENT_DIST,   "session", "dist",   "000.00 km", 0.5),
    "dist_total":     ("Mouse Total",   ACCENT_DIST,   "total",   "dist",   "000.00 km", 0.5),
    "scroll_today":   ("Scroll Today",  ACCENT_SCROLL, "today",   "scroll", "000.0k",    6.0),
    "scroll_session": ("Scroll Session", ACCENT_SCROLL, "session", "scroll", "000.0k",   6.0),
    "scroll_total":   ("Scroll Total",  ACCENT_SCROLL, "total",   "scroll", "000.0k",    6.0),
    "roll_today":     ("Wheel Rolled Today",   ACCENT_ROLL, "today",   "roll", "000.00 km", 0.02),
    "roll_session":   ("Wheel Rolled Session", ACCENT_ROLL, "session", "roll", "000.00 km", 0.02),
    "roll_total":     ("Wheel Rolled",         ACCENT_ROLL, "total",   "roll", "000.00 km", 0.02),
    "page_today":     ("Page Scrolled Today",   ACCENT_PAGE, "today",   "page", "000.00 km", 0.12),
    "page_session":   ("Page Scrolled Session", ACCENT_PAGE, "session", "page", "000.00 km", 0.12),
    "page_total":     ("Page Scrolled",         ACCENT_PAGE, "total",   "page", "000.00 km", 0.12),
    "clicks_today":   ("Clicks Today",  ACCENT_CLICK,  "today",   "clicks", "000.0k",    3.0),
    "clicks_session": ("Clicks Session", ACCENT_CLICK, "session", "clicks", "000.0k",    3.0),
    "clicks_total":   ("Clicks Total",  ACCENT_CLICK,  "total",   "clicks", "000.0k",    3.0),
    "active_today":   ("Active Today",  ACCENT_TIME,   "today",   "active", "00h 00m",   1.0),
}


class OdometerBar(QWidget):
    def __init__(self, cfg: dict, store, tracker):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.tracker = tracker
        self.chips: dict[str, Chip] = {}
        self._prev_raw: dict[str, float] = {}
        self._stats = None

        self.setWindowTitle("Mouse Odometer")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.Tool, True)
        self._apply_flags()
        self.setWindowOpacity(float(cfg.get("opacity", 0.93)))

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(5)
        root.addLayout(self.rows_box)

        self._drag_offset = None
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self._build_chips()
        self._restore_position()
        self._tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(int(float(cfg.get("refresh", 1.0)) * 1000))
        QTimer.singleShot(120, self.refresh)

    # ------------------------------------------------------------------ #
    def _build_chips(self):
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        w.setParent(None)
                        w.deleteLater()
                lay.deleteLater()
        self.chips.clear()
        self._prev_raw.clear()

        hist = int(self.cfg.get("history", 60))
        pt = int(self.cfg.get("font_size", 11))
        screen = QApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * 0.96) - 16

        row, used = self._new_row(), 0
        for key in self.cfg["chips"]:
            label, accent, _, _, reserve, _ = SPEC[key]
            chip = Chip(key, label, accent, hist, reserve, self)
            chip.show_spark = bool(self.cfg.get("show_sparklines", True))
            chip.set_font_size(pt)
            self.chips[key] = chip
            w = chip.width() + 6
            if used and used + w > max_w:
                row, used = self._new_row(), 0
            row.addWidget(chip)
            used += w
        self.adjustSize()

    def _new_row(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)
        self.rows_box.addLayout(row)
        return row

    def _apply_flags(self):
        layer = self.cfg.get("window_layer", "top")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, layer == "top")
        self.setWindowFlag(Qt.WindowStaysOnBottomHint, layer == "bottom")
        self.cfg["always_on_top"] = (layer == "top")
        self.setAttribute(Qt.WA_TransparentForMouseEvents,
                          bool(self.cfg.get("click_through", False)))

    # ------------------------------------------------------------------ #
    def _metres(self, row) -> float:
        return units.px_to_metres(row.get("px", 0.0),
                                  int(self.cfg.get("mouse_dpi", 800)),
                                  float(self.cfg.get("pointer_scale", 1.0)))

    def _roll_metres(self, notches: float) -> float:
        return units.wheel_rolled_metres(
            notches, float(self.cfg.get("wheel_diameter_mm", 20.0)),
            int(self.cfg.get("wheel_detents", 24)))

    def _page_metres(self, notches: float) -> float:
        return units.page_scrolled_metres(
            notches, int(self.cfg.get("screen_dpi", 96)),
            int(self.cfg.get("lines_per_notch", 3)),
            float(self.cfg.get("px_per_line", 20.0)))

    def refresh(self):
        snap = self.store.snapshot()
        interval = max(0.1, float(self.cfg.get("refresh", 1.0)))
        screen_h = QApplication.primaryScreen().geometry().height()

        for key, chip in self.chips.items():
            label, accent, scope, metric, reserve, norm = SPEC[key]
            row = snap[scope]

            if metric == "dist":
                raw = self._metres(row)
                text = units.fmt_distance(raw)
                tip = (f"{label}\n{raw:,.1f} m of desk movement\n"
                       f"{row.get('px', 0):,.0f} screen pixels at "
                       f"{self.cfg.get('mouse_dpi', 800)} DPI")
            elif metric == "scroll":
                raw = float(units.scroll_notches(row))
                text = units.fmt_count(raw)
                screens = units.scroll_screens(raw, screen_h)
                tip = (f"{label}\n{int(raw):,} wheel notches\n"
                       f"{int(row.get('su', 0)):,} up / "
                       f"{int(row.get('sd', 0)):,} down\n"
                       f"about {screens:,.0f} screen-heights")
            elif metric == "roll":
                notches = float(units.scroll_notches(row))
                raw = self._roll_metres(notches)
                text = units.fmt_distance(raw)
                tip = (f"{label}\nHow far the wheel's rim has rolled under "
                       f"your finger\n{int(notches):,} notches \u00d7 "
                       f"{self.cfg.get('wheel_diameter_mm', 20.0):g} mm wheel, "
                       f"{self.cfg.get('wheel_detents', 24)} detents per turn\n"
                       f"= {self._roll_metres(1) * 1000:.2f} mm per notch")
            elif metric == "page":
                notches = float(units.scroll_notches(row))
                raw = self._page_metres(notches)
                text = units.fmt_distance(raw)
                tip = (f"{label}\nHow much document has flowed past, as if the "
                       f"page were paper\n{int(notches):,} notches \u00d7 "
                       f"{self.cfg.get('lines_per_notch', 3)} lines at "
                       f"{self.cfg.get('screen_dpi', 96)} DPI\n"
                       f"= {self._page_metres(1) * 100:.2f} cm per notch")
            elif metric == "clicks":
                raw = float(units.clicks_total(row))
                text = units.fmt_count(raw)
                tip = (f"{label}\n{int(raw):,} clicks\n"
                       f"left {int(row.get('l', 0)):,} · "
                       f"right {int(row.get('r', 0)):,} · "
                       f"middle {int(row.get('m', 0)):,}")
            else:
                raw = float(row.get("sec", 0))
                text = units.fmt_duration(raw)
                tip = f"{label}\nSeconds with any mouse activity"

            prev = self._prev_raw.get(key)
            self._prev_raw[key] = raw
            rate = 0.0 if prev is None else max(0.0, (raw - prev) / interval)
            chip.update_value(text, min(1.0, rate / norm) if norm else 0.0, tip)

    # ------------------------------------------------------------------ #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        p.fillPath(path, BG)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.drawRoundedRect(r, 9, 9)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()

    def mouseDoubleClickEvent(self, e):
        self.show_stats()

    def _save_position(self):
        self.cfg["position"] = {"x": self.x(), "y": self.y()}
        cfg_mod.save(self.cfg)

    def _restore_position(self):
        pos = self.cfg.get("position") or {}
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        if pos.get("x") is not None and pos.get("y") is not None:
            p = QPoint(int(pos["x"]), int(pos["y"]))
            if screen.adjusted(-40, -40, 40, 40).contains(p):
                self.move(p)
                return
        self.move(screen.center().x() - self.width() // 2,
                  screen.bottom() - self.height() - 48)

    # ------------------------------------------------------------------ #
    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Stats and history…", self.show_stats)
        m.addSeparator()

        metrics = m.addMenu("Chips")
        for key in cfg_mod.ALL_CHIPS:
            a = QAction(SPEC[key][0], metrics)
            a.setCheckable(True)
            a.setChecked(key in self.cfg["chips"])
            a.toggled.connect(lambda on, k=key: self._toggle_chip(k, on))
            metrics.addAction(a)

        dpi = m.addMenu(f"Mouse DPI ({self.cfg.get('mouse_dpi', 800)})")
        grp = QActionGroup(dpi)
        for v in (400, 800, 1000, 1200, 1600, 2400, 3200):
            a = QAction(str(v), dpi)
            a.setCheckable(True)
            a.setChecked(int(self.cfg.get("mouse_dpi", 800)) == v)
            a.triggered.connect(lambda _c, val=v: self._set_dpi(val))
            grp.addAction(a)
            dpi.addAction(a)
        dpi.addSeparator()
        dpi.addAction("Custom…", self._ask_dpi)

        a = m.addAction("Sparklines")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("show_sparklines", True)))
        a.toggled.connect(self._toggle_spark)

        lm = m.addMenu("Window layer")
        lgrp = QActionGroup(lm)
        for value, text in (("top", "Always on top"),
                            ("normal", "Normal (can be covered)"),
                            ("bottom", "Always at the bottom")):
            act = QAction(text, lm)
            act.setCheckable(True)
            act.setChecked(self.cfg.get("window_layer", "top") == value)
            act.triggered.connect(lambda _c, v=value: self._set_layer(v))
            lgrp.addAction(act)
            lm.addAction(act)

        a = m.addAction("Click-through")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("click_through", False)))
        a.toggled.connect(lambda on: self._flag("click_through", on))

        om = m.addMenu("Opacity")
        for v in (1.0, 0.93, 0.8, 0.65, 0.5):
            a = om.addAction(f"{int(v * 100)}%")
            a.setCheckable(True)
            a.setChecked(abs(float(self.cfg.get("opacity", 0.93)) - v) < 0.01)
            a.triggered.connect(lambda _c, val=v: self._set_opacity(val))

        sm = m.addMenu("Text size")
        for v in (9, 10, 11, 12, 14, 16):
            a = sm.addAction(f"{v} pt")
            a.setCheckable(True)
            a.setChecked(int(self.cfg.get("font_size", 11)) == v)
            a.triggered.connect(lambda _c, val=v: self._set_font(val))

        m.addSeparator()
        m.addAction("Reset position", self._reset_position)
        m.addAction("Quit", self.quit)
        m.exec(self.mapToGlobal(pos))

    def show_stats(self):
        if self._stats is None:
            self._stats = StatsWindow(self.store, self.cfg, None)
        self._stats.show()
        self._stats.raise_()
        self._stats.activateWindow()

    def _toggle_chip(self, key, on):
        chips = [c for c in self.cfg["chips"] if c != key]
        if on:
            chips = [c for c in cfg_mod.ALL_CHIPS if c in chips or c == key]
        self.cfg["chips"] = chips or [key]
        cfg_mod.save(self.cfg)
        self._build_chips()

    def _toggle_spark(self, on):
        self.cfg["show_sparklines"] = bool(on)
        for c in self.chips.values():
            c.show_spark = bool(on)
            c.update()
        cfg_mod.save(self.cfg)

    def _set_layer(self, value):
        self.cfg["window_layer"] = value
        self._apply_flags()
        cfg_mod.save(self.cfg)
        self.show()

    def _flag(self, name, on):
        self.cfg[name] = bool(on)
        cfg_mod.save(self.cfg)
        self._apply_flags()
        self.show()

    def _set_opacity(self, v):
        self.cfg["opacity"] = v
        self.setWindowOpacity(v)
        cfg_mod.save(self.cfg)

    def _set_font(self, v):
        self.cfg["font_size"] = v
        cfg_mod.save(self.cfg)
        for c in self.chips.values():
            c.set_font_size(v)
        self.adjustSize()

    def _set_dpi(self, v):
        self.cfg["mouse_dpi"] = int(v)
        cfg_mod.save(self.cfg)
        self._prev_raw.clear()
        self.refresh()

    def _ask_dpi(self):
        v, ok = QInputDialog.getInt(
            self, "Mouse DPI",
            "Sensor DPI / CPI of your mouse.\n"
            "Distance is derived from this, so a wrong value scales it.",
            int(self.cfg.get("mouse_dpi", 800)), 100, 32000, 100)
        if ok:
            self._set_dpi(v)

    def _reset_position(self):
        self.cfg["position"] = {"x": None, "y": None}
        self._restore_position()
        self._save_position()

    # ------------------------------------------------------------------ #
    def _tray(self):
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(ACCENT_DIST), 2.4))
        p.drawArc(4, 6, 24, 24, 0 * 16, 180 * 16)
        p.setPen(QPen(QColor(ACCENT_CLICK), 2.4))
        p.drawLine(16, 20, 24, 11)
        p.setBrush(QColor(ACCENT_SCROLL))
        p.setPen(Qt.NoPen)
        p.drawEllipse(13, 17, 6, 6)
        p.end()

        self.tray = QSystemTrayIcon(QIcon(pm), self)
        self.tray.setToolTip("Mouse Odometer")
        menu = QMenu()
        menu.addAction("Stats and history…", self.show_stats)
        menu.addAction("Show / hide bar", self._toggle_visible)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_stats()
            if r == QSystemTrayIcon.DoubleClick else (
                self._toggle_visible() if r == QSystemTrayIcon.Trigger else None))
        self.tray.show()

        if self.tracker.backend == "none":
            QMessageBox.warning(
                self, "Mouse Odometer",
                "No mouse tracking backend is available, so nothing will be "
                "counted.\n\nInstall pynput:\n"
                "    pip install -r requirements.txt\n\n"
                f"Details: {self.tracker.error or 'unknown'}")

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def _bring_to_front(self):
        """The bar has no taskbar button, so this is how to dig it out."""
        self.show()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self._save_position()
        try:
            self.tracker.stop()
        except Exception:
            pass
        self.store.save(force=True)
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        self.quit()
        e.accept()
