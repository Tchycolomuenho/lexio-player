#!/bin/bash
# Build Lexio Player as a standalone Windows .exe
# Usage: ./build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Lexio Player Builder ==="
echo

# Clean previous build
echo "[1/4] Cleaning previous builds..."
rm -rf build dist lexio_player.spec

# Generate icon (PNG from Python)
echo "[2/4] Generating icon..."
python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (0,0,0,0))
draw = ImageDraw.Draw(img)

# Circle
cx, cy, r = 128, 128, 120
draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(139, 92, 246))

# Letter L
l_l, l_t, l_r, l_b = 75, 65, 175, 165
# Vertical line
draw.rectangle([l_l, l_t, l_l+20, l_b], fill=(255,255,255))
# Horizontal line
draw.rectangle([l_l, l_b-20, l_r, l_b], fill=(255,255,255))

# Save as ICO
img.save('icon.png', 'PNG')
# Create ICO using PIL (simple approach - just use PNG)
print('Icon generated')
"

echo "[3/4] Building with PyInstaller..."
pyinstaller --noconfirm \
    --onefile \
    --windowed \
    --name "LexioPlayer" \
    --add-data "icon.png:." \
    --clean \
    --hidden-import "PyQt5.QtMultimedia" \
    --hidden-import "cv2" \
    --hidden-import "numpy" \
    --hidden-import "PIL" \
    --collect-all "PyQt5" \
    lexio_player.py

echo
echo "[4/4] Build complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Output: dist/LexioPlayer.exe"
ls -lh dist/LexioPlayer.exe 2>/dev/null || echo "(not found)"
echo

echo "=== Done ==="
