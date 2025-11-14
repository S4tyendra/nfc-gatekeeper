#!/usr/bin/env python3
"""
nfc_ui.py

PySide6 GUI for the NFC Student ID Processor.
Theme: AMOLED black with neon accents.

Features:
 - Splash screen
 - Dark AMOLED styling
 - Start / Stop reader control (spawns controlled monitor thread)
 - Live log window (captures prints from the NFC module)
 - Big LED-style success indicator with animation
 - Card history table (reads from SQLite DB)
 - DB count and live updates
 - Lightweight animations and a compact layout

Usage:
 - Place this file next to your `main.py` (the NFC pipeline script you provided).
 - Activate your venv and install PySide6: `pip install PySide6`
 - Run: `python nfc_ui.py`

Notes:
 - This UI imports your NFC script as `import main as nfc`.
 - The UI does not rewrite your NFC logic; it creates its own CardMonitor
   using your StudentCardObserver class so it can start/stop cleanly.
 - If your NFC module changes APIs, you may need to adapt the wrapper.
"""

from __future__ import annotations
import sys
import threading
import sqlite3
import time
from queue import Queue, Empty
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QSplashScreen,
    QSizePolicy
)
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Property

# Import the user's NFC module (expects main.py next to this file)
import main as nfc

DB_FILE = nfc.DB_FILE

# ----------------------------- Styling (AMOLED) -----------------------------
AMOLED_STYLESHEET = """
QWidget { background: #000000; color: #E6F8E0; }
QTextEdit { background: #010101; border: 1px solid #0A0A0A; }
QPushButton { background: #0b0b0b; border: 1px solid #0b9e6a; padding: 6px; }
QPushButton:disabled { color: #555; border-color: #222; }
QTableWidget { background: #000000; gridline-color: #0b0b0b; }
QHeaderView::section { background: #050505; color: #7CFFB2; }
QLabel.title { color: #7CFFB2; font-weight: 700; font-size: 18px; }
QLabel.small { color: #9EF4C4; font-size: 12px; }
"""

# ----------------------------- Utility: DB ----------------------------------

def get_db_count() -> int:
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cards")
        (c,) = cur.fetchone()
        conn.close()
        return c
    except Exception:
        return 0


def fetch_recent_rows(limit: int = 50):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT student_id, card_uid, timestamp FROM cards ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

# ----------------------------- Animated Indicator ---------------------------

