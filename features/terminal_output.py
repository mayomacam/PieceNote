import subprocess

def get_command_output_markdown(command):
    """
    Executes a shell command and returns its output formatted as a Markdown block.
    """
    if not command:
        return ""
    try:
        # Using shell=True for convenience, but be aware of security implications.
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30 # 30-second timeout to prevent hangs
        )
        output = result.stdout
        if result.stderr:
            output += f"\n--- STDERR ---\n{result.stderr}"
    except subprocess.TimeoutExpired:
        output = "Error: Command timed out."
    except Exception as e:
        output = f"Error executing command: {e}"

    return f"```bash\n$ {command}\n{output.strip()}\n```\n"