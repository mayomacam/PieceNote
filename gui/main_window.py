from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMessageBox, QFileDialog, QLabel, QTabWidget, QWidget, QVBoxLayout
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QSettings

from gui.sidebar_panel import SidebarPanel
from gui.editor_panel import EditorPanel
from gui.settings_dialog import SettingsDialog
from features.storage import StorageManager, DatabaseCorruptError
from utils.helpers import SETTINGS, get_settings, log
from utils.logger import audit_log
from features.export import export_notes_to_file
from gui.search_dialog import SearchDialog
from gui.help_dialogs import MarkdownGuideDialog


class PieceNoteMainWindow(QMainWindow):
    def __init__(self, storage=None):
        super().__init__()
        self.setWindowTitle("PieceNote")
        self.setGeometry(100, 100, 1200, 800)

        self.open_tabs = {}
        self.master_password = getattr(storage, 'password', None) if storage else None

        try:
            self.storage = storage if storage else StorageManager()
            self.sidebar = SidebarPanel(self.storage)
        except DatabaseCorruptError:
            self.handle_db_corruption()
            return

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)

        self.placeholder_label = QLabel("Select a note from the sidebar to open.")
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setStyleSheet("color: var(--text-muted); font-size: 14pt;")
        self.tab_widget.addTab(self.placeholder_label, "")
        self.tab_widget.tabBar().setTabVisible(0, False)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.tab_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.splitter)
        self.setCentralWidget(container)

        # Status Bar setup
        self.status_folder_label = QLabel("  No folder selected")
        self.status_note_label = QLabel("No note open")
        self.status_metrics_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_folder_label)
        self.statusBar().addPermanentWidget(self.status_note_label, 1)
        self.statusBar().addPermanentWidget(self.status_metrics_label)

        # Signals
        self.sidebar.note_open_requested.connect(self.open_note_in_tab)
        self.sidebar.request_status_message.connect(self.statusBar().showMessage)
        self.sidebar.status_message_updated.connect(self.status_folder_label.setText)

        self.tab_widget.tabCloseRequested.connect(self.close_note_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        self.settings = SETTINGS
        self._create_menu_bar()
        self._restore_window_state()
        self.statusBar().showMessage("Ready", 3000)

    def apply_live_settings(self):
        self.settings = get_settings()
        autosave_ms = self.settings.get("autosave_interval_seconds", 30) * 1000
        for editor in self.open_tabs.values():
            editor.autosave_timer.setInterval(autosave_ms)
        audit_log("Settings Applied", f"New autosave interval: {autosave_ms}ms")

    def open_note_in_tab(self, note_id):
        if note_id in self.open_tabs:
            self.tab_widget.setCurrentWidget(self.open_tabs[note_id])
            return

        note = self.sidebar.get_note_by_id(note_id)
        if note is None:
            return

        body = self.storage.get_note_body(note_id)

        editor = EditorPanel(self)
        editor.apply_settings(self.settings)
        editor.note_saved.connect(self.sidebar.update_note_content)
        editor.metrics_updated.connect(self.update_metrics)
        editor.load_note(note_id, note["title"], body)

        index = self.tab_widget.addTab(editor, note["title"])
        self.tab_widget.setCurrentIndex(index)
        self.open_tabs[note_id] = editor
        self.tab_widget.tabBar().setTabVisible(0, False)

    def close_note_tab(self, index):
        editor = self.tab_widget.widget(index)
        if not isinstance(editor, EditorPanel):
            return

        editor._autosave()
        del self.open_tabs[editor.current_note_id]
        self.tab_widget.removeTab(index)

        if len(self.open_tabs) == 0:
            self.tab_widget.tabBar().setTabVisible(0, True)
            self.on_tab_changed(-1)

    def on_tab_changed(self, index):
        editor = self.tab_widget.currentWidget()
        if isinstance(editor, EditorPanel):
            title = self.tab_widget.tabText(index)
            self.status_note_label.setText(f"  📝 {title}")
            editor.calculate_metrics()
        else:
            self.status_note_label.setText("  No note open")
            self.status_metrics_label.setText("")

    def update_metrics(self, metrics):
        active_editor = self.tab_widget.currentWidget()
        if isinstance(active_editor, EditorPanel) and active_editor == self.sender():
            text = (f"Words: {metrics['words']} | Chars: {metrics['chars']} | "
                    f"Images: {metrics['images']} | Links: {metrics['links']}  ")
            self.status_metrics_label.setText(text)

    def handle_db_corruption(self):
        audit_log("Database Corruption Detected")
        reply = QMessageBox.critical(
            self, "Database Error", "Database is corrupt.\n\nRestore from backup?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if StorageManager(password=self.master_password).restore_from_backup():
                QMessageBox.information(self, "Success", "Database restored. Please restart.")
        self.close()

    def _create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction("New Folder", self.sidebar.create_folder, "Ctrl+Shift+N")
        file_menu.addAction("New Note", self.sidebar.create_note, "Ctrl+N")
        file_menu.addSeparator()
        file_menu.addAction("Save to Disk", self.storage.save_to_disk, "Ctrl+S")
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("Export")
        export_menu.addAction("Current Note...", self._export_current_note)
        export_menu.addAction("Selected Notes...", self._export_selected_notes)
        export_menu.addAction("Entire Folder...", self._export_current_folder)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction("Search...", self.open_search_dialog, "Ctrl+F")
        edit_menu.addSeparator()
        edit_menu.addAction("Rename Item", self.sidebar.rename_selected_item, "F2")
        edit_menu.addAction("Delete Item", self.sidebar.delete_selected_item, "Delete")

        settings_menu = menubar.addMenu("Settings")
        settings_menu.addAction("Preferences...", self.open_settings)

        help_menu = menubar.addMenu("Help")
        help_menu.addAction("Markdown Guide", self.show_markdown_guide)
        help_menu.addAction("About", self.show_about)

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def show_about(self):
        about_text = """
        <h2>PieceNote</h2>
        <p>A professional, SOC 2 aligned note-taking application for technical reports.</p>
        <p>Built with Python and PySide6.</p>
        """
        QMessageBox.about(self, "About PieceNote", about_text)

    def show_markdown_guide(self):
        dialog = MarkdownGuideDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        unsaved_editors = [e for e in self.open_tabs.values() if e._is_modified]
        if unsaved_editors:
            reply = QMessageBox.question(
                self, "Exit", "Save changes before exiting?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes:
                for editor in unsaved_editors: editor._autosave()

        if self.storage:
            self._save_window_state()
            self.storage.save_to_disk()
        event.accept()

    def _save_window_state(self):
        settings = QSettings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("splitterSizes", self.splitter.saveState())

    def _restore_window_state(self):
        settings = QSettings()
        if settings.value("geometry"):
            self.restoreGeometry(settings.value("geometry"))
        if settings.value("windowState"):
            self.restoreState(settings.value("windowState"))
        if settings.value("splitterSizes"):
            self.splitter.restoreState(settings.value("splitterSizes"))
        else:
            self.splitter.setSizes([300, 900])

    def open_search_dialog(self):
        dialog = SearchDialog(self.storage, self)
        dialog.result_activated.connect(self.handle_search_result)
        dialog.exec()

    def handle_search_result(self, note_id, folder_id):
        self.sidebar.select_folder_by_id(folder_id)
        self.open_note_in_tab(note_id)

    def _export_current_note(self):
        editor = self.tab_widget.currentWidget()
        if isinstance(editor, EditorPanel):
            self._run_export([self.sidebar.get_note_by_id(editor.current_note_id)], single_file=True)

    def _export_selected_notes(self):
        selected_ids = self.sidebar.get_selected_note_ids()
        if selected_ids:
            self._run_export([self.sidebar.get_note_by_id(nid) for nid in selected_ids])

    def _export_current_folder(self):
        fid = self.sidebar.current_folder
        if fid:
            notes = [self.sidebar.get_note_by_id(nid) for nid in self.sidebar.folders[fid]["notes"]]
            self._run_export(notes, single_file=True, default_filename=self.sidebar.folders[fid]["name"])

    def _run_export(self, notes_list, single_file=False, default_filename="export"):
        if not notes_list: return
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export As", default_filename, "HTML (*.html);;PDF (*.pdf);;Markdown (*.md)"
        )
        if not file_path: return

        file_format = "html"
        if "pdf" in selected_filter: file_format = "pdf"
        elif "md" in selected_filter: file_format = "md"

        try:
            export_notes_to_file(file_path, notes_list, file_format, single_file)
            self.statusBar().showMessage(f"Successfully exported to {file_path}", 5000)
            audit_log("Data Export", f"Exported {len(notes_list)} note(s) to {file_path}")
        except Exception as e:
            log.error(f"Export failed: {e}")
            QMessageBox.critical(self, "Export Failed", str(e))
