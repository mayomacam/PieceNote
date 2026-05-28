from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QAbstractItemView, QMenu, QLineEdit
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
import os
from utils.helpers import SETTINGS, log, APP_ROOT
from utils.logger import audit_log


class SidebarPanel(QWidget):
    note_open_requested = Signal(int)
    note_closed_or_deleted = Signal()
    status_message_updated = Signal(str)
    note_selection_changed = Signal(int)
    request_status_message = Signal(str, int)

    def __init__(self, storage_manager):
        super().__init__()
        self.storage = storage_manager
        self.current_folder = None
        self.folders = {}
        self.notes = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(24)

        # Folder section
        folder_frame = QFrame()
        folder_layout = QVBoxLayout(folder_frame)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(8)

        folder_header = QHBoxLayout()
        folder_label = QLabel("FOLDERS")
        folder_label.setStyleSheet("font-weight: bold; color: var(--primary); font-size: 8pt; letter-spacing: 1px;")
        folder_header.addWidget(folder_label)
        folder_header.addStretch()

        self.btn_folder_new = QPushButton()
        self.btn_folder_new.setIcon(QIcon("assets/icons/folder.svg"))
        self.btn_folder_rename = QPushButton()
        self.btn_folder_rename.setIcon(QIcon("assets/icons/actions/rename.svg"))
        self.btn_folder_del = QPushButton()
        self.btn_folder_del.setIcon(QIcon("assets/icons/actions/delete.svg"))
        for btn in [self.btn_folder_new, self.btn_folder_rename, self.btn_folder_del]:
            btn.setFixedWidth(32)
            btn.setFixedHeight(32)
            btn.setStyleSheet("QPushButton { border: none; background: transparent; padding: 4px; } QPushButton:hover { background: var(--bg-accent); border-radius: 4px; }")
            btn.setCursor(Qt.PointingHandCursor)
            folder_header.addWidget(btn)

        folder_layout.addLayout(folder_header)
        self.folder_list = QListWidget()
        folder_layout.addWidget(self.folder_list)
        main_layout.addWidget(folder_frame, stretch=2)

        # Note section
        note_frame = QFrame()
        note_layout = QVBoxLayout(note_frame)
        note_layout.setContentsMargins(0, 8, 0, 0)
        note_layout.setSpacing(8)

        note_header = QHBoxLayout()
        note_label = QLabel("NOTES")
        note_label.setStyleSheet("font-weight: bold; color: var(--primary); font-size: 8pt; letter-spacing: 1px;")
        note_header.addWidget(note_label)
        note_header.addStretch()

        self.btn_note_new = QPushButton()
        self.btn_note_new.setIcon(QIcon("assets/icons/note.svg"))
        self.btn_note_rename = QPushButton()
        self.btn_note_rename.setIcon(QIcon("assets/icons/actions/rename.svg"))
        self.btn_note_del = QPushButton()
        self.btn_note_del.setIcon(QIcon("assets/icons/actions/delete.svg"))
        for btn in [self.btn_note_new, self.btn_note_rename, self.btn_note_del]:
            btn.setFixedWidth(32)
            btn.setFixedHeight(32)
            btn.setStyleSheet("QPushButton { border: none; background: transparent; padding: 4px; } QPushButton:hover { background: var(--bg-accent); border-radius: 4px; }")
            btn.setCursor(Qt.PointingHandCursor)
            note_header.addWidget(btn)

        note_layout.addLayout(note_header)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter notes in folder...")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self._filter_notes)
        note_layout.addWidget(self.search_bar)

        self.note_list = QListWidget()
        self.note_list.setDragDropMode(QListWidget.InternalMove)
        self.note_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        note_layout.addWidget(self.note_list)
        main_layout.addWidget(note_frame, stretch=3)

        self.load_data_from_storage()
        self._populate_folder_list()

        # Select the first folder or handle no folders
        if self.folder_list.count() > 0:
            self.folder_list.setCurrentRow(0)
        else:
            self._on_folder_selection_changed()

        # Button connections
        self.btn_folder_new.clicked.connect(self.create_folder)
        self.btn_folder_rename.clicked.connect(self._rename_folder)
        self.btn_folder_del.clicked.connect(self._delete_folder)
        self.btn_note_new.clicked.connect(self.create_note)
        self.btn_note_rename.clicked.connect(self._rename_note)
        self.btn_note_del.clicked.connect(self._delete_notes)

        # Selection signals
        self.folder_list.itemSelectionChanged.connect(self._on_folder_selection_changed)
        self.note_list.itemSelectionChanged.connect(self._update_button_states)
        self.note_list.itemDoubleClicked.connect(self._on_note_double_clicked)
        self.note_list.model().rowsMoved.connect(self._on_note_reordered)
        self.note_list.itemSelectionChanged.connect(self._on_note_selection_changed)

        # Context menus
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._show_folder_context_menu)
        self.note_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.note_list.customContextMenuRequested.connect(self._show_note_context_menu)

    def _on_folder_selection_changed(self):
        current_item = self.folder_list.currentItem()
        if current_item:
            self.current_folder = current_item.data(Qt.UserRole)
            folder_name = self.folders[self.current_folder]['name']
            self.status_message_updated.emit(f"  📁 {folder_name}")
            self.search_bar.clear()
            self.note_list.setEnabled(True)
            self.search_bar.setEnabled(True)

            self.note_list.setUpdatesEnabled(False)
            try:
                self._populate_note_list()
            finally:
                self.note_list.setUpdatesEnabled(True)
        else:
            self.current_folder = None
            self.note_list.clear()
            self.note_list.setEnabled(False)
            self.search_bar.setEnabled(False)
            self.status_message_updated.emit("  No folder selected")
        self._update_button_states()

    def _on_note_selection_changed(self):
        items = self.note_list.selectedItems()
        if len(items) == 1:
            self.note_selection_changed.emit(items[0].data(Qt.UserRole))
        else:
            self.note_selection_changed.emit(-1)

    def _update_button_states(self):
        folder_selected = self.folder_list.currentItem() is not None
        self.btn_folder_rename.setEnabled(folder_selected)
        self.btn_folder_del.setEnabled(folder_selected)
        self.btn_note_new.setEnabled(folder_selected)
        note_selected = len(self.note_list.selectedItems()) > 0
        self.btn_note_rename.setEnabled(len(self.note_list.selectedItems()) == 1)
        self.btn_note_del.setEnabled(note_selected)

    def _show_folder_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        rename_action = menu.addAction("Rename Folder")
        delete_action = menu.addAction("Delete Folder")
        action = menu.exec(self.folder_list.mapToGlobal(pos))
        if action == rename_action:
            self._rename_folder()
        elif action == delete_action:
            self._delete_folder()

    def _show_note_context_menu(self, pos):
        items = self.note_list.selectedItems()
        if not items:
            return
        menu = QMenu()
        rename_action = menu.addAction("Rename Note")
        rename_action.setEnabled(len(items) == 1)
        delete_action = menu.addAction(f"Delete {len(items)} Note(s)")
        action = menu.exec(self.note_list.mapToGlobal(pos))
        if action == rename_action:
            self._rename_note()
        elif action == delete_action:
            self._delete_notes()

    def load_data_from_storage(self):
        data = self.storage.load()
        self.folders = data.get("folders", {})
        self.notes = data.get("notes", {})
        if not self.folders:
            default_name = SETTINGS.get("default_folder_name", "Default")
            fid = self.storage.create_folder(default_name)
            if fid:
                self.folders[fid] = {"name": default_name, "notes": []}

    def create_folder(self, name=None, activate=True):
        if not name:
            name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
            if not ok or not name.strip():
                return

        fid = self.storage.create_folder(name)
        if fid:
            audit_log("Folder Created", f"Name: {name} (ID: {fid})")
            self.folders[fid] = {"name": name, "notes": []}
            self._populate_folder_list()
            if activate:
                self.select_folder_by_id(fid)
            self.request_status_message.emit(f"Folder '{name}' created.", 3000)
        else:
            QMessageBox.critical(self, "Error", "Failed to create folder in database.")

    def create_note(self):
        if self.current_folder is None:
            QMessageBox.warning(self, "No Folder", "Please select a folder to create a note in.")
            return

        temp_title = "Untitled Note"
        nid = self.storage.create_note(self.current_folder, temp_title)

        if nid:
            audit_log("Note Created", f"Title: {temp_title} (ID: {nid}) in Folder ID: {self.current_folder}")
            self.notes[nid] = {"title": temp_title}
            self.folders[self.current_folder]["notes"].append(nid)
            self._populate_note_list()
            self.update_folder_item_text(self.current_folder)

            for i in range(self.note_list.count()):
                item = self.note_list.item(i)
                if item.data(Qt.UserRole) == nid:
                    self.note_list.setCurrentItem(item)
                    self.note_open_requested.emit(nid)
                    break
            self.request_status_message.emit("Note created.", 3000)
        else:
            QMessageBox.critical(self, "Error", "Failed to create note in database.")

    def update_note_content(self, nid, new_body):
        if self.storage.update_note_body(nid, new_body):
            self.request_status_message.emit("Note saved.", 2000)

    def _populate_folder_list(self):
        self.folder_list.setUpdatesEnabled(False)
        self.folder_list.clear()
        for fid in sorted(self.folders.keys()):
            self._add_folder_item_to_list(fid, self.folders[fid]["name"])
        self.folder_list.setUpdatesEnabled(True)

    def _add_folder_item_to_list(self, fid, name):
        count = len(self.folders[fid].get("notes", []))
        item = QListWidgetItem(f"📁 {name}")
        item.setData(Qt.UserRole, fid)
        # Small trick for counts: add them to the right or use a custom widget
        # For simplicity, just append to text
        item.setText(f"{name} ({count})")
        self.folder_list.addItem(item)

    def _populate_note_list(self):
        self.note_list.setUpdatesEnabled(False)
        self.note_list.clear()
        if self.current_folder in self.folders:
            for i, nid in enumerate(self.folders[self.current_folder]["notes"]):
                if nid in self.notes:
                    item = QListWidgetItem(f"{self.notes[nid]['title']}")
                    item.setData(Qt.UserRole, nid)
                    self.note_list.addItem(item)
        self._filter_notes()
        self.note_list.setUpdatesEnabled(True)

    def update_folder_item_text(self, fid):
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.data(Qt.UserRole) == fid:
                count = len(self.folders[fid]["notes"])
                item.setText(f"{self.folders[fid]['name']} ({count})")
                break

    def get_note_by_id(self, nid):
        return self.notes.get(nid)

    def get_selected_note_ids(self):
        return [item.data(Qt.UserRole) for item in self.note_list.selectedItems()]

    def rename_selected_item(self):
        if self.note_list.hasFocus():
            self._rename_note()
        elif self.folder_list.hasFocus():
            self._rename_folder()

    def delete_selected_item(self):
        if self.note_list.hasFocus():
            self._delete_notes()
        elif self.folder_list.hasFocus():
            self._delete_folder()

    def _rename_folder(self):
        item = self.folder_list.currentItem()
        if not item:
            return
        fid = item.data(Qt.UserRole)
        old_name = self.folders[fid]["name"]
        new_name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            if self.storage.rename_folder(fid, new_name):
                audit_log("Folder Renamed", f"Old: {old_name} -> New: {new_name} (ID: {fid})")
                self.folders[fid]["name"] = new_name
                self.update_folder_item_text(fid)
                self.request_status_message.emit("Folder renamed.", 2000)
            else:
                QMessageBox.critical(self, "Error", "Failed to rename folder in database.")

    def _rename_note(self):
        if len(self.note_list.selectedItems()) != 1:
            return
        item = self.note_list.currentItem()
        nid = item.data(Qt.UserRole)
        old_title = self.notes[nid]["title"]
        new_title, ok = QInputDialog.getText(self, "Rename Note", "New title:", text=old_title)
        if ok and new_title.strip() and new_title != old_title:
            if self.storage.update_note_title(nid, new_title):
                audit_log("Note Renamed", f"Old: {old_title} -> New: {new_title} (ID: {nid})")
                self.notes[nid]["title"] = new_title
                self._populate_note_list()
                self.request_status_message.emit("Note renamed.", 2000)
            else:
                QMessageBox.critical(self, "Error", "Failed to rename note in database.")

    def _delete_folder(self):
        item = self.folder_list.currentItem()
        if not item:
            return
        fid = item.data(Qt.UserRole)
        folder_name = self.folders[fid]['name']
        reply = QMessageBox.question(
            self, "Delete Folder",
            f"Delete '{folder_name}' and all notes within?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            audit_log("Folder Deletion", f"Folder: {folder_name} (ID: {fid})")
            if self.storage.delete_folder(fid):
                for nid in self.folders[fid]["notes"]:
                    if nid in self.notes:
                        del self.notes[nid]
                del self.folders[fid]
                self.folder_list.takeItem(self.folder_list.row(item))
                if self.current_folder == fid:
                    self.current_folder = None
                    self.note_list.clear()
                    self.note_closed_or_deleted.emit()
                self._update_button_states()
                self.request_status_message.emit("Folder deleted.", 3000)
            else:
                QMessageBox.critical(self, "Error", "Failed to delete folder from database.")

    def _delete_notes(self):
        items = self.note_list.selectedItems()
        if not items:
            return
        note_count = len(items)
        reply = QMessageBox.question(
            self, "Delete Notes", f"Delete {note_count} note(s)?", QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            ids_to_remove = [item.data(Qt.UserRole) for item in items]
            audit_log("Note Deletion", f"Note IDs: {ids_to_remove}")

            if self.storage.delete_notes(ids_to_remove):
                folder_notes = self.folders[self.current_folder]["notes"]
                for nid in ids_to_remove:
                    if nid in self.notes:
                        del self.notes[nid]
                self.folders[self.current_folder]["notes"] = [
                    nid for nid in folder_notes if nid not in ids_to_remove
                ]
                self._populate_note_list()
                self.update_folder_item_text(self.current_folder)
                self.note_closed_or_deleted.emit()
                self._update_button_states()
                self.request_status_message.emit(f"{note_count} note(s) deleted.", 3000)
            else:
                QMessageBox.critical(self, "Error", "Failed to delete notes from database.")

    def _on_note_double_clicked(self, item):
        self.note_open_requested.emit(item.data(Qt.UserRole))

    def _on_note_reordered(self, parent, start, end, dest, row):
        if self.current_folder is None:
            return
        new_order = [self.note_list.item(i).data(Qt.UserRole) for i in range(self.note_list.count())]
        if self.storage.reorder_notes(self.current_folder, new_order):
            self.folders[self.current_folder]["notes"] = new_order
            self.request_status_message.emit("Notes reordered.", 2000)
        else:
            QMessageBox.critical(self, "Error", "Failed to save new order.")

    def _filter_notes(self):
        query = self.search_bar.text().lower()
        self.note_list.setUpdatesEnabled(False)
        for i in range(self.note_list.count()):
            item = self.note_list.item(i)
            item.setHidden(query not in item.text().lower())
        self.note_list.setUpdatesEnabled(True)

    def select_folder_by_id(self, folder_id_to_select):
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.data(Qt.UserRole) == folder_id_to_select:
                self.folder_list.setCurrentItem(item)
                return
