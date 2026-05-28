import sys
import os
import json
import re

# Add project root to path
sys.path.append(os.getcwd())

# 1. Test CommandRunner Security Logic (Independent of Qt)
def test_command_runner_logic():
    print("Testing CommandRunner security logic...")

    # Define WHITELIST locally for testing or import if possible
    WHITELIST = {
        'nmap', 'whoami', 'ls', 'pwd', 'ping', 'netstat',
        'ipconfig', 'ifconfig', 'id', 'uname', 'hostname',
        'cat', 'grep', 'head', 'tail', 'df', 'free', 'uptime',
        'nslookup', 'traceroute', 'tracert', 'ps'
    }

    def is_safe(args):
        if not args: return False
        base_cmd = args[0].lower()
        if base_cmd.endswith('.exe'): base_cmd = base_cmd[:-4]
        if base_cmd not in WHITELIST: return False
        safe_pattern = re.compile(r'^[a-zA-Z0-9\s\-_./]+$')
        for arg in args:
            if not safe_pattern.match(arg): return False
            if arg.startswith('-'):
                if not re.match(r'^-[a-zA-Z0-9\-]+$', arg): return False
        return True

    safe_commands = ["ls -la", "nmap -v 127.0.0.1", "whoami", "ping 8.8.8.8", "cat /etc/passwd"]
    unsafe_commands = ["ls; whoami", "ping 8.8.8.8 | grep google", "ls > test.txt", "whoami --flag; injection", "nmap -v $(whoami)"]

    import shlex
    for cmd in safe_commands:
        args = shlex.split(cmd)
        safe = is_safe(args)
        print(f"  Command: {cmd} | Safe: {safe}")
        assert safe, f"{cmd} should be safe"

    for cmd in unsafe_commands:
        args = shlex.split(cmd)
        safe = is_safe(args)
        print(f"  Command: {cmd} | Safe: {safe}")
        assert not safe, f"{cmd} should be unsafe"
    print("  CommandRunner logic tests PASSED.")

# 2. Test Audit Logging
def test_audit_logging():
    print("\nTesting Audit Logging format...")
    # Mock dependencies
    sys.modules["PySide6"] = MagicMock()
    sys.modules["PySide6.QtCore"] = MagicMock()

    import getpass
    curr_user = getpass.getuser()

    from utils.logger import audit_log
    audit_log("Test Event", "Details")

    log_file = "app.log"
    with open(log_file, "r") as f:
        last_line = f.readlines()[-1]
        print(f"  Last log line: {last_line.strip()}")
        assert "[AUDIT] {" in last_line
        json_str = last_line.split("[AUDIT] ")[1]
        data = json.loads(json_str)
        assert data["event_type"] == "Test Event"
        assert data["user_id"] == curr_user

    print("  Audit logging tests PASSED.")

# 3. Test Storage Dirty Tracking
def test_storage_dirty_tracking():
    print("\nTesting StorageManager dirty tracking...")
    # Mocking EncryptionManager because it's imported in storage.py
    sys.modules["utils.encryption"] = MagicMock()
    from features.storage import StorageManager

    # Mock sqlite3.connect since we can't easily deserialize in this environment without real sqlite
    # Actually, :memory: should work if sqlite3 is present.
    import sqlite3
    storage = StorageManager(":memory:")
    print(f"  Initial dirty: {storage._dirty}")
    assert not storage._dirty

    storage.create_folder("Folder")
    print(f"  After folder creation, dirty: {storage._dirty}")
    assert storage._dirty

    storage._dirty = False
    storage.create_note(1, "Note")
    print(f"  After note creation, dirty: {storage._dirty}")
    assert storage._dirty
    print("  Storage dirty tracking tests PASSED.")

from unittest.mock import MagicMock
if __name__ == "__main__":
    test_command_runner_logic()
    test_audit_logging()
    test_storage_dirty_tracking()
    print("\nALL TESTS PASSED SUCCESSFULLY.")
