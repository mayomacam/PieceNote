### **2. New File: `features/command_runner.py`**
#(Improvement #3: The threading logic to prevent UI freezing)*

import subprocess
from PySide6.QtCore import QObject, Signal

class CommandRunner(QObject):
    """
    A worker QObject that runs a shell command in a separate thread.
    """
    finished = Signal(str)  # Signal emitting the markdown-formatted result

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        """Executes the command and emits the result."""
        if not self.command:
            self.finished.emit("")
            return

        try:
            result = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60  # 60-second timeout
            )
            output = result.stdout
            if result.stderr:
                output += f"\n--- STDERR ---\n{result.stderr}"
        except subprocess.TimeoutExpired:
            output = "Error: Command timed out after 60 seconds."
        except Exception as e:
            output = f"Error executing command: {e}"

        markdown = f"```bash\n$ {self.command}\n{output.strip()}\n```\n"
        self.finished.emit(markdown)