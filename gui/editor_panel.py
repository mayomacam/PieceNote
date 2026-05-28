import os
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QHBoxLayout,
    QPushButton, QMessageBox, QApplication, QSplitter
)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl, QThread, QObject, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebChannel import QWebChannel

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False


import markdown
import bleach
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from pymdownx.tasklist import TasklistExtension

from pygments.formatters import HtmlFormatter
from features.image_handler import select_image, image_path_to_markdown
from features.command_runner import CommandRunner
from gui.command_dialog import RunCommandDialog
from utils.logger import audit_log


class ChecklistBridge(QObject):
    state_changed = Signal(int, bool)

    @Slot(int, bool)
    def update_checklist_state(self, task_list_item_index, is_checked):
        self.state_changed.emit(task_list_item_index, is_checked)


class EditorPanel(QWidget):
    note_saved = Signal(int, str)
    metrics_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_note_id = None
        self._is_modified = False
        self.command_thread = None
        self.render_cache = {}
        self._last_rendered_text = ""

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(300)
        self.preview_timer.timeout.connect(self._update_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(10, 5, 10, 5)
        button_layout.setSpacing(10)
        self.btn_save = QPushButton("💾 Save")
        self.btn_img = QPushButton("🖼️ Image")
        self.btn_term = QPushButton("📟 Command")
        self.btn_preview = QPushButton("👁️ Preview")

        for btn in [self.btn_save, self.btn_img, self.btn_term, self.btn_preview]:
            btn.setCursor(Qt.PointingHandCursor)

        button_layout.addWidget(self.btn_save)
        button_layout.addWidget(self.btn_img)
        button_layout.addWidget(self.btn_term)
        button_layout.addWidget(self.btn_preview)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.editor_splitter = QSplitter(Qt.Horizontal)
        self.editor_splitter.setHandleWidth(1)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setFrameStyle(QTextEdit.NoFrame)

        if WEB_ENGINE_AVAILABLE:
            self.preview = QWebEngineView()
            self.page = QWebEnginePage(self.preview)
            self.channel = QWebChannel(self.page)
            self.bridge = ChecklistBridge()
            self.page.setWebChannel(self.channel)
            self.channel.registerObject("py_bridge", self.bridge)
            self.preview.setPage(self.page)
            self.bridge.state_changed.connect(self._on_checklist_toggled)
        else:
            self.preview = QTextEdit()
            self.preview.setReadOnly(True)
            self.preview.setFrameStyle(QTextEdit.NoFrame)

        self.editor_splitter.addWidget(self.editor)
        self.editor_splitter.addWidget(self.preview)
        self.editor_splitter.setStretchFactor(0, 1)
        self.editor_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.editor_splitter)

        self.btn_save.clicked.connect(self._save_note)
        self.btn_img.clicked.connect(self._insert_image)
        self.btn_term.clicked.connect(self._run_terminal_command)
        self.btn_preview.clicked.connect(self._toggle_preview)
        self.editor.textChanged.connect(self.trigger_preview_update)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(30000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()

        self.clear_and_disable()

    def trigger_preview_update(self):
        self._mark_as_modified()
        self.calculate_metrics()
        self.preview_timer.start()

    def apply_settings(self, settings):
        font = QFont(
            settings.get("editor_font_family", "Monospace"),
            settings.get("editor_font_size", 11)
        )
        self.editor.setFont(font)

    def _toggle_preview(self):
        self.preview.setVisible(not self.preview.isVisible())

    def calculate_metrics(self):
        text = self.editor.toPlainText()
        words = len(text.split()) if text else 0
        chars = len(text)
        lines = text.count('\n') + 1 if text else 0
        images = len(re.findall(r'!\[.*?\]\(.*?\)', text))
        links = len(re.findall(r'https?://[^\s)]+', text))
        metrics = {
            "words": words,
            "chars": chars,
            "lines": lines,
            "images": images,
            "links": links
        }
        self.metrics_updated.emit(metrics)

    def clear_and_disable(self):
        self.current_note_id = None
        self._is_modified = False
        self.editor.clear()
        self.editor.setPlaceholderText("Select a note from the sidebar to begin editing.")
        if WEB_ENGINE_AVAILABLE:
            self.preview.setHtml("")
        else:
            self.preview.clear()
        self.btn_save.setEnabled(False)
        self.btn_img.setEnabled(False)
        self.btn_term.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.editor.setEnabled(False)
        self.calculate_metrics()

    def load_note(self, nid, title, body):
        self.current_note_id = nid
        self.editor.blockSignals(True)
        self.editor.setPlainText(body or "")
        self.editor.blockSignals(False)
        self._is_modified = False
        self._last_rendered_text = ""
        self.trigger_preview_update()
        self.btn_save.setEnabled(True)
        self.btn_img.setEnabled(True)
        self.btn_term.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.editor.setEnabled(True)
        self.editor.setFocus()
        self.calculate_metrics()

    def _mark_as_modified(self):
        self._is_modified = True

    def _save_note(self):
        if self.current_note_id is not None and self._is_modified:
            self.note_saved.emit(self.current_note_id, self.editor.toPlainText())
            self._is_modified = False
            if self.window() and hasattr(self.window(), 'storage'):
                self.window().storage.save_to_disk()
                self.window().statusBar().showMessage("Note saved!", 2000)

    def _autosave(self):
        if self._is_modified:
            self._save_note()

    def _update_preview(self):
        raw_text = self.editor.toPlainText()
        if raw_text == self._last_rendered_text:
            return

        self._last_rendered_text = raw_text

        if raw_text in self.render_cache:
            full_html = self.render_cache[raw_text]
        else:
            css = HtmlFormatter(style='monokai').get_style_defs('.codehilite')
            js_script = (
                """<script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>"""
                """<script>document.addEventListener("DOMContentLoaded",function(){"""
                """new QWebChannel(qt.webChannelTransport,function(c){window.py_bridge=c.objects.py_bridge;"""
                """var e=document.querySelectorAll("li.task-list-item");"""
                """e.forEach(function(c,t){let n=c.querySelector('input[type=checkbox]');"""
                """n&&n.addEventListener("change",function(c){window.py_bridge&&window.py_bridge.update_checklist_state(t,c.target.checked)})})})});</script>"""
            )

            md_extensions = [
                FencedCodeExtension(),
                TableExtension(),
                TasklistExtension(custom_checkbox=True)
            ]
            html_body_raw = markdown.markdown(raw_text, extensions=md_extensions)

            allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
                'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr', 'pre', 'code',
                'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img', 'span', 'div',
                'input', 'li', 'ul', 'ol'
            ]
            allowed_attrs = bleach.sanitizer.ALLOWED_ATTRIBUTES.copy()
            allowed_attrs.update({
                'img': ['src', 'alt', 'title', 'width', 'height'],
                'code': ['class'],
                'span': ['class'],
                'div': ['class'],
                'input': ['type', 'checked', 'disabled'],
                'li': ['class']
            })

            sanitized_html = bleach.clean(html_body_raw, tags=allowed_tags, attributes=allowed_attrs)

            full_html = (
                f"""<html><head><meta charset="UTF-8">{js_script}"""
                f"""<style>body{{background-color:#121212;color:#e1e1e1;font-family:sans-serif;padding:30px;line-height:1.6;}}"""
                f"""li.task-list-item{{list-style-type:none;}}"""
                f"""li.task-list-item input[type=checkbox]{{margin-right:8px;}}"""
                f"""{css}pre code{{background-color:transparent!important;}}"""
                f"""pre{{background-color:#1e1e1e;padding:15px;border-radius:8px;border:1px solid #333;overflow-x:auto;}}"""
                f"""table{{border-collapse:collapse;width:100%;margin-bottom:1em;}}"""
                f"""th,td{{border:1px solid #333;padding:10px;text-align:left;}}"""
                f"""th{{background-color:#1e1e1e;}}"""
                f"""h1,h2,h3{{color:#0a84ff;}}"""
                f"""img{{max-width:100%;border-radius:8px;}}"""
                f"""</style></head><body>{sanitized_html}</body></html>"""
            )

            if len(self.render_cache) > 100:
                self.render_cache.pop(next(iter(self.render_cache)))
            self.render_cache[raw_text] = full_html

        if WEB_ENGINE_AVAILABLE:
            base_url = QUrl.fromLocalFile(os.getcwd() + os.path.sep)
            self.preview.setHtml(full_html, baseUrl=base_url)
        else:
            self.preview.setPlainText(full_html)

    @Slot(int, bool)
    def _on_checklist_toggled(self, task_list_item_index, is_checked):
        text = self.editor.toPlainText()
        lines = text.split('\n')
        task_count = -1
        target_line_index = -1
        for i, line in enumerate(lines):
            if line.lstrip().startswith(('- [ ] ', '- [x] ', '* [ ] ', '* [x] ')):
                task_count += 1
                if task_count == task_list_item_index:
                    target_line_index = i
                    break
        if target_line_index != -1:
            line_content = lines[target_line_index]
            if is_checked:
                new_line = line_content.replace('[ ]', '[x]', 1)
            else:
                new_line = line_content.replace('[x]', '[ ]', 1)
            if new_line != line_content:
                self.editor.blockSignals(True)
                cursor = self.editor.textCursor()
                cursor.beginEditBlock()
                cursor.movePosition(QTextCursor.Start)
                for _ in range(target_line_index):
                    cursor.movePosition(QTextCursor.NextBlock)
                cursor.select(QTextCursor.LineUnderCursor)
                cursor.insertText(new_line)
                cursor.endEditBlock()
                self.editor.blockSignals(False)
                self._mark_as_modified()

    def _insert_text(self, text):
        self.editor.textCursor().insertText(text)
        self.editor.setFocus()

    def _insert_image(self):
        image_path = select_image(self)
        if image_path:
            self._insert_text(image_path_to_markdown(image_path))

    def _run_terminal_command(self):
        dialog = RunCommandDialog(self)
        if dialog.exec():
            command = dialog.get_command()
            if command:
                audit_log("Command Execution", f"User initiated command: {command}")
                if self.window():
                    self.window().statusBar().showMessage(f"Running: {command}...")
                self.command_thread = QThread()
                worker = CommandRunner(command)
                worker.moveToThread(self.command_thread)
                self.command_thread.started.connect(worker.run)
                worker.finished.connect(self._on_command_finished)
                worker.finished.connect(self.command_thread.quit)
                worker.finished.connect(worker.deleteLater)
                self.command_thread.finished.connect(self.command_thread.deleteLater)
                self.command_thread.start()
                self.btn_term.setEnabled(False)

    def _on_command_finished(self, markdown_output):
        if not self.isVisible():
            return
        self._insert_text(markdown_output)
        if self.window():
            self.window().statusBar().showMessage("Command output inserted.", 3000)
            self.btn_term.setEnabled(True)
