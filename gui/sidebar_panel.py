from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QAbstractItemView, QMenu, QLineEdit
)
from PySide6.QtCore import Qt, Signal
from utils.helpers import SETTINGS, log


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
        self.next_folder_id = 1
        self.next_note_id = 1

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Folder section
        folder_frame = QFrame()
        folder_layout = QVBoxLayout(folder_frame)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_header = QHBoxLayout()
        folder_header.addWidget(QLabel("Folders"))
        folder_header.addStretch()
        self.btn_folder_new = QPushButton("＋")
        self.btn_folder_rename = QPushButton("✏")
        self.btn_folder_del = QPushButton("🗑")
        folder_header.addWidget(self.btn_folder_new)
        folder_header.addWidget(self.btn_folder_rename)
        folder_header.addWidget(self.btn_folder_del)
        folder_layout.addLayout(folder_header)
        self.folder_list = QListWidget()
        folder_layout.addWidget(self.folder_list)
        main_layout.addWidget(folder_frame, stretch=1)

        # Note section
        note_frame = QFrame()
        note_layout = QVBoxLayout(note_frame)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_header = QHBoxLayout()
        note_header.addWidget(QLabel("Notes"))
        note_header.addStretch()
        self.btn_note_new = QPushButton("＋")
        self.btn_note_rename = QPushButton("✏")
        self.btn_note_del = QPushButton("🗑")
        note_header.addWidget(self.btn_note_new)
        note_header.addWidget(self.btn_note_rename)
        note_header.addWidget(self.btn_note_del)
        note_layout.addLayout(note_header)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search notes...")
        self.search_bar.textChanged.connect(self._filter_notes)
        note_layout.addWidget(self.search_bar)
        self.note_list = QListWidget()
        self.note_list.setDragDropMode(QListWidget.InternalMove)
        self.note_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        note_layout.addWidget(self.note_list)
        main_layout.addWidget(note_frame, stretch=2)

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
        """Handles folder selection and deselection to manage UI state."""
        current_item = self.folder_list.currentItem()
        if current_item:
            self.current_folder = current_item.data(Qt.UserRole)
            folder_name = self.folders[self.current_folder]['name']
            self.status_message_updated.emit(f"Folder: {folder_name}")
            self.search_bar.clear()
            self.note_list.setEnabled(True)
            self.search_bar.setEnabled(True)
            self._populate_note_list()
        else:
            self.current_folder = None
            self.note_list.clear()
            self.note_list.setEnabled(False)
            self.search_bar.setEnabled(False)
            self.status_message_updated.emit("No folder selected")
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
        self.folders = {int(k): v for k, v in data.get("folders", {}).items()}
        self.notes = {int(k): v for k, v in data.get("notes", {}).items()}
        self.next_folder_id = data.get("next_folder_id", 1)
        self.next_note_id = data.get("next_note_id", 1)
        if not self.folders:
            fid = self.next_folder_id
            self.next_folder_id += 1
            default_name = SETTINGS.get("default_folder_name", "Default")
            self.folders[fid] = {"name": default_name, "notes": []}
            self.save_data_to_storage()

    def save_data_to_storage(self):
        data = {
            "folders": self.folders,
            "notes": self.notes,
            "next_folder_id": self.next_folder_id,
            "next_note_id": self.next_note_id,
        }
        if self.storage.save(data):
            self.request_status_message.emit("All data saved.", 3000)
        else:
            self.request_status_message.emit("Failed to save data.", 5000)

    def create_folder(self, name=None, activate=True):
        if not name:
            name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
        if not name or not ok or not name.strip():
            return
        fid = self.next_folder_id
        self.next_folder_id += 1
        self.folders[fid] = {"name": name, "notes": []}
        self._add_folder_item_to_list(fid, name)
        if activate:
            self.folder_list.setCurrentRow(self.folder_list.count() - 1)
        self.save_data_to_storage()

    def create_note(self):
        if self.current_folder is None:
            QMessageBox.warning(self, "No Folder", "Please select a folder to create a note in.")
            return
        nid = self.next_note_id
        self.next_note_id += 1
        title = f"Untitled Note {nid}"
        self.notes[nid] = {"title": title, "body": ""}
        self.folders[self.current_folder]["notes"].append(nid)
        self._populate_note_list()
        self.update_folder_item_text(self.current_folder)
        self.save_data_to_storage()
        for i in range(self.note_list.count()):
            item = self.note_list.item(i)
            if item.data(Qt.UserRole) == nid:
                self.note_list.setCurrentItem(item)
                self.note_open_requested.emit(nid)
                break

    def update_note_content(self, nid, new_body):
        if nid in self.notes:
            self.notes[nid]["body"] = new_body
            self.save_data_to_storage()

    def _populate_folder_list(self):
        self.folder_list.clear()
        for fid in sorted(self.folders.keys()):
            self._add_folder_item_to_list(fid, self.folders[fid]["name"])

    def _add_folder_item_to_list(self, fid, name):
        count = len(self.folders[fid].get("notes", []))
        item = QListWidgetItem(f"📁 {name} ({count})")
        item.setData(Qt.UserRole, fid)
        self.folder_list.addItem(item)

    def _populate_note_list(self):
        self.note_list.clear()
        if self.current_folder in self.folders:
            for i, nid in enumerate(self.folders[self.current_folder]["notes"]):
                if nid in self.notes:
                    item = QListWidgetItem(f"#{i+1:02d} - {self.notes[nid]['title']}")
                    item.setData(Qt.UserRole, nid)
                    self.note_list.addItem(item)
        self._filter_notes()

    def update_folder_item_text(self, fid):
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.data(Qt.UserRole) == fid:
                count = len(self.folders[fid]["notes"])
                item.setText(f"📁 {self.folders[fid]['name']} ({count})")
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
            self.folders[fid]["name"] = new_name
            self.update_folder_item_text(fid)
            self.save_data_to_storage()

    def _rename_note(self):
        if len(self.note_list.selectedItems()) != 1:
            return
        item = self.note_list.currentItem()
        nid = item.data(Qt.UserRole)
        old_title = self.notes[nid]["title"]
        new_title, ok = QInputDialog.getText(self, "Rename Note", "New title:", text=old_title)
        if ok and new_title.strip() and new_title != old_title:
            self.notes[nid]["title"] = new_title
            self._populate_note_list()
            self.save_data_to_storage()

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
            for nid in self.folders[fid]["notes"]:
                if nid in self.notes:
                    del self.notes[nid]
            del self.folders[fid]
            self.folder_list.takeItem(self.folder_list.row(item))
            if self.current_folder == fid:
                self.current_folder = None
                self.note_list.clear()
                self.note_closed_or_deleted.emit()
            self.save_data_to_storage()
            self._update_button_states()

    def _delete_notes(self):
        items = self.note_list.selectedItems()
        if not items:
            return
        note_count = len(items)
        if note_count == 1:
            note_title = items[0].text().split(' - ', 1)[-1]
            question = f"Delete '{note_title}'?"
        else:
            question = f"Delete {note_count} notes?"
        reply = QMessageBox.question(
            self, "Delete Notes", question, QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            folder_notes = self.folders[self.current_folder]["notes"]
            ids_to_remove = {item.data(Qt.UserRole) for item in items}
            for nid in ids_to_remove:
                if nid in self.notes:
                    del self.notes[nid]
            self.folders[self.current_folder]["notes"] = [
                nid for nid in folder_notes if nid not in ids_to_remove
            ]
            self._populate_note_list()
            self.update_folder_item_text(self.current_folder)
            self.save_data_to_storage()
            self.note_closed_or_deleted.emit()
            self._update_button_states()

    def _on_note_double_clicked(self, item):
        self.note_open_requested.emit(item.data(Qt.UserRole))

    def _on_note_reordered(self, parent, start, end, dest, row):
        if self.current_folder is None:
            return
        new_order = [self.note_list.item(i).data(Qt.UserRole) for i in range(self.note_list.count())]
        self.folders[self.current_folder]["notes"] = new_order
        self._populate_note_list()
        self.save_data_to_storage()

    def _filter_notes(self):
        query = self.search_bar.text().lower()
        for i in range(self.note_list.count()):
            item = self.note_list.item(i)
            item.setHidden(query not in item.text().lower())

    def select_folder_by_id(self, folder_id_to_select):
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.data(Qt.UserRole) == folder_id_to_select:
                self.folder_list.setCurrentItem(item)
                return