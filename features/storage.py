import sqlite3
import json
import os
import shutil
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
from utils.helpers import DB_FILE_PATH, BACKUP_LOCATION, JSON_IMPORT_PATH, get_settings, log
from utils.logger import audit_log

# ---------------- Storage handling ----------------------------------

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass

class StorageManager:
    def __init__(self, password, filepath=DB_FILE_PATH):
        self.filepath = filepath
        self.password = password
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        self._cached_key = None

        # In-memory database for runtime operations
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._apply_performance_pragmas(self.conn)
        self._is_dirty = False

        self._load_from_disk()
        self._create_tables()
        self._import_from_json_if_needed()

    def _apply_performance_pragmas(self, conn):
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA mmap_size = 30000000000") # 30GB to allow mapping entire DB if needed

    def _get_encryption_key(self, salt=None):
        if self._cached_key:
            return self._cached_key

        if salt is None:
            salt = b'piece_note_fixed_salt' # In a real SOC 2 app, salt should be stored per-user
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        self._cached_key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        return self._cached_key

    def _load_from_disk(self):
        if not os.path.exists(self.filepath):
            return

        try:
            with open(self.filepath, "rb") as f:
                data = f.read()

            # Check if it's a plain SQLite file
            if data.startswith(b"SQLite format 3"):
                log.info("Detected plaintext SQLite database. Migrating to encrypted format.")
                self.conn = sqlite3.connect(":memory:", check_same_thread=False)
                temp_conn = sqlite3.connect(self.filepath)
                temp_conn.backup(self.conn)
                temp_conn.close()
                self._is_dirty = True
                self.save_to_disk()
                return

            # Attempt to decrypt
            f_fernet = Fernet(self._get_encryption_key())
            decrypted_data = f_fernet.decrypt(data)
            self.conn.deserialize(decrypted_data)
            log.info("Encrypted database loaded successfully.")

        except Exception as e:
            log.error(f"Failed to load/decrypt database: {e}")
            raise DatabaseCorruptError(f"Database loading failed: {e}")

    def save_to_disk(self, force=False):
        """Serializes the in-memory database and saves it encrypted to disk."""
        if not self._is_dirty and not force:
            return True

        try:
            self._create_backup()
            serialized_data = self.conn.serialize()
            f_fernet = Fernet(self._get_encryption_key())
            encrypted_data = f_fernet.encrypt(serialized_data)

            with open(self.filepath, "wb") as f:
                f.write(encrypted_data)
            log.info("Database saved securely to disk.")
            self._is_dirty = False
            return True
        except Exception as e:
            log.error(f"Failed to save database to disk: {e}")
            return False

    def _create_tables(self):
        try:
            cursor = self.conn.cursor()
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_folder_id ON notes(folder_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_sort_order ON notes(sort_order)")

            # Create FTS5 virtual table for searching
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    note_id UNINDEXED,
                    title,
                    body,
                    content='notes',
                    content_rowid='note_id'
                )
            """)

            # Triggers to keep FTS table in sync with notes table
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                    INSERT INTO notes_fts(rowid, title, body) VALUES (new.note_id, new.title, new.body);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES('delete', old.note_id, old.title, old.body);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES('delete', old.note_id, old.title, old.body);
                    INSERT INTO notes_fts(rowid, title, body) VALUES (new.note_id, new.title, new.body);
                END
            """)
            self.conn.commit()
        except Exception as e:
            log.error(f"Failed to create tables: {e}")

    def load(self):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT folder_id, name FROM folders")
            folders_data = {fid: {"name": name, "notes": []} for fid, name in cursor.fetchall()}

            cursor.execute("SELECT note_id, title, folder_id FROM notes ORDER BY sort_order ASC")
            notes_data = {}
            for nid, title, fid in cursor.fetchall():
                notes_data[nid] = {"title": title}
                if fid in folders_data:
                    folders_data[fid]["notes"].append(nid)

            next_folder_id = (cursor.execute("SELECT MAX(folder_id) FROM folders").fetchone()[0] or 0) + 1
            next_note_id = (cursor.execute("SELECT MAX(note_id) FROM notes").fetchone()[0] or 0) + 1

            return {
                "folders": folders_data, "notes": notes_data,
                "next_folder_id": next_folder_id, "next_note_id": next_note_id,
            }
        except sqlite3.DatabaseError as e:
            log.error(f"Database error on load: {e}")
            raise DatabaseCorruptError("The database file appears to be corrupt.")

    _backup_done_this_session = False

    def _create_backup(self, force=False):
        if not force and StorageManager._backup_done_this_session:
            return True

        if os.path.exists(self.filepath):
            try:
                os.makedirs(os.path.dirname(self.backup_path), exist_ok=True)
                shutil.copy2(self.filepath, self.backup_path)
                log.info(f"Database backup created at {self.backup_path}")
                StorageManager._backup_done_this_session = True
                return True
            except IOError as e:
                log.error(f"Could not create database backup: {e}")
                return False
        return True

    def update_note_body(self, note_id, body):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE notes SET body = ? WHERE note_id = ?", (body, note_id))
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to update note body: {e}")
            return False

    def update_note_title(self, note_id, title):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE notes SET title = ? WHERE note_id = ?", (title, note_id))
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to update note title: {e}")
            return False

    def create_note(self, folder_id, title, note_id=None):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT MAX(sort_order) FROM notes WHERE folder_id = ?", (folder_id,))
            max_order = cursor.fetchone()[0]
            sort_order = 0 if max_order is None else max_order + 1

            if note_id is None:
                cursor.execute(
                    "INSERT INTO notes (title, folder_id, sort_order) VALUES (?, ?, ?)",
                    (title, folder_id, sort_order)
                )
                new_id = cursor.lastrowid
            else:
                cursor.execute(
                    "INSERT INTO notes (note_id, title, folder_id, sort_order) VALUES (?, ?, ?, ?)",
                    (note_id, title, folder_id, sort_order)
                )
                new_id = note_id
            self.conn.commit()
            self._is_dirty = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create note: {e}")
            return None

    def delete_note(self, note_id):
        return self.delete_notes([note_id])

    def delete_notes(self, note_ids):
        if not note_ids:
            return True
        try:
            cursor = self.conn.cursor()
            placeholders = ",".join(["?"] * len(note_ids))
            cursor.execute(f"DELETE FROM notes WHERE note_id IN ({placeholders})", note_ids)
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to delete notes: {e}")
            return False

    def create_folder(self, name, folder_id=None):
        try:
            cursor = self.conn.cursor()
            if folder_id is None:
                cursor.execute("INSERT INTO folders (name) VALUES (?)", (name,))
                new_id = cursor.lastrowid
            else:
                cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (folder_id, name))
                new_id = folder_id
            self.conn.commit()
            self._is_dirty = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create folder: {e}")
            return None

    def rename_folder(self, folder_id, name):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE folders SET name = ? WHERE folder_id = ?", (name, folder_id))
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to rename folder: {e}")
            return False

    def delete_folder(self, folder_id):
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to delete folder: {e}")
            return False

    def reorder_notes(self, folder_id, note_ids):
        try:
            cursor = self.conn.cursor()
            cursor.execute("BEGIN")
            for i, note_id in enumerate(note_ids):
                cursor.execute(
                    "UPDATE notes SET sort_order = ? WHERE note_id = ? AND folder_id = ?",
                    (i, note_id, folder_id)
                )
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to reorder notes: {e}")
            self.conn.rollback()
            return False

    def save_full_import(self, data):
        try:
            cursor = self.conn.cursor()
            cursor.execute("BEGIN")
            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM folders")

            for folder_id, folder_data in data.get("folders", {}).items():
                cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (folder_id, folder_data["name"]))
                for i, note_id in enumerate(folder_data.get("notes", [])):
                    note_data = data["notes"].get(note_id)
                    if note_data:
                        cursor.execute(
                            "INSERT INTO notes (note_id, title, body, folder_id, sort_order) VALUES (?, ?, ?, ?, ?)",
                            (note_id, note_data["title"], note_data.get("body", ""), folder_id, i)
                        )
            self.conn.commit()
            self._is_dirty = True
            return True
        except Exception as e:
            log.error(f"Error during full data save: {e}")
            self.conn.rollback()
            return False

    def restore_from_backup(self):
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                # After restoring, we need to reload the in-memory database
                self._load_from_disk()
                return True
            except IOError as e:
                log.error(f"Failed to restore from backup: {e}")
                return False
        return False

    def get_note_body(self, note_id):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT body FROM notes WHERE note_id = ?", (note_id,))
            result = cursor.fetchone()
            return result[0] if result else ""
        except Exception as e:
            log.error(f"Failed to fetch note body: {e}")
            return ""

    def search_notes(self, query):
        if not query:
            return []

        try:
            cursor = self.conn.cursor()
            sql_query = """
                SELECT n.note_id, n.title, f.folder_id, f.name
                FROM notes_fts fts
                JOIN notes n ON fts.rowid = n.note_id
                JOIN folders f ON n.folder_id = f.folder_id
                WHERE notes_fts MATCH ?
                ORDER BY rank
            """
            cursor.execute(sql_query, (query,))

            results = []
            for note_id, title, folder_id, folder_name in cursor.fetchall():
                results.append({
                    "note_id": note_id, "title": title,
                    "folder_id": folder_id, "folder_name": folder_name
                })
            return results
        except sqlite3.OperationalError as e:
            log.error(f"FTS5 Search error: {e}")
            try:
                search_term = f"%{query}%"
                cursor.execute("""
                    SELECT n.note_id, n.title, f.folder_id, f.name
                    FROM notes n
                    JOIN folders f ON n.folder_id = f.folder_id
                    WHERE n.title LIKE ? OR n.body LIKE ?
                """, (search_term, search_term))
                results = []
                for note_id, title, folder_id, folder_name in cursor.fetchall():
                    results.append({
                        "note_id": note_id, "title": title,
                        "folder_id": folder_id, "folder_name": folder_name
                    })
                return results
            except Exception:
                return []

    def _import_from_json_if_needed(self):
        json_path = JSON_IMPORT_PATH
        if os.path.exists(json_path):
            log.info("Found 'cybernotes_data.json', attempting to import.")
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                data['folders'] = {int(k): v for k, v in data['folders'].items()}
                data['notes'] = {int(k): v for k, v in data['notes'].items()}

                save_successful = self.save_full_import(data)

                if save_successful:
                    os.rename(json_path, f"{json_path}.imported")
                    log.info("Successfully imported data. The old file has been renamed.")
                else:
                    log.error("Import failed due to a database error. The JSON file has not been changed.")
            except Exception as e:
                log.error(f"Failed to read or process JSON file: {e}")
