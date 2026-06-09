"""Generate icon.ico"""
import sys
# Force Python path
sys.path.insert(0, r"C:\Users\tchic\AppData\Roaming\Python\Python314\site-packages")
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QRadialGradient
from PyQt5.QtCore import Qt
import struct, os
os.chdir(r"C:\Users\tchic\lexio-player")

pm = QPixmap(256, 256)
pm.fill(Qt.transparent)
p = QPainter(pm)
p.setRenderHint(p.Antialiasing)
g = QRadialGradient(128, 128, 128)
g.setColorAt(0, QColor(167, 124, 252))
g.setColorAt(1, QColor(139, 92, 246).darker(130))
p.setBrush(g)
p.setPen(Qt.NoPen)
p.drawEllipse(4, 4, 248, 248)
p.setPen(QPen(QColor(255,255,255), 24, Qt.SolidLine, Qt.RoundCap))
lx, ly, lw, lh = 85, 72, 95, 112
p.drawLine(lx, ly, lx, ly + lh)
p.drawLine(lx, ly + lh - 24, lx + lw, ly + lh - 24)
p.end()
pm.save("icon.png", "PNG")
print("icon.png created")
with open("icon.png", "rb") as f:
    png_data = f.read()
header = struct.pack("<HHH", 0, 1, 1)
entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_data), 22)
with open("icon.ico", "wb") as f:
    f.write(header + entry + png_data)
print("icon.ico created")
print("DONE")
