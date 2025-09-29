import os
import re
import pathlib
import markdown
from pygments.formatters import HtmlFormatter

try:
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False

def _sanitize_filename(name):
    """Removes characters that are invalid for filenames."""
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.split(' - ')[-1])
    return name[:100]

def _preprocess_markdown_images(markdown_content):
    """
    Finds all relative image paths in Markdown and converts them to absolute file URIs.
    """
    def replacer(match):
        alt_text = match.group(1)
        path = match.group(2)
        if path.startswith(('http://', 'https://', 'file:///')):
            if path.startswith(('file:///')):
                path = path[7:]  # Remove 'file:///' prefix
            return f"![{alt_text}]({path})"
        absolute_path = os.path.abspath(path)
        uri = pathlib.Path(absolute_path).as_uri()
        return f"![{alt_text}]({uri})"

    image_regex = re.compile(r'!\[(.*?)\]\((.*?)\)')
    return image_regex.sub(replacer, markdown_content)

def export_notes_to_file(filepath, notes_list, file_format, single_file=False):
    """
    Exports a LIST of notes to a specified file or files, preserving order.
    """
    if single_file:
        combined_content = ""
        for note in notes_list:
            if not note: continue
            processed_body = _preprocess_markdown_images(note['body'])
            combined_content += f"# {note['title']}\n\n{processed_body}\n\n---\n\n"
        _write_file(filepath, combined_content.strip(), "CyberNotes Export", file_format)
    else:
        output_dir = os.path.dirname(filepath)
        base_filename = os.path.splitext(os.path.basename(filepath))[0]
        for i, note in enumerate(notes_list):
            if not note: continue
            safe_title = _sanitize_filename(note['title'])
            new_filename = f"{base_filename}_{i+1}_{safe_title}.{file_format}"
            new_filepath = os.path.join(output_dir, new_filename)
            processed_body = _preprocess_markdown_images(note['body'])
            content = f"# {note['title']}\n\n{processed_body}"
            _write_file(new_filepath, content, note['title'], file_format)

def _write_file(path, content, title, file_format):
    """
    Helper function to write content to a file with professional styling.
    """
    pygments_css = HtmlFormatter(style='monokai').get_style_defs('.codehilite')

    # --- The CSS has been updated below ---
    html_css = f"""
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; background-color: #0d1117; color: #c9d1d9; padding: 30px; }}
        h1, h2, h3, h4, h5, h6 {{ border-bottom: 1px solid #30363d; padding-bottom: .3em; margin-top: 24px; }}

        /* General style for inline code snippets */
        code {{
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            background-color: rgba(175,184,193,0.2);
            padding: .2em .4em;
            font-size: 85%;
            border-radius: 6px;
        }}

        /* --- THIS IS THE FIX --- */
        /* Override the background for code inside a PRE block */
        pre code {{
            background-color: transparent;
            padding: 0;
            font-size: 100%;
            border-radius: 0;
        }}

        div.codehilite {{ margin-bottom: 16px; }}
        pre {{ background-color: #161b22; padding: 16px; overflow: auto; border-radius: 6px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
        th, td {{ border: 1px solid #30363d; padding: 8px 12px; }}
        th {{ background-color: #161b22; }}
        hr {{ border: 0; height: .25em; padding: 0; margin: 24px 0; background-color: #30363d; }}
        img {{ max-width: 100%; height: auto; background: white; padding: 5px; border-radius: 5px; }}
        {pygments_css}
    </style>
    """

    if file_format == 'md':
        with open(path, 'w', encoding='utf-8') as f: f.write(content)
        return

    html_body = markdown.markdown(content, extensions=['fenced_code', 'codehilite', 'tables'])
    full_html = f"<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><title>{title}</title>{html_css}</head><body>{html_body}</body></html>"

    if file_format == 'html':
        with open(path, 'w', encoding='utf-8') as f: f.write(full_html)

    elif file_format == 'pdf':
        if not XHTML2PDF_AVAILABLE:
            raise ImportError("PDF export requires 'xhtml2pdf'. Please install it: pip install xhtml2pdf")
        with open(path, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(full_html.encode('utf-8'), dest=pdf_file, encoding='utf-8')
        if pisa_status.err:
            raise Exception(f"PDF conversion failed with error code {pisa_status.err}")