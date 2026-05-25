from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import os
from utils.helpers import APP_ROOT

class MasterPasswordDialog(QDialog):
    def __init__(self, parent=None, confirm_mode=False):
        super().__init__(parent)
        self.confirm_mode = confirm_mode
        self.setWindowTitle("PieceNote - Authentication")
        self.setFixedSize(400, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # Icon and Header
        header_label = QLabel("Enter Master Password")
        header_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #007acc;")
        layout.addWidget(header_label, alignment=Qt.AlignCenter)

        if self.confirm_mode:
            sub_label = QLabel("Set a new master password for your encrypted database.")
        else:
            sub_label = QLabel("Unlock your notes with your master password.")
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("color: #888;")
        layout.addWidget(sub_label, alignment=Qt.AlignCenter)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Password")
        self.password_input.setStyleSheet("padding: 8px; font-size: 11pt;")
        layout.addWidget(self.password_input)

        if self.confirm_mode:
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.Password)
            self.confirm_input.setPlaceholderText("Confirm Password")
            self.confirm_input.setStyleSheet("padding: 8px; font-size: 11pt;")
            layout.addWidget(self.confirm_input)
            self.setFixedSize(400, 240)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.handle_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Set Icon if available
        icon_path = os.path.join(APP_ROOT, "assets", "icons", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def handle_accept(self):
        password = self.password_input.text()
        if not password:
            QMessageBox.warning(self, "Error", "Password cannot be empty.")
            return

        if self.confirm_mode:
            if password != self.confirm_input.text():
                QMessageBox.warning(self, "Error", "Passwords do not match.")
                return

        self.accept()

    def get_password(self):
        return self.password_input.text()
