import subprocess
import shlex
import re
from PySide6.QtCore import QObject, Signal
from utils.logger import audit_log

class CommandRunner(QObject):
    """
    A worker QObject that runs a shell command in a separate thread with strict validation.
    """
    finished = Signal(str)  # Signal emitting the markdown-formatted result

    # Whitelist of allowed base commands for pentesting
    WHITELIST = {
        'nmap', 'whoami', 'ls', 'pwd', 'ping', 'netstat',
        'ipconfig', 'ifconfig', 'id', 'uname', 'hostname',
        'cat', 'grep', 'head', 'tail', 'df', 'free', 'uptime'
    }

    def __init__(self, command):
        super().__init__()
        self.command = command.strip()

    def is_safe(self, args):
        """Validates the command against the whitelist and checks for suspicious patterns."""
        if not args:
            return False

        base_cmd = args[0]
        if base_cmd not in self.WHITELIST:
            audit_log("Security Violation", f"Command rejected (not in whitelist): {base_cmd}")
            return False

        # Disallow command chaining and redirection to prevent shell injection
        # shlex already handles many cases, but we want to be extra strict.
        forbidden_chars = [';', '&', '|', '>', '<', '`', '$', '(', ')']
        for arg in args:
            if any(char in arg for char in forbidden_chars):
                audit_log("Security Violation", f"Command rejected (suspicious characters): {self.command}")
                return False

        return True

    def run(self):
        """Executes the command and emits the result."""
        if not self.command:
            self.finished.emit("")
            return

        try:
            # Use shlex to safely split the command string into a list
            args = shlex.split(self.command)

            if not self.is_safe(args):
                self.finished.emit(f"```bash\n$ {self.command}\nError: Command rejected for security reasons.\n```\n")
                return

            result = subprocess.run(
                args,
                shell=False, # Crucial: shell=False prevents most injection
                capture_output=True,
                text=True,
                timeout=60
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
