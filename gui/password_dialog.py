from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt

class PasswordDialog(QDialog):
    def __init__(self, parent=None, mode="login"):
        super().__init__(parent)
        self.setWindowTitle("PieceNote Security")
        self.setFixedWidth(350)
        self.password = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        if mode == "login":
            self.label = QLabel("Enter Master Password to Unlock:")
        else:
            self.label = QLabel("Set a new Master Password for Encryption:")

        self.label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Master Password")
        layout.addWidget(self.password_input)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("Unlock" if mode == "login" else "Set Password")
        self.btn_cancel = QPushButton("Cancel")
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.password_input.returnPressed.connect(self.accept)

    def get_password(self):
        return self.password_input.text()
