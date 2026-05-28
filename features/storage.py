import sqlite3
import json
import os
import shutil
from utils.helpers import DB_FILE_PATH, BACKUP_LOCATION, JSON_IMPORT_PATH, log
from utils.encryption import EncryptionManager
from utils.logger import audit_log

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass

class StorageManager:
    def __init__(self, filepath=DB_FILE_PATH, password=None):
        self.filepath = filepath
        self.password = password
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        self._in_memory_conn = None
        self._encryption_manager = None
        self._dirty = False

        if password:
            self._load_encrypted_to_memory(password)
        else:
            self._load_unencrypted_to_memory()

    def _load_encrypted_to_memory(self, password):
        """Loads and decrypts the database file into an in-memory connection."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'rb') as f:
                    encrypted_data = f.read()

                if encrypted_data.startswith(b'SQLite format 3'):
                    audit_log("Warning", "Loading unencrypted database even though password provided.")
                    self._load_unencrypted_to_memory()
                    # We still want an encryption manager for future saves
                    self._encryption_manager = EncryptionManager(password)
                    return

                # The unified EncryptionManager expects salt as first 16 bytes
                decrypted_data = EncryptionManager.decrypt(encrypted_data, password)
                # Initialize encryption manager with the salt from the file for future consistent saves
                salt = encrypted_data[:16]
                self._encryption_manager = EncryptionManager(password, salt=salt)

                self._in_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._in_memory_conn.deserialize(decrypted_data)
                audit_log("Database Load", "Encrypted database loaded to memory successfully")
                self._create_tables()
                self._import_from_json_if_needed()
            except Exception as e:
                log.error(f"Failed to load encrypted database: {e}")
                raise DatabaseCorruptError(f"Failed to decrypt database: {e}")
        else:
            # New database with password
            self._encryption_manager = EncryptionManager(password)
            self._load_unencrypted_to_memory()

    def _load_unencrypted_to_memory(self):
        """Loads unencrypted database into memory, or creates a new one in memory."""
        self._in_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'rb') as f:
                    data = f.read()
                if data.startswith(b'SQLite format 3'):
                    self._in_memory_conn.deserialize(data)
                    audit_log("Database Load", "Unencrypted database loaded to memory")
                else:
                    log.error("Database file exists but is not a valid SQLite file.")
            except Exception as e:
                log.error(f"Failed to load existing database: {e}")

        self._create_tables()
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
        """Returns the in-memory connection with optimized PRAGMAs."""
        conn = self._in_memory_conn
        conn.execute("PRAGMA foreign_keys = ON")
        # Optimization for large data and performance
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA mmap_size = 268435456") # 256MB
        return conn

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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_folder_id ON notes(folder_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_sort_order ON notes(sort_order)")

            # Full Text Search
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    note_id UNINDEXED,
                    title,
                    body,
                    content='notes',
                    content_rowid='note_id'
                )
            """)

            # Triggers for FTS sync
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
        except Exception as e:
            log.error(f"Failed to create tables: {e}")

    def save_to_disk(self, force=False):
        """Serializes the in-memory database and saves it to disk if dirty."""
        if not self._in_memory_conn or (not self._dirty and not force):
            return True

        try:
            data = self._in_memory_conn.serialize()
            if self._encryption_manager:
                data_to_save = self._encryption_manager.encrypt(data)
                audit_log("Database Save", "Saving encrypted database to disk")
            else:
                data_to_save = data
                audit_log("Database Save", "Saving unencrypted database to disk")

            self._create_backup(force=False) # Backup once per session usually

            # Atomic-ish write
            with open(self.filepath, 'wb') as f:
                f.write(data_to_save)

            self._dirty = False
            return True
        except Exception as e:
            log.error(f"Failed to save database to disk: {e}")
            return False

    def load(self):
        """Loads metadata for the UI (folders and notes headers)."""
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
                "folders": folders_data,
                "notes": notes_data,
                "next_folder_id": next_folder_id,
                "next_note_id": next_note_id,
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
                StorageManager._backup_done_this_session = True
                audit_log("Backup", f"Created database backup at {self.backup_path}")
                return True
            except IOError as e:
                log.error(f"Could not create database backup: {e}")
                return False
        return True

    def restore_from_backup(self):
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                audit_log("Backup Restore", f"Restored database from {self.backup_path}")
                return True
            except Exception as e:
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
        except Exception as e:
            log.error(f"Failed to get note body: {e}")
            return ""

    def update_note_body(self, note_id, body):
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE notes SET body = ? WHERE note_id = ?", (body, note_id))
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to update note body: {e}")
            return False

    def update_note_title(self, note_id, title):
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE notes SET title = ? WHERE note_id = ?", (title, note_id))
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to update note title: {e}")
            return False

    def create_note(self, folder_id, title):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(sort_order) FROM notes WHERE folder_id = ?", (folder_id,))
            max_order = cursor.fetchone()[0]
            sort_order = 0 if max_order is None else max_order + 1

            cursor.execute(
                "INSERT INTO notes (title, folder_id, sort_order) VALUES (?, ?, ?)",
                (title, folder_id, sort_order)
            )
            new_id = cursor.lastrowid
            conn.commit()
            self._dirty = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create note: {e}")
            return None

    def delete_notes(self, note_ids):
        if not note_ids:
            return True
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            placeholders = ",".join(["?"] * len(note_ids))
            cursor.execute(f"DELETE FROM notes WHERE note_id IN ({placeholders})", note_ids)
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to delete notes: {e}")
            return False

    def create_folder(self, name):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO folders (name) VALUES (?)", (name,))
            new_id = cursor.lastrowid
            conn.commit()
            self._dirty = True
            return new_id
        except Exception as e:
            log.error(f"Failed to create folder: {e}")
            return None

    def rename_folder(self, folder_id, name):
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE folders SET name = ? WHERE folder_id = ?", (name, folder_id))
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to rename folder: {e}")
            return False

    def delete_folder(self, folder_id):
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to delete folder: {e}")
            return False

    def reorder_notes(self, folder_id, note_ids):
        conn = self._get_connection()
        try:
            cursor = self.conn.cursor()
            cursor.execute("BEGIN")
            for i, note_id in enumerate(note_ids):
                cursor.execute(
                    "UPDATE notes SET sort_order = ? WHERE note_id = ? AND folder_id = ?",
                    (i, note_id, folder_id)
                )
            conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            log.error(f"Failed to reorder notes: {e}")
            conn.rollback()
            return False

    def search_notes(self, query):
        if not query:
            return []
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Try FTS5 first
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
        except sqlite3.OperationalError:
            # Fallback to LIKE
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

    def _import_from_json_if_needed(self):
        json_path = JSON_IMPORT_PATH
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                cursor.execute("DELETE FROM notes")
                cursor.execute("DELETE FROM folders")
                for fid_str, fdata in data.get("folders", {}).items():
                    fid = int(fid_str)
                    cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (fid, fdata["name"]))
                    for i, nid_str in enumerate(fdata.get("notes", [])):
                        nid = int(nid_str)
                        ndata = data["notes"].get(nid_str) or data["notes"].get(nid)
                        if ndata:
                            cursor.execute(
                                "INSERT INTO notes (note_id, title, body, folder_id, sort_order) VALUES (?, ?, ?, ?, ?)",
                                (nid, ndata["title"], ndata.get("body", ""), fid, i)
                            )
                conn.commit()
                self._dirty = True
                self.save_to_disk()
                os.rename(json_path, f"{json_path}.imported")
                audit_log("Import", f"Imported data from {json_path}")
            except Exception as e:
                log.error(f"JSON Import failed: {e}")
                if 'conn' in locals(): conn.rollback()
