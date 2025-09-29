import os
import pathlib # <-- IMPORT ADDED
from PySide6.QtWidgets import QFileDialog

def select_image(parent=None):
    """
    Opens a file dialog to select an image file.
    Returns the absolute path to the selected image or None.
    """
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Select an Image",
        "",
        "Images (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)"
    )
    return file_path if file_path else None

def image_path_to_markdown(path, alt_text="image"):
    """
    Converts a file path to a Markdown image link using a file URI.
    """
    if not path:
        return ""
    # FIX: Convert the absolute path to a file URI so the web engine can find it
    uri = pathlib.Path(path).as_uri()
    return f"![{alt_text}]({uri})"