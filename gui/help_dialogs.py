# gui/help_dialogs.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QDialogButtonBox, QTextBrowser
)
from PySide6.QtCore import Qt

class MarkdownGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Markdown Quick Guide")
        self.text_browser = QTextBrowser(); self.text_browser.setOpenExternalLinks(True); self.text_browser.setHtml(self.get_guide_html())
        button_box = QDialogButtonBox(QDialogButtonBox.Ok); button_box.accepted.connect(self.accept)
        layout = QVBoxLayout(self); layout.addWidget(self.text_browser); layout.addWidget(button_box)
        self.resize(600, 500)

    def get_guide_html(self):
        """Returns the full HTML content for the guide."""
        return """
        <h2>Markdown Quick Guide</h2>
        <p>PieceNote uses a powerful Markdown engine with several key features enabled.</p>

        <h3>Special Features</h3>
        <hr>
        <h4>Interactive Checklists</h4>
        <p>Create checklists by starting a line with <code>- [ ]</code> or <code>- [x]</code>. You can click the checkbox in the preview pane to toggle its state.</p>
        <pre>- [ ] An incomplete task<br>- [x] A completed task</pre>

        <h4>Collapsible Sections</h4>
        <p>Create sections that can be expanded and collapsed using the standard HTML <code>&lt;details&gt;</code> tag.</p>
        <pre>&lt;details&gt;<br>  &lt;summary&gt;Click to Expand Nmap Results&lt;/summary&gt;<br><br>  Your detailed notes, code blocks,<br>  and images go here.<br><br>&lt;/details&gt;</pre>

        <h3>Standard Syntax</h3>
        <hr>
        <h4>Text Formatting</h4>
        <pre># Heading 1<br>## Heading 2<br><br>**Bold Text** or __Bold Text__<br>*Italic Text* or _Italic Text_<br>~~Strikethrough~~</pre>

        <h4>Code Blocks</h4>
        <p>For syntax highlighting, specify the language after the backticks.</p>
        <pre>```python<br># Your Python code here<br>print("Hello, World!")<br>```</pre>

        <h4>Tables</h4>
        <p><b>Important:</b> Tables require a header row and a separator line with hyphens (---) for them to render correctly.</p>
        <pre>| Header 1 | Header 2 |<br>|----------|----------|<br>| Cell 1   | Cell 2   |<br>| Cell 3   | Cell 4   |</pre>
        """