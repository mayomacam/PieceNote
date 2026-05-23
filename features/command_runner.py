import subprocess
import shlex
from PySide6.QtCore import QObject, Signal
from utils.logger import audit_log

class CommandRunner(QObject):
    """
    A worker QObject that runs a shell command in a separate thread.
    Includes a whitelist for SOC 2 grade security.
    """
    finished = Signal(str)

    # SOC 2 alignment: Only allow a specific subset of safe/necessary commands.
    WHITELIST = {
        'nmap', 'ping', 'whoami', 'ls', 'dir', 'ipconfig', 'ifconfig',
        'netstat', 'nslookup', 'traceroute', 'tracert', 'df', 'free', 'uptime'
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

            base_cmd = args[0].lower()
            # Handle Windows .exe suffix if present
            if base_cmd.endswith('.exe'):
                base_cmd = base_cmd[:-4]

            if base_cmd not in self.WHITELIST:
                audit_log("Command Blocked (Security)", f"Command: {self.command}")
                output = f"Security Error: Command '{base_cmd}' is not in the whitelist."
            else:
                audit_log("Command Executed", f"Command: {self.command}")
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
        except FileNotFoundError:
            output = f"Error: Command '{args[0]}' not found."
        except Exception as e:
            output = f"Error executing command: {e}"

        markdown = f"```bash\n$ {self.command}\n{output.strip()}\n```\n"
        self.finished.emit(markdown)
