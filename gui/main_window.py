from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMessageBox, QFileDialog, QLabel, QTabWidget
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QSettings

from gui.sidebar_panel import SidebarPanel
from gui.editor_panel import EditorPanel
from gui.settings_dialog import SettingsDialog
from features.storage import StorageManager, DatabaseCorruptError
from utils.helpers import SETTINGS, get_settings, log
from features.export import export_notes_to_file
from gui.search_dialog import SearchDialog
from gui.help_dialogs import MarkdownGuideDialog


class PieceNoteMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PieceNote - The Pentester's Companion V1.0")
        self.setGeometry(100, 100, 1200, 760)

        # A dictionary to keep track of open tabs: {note_id: editor_widget}
        self.open_tabs = {}

        try:
            self.storage = StorageManager()
            self.sidebar = SidebarPanel(self.storage)
        except DatabaseCorruptError:
            self.handle_db_corruption()
            return

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)

        self.placeholder_label = QLabel("Double-click a note in the sidebar to open it.")
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.tab_widget.addTab(self.placeholder_label, "")
        self.tab_widget.tabBar().setTabVisible(0, False)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.tab_widget)
        self.setCentralWidget(self.splitter)

        # Setup the detailed, multi-part status bar
        self.status_folder_label = QLabel("No folder selected")
        self.status_note_label = QLabel("No note open")
        self.status_metrics_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_folder_label)
        self.statusBar().addPermanentWidget(QLabel(" | "))
        self.statusBar().addPermanentWidget(self.status_note_label, 1) # Give it stretch
        self.statusBar().addPermanentWidget(self.status_metrics_label)

        # --- Signal Connections ---
        self.sidebar.note_open_requested.connect(self.open_note_in_tab)
        self.sidebar.request_status_message.connect(self.statusBar().showMessage)
        self.sidebar.status_message_updated.connect(self.status_folder_label.setText)

        self.tab_widget.tabCloseRequested.connect(self.close_note_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # Load startup settings
        self.settings = SETTINGS
        self._create_menu_bar()
        self._restore_window_state()
        self.statusBar().showMessage("Ready", 3000)

    def apply_live_settings(self):
        """Applies settings that can be changed without a restart."""
        self.settings = get_settings()
        # The ONLY live setting is the autosave interval
        autosave_ms = self.settings.get("autosave_interval_seconds", 30) * 1000
        for editor in self.open_tabs.values():
            editor.autosave_timer.setInterval(autosave_ms)
        log.info(f"Live settings applied. New autosave interval: {autosave_ms}ms.")

    def open_note_in_tab(self, note_id):
        if note_id in self.open_tabs:
            self.tab_widget.setCurrentWidget(self.open_tabs[note_id])
            return

        note = self.sidebar.get_note_by_id(note_id)
        if note is None:
            QMessageBox.warning(self, "Open Note", f"Note with ID {note_id} not found.")
            return

        editor = EditorPanel(self)
        # Apply the startup settings (including font) to the new editor
        editor.apply_settings(self.settings)
        editor.note_saved.connect(self.sidebar.update_note_content)
        editor.metrics_updated.connect(self.update_metrics)
        editor.load_note(note_id, note["title"], note["body"])

        index = self.tab_widget.addTab(editor, note["title"])
        self.tab_widget.setCurrentIndex(index)
        self.open_tabs[note_id] = editor
        self.tab_widget.setTabVisible(0, False)

    def close_note_tab(self, index):
        editor = self.tab_widget.widget(index)
        if not isinstance(editor, EditorPanel):
            return

        editor._autosave()
        del self.open_tabs[editor.current_note_id]
        self.tab_widget.removeTab(index)

        if len(self.open_tabs) == 0:
            self.tab_widget.setTabVisible(0, True)
            self.on_tab_changed(-1) # Update status bar to empty state

    def on_tab_changed(self, index):
        editor = self.tab_widget.currentWidget()
        if isinstance(editor, EditorPanel):
            title = self.tab_widget.tabText(index)
            self.status_note_label.setText(f"Editing: {title}")
            editor.calculate_metrics()
        else:
            self.status_note_label.setText("No note open")
            self.status_metrics_label.setText("")

    def update_metrics(self, metrics):
        active_editor = self.tab_widget.currentWidget()
        if isinstance(active_editor, EditorPanel) and active_editor == self.sender():
            text = (f"W: {metrics['words']} | C: {metrics['chars']} | L: {metrics['lines']} | "
                    f"Img: {metrics['images']} | Links: {metrics['links']}")
            self.status_metrics_label.setText(text)

    def _export_current_note(self):
        editor = self.tab_widget.currentWidget()
        if not isinstance(editor, EditorPanel):
            QMessageBox.warning(self, "Export Error", "No note tab is currently active.")
            return
        note_id = editor.current_note_id
        self._run_export([self.sidebar.get_note_by_id(note_id)], single_file=True)

    def handle_db_corruption(self):
        self.storage = None
        reply = QMessageBox.critical(
            self,
            "Database Error",
            "Database is corrupt.\n\nRestore from backup?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if StorageManager().restore_from_backup():
                QMessageBox.information(self, "Success", "Database restored. Application will restart.")
            else:
                QMessageBox.warning(self, "Restore Failed", "No backup file was found.")
        self.close()

    def _create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction("New Folder...", self.sidebar.create_folder, "Ctrl+Shift+N")
        file_menu.addAction("New Note", self.sidebar.create_note, "Ctrl+N")
        file_menu.addSeparator()
        file_menu.addAction("Save All", self.sidebar.save_data_to_storage, "Ctrl+S")
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("Export")
        export_menu.addAction("Export Current Note...", self._export_current_note)
        export_menu.addAction("Export Selected Notes...", self._export_selected_notes)
        export_menu.addAction("Export Entire Folder...", self._export_current_folder)
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
        help_menu.addSeparator()
        help_menu.addAction("About", self.show_about)

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def show_about(self):
        about_text = """
        <h2>PieceNote V1.0</h2>
        <p><b>The Pentester's Companion</b></p>
        <p>
            PieceNote is a lightweight, offline-first note-taking application
            designed to solve the "single messy file" problem during penetration tests.
            It provides a structured environment for logging commands, documenting findings,
            and progressively building a report.
        </p>

        <h3>Core Features:</h3>
        <ul>
            <li>Robust SQLite database backend with automatic backups.</li>
            <li>Multi-tab editor with a live Markdown preview.</li>
            <li>Interactive checklists and support for collapsible sections.</li>
            <li>Pentester tool integration via a threaded command runner.</li>
            <li>Professional HTML/PDF export for easy reporting.</li>
            <li>Full-text search of note content.</li>
        </ul>

        <h3>Technologies Used:</h3>
        <p>
            <code>Python 3</code>, <code>PySide6 (Qt 6)</code>, <code>SQLite</code>,
            <code>Markdown</code>, <code>Pygments</code>, <code>pymdown-extensions</code>
        </p>

        <p>Created by <b>Mayomacam</b>.</p>
        """
        QMessageBox.about(self, "About PieceNote", about_text)

    def show_markdown_guide(self):
        dialog = MarkdownGuideDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Exit",
            "Save all changes before exiting?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        if reply == QMessageBox.Cancel:
            event.ignore()
            return

        if self.storage: # Ensure storage was initialized before trying to save
            if reply == QMessageBox.Yes:
                for editor in self.open_tabs.values():
                    editor._autosave()
                self.sidebar.save_data_to_storage()
            self._save_window_state()

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
            self.splitter.setSizes([350, 850])

    def open_search_dialog(self):
        dialog = SearchDialog(self.storage, self)
        dialog.result_activated.connect(self.handle_search_result)
        dialog.exec()

    def handle_search_result(self, note_id, folder_id):
        self.sidebar.select_folder_by_id(folder_id)
        self.open_note_in_tab(note_id)

    def _export_selected_notes(self):
        selected_items = self.sidebar.note_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Export Error", "No notes selected.")
            return
        self._run_export(
            [self.sidebar.get_note_by_id(item.data(Qt.UserRole)) for item in selected_items]
        )

    def _export_current_folder(self):
        folder_id = self.sidebar.current_folder
        if folder_id is None:
            QMessageBox.warning(self, "Export Error", "No folder selected.")
            return
        note_ids_in_order = self.sidebar.folders[folder_id]["notes"]
        notes_to_export = [self.sidebar.get_note_by_id(nid) for nid in note_ids_in_order]
        folder_name = self.sidebar.folders[folder_id]["name"]
        self._run_export(notes_to_export, single_file=True, default_filename=folder_name)

    def _run_export(self, notes_list, single_file=False, default_filename="export"):
        if not notes_list:
            return
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export As",
            default_filename,
            "HTML (*.html);;PDF (*.pdf);;Markdown (*.md)"
        )
        if not file_path:
            return

        file_format = "html"
        if "pdf" in selected_filter:
            file_format = "pdf"
        elif "md" in selected_filter:
            file_format = "md"

        try:
            export_notes_to_file(file_path, notes_list, file_format, single_file)
            self.statusBar().showMessage(f"Successfully exported to {file_path}", 5000)
        except Exception as e:
            log.error(f"Export failed: {e}")
            QMessageBox.critical(self, "Export Failed", f"An error occurred during export:\n{e}")