"""Test if QAxContainer + WMP works"""
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget

app = QApplication(sys.argv)
try:
    wmp = QAxWidget("WMPlayer.OCX")
    print("WMPlayer.OCX: OK")
    # Test getting a property
    version = wmp.dynamicCall("versionInfo")
    print(f"WMP version: {version}")
except Exception as e:
    print(f"WMP failed: {e}")
    # Try fallback
    try:
        wmp = QAxWidget("{6BF52A52-394A-11D3-B153-00C04F79FAA6}")
        print("WMP CLSID: OK")
    except Exception as e2:
        print(f"WMP CLSID failed: {e2}")
