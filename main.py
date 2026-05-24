# main.py
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from gui.main_window import PieceNoteMainWindow
from gui.password_dialog import PasswordDialog
from utils.helpers import STYLE_SHEET_PATH, APP_ROOT, log, DB_FILE_PATH
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

    # Master Password Authentication
    mode = "login" if os.path.exists(DB_FILE_PATH) else "setup"
    pwd_dlg = PasswordDialog(mode=mode)
    if pwd_dlg.exec():
        password = pwd_dlg.get_password()
        if not password:
            sys.exit(0)
    else:
        sys.exit(0)

    try:
        window = PieceNoteMainWindow(password=password)
        window.show()
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Fatal Error", f"Failed to initialize application: {e}")
        sys.exit(1)

    sys.exit(app.exec())