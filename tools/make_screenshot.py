"""Render the bar and the stats window with made-up counts to docs/.

No mouse hook is installed and your own data/odometer.json is never read.
    python tools/make_screenshot.py [output_dir]
Set QT_SCALE_FACTOR=2 for high-DPI images.
"""
import json
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

app_dir = Path(__file__).resolve().parent.parent
out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else app_dir / "docs"
out_dir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(app_dir))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

from odometer import config as cfg_mod
from odometer.store import Store
from odometer.widget import OdometerBar
from odometer.statswindow import StatsWindow

random.seed(11)


def demo_day(scale=1.0):
    s = scale * random.uniform(0.55, 1.25)
    return {"px": 1_900_000 * s, "su": int(1400 * s), "sd": int(2300 * s),
            "l": int(3100 * s), "r": int(510 * s), "m": int(120 * s), "sec": int(15000 * s)}


class DemoTracker:
    backend, error = "pynput", None

    def stop(self):
        pass


cfg = json.loads(json.dumps(cfg_mod.DEFAULTS))
cfg.update({"opacity": 1.0, "position": {"x": 40, "y": 40}})

store = Store(Path(tempfile.mkdtemp()) / "odometer.json")
today = date.today()
days = {}
for i in range(89, -1, -1):
    d = today - timedelta(days=i)
    days[d.isoformat()] = demo_day(0.35 if d.weekday() >= 5 else 1.0)
days[today.isoformat()] = demo_day(0.6)
totals = {k: 0 for k in days[today.isoformat()]}
for row in days.values():
    for k, v in row.items():
        totals[k] += v
for k in totals:  # pretend there's history from before these 90 days
    totals[k] *= 2.7
store.data.update({"created": (today - timedelta(days=240)).isoformat() + "T09:00:00",
                   "totals": totals, "days": days})
store.session.update({k: v * 0.4 for k, v in days[today.isoformat()].items()})

app = QApplication([])


def save(widget, name, pad=24):
    widget.show()
    app.processEvents()
    img = widget.grab().toImage()
    dpr = img.devicePixelRatio()
    img.setDevicePixelRatio(1)
    pad = int(pad * dpr)
    bg = QImage(img.width() + 2 * pad, img.height() + 2 * pad, QImage.Format_ARGB32)
    p = QPainter(bg)
    g = QLinearGradient(0, 0, bg.width(), bg.height())
    g.setColorAt(0, QColor("#1f3b57"))
    g.setColorAt(1, QColor("#3a2448"))
    p.fillRect(bg.rect(), g)
    p.drawImage(QPoint(pad, pad), img)
    p.end()
    bg.save(str(out_dir / name))
    print(out_dir / name, bg.width(), bg.height())


bar = OdometerBar(cfg, store, DemoTracker())
for _ in range(30):
    bar.refresh()
save(bar, "bar.png")
save(StatsWindow(store, cfg), "stats.png")
