import sqlite3
import json
import os
from utils.helpers import DB_FILE_PATH, BACKUP_LOCATION, JSON_IMPORT_PATH, get_settings, log
import shutil


# ---------------- Storage handling ----------------------------------

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass



class StorageManager:
    def __init__(self, filepath=DB_FILE_PATH):
        self.filepath = filepath
        # backup path in case we need to restore
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        # Always ensure the tables exist before doing anything else.
        # "CREATE TABLE IF NOT EXISTS" is safe to run every time.
        self._create_tables()
        self._import_from_json_if_needed()

    def _get_connection(self):
        return sqlite3.connect(self.filepath)

    def _create_tables(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    folder_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    note_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT,
                    folder_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    FOREIGN KEY (folder_id) REFERENCES folders (folder_id) ON DELETE CASCADE
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def load(self):
        """
        Loads all data. If it fails due to a database error,
        it raises a custom exception to be handled by the UI.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT folder_id, name FROM folders")
            folders_data = {fid: {"name": name, "notes": []} for fid, name in cursor.fetchall()}

            cursor.execute("SELECT note_id, title, body, folder_id FROM notes ORDER BY sort_order ASC")
            notes_data = {}
            for nid, title, body, fid in cursor.fetchall():
                notes_data[nid] = {"title": title, "body": body}
                if fid in folders_data:
                    folders_data[fid]["notes"].append(nid)

            next_folder_id = (cursor.execute("SELECT MAX(folder_id) FROM folders").fetchone()[0] or 0) + 1
            next_note_id = (cursor.execute("SELECT MAX(note_id) FROM notes").fetchone()[0] or 0) + 1

            return {
                "folders": folders_data, "notes": notes_data,
                "next_folder_id": next_folder_id, "next_note_id": next_note_id,
            }
        except sqlite3.DatabaseError as e:
            # If the DB is corrupt, raise our custom error
            log.error(f"Database error on load: {e}")
            raise DatabaseCorruptError("The database file appears to be corrupt.")
        finally:
            if conn:
                conn.close()

    def save(self, data):
        """
        Saves the entire application state to the SQLite database.
        Returns True on success, False on failure.
        Also creates a backup of the existing database before overwriting.
        """
        if os.path.exists(self.filepath):
            try:
                shutil.copy2(self.filepath, self.backup_path)
                log.info(f"Database backup created at {self.backup_path}")
            except IOError as e:
                log.error(f"Could not create database backup: {e}")
                # We can decide whether to proceed without a backup
                # For safety, let's return False
                return False
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN")

            folder_names_seen = set()
            modified_folders = {}
            # The keys in the live data model are integers.
            for folder_id, folder_data in data.get("folders", {}).items():
                original_name = folder_data["name"]
                new_name = original_name
                count = 1
                while new_name in folder_names_seen:
                    new_name = f"{original_name} (Copy {count})"
                    count += 1
                folder_names_seen.add(new_name)
                modified_folders[folder_id] = folder_data.copy()
                modified_folders[folder_id]['name'] = new_name

            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM folders")

            for folder_id, folder_data in modified_folders.items():
                cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (folder_id, folder_data["name"]))

                for i, note_id in enumerate(folder_data.get("notes", [])):
                    # The note_id is an integer, so we look it up with an integer key.
                    # The str() conversion was the bug.
                    note_data = data["notes"].get(note_id)
                    if note_data:
                        cursor.execute(
                            "INSERT INTO notes (note_id, title, body, folder_id, sort_order) VALUES (?, ?, ?, ?, ?)",
                            (note_id, note_data["title"], note_data["body"], folder_id, i)
                        )

            conn.commit()
            return True
        except Exception as e:
            log.error(f"Error saving data to SQLite: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def restore_from_backup(self): # new method for restoring
        """Copies the backup file over the main database file."""
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                return True
            except IOError as e:
                log.error(f"Failed to restore from backup: {e}")
                return False
        return False

    def search_notes(self, query):
        """
        Searches the TITLE and BODY of all notes for a given query.
        Returns a list of dictionaries containing note info.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # searches both title and body for better results.
            sql_query = """
                SELECT n.note_id, n.title, f.folder_id, f.name
                FROM notes n
                JOIN folders f ON n.folder_id = f.folder_id
                WHERE n.title LIKE ? OR n.body LIKE ?
            """
            search_term = f"%{query}%"
            # Pass the search term twice, once for title and once for body
            cursor.execute(sql_query, (search_term, search_term))

            results = []
            for note_id, title, folder_id, folder_name in cursor.fetchall():
                results.append({
                    "note_id": note_id, "title": title,
                    "folder_id": folder_id, "folder_name": folder_name
                })
            return results
        finally:
            conn.close()

    def _import_from_json_if_needed(self):
        json_path = JSON_IMPORT_PATH
        if os.path.exists(json_path):
            log.info("Found 'cybernotes_data.json', attempting to import.")
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # The data from json.load has keys as strings, we need to fix this first
                data['folders'] = {int(k): v for k, v in data['folders'].items()}
                data['notes'] = {int(k): v for k, v in data['notes'].items()}

                save_successful = self.save(data)

                if save_successful:
                    os.rename(json_path, f"{json_path}.imported")
                    log.info("Successfully imported data. The old file has been renamed.")
                else:
                    log.error("Import failed due to a database error. The JSON file has not been changed.")
            except Exception as e:
                log.error(f"Failed to read or process JSON file: {e}")
