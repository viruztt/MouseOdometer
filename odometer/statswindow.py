"""Stats window: headline figures, and a daily bar chart."""
from __future__ import annotations

import math
import os
import subprocess
import sys
from datetime import date

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from . import units

# Surfaces and ink — one dark theme, stated explicitly rather than inherited.
SURFACE = QColor(20, 21, 26)
PANEL = QColor(26, 28, 36)
INK = QColor(238, 240, 245)
INK_2 = QColor(176, 182, 196)
INK_MUTED = QColor(124, 131, 148)
GRID = QColor(255, 255, 255, 26)

# One hue per metric; only ever one series is drawn at a time, so these are
# identity colours for the chart's subject, not a categorical scale.
METRICS = [
    ("Distance", "dist", "#3FC1E0"),
    ("Scroll notches", "scroll", "#56D07A"),
    ("Wheel rolled", "roll", "#7C6CE8"),
    ("Page scrolled", "page", "#E04FB0"),
    ("Clicks", "clicks", "#E0A03F"),
]
RANGES = [("Last 7 days", 7), ("Last 30 days", 30), ("Last 90 days", 90)]


def dist_formatter(top: float):
    """One unit for the whole axis — mixing 'cm' and 'm' on one scale misreads."""
    if top >= 1000:
        return lambda v: f"{v / 1000:.2f} km"
    if top >= 100:
        return lambda v: f"{v:.0f} m"
    if top >= 1:
        return lambda v: f"{v:.1f} m"
    return lambda v: f"{v * 100:.0f} cm"


def count_formatter(top: float, suffix: str = ""):
    if top >= 10000:
        return lambda v: f"{v / 1000:.1f}k{suffix}"
    return lambda v: f"{int(v):,}{suffix}"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    base = v / (10 ** exp)
    for step in (1, 2, 2.5, 5, 10):
        if base <= step:
            return step * (10 ** exp)
    return 10 ** (exp + 1)


