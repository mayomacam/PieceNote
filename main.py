# main.py
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from gui.main_window import PieceNoteMainWindow
from gui.password_dialog import PasswordDialog
from features.storage import StorageManager, DatabaseCorruptError
from utils.helpers import STYLE_SHEET_PATH, APP_ROOT, DB_FILE_PATH, log
from utils.logger import audit_log
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

    # --- Authentication Flow ---
    db_exists = os.path.exists(DB_FILE_PATH)
    mode = "login" if db_exists else "setup"

    auth_dlg = PasswordDialog(mode=mode)
    if auth_dlg.exec():
        password = auth_dlg.get_password()
        try:
            storage = StorageManager(password=password)
            audit_log("User Authenticated", "Database unlocked successfully.")
            window = PieceNoteMainWindow(storage=storage)
            window.show()
            sys.exit(app.exec())
        except DatabaseCorruptError:
            audit_log("Authentication Failed", "Invalid password or corrupt database.")
            QMessageBox.critical(None, "Access Denied", "Invalid password or the database is corrupt.")
            sys.exit(1)
        except Exception as e:
            log.error(f"Unexpected error during startup: {e}")
            sys.exit(1)
    else:
        audit_log("Authentication Cancelled")
        sys.exit(0)