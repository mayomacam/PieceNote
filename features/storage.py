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

# ---------------- Constants ----------------------------------
PBKDF2_ITERATIONS = 600000
SALT_SIZE = 16

# ---------------- Storage handling ----------------------------------

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass

class EncryptionError(Exception):
    """Custom exception for encryption/decryption issues."""
    pass

class StorageManager:
    def __init__(self, password=None, filepath=DB_FILE_PATH):
        self.filepath = filepath
        self.password = password
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        self._cached_key = None
        self._in_memory_conn = None
        self._is_modified = False

        # Initialize the in-memory connection
        self._init_memory_db()

        if os.path.exists(self.filepath):
            self._load_from_disk()
        else:
            self._create_tables()
            # If a password was provided, save the empty DB in encrypted format immediately
            if self.password:
                self._is_modified = True
                self.save_to_disk()

        self._import_from_json_if_needed()

    def _init_memory_db(self):
        """Initializes the in-memory SQLite database connection."""
        if not hasattr(sqlite3.Connection, "serialize"):
            raise RuntimeError(
                "SQLite serialize/deserialize APIs are not available in this Python environment. "
                "Please ensure you are using Python 3.11+ and that SQLite is compiled with SQLITE_ENABLE_SERIALIZE."
            )
        self._in_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._in_memory_conn.execute("PRAGMA foreign_keys = ON")
        # Apply performance PRAGMAs
        self._in_memory_conn.execute("PRAGMA journal_mode = MEMORY")
        self._in_memory_conn.execute("PRAGMA synchronous = OFF")
        self._in_memory_conn.execute("PRAGMA mmap_size = 30000000000")

    def _get_connection(self):
        """Returns the in-memory connection."""
        return self._in_memory_conn

    def _derive_key(self, salt):
        """Derives an encryption key from the password and salt."""
        if self._cached_key and salt == self._cached_salt:
            return self._cached_key

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        self._cached_key = key
        self._cached_salt = salt
        return key

    def _load_from_disk(self):
        """Loads data from the disk file into the in-memory database."""
        with open(self.filepath, "rb") as f:
            data = f.read()

        if not data:
            self._create_tables()
            return

        # Check if it's a plaintext SQLite database
        if data.startswith(b"SQLite format 3"):
            log.info("Plaintext SQLite database detected. Migrating to encrypted format.")
            temp_conn = sqlite3.connect(self.filepath)
            serialized = temp_conn.serialize()
            temp_conn.close()
            self._in_memory_conn.deserialize(serialized)
            self._is_modified = True
            if self.password:
                self.save_to_disk()
            return

        # Attempt to decrypt
        try:
            if not self.password:
                raise EncryptionError("Password required for encrypted database.")

            salt = data[:SALT_SIZE]
            ciphertext = data[SALT_SIZE:]
            key = self._derive_key(salt)
            fernet = Fernet(key)
            decrypted_data = fernet.decrypt(ciphertext)
            self._in_memory_conn.deserialize(decrypted_data)
        except Exception as e:
            audit_log("Decryption Failed", f"Error: {str(e)}")
            log.error(f"Failed to decrypt database: {e}")
            raise DatabaseCorruptError("Invalid password or corrupt encrypted database.")

    def save_to_disk(self):
        """Serializes the in-memory DB, encrypts it, and writes to disk."""
        if not self._is_modified:
            return True
        if not self.password:
            # If no password, we don't encrypt (legacy or developer mode)
            # but for SOC 2, we should probably enforce it.
            # For now, let's just write plaintext if no password.
            serialized = self._in_memory_conn.serialize()
            with open(self.filepath, "wb") as f:
                f.write(serialized)
            self._is_modified = False
            return True

        self._create_backup()
        try:
            serialized = self._in_memory_conn.serialize()
            salt = os.urandom(SALT_SIZE)
            key = self._derive_key(salt)
            fernet = Fernet(key)
            encrypted_data = fernet.encrypt(serialized)

            with open(self.filepath, "wb") as f:
                f.write(salt + encrypted_data)

            self._is_modified = False
            return True
        except Exception as e:
            audit_log("Encryption Failed", f"Error: {str(e)}")
            log.error(f"Failed to encrypt database: {e}")
            return False

    def _create_tables(self):
        conn = self._get_connection()
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
        conn.commit()

    def load(self):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
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
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE notes SET body = ? WHERE note_id = ?", (body, note_id))
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to update note body: {e}")
            return False

    def update_note_title(self, note_id, title):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE notes SET title = ? WHERE note_id = ?", (title, note_id))
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to update note title: {e}")
            return False

    def create_note(self, folder_id, title, note_id=None):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
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
            conn.commit()
            self._is_modified = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create note: {e}")
            return None

    def delete_notes(self, note_ids):
        if not note_ids:
            return True
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(note_ids))
            cursor.execute(f"DELETE FROM notes WHERE note_id IN ({placeholders})", note_ids)
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to delete notes: {e}")
            return False

    def create_folder(self, name, folder_id=None):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if folder_id is None:
                cursor.execute("INSERT INTO folders (name) VALUES (?)", (name,))
                new_id = cursor.lastrowid
            else:
                cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (folder_id, name))
                new_id = folder_id
            conn.commit()
            self._is_modified = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create folder: {e}")
            return None

    def rename_folder(self, folder_id, name):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE folders SET name = ? WHERE folder_id = ?", (name, folder_id))
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to rename folder: {e}")
            return False

    def delete_folder(self, folder_id):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to delete folder: {e}")
            return False

    def reorder_notes(self, folder_id, note_ids):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            for i, note_id in enumerate(note_ids):
                cursor.execute(
                    "UPDATE notes SET sort_order = ? WHERE note_id = ? AND folder_id = ?",
                    (i, note_id, folder_id)
                )
            conn.commit()
            self._is_modified = True
            return True
        except Exception as e:
            log.error(f"Failed to reorder notes: {e}")
            conn.rollback()
            return False

    def save_full_import(self, data):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
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
            conn.commit()
            self._is_modified = True
            self.save_to_disk()
            return True
        except Exception as e:
            log.error(f"Error during full data save: {e}")
            conn.rollback()
            return False

    def restore_from_backup(self):
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                self._load_from_disk()
                return True
            except IOError as e:
                log.error(f"Failed to restore from backup: {e}")
                return False
        return False

    def get_note_body(self, note_id):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT body FROM notes WHERE note_id = ?", (note_id,))
            result = cursor.fetchone()
            return result[0] if result else ""
        finally:
            pass # We don't close the in-memory connection

    def search_notes(self, query):
        if not query:
            return []

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
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
                    log.error("Import failed due to a database error.")
            except Exception as e:
                log.error(f"Failed to read or process JSON file: {e}")
