import subprocess
import shlex
from PySide6.QtCore import QObject, Signal
from utils.logger import audit_log

class CommandRunner(QObject):
    """
    A worker QObject that runs a shell command in a separate thread.
    """
    finished = Signal(str)  # Signal emitting the markdown-formatted result

    # SOC 2: Command Whitelist to prevent arbitrary code execution
    WHITELIST = {
        "nmap", "whoami", "ls", "pwd", "ping", "netstat", "ipconfig", "ifconfig",
        "id", "uname", "hostname", "cat", "grep", "head", "tail", "df", "free", "uptime"
    }

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        """Executes the command and emits the result."""
        if not self.command:
            self.finished.emit("")
            return

        try:
            args = shlex.split(self.command)
            if not args:
                 self.finished.emit("Error: Empty command.")
                 return

            base_cmd = args[0]
            if base_cmd not in self.WHITELIST:
                audit_log("Security Violation", f"Unauthorized command attempted: {base_cmd}")
                output = f"Error: Command '{base_cmd}' is not in the whitelist and cannot be executed for security reasons."
            else:
                result = subprocess.run(
                    args,
                    shell=False, # Crucial: avoids shell expansion vulnerabilities
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
