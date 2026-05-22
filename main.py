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

    password, ok = QInputDialog.getText(
        None, "Master Password",
        "Enter Master Password to Unlock Database:",
        QLineEdit.Password
    )

    if not ok or not password:
        sys.exit(0)

    # Decrypt if necessary
    try:
        temp_storage = StorageManager(DB_FILE_PATH)
        temp_storage.decrypt_database(password)
    except Exception as e:
        # If it was already decrypted (SQLite header), this might fail or do nothing.
        # But if it fails because of wrong password, we should catch it.
        # SQLite header is "SQLite format 3\x00"
        with open(DB_FILE_PATH, 'rb') as f:
            header = f.read(16)
        if not header.startswith(b'SQLite format 3'):
             log.error(f"Failed to unlock database: {e}")
             QMessageBox.critical(None, "Unlock Failed", f"Incorrect password or corrupted database: {e}")
             sys.exit(1)

    window = PieceNoteMainWindow()
    window.master_password = password # Pass it to window for encryption on close
    window.show()

    exit_code = app.exec()

    # Encrypt on shutdown
    if window.storage and window.master_password:
        window.storage.encrypt_database(window.master_password)

    audit_log("Application Exiting")
    sys.exit(exit_code)