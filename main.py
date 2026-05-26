# main.py
import sys
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from gui.main_window import PieceNoteMainWindow
from utils.helpers import STYLE_SHEET_PATH, APP_ROOT, log, DB_FILE_PATH
from features.storage import StorageManager
from utils.logger import audit_log
import os

if __name__ == "__main__":
    audit_log("Application Starting")
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

    # Check if database is encrypted
    is_encrypted = False
    if os.path.exists(DB_FILE_PATH):
        with open(DB_FILE_PATH, 'rb') as f:
            header = f.read(16)
        if not header.startswith(b'SQLite format 3'):
            is_encrypted = True

    password = None
    if is_encrypted or not os.path.exists(DB_FILE_PATH):
        password, ok = QInputDialog.getText(
            None, "Master Password",
            "Enter Master Password to Unlock/Create Database:",
            QLineEdit.Password
        )

        if not ok or not password:
            sys.exit(0)

    # Initialize storage with in-memory decryption
    try:
        storage = StorageManager(DB_FILE_PATH, password)
    except Exception as e:
         log.error(f"Failed to unlock database: {e}")
         QMessageBox.critical(None, "Unlock Failed", f"Incorrect password or corrupted database: {e}")
         sys.exit(1)

    window = PieceNoteMainWindow(storage=storage)
    window.master_password = password
    window.show()

    exit_code = app.exec()

    # Securely save and encrypt to disk on shutdown
    if window.storage:
        window.storage.save_to_disk()

    audit_log("Application Exiting")
    sys.exit(exit_code)
