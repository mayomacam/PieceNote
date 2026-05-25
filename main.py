# main.py
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from gui.main_window import PieceNoteMainWindow
from gui.password_dialog import MasterPasswordDialog
from utils.helpers import STYLE_SHEET_PATH, APP_ROOT, log, DB_FILE_PATH
import os

if __name__ == "__main__":
    QCoreApplication.setOrganizationName("PieceNote")
    QCoreApplication.setApplicationName("PieceNote")

    app = QApplication(sys.argv)

    # --- Set Application Icon ---
    icon_path = os.path.join(APP_ROOT, "assets", "icons", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    try:
        with open(STYLE_SHEET_PATH, "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        log.warning(f"Stylesheet not found at: {STYLE_SHEET_PATH}")

    # SOC 2: Require Authentication on Startup
    is_new_db = not os.path.exists(DB_FILE_PATH)
    pwd_dialog = MasterPasswordDialog(confirm_mode=is_new_db)

    if pwd_dialog.exec():
        password = pwd_dialog.get_password()
        try:
            window = PieceNoteMainWindow(password=password)
            window.show()
            sys.exit(app.exec())
        except Exception as e:
            log.critical(f"Failed to start application: {e}")
    else:
        sys.exit(0)