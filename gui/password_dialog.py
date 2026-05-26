from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import os
from utils.helpers import APP_ROOT

class PasswordDialog(QDialog):
    def __init__(self, parent=None, mode="login"):
        super().__init__(parent)
        self.mode = mode # "login" or "setup"
        self.password = None
        self.setWindowTitle("PieceNote - Authentication")
        self.setFixedWidth(350)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("Secure Vault Access")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        msg = "Enter your master password to unlock the database."
        if mode == "setup":
            msg = "Set a master password to encrypt your notes."

        info = QLabel(msg)
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Password")
        self.password_input.returnPressed.connect(self.accept)
        layout.addWidget(self.password_input)

        if mode == "setup":
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.Password)
            self.confirm_input.setPlaceholderText("Confirm Password")
            self.confirm_input.returnPressed.connect(self.accept)
            layout.addWidget(self.confirm_input)

        btn_layout = QHBoxLayout()
        self.btn_submit = QPushButton("Unlock" if mode == "login" else "Set Password")
        self.btn_submit.clicked.connect(self.accept)
        self.btn_submit.setDefault(True)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_submit)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def accept(self):
        password = self.password_input.text()
        if not password:
            QMessageBox.warning(self, "Validation Error", "Password cannot be empty.")
            return

        if self.mode == "setup":
            if password != self.confirm_input.text():
                QMessageBox.warning(self, "Validation Error", "Passwords do not match.")
                return

        self.password = password
        super().accept()

    def get_password(self):
        return self.password
