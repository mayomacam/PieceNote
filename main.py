# main.py
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from gui.main_window import PieceNoteMainWindow
from utils.helpers import STYLE_SHEET_PATH, APP_ROOT, log
import os

if __name__ == "__main__":
    QCoreApplication.setOrganizationName("PieceNote")
    QCoreApplication.setApplicationName("PieceNote")

    app = QApplication(sys.argv)

    # --- Set Application Icon ---
    icon_path = os.path.join(APP_ROOT, "assets", "icons", "icon.png") # Assuming you create this file
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    try:
        with open(STYLE_SHEET_PATH, "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        log.warning(f"Stylesheet not found at: {STYLE_SHEET_PATH}")

    window = PieceNoteMainWindow()
    window.show()
    sys.exit(app.exec())