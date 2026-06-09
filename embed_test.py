"""Test embedding ffplay window"""
import os, subprocess, time, sys, ctypes
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, QTimer
import win32gui, win32con, win32api

class TestWin(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FFplay Embed Test")
        self.resize(800, 600)
        
        c = QWidget()
        self.setCentralWidget(c)
        l = QVBoxLayout(c)
        
        self.container = QWidget()
        self.container.setStyleSheet("background: #111;")
        self.container.setMinimumHeight(400)
        l.addWidget(self.container)
        
        self.btn = QPushButton("▶ Launch Video")
        self.btn.clicked.connect(self.launch)
        l.addWidget(self.btn)
        
        self.proc = None
        self.embed_hwnd = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._try_embed)
        
        self.path = None
        
    def launch(self):
        if not self.path:
            from PyQt5.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, "Select Video")
            if not path: return
            self.path = path
        
        # Kill old ffplay
        if self.proc:
            try: 
                subprocess.run(['taskkill', '/f', '/t', '/pid', str(self.proc.pid)], 
                             capture_output=True)
            except: pass
        
        self.title = f"LexioEmbed_{id(self)}"
        self.proc = subprocess.Popen([
            'ffplay', '-autoexit', '-noborder', '-window_title', self.title,
            '-x', '800', '-y', '480', self.path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._timer.start(200)
        self.btn.setText("⏳ Waiting...")
    
    def _try_embed(self):
        hwnd = win32gui.FindWindow(None, self.title)
        if hwnd:
            self._timer.stop()
            self.embed_hwnd = hwnd
            print(f"Found ffplay HWND: {hwnd}")
            
            # Get container HWND
            container_hwnd = int(self.container.winId())
            print(f"Container HWND: {container_hwnd}")
            
            # Remove caption, thickframe, etc.
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            new_style = style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME | 
                                  win32con.WS_BORDER | win32con.WS_DLGFRAME |
                                  win32con.WS_SYSMENU | win32con.WS_MINIMIZEBOX |
                                  win32con.WS_MAXIMIZEBOX)
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
            
            # Reparent
            ctypes.windll.user32.SetParent(hwnd, container_hwnd)
            
            # Resize to fit container
            r = self.container.rect()
            ctypes.windll.user32.MoveWindow(hwnd, 0, 0, r.width(), r.height(), True)
            
            self.btn.setText("⏸ Pause")
            print("✅ Embedded!")
            
            # Track container resize
            self.container.resizeEvent = lambda e: (
                setattr(self.container, '_resize', True),
                ctypes.windll.user32.MoveWindow(hwnd, 0, 0, 
                    self.container.width(), self.container.height(), True)
            )

app = QApplication(sys.argv)
w = TestWin()
w.show()
sys.exit(app.exec_())