class DailyChart(QWidget):
    """Single-series daily bars. No legend — the title names the series."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, float]] = []
        self.accent = QColor("#3FC1E0")
        self.unit_fmt = str
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(190)

    def set_data(self, rows, accent, unit_fmt):
        self.rows = list(rows)
        self.accent = QColor(accent)
        self.unit_fmt = unit_fmt
        self.hover = -1
        self.update()

    # -- geometry -------------------------------------------------------- #
    def _plot_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(58, 24, -12, -24)

    def _index_at(self, x: float) -> int:
        plot = self._plot_rect()
        n = len(self.rows)
        if n == 0 or not plot.contains(x, plot.center().y()):
            return -1
        i = int((x - plot.left()) / (plot.width() / n))
        return i if 0 <= i < n else -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().x())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, _):
        self.hover = -1
        self.update()

    # -- painting -------------------------------------------------------- #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), PANEL)
        if not self.rows:
            return

        plot = self._plot_rect()
        values = [v for _, v in self.rows]
        top = _nice_max(max(values) if max(values) > 0 else 1.0)

        # Recessive gridlines + y labels.
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, self.font().pointSizeF() - 1.5))
        p.setFont(f)
        for frac in (0.0, 0.5, 1.0):
            y = plot.bottom() - plot.height() * frac
            p.setPen(QPen(GRID, 1.0))
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            p.setPen(INK_MUTED)
            p.drawText(QRectF(0, y - 8, plot.left() - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, self.unit_fmt(top * frac))

        n = len(self.rows)
        slot = plot.width() / n
        gap = 2.0
        bar_w = max(2.0, slot - gap)
        peak = max(range(n), key=lambda i: values[i])

        for i, (day, v) in enumerate(self.rows):
            h = plot.height() * (v / top) if top else 0.0
            x = plot.left() + i * slot
            is_today = i == n - 1
            col = QColor(self.accent)
            if self.hover == i:
                col = col.lighter(125)
            elif v == 0:
                col.setAlpha(60)
            elif not is_today and i != peak:
                col.setAlpha(205)

            if h < 1.5:
                # Zero days still get a visible baseline tick.
                p.fillRect(QRectF(x, plot.bottom() - 1.5, bar_w, 1.5),
                           QColor(255, 255, 255, 34))
                continue
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, plot.bottom() - h, bar_w, h), 4, 4)
            # Square off the bottom so bars sit on the baseline.
            path.addRect(QRectF(x, plot.bottom() - min(h, 5), bar_w, min(h, 5)))
            p.fillPath(path.simplified(), col)

        # Selective direct labels: the peak day, and today if it isn't the peak.
        p.setPen(INK_2)
        for i in {peak, n - 1}:
            v = values[i]
            if v <= 0:
                continue
            h = plot.height() * (v / top)
            x = plot.left() + i * slot
            label = self.unit_fmt(v)
            w = max(bar_w + 68, p.fontMetrics().horizontalAdvance(label) + 8)
            left = min(max(0.0, x + bar_w / 2 - w / 2), self.width() - w)
            p.drawText(QRectF(left, plot.bottom() - h - 18, w, 14),
                       Qt.AlignCenter, label)

        # x labels: first, middle, last.
        p.setPen(INK_MUTED)
        for i in (0, n // 2, n - 1):
            x = plot.left() + i * slot
            d = date.fromisoformat(self.rows[i][0])
            text = "today" if i == n - 1 else d.strftime("%d %b")
            w = bar_w + 60
            left = min(max(0.0, x + bar_w / 2 - w / 2), self.width() - w)
            p.drawText(QRectF(left, plot.bottom() + 4, w, 16),
                       Qt.AlignCenter, text)

        # Hover readout.
        if 0 <= self.hover < n:
            day, v = self.rows[self.hover]
            d = date.fromisoformat(day)
            text = f"{d.strftime('%a %d %b')}   {self.unit_fmt(v)}"
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 16
            x = min(max(plot.left(), plot.left() + self.hover * slot - w / 2),
                    plot.right() - w)
            box = QRectF(x, plot.top() - 20, w, 18)
            path = QPainterPath()
            path.addRoundedRect(box, 4, 4)
            p.fillPath(path, QColor(40, 43, 54, 240))
            p.setPen(INK)
            p.drawText(box, Qt.AlignCenter, text)


class StatsWindow(QDialog):
    def __init__(self, store, cfg, parent=None):
        super().__init__(parent)
        self.store = store
        self.cfg = cfg
        self.setWindowTitle("Mouse Odometer — stats")
        self.resize(720, 520)
        self.setStyleSheet(f"""
            QDialog {{ background: {SURFACE.name()}; }}
            QLabel {{ color: {INK.name()}; }}
            QComboBox, QPushButton {{
                background: {PANEL.name()}; color: {INK.name()};
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 5px; padding: 5px 10px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QPushButton:hover {{ border-color: rgba(255,255,255,0.3); }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(14)

        title = QLabel("Mouse Odometer")
        tf = QFont(self.font())
        tf.setPointSize(self.font().pointSize() + 5)
        tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        # ---- summary table (also the chart's accessible data view) ----- #
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(26)
        self.grid.setVerticalSpacing(7)
        panel = QFrame()
        panel.setStyleSheet(
            f"background: {PANEL.name()}; border-radius: 8px;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.addLayout(self.grid)
        root.addWidget(panel)
        self._cells = {}
        self._build_grid()

        # ---- filters, one row above the chart -------------------------- #
        filters = QHBoxLayout()
        self.chart_title = QLabel()
        ctf = QFont(self.font())
        ctf.setBold(True)
        self.chart_title.setFont(ctf)
        filters.addWidget(self.chart_title)
        filters.addStretch(1)
        self.metric_box = QComboBox()
        for name, _, _ in METRICS:
            self.metric_box.addItem(name)
        self.metric_box.setCurrentIndex(0)
        self.metric_box.currentIndexChanged.connect(self.refresh)
        self.range_box = QComboBox()
        for name, _ in RANGES:
            self.range_box.addItem(name)
        self.range_box.setCurrentIndex(1)
        self.range_box.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.metric_box)
        filters.addWidget(self.range_box)
        root.addLayout(filters)

        self.chart = DailyChart()
        root.addWidget(self.chart, 1)

        self.footer = QLabel()
        self.footer.setStyleSheet(f"color: {INK_MUTED.name()};")
        root.addWidget(self.footer)

        buttons = QHBoxLayout()
        b = QPushButton("Open data folder")
        b.clicked.connect(self._open_folder)
        buttons.addWidget(b)
        buttons.addStretch(1)
        b = QPushButton("Reset today")
        b.clicked.connect(lambda: self._reset("today"))
        buttons.addWidget(b)
        b = QPushButton("Reset everything")
        b.clicked.connect(lambda: self._reset("all"))
        buttons.addWidget(b)
        b = QPushButton("Close")
        b.clicked.connect(self.accept)
        buttons.addWidget(b)
        root.addLayout(buttons)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

    # ------------------------------------------------------------------ #
    def _build_grid(self):
        heads = ["", "Today", "This session", "All time"]
        for c, h in enumerate(heads):
            lab = QLabel(h)
            lab.setStyleSheet(f"color: {INK_MUTED.name()};")
            if c:
                lab.setAlignment(Qt.AlignRight)
            self.grid.addWidget(lab, 0, c)
        rows = ["Distance", "Scroll", "Wheel rolled", "Page scrolled",
                "Clicks", "Active time"]
        vf = QFont(self.font())
        vf.setBold(True)
        for r, name in enumerate(rows, start=1):
            lab = QLabel(name)
            lab.setStyleSheet(f"color: {INK_2.name()};")
            self.grid.addWidget(lab, r, 0)
            for c, scope in enumerate(("today", "session", "total"), start=1):
                v = QLabel("—")
                v.setFont(vf)
                v.setAlignment(Qt.AlignRight)
                self.grid.addWidget(v, r, c)
                self._cells[(name, scope)] = v

    def _metres(self, row) -> float:
        return units.px_to_metres(row.get("px", 0.0),
                                  int(self.cfg.get("mouse_dpi", 800)),
                                  float(self.cfg.get("pointer_scale", 1.0)))

    def _roll(self, row) -> float:
        return units.wheel_rolled_metres(
            units.scroll_notches(row),
            float(self.cfg.get("wheel_diameter_mm", 20.0)),
            int(self.cfg.get("wheel_detents", 24)))

    def _page(self, row) -> float:
        return units.page_scrolled_metres(
            units.scroll_notches(row), int(self.cfg.get("screen_dpi", 96)),
            int(self.cfg.get("lines_per_notch", 3)),
            float(self.cfg.get("px_per_line", 20.0)))

    def refresh(self):
        snap = self.store.snapshot()
        for scope in ("today", "session", "total"):
            row = snap[scope]
            self._cells[("Distance", scope)].setText(
                units.fmt_distance(self._metres(row)))
            self._cells[("Scroll", scope)].setText(
                units.fmt_count(units.scroll_notches(row)) + " notches")
            self._cells[("Wheel rolled", scope)].setText(
                units.fmt_distance(self._roll(row)))
            self._cells[("Page scrolled", scope)].setText(
                units.fmt_distance(self._page(row)))
            self._cells[("Clicks", scope)].setText(
                units.fmt_count(units.clicks_total(row)))
            self._cells[("Active time", scope)].setText(
                units.fmt_duration(row.get("sec", 0)))

        name, key, accent = METRICS[max(0, self.metric_box.currentIndex())]
        days = RANGES[max(0, self.range_box.currentIndex())][1]
        rows = self.store.recent_days(days)

        if key == "dist":
            data = [(d, self._metres(r)) for d, r in rows]
            self.chart_title.setText(f"Mouse distance, last {days} days")
        elif key == "scroll":
            data = [(d, float(units.scroll_notches(r))) for d, r in rows]
            self.chart_title.setText(f"Wheel notches, last {days} days")
        elif key == "roll":
            data = [(d, self._roll(r)) for d, r in rows]
            self.chart_title.setText(f"Wheel rim rolled, last {days} days")
        elif key == "page":
            data = [(d, self._page(r)) for d, r in rows]
            self.chart_title.setText(f"Document scrolled past, last {days} days")
        else:
            data = [(d, float(units.clicks_total(r))) for d, r in rows]
            self.chart_title.setText(f"Clicks, last {days} days")

        top = _nice_max(max((v for _, v in data), default=0.0))
        fmt = (dist_formatter(top) if key in ("dist", "roll", "page")
               else count_formatter(top))
        self.chart.set_data(data, accent, fmt)

        tot = snap["total"]
        self.footer.setText(
            f"Tracking since {snap['created'][:10]} · "
            f"{snap['day_count']} days recorded · "
            f"{units.fmt_count(tot.get('l', 0))} left, "
            f"{units.fmt_count(tot.get('r', 0))} right, "
            f"{units.fmt_count(tot.get('m', 0))} middle clicks · "
            f"{units.fmt_count(tot.get('su', 0))} up / "
            f"{units.fmt_count(tot.get('sd', 0))} down notches"
        )

    # ------------------------------------------------------------------ #
    def _open_folder(self):
        folder = str(self.store.path.parent)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            QMessageBox.information(self, "Data folder", folder)

    def _reset(self, scope):
        what = "today's counters" if scope == "today" else \
            "every counter, including the full history"
        if QMessageBox.question(
                self, "Reset", f"Reset {what}? This cannot be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.store.reset(scope)
            self.refresh()
