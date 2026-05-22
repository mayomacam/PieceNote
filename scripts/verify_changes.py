import bleach
import sys
import os

# Mocking some parts for testing
from features.command_runner import CommandRunner
from PySide6.QtCore import QCoreApplication

def test_bleach():
    print("Testing Bleach Sanitization...")
    payload = "<script>alert('xss')</script><b>Hello</b>"
    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + ['p', 'b']
    sanitized = bleach.clean(payload, tags=allowed_tags)
    print(f"Original: {payload}")
    print(f"Sanitized: {sanitized}")
    if "<script>" not in sanitized and "<b>Hello</b>" in sanitized:
        print("SUCCESS: XSS Payload removed, safe tags kept.")
    else:
        print("FAILURE: Sanitization failed.")

def test_command_runner():
    print("\nTesting CommandRunner Whitelist...")

    def on_finished(output):
        print(f"Output received: {output}")
        if "not whitelisted" in output:
             print("SUCCESS: Unauthorized command blocked.")
        elif any(x in output for x in ["bin", "total", "main.py", "scripts"]):
             print("SUCCESS: Whitelisted command executed.")
        else:
             print("FAILURE: Unexpected output.")

    print("Trying 'ls' (Whitelisted):")
    cr_safe = CommandRunner("ls")
    cr_safe.finished.connect(on_finished)
    cr_safe.run()

    print("Trying 'rm -rf /' (Not Whitelisted):")
    cr_unsafe = CommandRunner("rm -rf /")
    cr_unsafe.finished.connect(on_finished)
    cr_unsafe.run()

if __name__ == "__main__":
    app = QCoreApplication(sys.argv)
    test_bleach()
    test_command_runner()
