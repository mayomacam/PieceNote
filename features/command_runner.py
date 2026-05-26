import subprocess
import shlex
from PySide6.QtCore import QObject, Signal
from utils.logger import audit_log

# Whitelist of allowed commands for security (SOC 2 alignment)
COMMAND_WHITELIST = {
    "nmap", "whoami", "ls", "pwd", "ping", "netstat",
    "ipconfig", "ifconfig", "id", "uname", "hostname",
    "cat", "grep", "head", "tail", "df", "free", "uptime"
}

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
            # Use shlex to safely split the command string into a list
            # and avoid shell=True to prevent command injection.
            args = shlex.split(self.command)

            if not args:
                self.finished.emit("")
                return

            base_command = args[0]
            if base_command not in COMMAND_WHITELIST:
                audit_log("Command Blocked", f"Unauthorized command: {base_command}")
                output = f"Error: Command '{base_command}' is not in the whitelist."
            else:
                result = subprocess.run(
                    args,
                    shell=False,
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
