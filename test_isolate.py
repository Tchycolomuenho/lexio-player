#!/usr/bin/env python3
"""Test to isolate the hang point by running _setup_ui in stages."""
import os, sys, time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QTabWidget, QStatusBar,
    QListWidget, QScrollArea, QComboBox, QTextEdit,
    QGraphicsOpacityEffect, QStyle, QStyleOptionSlider, QDialog,
    QMenu, QMessageBox, QSizePolicy, QFileDialog,
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QColor, QFont, QIcon, QCursor,
    QRadialGradient, QLinearGradient, QFontMetrics, QFontInfo,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import Qt, QTimer

import lexio_player as lp

app = QApplication(sys.argv)
app.setStyle('Fusion')

# Build the components that _setup_ui creates
w = QMainWindow()
w._playlist = []; w._pl_idx = -1
w._cur_sub = ''; w._rate = 1.0; w._vol = 50; w._seeking = False
w._tools_visible = True; w._overlay_shown = False
w._focus_mode = True; w._autopause_on = False
w._tracks = []; w._listening_mode = False
w._listening_interval = 3; w._listening_sub_count = 0
w._listening_pending = False
w._study_mode = False; w._transport_overlay = None
w._transport_floating = False; w._controls_state = {}
w._session_start = None; w._session_video = ''
w._session_words = []; w.video_path = None
w.mgr = lp.StudyMgr()
w._fs_hide_timer = QTimer(w); w._fs_hide_timer.setSingleShot(True)
w._fs_hide_timer.setInterval(2800)
w._fs_hide_timer.timeout.connect(lambda: None)

# Now call _setup_ui
print("Calling _setup_ui...", flush=True)
t0 = time.time()
try:
    lp.MainWindow._setup_ui(w)
    print(f"_setup_ui OK in {time.time() - t0:.1f}s", flush=True)
except Exception as e:
    import traceback
    print(f"_setup_ui ERROR after {time.time() - t0:.1f}s: {e}", flush=True)
    traceback.print_exc()
