from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox, QLabel, QSpinBox,
    QPushButton, QFontDialog, QLineEdit, QFileDialog, QHBoxLayout, QMessageBox
)
from PySide6.QtGui import QFont
from utils.helpers import get_settings, SETTINGS_FILE_PATH, log
import json

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)

        self.settings = get_settings()
        self.original_paths = {
            "db": self.settings.get("database_path"),
            "backup": self.settings.get("backup_location")
        }

        # This will hold the font chosen by the user, but won't be applied live
        self.chosen_font = QFont(self.settings.get("editor_font_family"), self.settings.get("editor_font_size"))

        # --- UI Elements ---
        self.db_path_edit = QLineEdit()
        self.db_path_button = QPushButton("Browse...")
        db_layout = QHBoxLayout(); db_layout.addWidget(self.db_path_edit); db_layout.addWidget(self.db_path_button)
        self.backup_path_edit = QLineEdit()
        self.backup_path_button = QPushButton("Browse...")
        backup_layout = QHBoxLayout(); backup_layout.addWidget(self.backup_path_edit); backup_layout.addWidget(self.backup_path_button)
        self.default_folder_edit = QLineEdit()
        self.autosave_spinbox = QSpinBox(); self.autosave_spinbox.setRange(5, 300); self.autosave_spinbox.setSuffix(" seconds")
        self.font_button = QPushButton()

        # --- Layout ---
        form_layout = QFormLayout()
        form_layout.addRow("Database File:", db_layout)
        form_layout.addRow("Backup Location:", backup_layout)
        form_layout.addRow("Default Folder Name:", self.default_folder_edit)
        form_layout.addRow("Autosave Interval:", self.autosave_spinbox)
        form_layout.addRow("Editor Font:", self.font_button)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.restart_label = QLabel("Note: Path and Font changes will apply after restarting the application.")
        self.restart_label.setVisible(False)
        main_layout = QVBoxLayout(self); main_layout.addLayout(form_layout); main_layout.addWidget(self.restart_label); main_layout.addWidget(button_box)

        # --- Connections ---
        self.db_path_button.clicked.connect(self.select_db_file)
        self.backup_path_button.clicked.connect(self.select_backup_dir)
        self.font_button.clicked.connect(self.select_font)
        button_box.accepted.connect(self.accept); button_box.rejected.connect(self.reject)

        self.load_initial_values()

    def load_initial_values(self):
        self.db_path_edit.setText(self.settings.get("database_path"))
        self.backup_path_edit.setText(self.settings.get("backup_location"))
        self.default_folder_edit.setText(self.settings.get("default_folder_name"))
        self.autosave_spinbox.setValue(self.settings.get("autosave_interval_seconds"))
        self.update_font_button_text()

    def select_db_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select Database File", self.db_path_edit.text(), "SQLite Database (*.sqlite)")
        if path: self.db_path_edit.setText(path); self.restart_label.setVisible(True)

    def select_backup_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Backup Directory", self.backup_path_edit.text())
        if path: self.backup_path_edit.setText(path); self.restart_label.setVisible(True)

    def select_font(self):
        # --- THIS IS THE DEFINITIVE FIX ---
        font, ok = QFontDialog.getFont(self.chosen_font, self)
        # We only update our temporary font object IF the user clicked "OK".
        # This prevents any corruption from clicking "Cancel".
        if ok and isinstance(font, QFont):
            self.chosen_font = font
            self.update_font_button_text()
            self.restart_label.setVisible(True)

    def update_font_button_text(self):
        self.font_button.setText(f"{self.chosen_font.family()}, {self.chosen_font.pointSize()}pt")

    def accept(self):
        font_changed = (self.chosen_font.family() != self.settings.get("editor_font_family") or
                        self.chosen_font.pointSize() != self.settings.get("editor_font_size"))
        path_changed = (self.original_paths["db"] != self.db_path_edit.text() or
                        self.original_paths["backup"] != self.backup_path_edit.text())

        # Save all settings to the file
        self.settings["database_path"] = self.db_path_edit.text()
        self.settings["backup_location"] = self.backup_path_edit.text()
        self.settings["default_folder_name"] = self.default_folder_edit.text()
        self.settings["autosave_interval_seconds"] = self.autosave_spinbox.value()
        self.settings["editor_font_family"] = self.chosen_font.family()
        self.settings["editor_font_size"] = self.chosen_font.pointSize()

        try:
            with open(SETTINGS_FILE_PATH, 'w') as f: json.dump(self.settings, f, indent=4)
        except IOError as e: log.error(f"Error saving settings: {e}")

        if path_changed or font_changed:
            QMessageBox.information(self, "Restart Required", "Some changes (like paths or fonts) will be applied the next time you start PieceNote.")

        if hasattr(self.parent(), 'apply_live_settings'):
            self.parent().apply_live_settings()
        super().accept()