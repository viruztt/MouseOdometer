"""The chip widget — a coloured label pill, a value, and a history sparkline.

Same visual language as the System Monitor Bar so the two sit together nicely.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import QWidget

BG = QColor(14, 15, 20, 225)
CHIP_BG = QColor(26, 28, 36, 235)
TEXT = QColor(238, 240, 245)
INK_DIM = QColor(150, 156, 170)


class Chip(QWidget):
    def __init__(self, key: str, label: str, accent: str, history: int,
                 reserve: str = "000.00 km", parent=None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.reserve = reserve
        self.accent = QColor(accent)
        self.value_text = "0"
        self.level = 0.0
        self.hist = deque([0.0] * history, maxlen=history)
        self.show_spark = True
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedHeight(26)
        self._relayout()

    # -- metrics -------------------------------------------------------- #
    def _relayout(self):
        fm_label = QFontMetrics(self._label_font())
        fm_value = QFontMetrics(self._value_font())
        self._label_w = fm_label.horizontalAdvance(self.label) + 14
        self._value_w = max(fm_value.horizontalAdvance(self.value_text),
                            fm_value.horizontalAdvance(self.reserve))
        self.setFixedWidth(self._label_w + self._value_w + 18)

    def _label_font(self):
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, self.font().pointSizeF() - 1.5))
        f.setBold(True)
        return f

    def _value_font(self):
        f = QFont(self.font())
        f.setBold(True)
        return f

    def set_font_size(self, pt: int):
        f = QFont(self.font())
        f.setPointSize(pt)
        self.setFont(f)
        self.setFixedHeight(max(22, int(pt * 2.3)))
        self._relayout()

    def update_value(self, text: str, level: float | None, tooltip: str = ""):
        grew = len(text) > len(self.value_text)
        self.value_text = text
        if grew:
            self._relayout()
        self.level = 0.0 if level is None else max(0.0, min(1.0, level))
        self.hist.append(self.level)
        if tooltip:
            self.setToolTip(tooltip)
        self.update()

    # -- painting ------------------------------------------------------- #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QPainterPath()
        path.addRoundedRect(r, 5, 5)
        p.fillPath(path, CHIP_BG)

        if self.show_spark and len(self.hist) > 1:
            p.save()
            p.setClipPath(path)
            spark = QRectF(r.left() + self._label_w, r.top(),
                           r.width() - self._label_w, r.height())
            pts = [QPointF(spark.left(), spark.bottom())]
            n = len(self.hist)
            for i, v in enumerate(self.hist):
                x = spark.left() + spark.width() * (i / (n - 1))
                y = spark.bottom() - (spark.height() - 3) * v
                pts.append(QPointF(x, y))
            pts.append(QPointF(spark.right(), spark.bottom()))
            fill = QColor(self.accent)
            fill.setAlpha(52)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPolygon(QPolygonF(pts))
            line = QColor(self.accent)
            line.setAlpha(150)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(line, 1.0))
            p.drawPolyline(QPolygonF(pts[1:-1]))
            p.restore()

        pill = QRectF(r.left(), r.top(), self._label_w, r.height())
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill, 5, 5)
        p.fillPath(pill_path, self.accent)
        p.setPen(QColor(12, 13, 17))
        p.setFont(self._label_font())
        p.drawText(pill, Qt.AlignCenter, self.label)

        p.setPen(TEXT)
        p.setFont(self._value_font())
        vr = QRectF(r.left() + self._label_w + 8, r.top(),
                    r.width() - self._label_w - 16, r.height())
        p.drawText(vr, Qt.AlignRight | Qt.AlignVCenter, self.value_text)

        border = QColor(self.accent)
        border.setAlpha(120)
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 5, 5)
