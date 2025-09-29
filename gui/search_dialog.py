# gui/search_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QDialogButtonBox, QLabel
)
from PySide6.QtCore import Qt, Signal

class SearchDialog(QDialog):
    # Signal to be emitted when a search result is activated (double-clicked)
    # It will send the note_id and folder_id of the selected result
    result_activated = Signal(int, int)

    def __init__(self, storage_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search All Notes")
        self.storage = storage_manager

        # UI Elements
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter query to search note contents...")

        self.results_list = QListWidget()
        self.results_label = QLabel("Results:")

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addWidget(self.results_label)
        layout.addWidget(self.results_list)

        # Connections
        self.search_input.returnPressed.connect(self.perform_search)
        self.results_list.itemDoubleClicked.connect(self._on_result_activated)

        self.resize(500, 400)

    def perform_search(self):
        """Executes the search and populates the results list."""
        query = self.search_input.text()
        if not query or len(query) < 3:
            self.results_list.clear()
            self.results_label.setText("Results: (Enter at least 3 characters)")
            return

        results = self.storage.search_notes(query)
        self.results_list.clear()

        self.results_label.setText(f"Found {len(results)} result(s) for '{query}':")
        if not results:
            item = QListWidgetItem("No results found.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.results_list.addItem(item)
        else:
            for result in results:
                # Store note_id, folder_id, and title in the item
                item = QListWidgetItem(f"📄 {result['title']}  (in folder: {result['folder_name']})")
                item.setData(Qt.UserRole, result) # Store the whole dict
                self.results_list.addItem(item)

    def _on_result_activated(self, item):
        """Emits the signal with the necessary IDs when a result is double-clicked."""
        result_data = item.data(Qt.UserRole)
        if result_data:
            self.result_activated.emit(result_data['note_id'], result_data['folder_id'])
            self.accept() # Close the dialog after selection