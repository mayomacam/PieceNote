# utils/helpers.py
import os
import sys
from .logger import log
import json

def get_app_info():
    """
    Returns application metadata.
    Useful for an 'About' dialog or for logging purposes.
    """
    return {
        "name": "CyberNotes",
        "version": "1.0.0",
        "author": "Mayomacam",
        "description": "A lightweight note-taking and folder management tool for pentesters."
    }

# You can add other utility functions here as the application grows.
# For example, functions for formatting dates, validating input, etc.


def get_app_root_path():
    """
    Determines the absolute path to the application's root directory.
    This is crucial for finding asset and data files correctly,
    especially when the application is bundled.
    """
    # If the app is running as a bundled executable (e.g., with PyInstaller)
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # If running as a normal script
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Define key paths that the application will use
APP_ROOT = get_app_root_path()
log.info(f"Application Root Path set to: {APP_ROOT}")

def get_settings():
    """Loads, validates, and returns the application settings."""
    defaults = {
        "database_path": os.path.join(APP_ROOT, "PieceNote.sqlite"),
        "backup_location": os.path.join(APP_ROOT, "backups"),
        "default_folder_name": "Default",
        "autosave_interval_seconds": 30,
        "editor_font_family": "Monospace",
        "editor_font_size": 11
    }
    settings_file = os.path.join(APP_ROOT, "settings.json")

    if not os.path.exists(settings_file):
        return defaults
    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
        # Ensure all keys are present, falling back to defaults
        defaults.update(settings)
        return defaults
    except (IOError, json.JSONDecodeError) as e:
        log.error(f"Failed to load settings.json: {e}. Using default settings.")
        return defaults

# Load settings once on startup
SETTINGS = get_settings()
DB_FILE_PATH = SETTINGS["database_path"]
BACKUP_LOCATION = SETTINGS["backup_location"]
SETTINGS_FILE_PATH = os.path.join(APP_ROOT, "settings.json")
STYLE_SHEET_PATH = os.path.join(APP_ROOT, "assets", "styles", "theme.css")
JSON_IMPORT_PATH = os.path.join(APP_ROOT, "cybernotes_data.json")

# Ensure backup directory exists on startup
try:
    os.makedirs(BACKUP_LOCATION, exist_ok=True)
except OSError as e:
    log.error(f"Could not create backup directory at {BACKUP_LOCATION}: {e}")