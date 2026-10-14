"""Entry point: python main.py  (or run.bat)

Flags:
  --selftest   exercise the store and print the current figures, then exit
  --report     print accumulated stats to the console and exit
"""
from __future__ import annotations

import sys


def _load():
    from odometer import config as cfg_mod
    from odometer.store import Store
    cfg = cfg_mod.load()
    return cfg, Store(cfg_mod.data_path(cfg))


def report() -> int:
    from odometer import units
    cfg, store = _load()
    snap = store.snapshot()
    dpi = int(cfg.get("mouse_dpi", 800))
    scale = float(cfg.get("pointer_scale", 1.0))

    print("Mouse Odometer\n" + "-" * 46)
    print(f"data file : {store.path}")
    print(f"since     : {snap['created'][:10]}   ({snap['day_count']} days)")
    print(f"mouse DPI : {dpi}\n")
    head = f"{'':15}{'today':>14}{'session':>14}{'all time':>14}"
    print(head)
    rows = [
        ("distance", lambda r: units.fmt_distance(
            units.px_to_metres(r.get("px", 0.0), dpi, scale))),
        ("scroll", lambda r: f"{units.scroll_notches(r):,} n"),
        ("wheel rolled", lambda r: units.fmt_distance(
            units.wheel_rolled_metres(
                units.scroll_notches(r),
                float(cfg.get("wheel_diameter_mm", 20.0)),
                int(cfg.get("wheel_detents", 24))))),
        ("page scrolled", lambda r: units.fmt_distance(
            units.page_scrolled_metres(
                units.scroll_notches(r), int(cfg.get("screen_dpi", 96)),
                int(cfg.get("lines_per_notch", 3)),
                float(cfg.get("px_per_line", 20.0))))),
        ("clicks", lambda r: f"{units.clicks_total(r):,}"),
        ("active", lambda r: units.fmt_duration(r.get("sec", 0))),
    ]
    for name, fn in rows:
        cells = "".join(f"{fn(snap[s]):>14}"
                        for s in ("today", "session", "total"))
        print(f"{name:15}{cells}")
    return 0


def selftest() -> int:
    import tempfile
    from pathlib import Path

    from odometer import units
    from odometer.store import Store
    from odometer.tracker import Tracker

    print("Mouse Odometer — self-test\n" + "-" * 46)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "odometer.json"
        s = Store(path)
        for _ in range(100):
            s.add_distance(37.5)
        s.add_scroll(5)
        s.add_scroll(-3)
        for b in ("left", "left", "right", "middle"):
            s.add_click(b)
        assert s.save(force=True), "save failed"

        again = Store(path)
        snap = again.snapshot()
        px = snap["total"]["px"]
        print(f"persisted pixels  : {px:,.0f}  (expected 3,750)")
        print(f"persisted scroll  : up {snap['total']['su']}, "
              f"down {snap['total']['sd']}  (expected 5, 3)")
        print(f"persisted clicks  : L{snap['total']['l']} "
              f"R{snap['total']['r']} M{snap['total']['m']}  (expected L2 R1 M1)")
        ok = (abs(px - 3750) < 0.01 and snap["total"]["su"] == 5
              and snap["total"]["sd"] == 3 and snap["total"]["l"] == 2)
        print(f"session counters  : reset on reload -> "
              f"{again.snapshot()['session']['px']:.0f} px")
        print(f"distance at 800dpi: "
              f"{units.fmt_distance(units.px_to_metres(px, 800))}")
        print(f"30-day history    : {len(again.recent_days(30))} rows")
        print("\npersistence       :", "PASS" if ok else "FAIL")

    cfg, store = _load()
    t = Tracker(store)
    backend = t.start()
    t.stop()
    print("tracking backend  :", backend, f"({t.error})" if t.error else "")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--report" in sys.argv:
        return report()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not installed. Run:\n"
              "    pip install -r requirements.txt", file=sys.stderr)
        return 1

    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    from odometer import config as cfg_mod
    from odometer.store import AutoSaver, Store
    from odometer.tracker import Tracker
    from odometer.widget import OdometerBar

    cfg = cfg_mod.load()

    app = QApplication(sys.argv)
    app.setApplicationName("Mouse Odometer")
    app.setQuitOnLastWindowClosed(False)

    # One instance only. Two would each install a hook and both write the same
    # data file, so the counts would clobber each other.
    key = "MouseOdometer-" + str(cfg_mod.data_path(cfg)).lower().replace("\\", "-")
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(400):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(400)
        probe.disconnectFromServer()
        print("Mouse Odometer is already running — showing the existing one.")
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    store = Store(cfg_mod.data_path(cfg))

    tracker = Tracker(store, float(cfg.get("teleport_px", 4000)))
    tracker.start()
    saver = AutoSaver(store, float(cfg.get("autosave", 30.0)))
    saver.start()
    app.aboutToQuit.connect(saver.stop)

    bar = OdometerBar(cfg, store, tracker)
    bar.show()

    def _second_launch():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        bar.show()
        bar.raise_()
        bar.activateWindow()

    server.newConnection.connect(_second_launch)
    app.aboutToQuit.connect(server.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
