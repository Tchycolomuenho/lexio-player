"""Generate icon.ico (multi-size) for Lexio Player."""
import os, sys
os.chdir(r'C:\Users\tchic\lexio-player')

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QRadialGradient, QIcon
from PyQt5.QtCore import Qt, QBuffer, QByteArray

app = QApplication(sys.argv)


def make_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    g = QRadialGradient(128 * s, 128 * s, 128 * s)
    g.setColorAt(0, QColor(167, 124, 252))
    g.setColorAt(1, QColor(139, 92, 246).darker(130))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawEllipse(int(4 * s), int(4 * s), int(248 * s), int(248 * s))
    pen = QPen(QColor(255, 255, 255), max(2, int(24 * s)), Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    lx, ly, lw, lh = 85 * s, 72 * s, 95 * s, 112 * s
    p.drawLine(int(lx), int(ly), int(lx), int(ly + lh))
    p.drawLine(int(lx), int(ly + lh - 24 * s), int(lx + lw), int(ly + lh - 24 * s))
    p.end()
    return pm


# Save a PNG preview of the largest size
big = make_pixmap(256)
big.save('icon.png', 'PNG')
print('icon.png created')

# Build multi-size ICO manually from PNG-encoded entries
import struct
sizes = [16, 24, 32, 48, 64, 128, 256]
images = []
for sz in sizes:
    pm = make_pixmap(sz)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, 'PNG')
    buf.close()
    images.append((sz, bytes(ba)))

header = struct.pack('<HHH', 0, 1, len(images))
offset = 6 + 16 * len(images)
entries = b''
data = b''
for sz, png in images:
    w = 0 if sz >= 256 else sz
    h = 0 if sz >= 256 else sz
    entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(png), offset)
    data += png
    offset += len(png)

with open('icon.ico', 'wb') as f:
    f.write(header + entries + data)
print('icon.ico created, size =', os.path.getsize('icon.ico'))
print('DONE')
