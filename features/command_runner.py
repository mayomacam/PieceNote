import subprocess
import shlex
from PySide6.QtCore import QObject, Signal
from utils.logger import audit_log

class CommandRunner(QObject):
    """
    A worker QObject that runs a shell command in a separate thread.
    Includes a strict whitelist for SOC 2 grade security.
    """
    finished = Signal(str)

    # SOC 2 Alignment: Whitelist of allowed base commands for pentesting/system info.
    WHITELIST = {
        'nmap', 'whoami', 'ls', 'pwd', 'ping', 'netstat',
        'ipconfig', 'ifconfig', 'id', 'uname', 'hostname',
        'cat', 'grep', 'head', 'tail', 'df', 'free', 'uptime',
        'nslookup', 'traceroute', 'tracert', 'ps'
    }

    # SOC 2: Command Whitelist to prevent arbitrary code execution
    WHITELIST = {
        "nmap", "whoami", "ls", "pwd", "ping", "netstat", "ipconfig", "ifconfig",
        "id", "uname", "hostname", "cat", "grep", "head", "tail", "df", "free", "uptime"
    }

    def __init__(self, command):
        super().__init__()
        self.command = command.strip()

    def is_safe(self, args):
        """Validates the command against the whitelist and checks for suspicious patterns."""
        if not args:
            return False

        base_cmd = args[0].lower()
        if base_cmd.endswith('.exe'):
            base_cmd = base_cmd[:-4]

        if base_cmd not in self.WHITELIST:
            audit_log("Security Violation", f"Command rejected (not in whitelist): {base_cmd}")
            return False

        # Disallow command chaining and redirection to prevent shell injection.
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
            args = shlex.split(self.command)
            if not args:
                self.finished.emit("Error: Empty command.")
                return

            if not self.is_safe(args):
                self.finished.emit(f"```bash\n$ {self.command}\nError: Command rejected for security reasons.\n```\n")
                return

            result = subprocess.run(
                args,
                shell=False, # Crucial: shell=False prevents shell injection
                capture_output=True,
                text=True,
                timeout=60
            )
            output = result.stdout
            if result.stderr:
                output += f"\n--- STDERR ---\n{result.stderr}"

            audit_log("Command Executed", f"Successfully ran: {self.command}")
        except subprocess.TimeoutExpired:
            output = "Error: Command timed out after 60 seconds."
            audit_log("Command Error", f"Timeout running: {self.command}")
        except FileNotFoundError:
            output = f"Error: Command '{args[0]}' not found."
        except Exception as e:
            output = f"Error executing command: {e}"
            audit_log("Command Error", f"Exception running {self.command}: {e}")

        markdown = f"```bash\n$ {self.command}\n{output.strip()}\n```\n"
        self.finished.emit(markdown)