class PulseIndicator(QWidget):
    def __init__(self, size=120, parent=None):
        super().__init__(parent)
        self._intensity = 0.0
        self._color = QColor(24, 255, 129)  # neon green default
        self.setFixedSize(size, size)
        self._anim = QPropertyAnimation(self, b"intensity")
        self._anim.setDuration(800)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.setLoopCount(2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        center = r.center()
        radius = min(r.width(), r.height()) / 2.2

        # Outer glow (based on intensity)
        glow = int(80 * self._intensity)
        c = QColor(self._color)
        c.setAlpha(60 + glow)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(center, radius + 12 * self._intensity, radius + 12 * self._intensity)

        # Main circle
        c2 = QColor(self._color)
        c2.setAlpha(200 - int(80 * (1 - self._intensity)))
        p.setBrush(c2)
        p.setPen(Qt.NoPen)
        p.drawEllipse(center, radius, radius)

    def trigger(self):
        self._anim.stop()
        self._anim.setDirection(QPropertyAnimation.Forward)
        self._anim.start()

    def getIntensity(self) -> float:
        return self._intensity

    def setIntensity(self, v: float):
        self._intensity = v
        self.update()

    intensity = Property(float, getIntensity, setIntensity)

# ----------------------------- NFC Worker ----------------------------------

class NFCWorker(threading.Thread):
    """Runs the NFC CardMonitor using the StudentCardObserver but inside a
    controlled thread so UI can start/stop the monitor cleanly.

    Behavior:
      - Patches print in the nfc module to route into UI via a message queue.
      - On start: calls nfc.init_db, finds readers, calls setup_and_configure_reader,
        creates CardMonitor and adds nfc.StudentCardObserver.
      - Blocks until stop_event is set; then deletes observer and exits.
    """

    def __init__(self, msg_queue: Queue):
        super().__init__(daemon=True)
        self.msg_queue = msg_queue
        self.stop_event = threading.Event()
        self.monitor = None
        self.observer = None

    def log(self, s: str):
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            self.msg_queue.put(f"[{ts}] {s}")
        except Exception:
            pass

    def run(self):
        try:
            # Patch prints in the NFC module to forward to UI
            def patched_print(*args, **kwargs):
                try:
                    self.log(" ".join(str(a) for a in args))
                except Exception:
                    pass

            nfc.print = patched_print

            self.log("Initializing DB (UI wrapper)...")
            nfc.init_db(DB_FILE)

            readers = nfc.readers()
            if not readers:
                self.log("❌ No NFC reader found. Attach reader and Start again.")
                return

            reader = readers[0]
            self.log(f"Found reader: {reader}")

            # Configure reader once
            try:
                nfc.setup_and_configure_reader(reader)
            except Exception as e:
                self.log(f"⚠ Reader configure failed: {e}")

            # Start CardMonitor using the class from nfc
            from smartcard.CardMonitoring import CardMonitor

            self.monitor = CardMonitor()
            self.observer = nfc.StudentCardObserver(DB_FILE)
            self.monitor.addObserver(self.observer)

            self.log("Monitor started. Waiting for cards...")

            # Wait until stop_event
            while not self.stop_event.is_set():
                time.sleep(0.2)

        except Exception as e:
            self.log(f"UNHANDLED WORKER ERROR: {e}")
        finally:
            try:
                if self.monitor and self.observer:
                    self.monitor.deleteObserver(self.observer)
                    self.log("Monitor stopped and observer removed.")
            except Exception as e:
                self.log(f"Error stopping monitor: {e}")

    def stop(self):
        self.stop_event.set()

# ----------------------------- Main UI -------------------------------------

class NFCUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NFC Student ID Processor")
        self.setMinimumSize(980, 640)
        self.setStyleSheet(AMOLED_STYLESHEET)

        self.msg_queue: Queue = Queue()
        self.worker: Optional[NFCWorker] = None

        self._build_layout()
        self._setup_timers()

    def _build_layout(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("NFC Student ID Processor")
        title.setProperty('class', 'title')
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # Top row: controls + status
        top = QHBoxLayout()
        left_col = QVBoxLayout()

        # DB count and controls
        self.db_label = QLabel(f"DB Entries: {get_db_count()}")
        self.db_label.setProperty('class', 'small')
        left_col.addWidget(self.db_label)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Reader")
        self.stop_btn = QPushButton("Stop Reader")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_reader)
        self.stop_btn.clicked.connect(self.stop_reader)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        left_col.addLayout(btn_row)

        left_col.addSpacing(8)

        # Recent DB table
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Student ID", "Card UID", "Timestamp"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_col.addWidget(self.history_table, 1)

        top.addLayout(left_col, 3)

        # Right column: big indicator + logs
        right_col = QVBoxLayout()
        self.indicator = PulseIndicator(size=160)
        right_col.addWidget(self.indicator, alignment=Qt.AlignCenter)

        status_label = QLabel("Last Scan")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setProperty('class', 'small')
        right_col.addWidget(status_label)

        self.last_label = QLabel("—")
        self.last_label.setAlignment(Qt.AlignCenter)
        self.last_label.setStyleSheet("font-size: 14px; color: #9EF4C4;")
        right_col.addWidget(self.last_label)

        # Log window
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(220)
        right_col.addWidget(self.log_box)

        top.addLayout(right_col, 2)

        root.addLayout(top, 8)

        # Footer
        footer = QHBoxLayout()
        self.slow_label = QLabel("AMOLED • Neon")
        self.slow_label.setProperty('class', 'small')
        footer.addWidget(self.slow_label)
        footer.addStretch()
        self.version_label = QLabel("v1.0")
        self.version_label.setProperty('class', 'small')
        footer.addWidget(self.version_label)
        root.addLayout(footer)

    def _setup_timers(self):
        # Timer to pull messages from the queue
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_queue)
        self.timer.start(120)

        # Timer to refresh DB history & count every 2s
        self.db_timer = QTimer(self)
        self.db_timer.timeout.connect(self._refresh_db)
        self.db_timer.start(2000)

    def _drain_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self.log_box.append(msg)
                self._parse_message_for_ui(msg)
        except Empty:
            pass

    def _parse_message_for_ui(self, msg: str):
        # Update last scanned student/uid lines on certain messages
        if "[CARD DETECTED] UID:" in msg or "UID:" in msg:
            # crude parse: extract hex UID
            parts = msg.split('UID:')
            if len(parts) > 1:
                uid = parts[-1].strip()
                self.last_label.setText(uid)

        # Success triggers
        if "LOCKED successfully" in msg or "✅ LOCKED" in msg or "Logged new entry" in msg or "Logged new entry to DB." in msg:
            self.indicator.trigger()
            # small visual confirmation in logs
            self.log_box.append("[UI] SUCCESS animation triggered.")

        # DB related messages trigger immediate DB refresh
        if "Logged" in msg or "Entry" in msg:
            self._refresh_db()

    def _refresh_db(self):
        # update count
        cnt = get_db_count()
        self.db_label.setText(f"DB Entries: {cnt}")

        # update history table
        rows = fetch_recent_rows(80)
        self.history_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            sid, uid, ts = row
            self.history_table.setItem(r_idx, 0, QTableWidgetItem(sid))
            self.history_table.setItem(r_idx, 1, QTableWidgetItem(uid))
            self.history_table.setItem(r_idx, 2, QTableWidgetItem(str(ts)))

    # Control methods
    def start_reader(self):
        if self.worker and self.worker.is_alive():
            self.log_box.append("[UI] Reader already running.")
            return

        self.worker = NFCWorker(self.msg_queue)
        self.worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_box.append("[UI] Reader thread started.")

    def stop_reader(self):
        if not self.worker:
            return
        self.worker.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.log_box.append("[UI] Stop requested. Waiting for worker to stop...")

    # Splash helper
    def show_splash_and_start(self):
        splash_pix = QPixmap(480, 240)
        splash_pix.fill(QColor('#000000'))
        painter = QPainter(splash_pix)
        painter.setPen(QColor('#7CFFB2'))
        f = QFont('Sans Serif', 24)
        painter.setFont(f)
        painter.drawText(splash_pix.rect(), Qt.AlignCenter, "NFC Student ID Processor")
        painter.end()

        splash = QSplashScreen(splash_pix)
        splash.show()
        QApplication.processEvents()
        time.sleep(0.9)
        splash.finish(self)

# ----------------------------- Entrypoint ----------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(AMOLED_STYLESHEET)

    ui = NFCUI()
    ui.show_splash_and_start()
    ui.show()

    sys.exit(app.exec())

if __name__ == '__main__':
    main()

