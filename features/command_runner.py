import subprocess
import shlex
import re
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

        # SOC 2 Alignment: Command Validation (Whitelist)
        allowed_commands = {'ls', 'nmap', 'ping', 'whoami', 'ps', 'cat', 'grep', 'find'}

        try:
            args = shlex.split(self.command)
            if not args:
                self.finished.emit("Error: Empty command.")
                return

            base_cmd = args[0].lower()
            # Handle Windows .exe suffix if present
            if base_cmd.endswith('.exe'):
                base_cmd = base_cmd[:-4]

            if not args or args[0] not in allowed_commands:
                output = f"Error: Command '{args[0] if args else ''}' is not whitelisted for execution."
                markdown = f"```bash\n$ {self.command}\n{output.strip()}\n```\n"
                self.finished.emit(markdown)
                return

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
        except FileNotFoundError:
            output = f"Error: Command '{args[0]}' not found."
        except Exception as e:
            output = f"Error executing command: {e}"

        markdown = f"```bash\n$ {self.command}\n{output.strip()}\n```\n"
        self.finished.emit(markdown)
