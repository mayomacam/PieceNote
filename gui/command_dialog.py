from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox
from PySide6.QtCore import Qt

class RunCommandDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run Shell Command")

        self.layout = QVBoxLayout(self)

        self.label = QLabel("Enter the command to execute and capture its output:")
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("e.g., ls -l or ping -c 1 google.com")

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.command_input)
        self.layout.addWidget(self.buttons)

        self.resize(400, 100)

    def get_command(self):
        """Returns the command entered by the user."""
        return self.command_input.text()