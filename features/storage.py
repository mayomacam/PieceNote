import sqlite3
import json
import os
import shutil
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
from utils.helpers import DB_FILE_PATH, BACKUP_LOCATION, JSON_IMPORT_PATH, log
from utils.logger import audit_log

# ---------------- Storage handling ----------------------------------

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass

class StorageManager:
    def __init__(self, filepath=DB_FILE_PATH, password=None):
        self.filepath = filepath
        self.password = password
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        self._cached_key = None

        # We use an in-memory database for performance and to keep decrypted data off-disk
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")

        if os.path.exists(self.filepath):
            self._load_from_disk()
        else:
            self._create_tables()
            if password:
                self.save_to_disk()

        self._import_from_json_if_needed()

    def _derive_key(self, salt):
        if self._cached_key:
            return self._cached_key

        if not self.password:
            raise ValueError("Password is required for encryption/decryption.")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        self._cached_key = key
        return key

    def _load_from_disk(self):
        """Loads and decrypts the database from disk into memory."""
        try:
            with open(self.filepath, "rb") as f:
                salt = f.read(16)
                encrypted_data = f.read()

            if not encrypted_data:
                # Handle case where file might just have salt but no data (shouldn't happen normally)
                self._create_tables()
                return

            key = self._derive_key(salt)
            f_obj = Fernet(key)
            try:
                decrypted_data = f_obj.decrypt(encrypted_data)
            except Exception:
                # Likely wrong password
                audit_log("Authentication Failed", "Incorrect master password provided.")
                raise DatabaseCorruptError("Invalid password or corrupt database.")

            self.conn.deserialize(decrypted_data)
            audit_log("Database Loaded", "Encrypted database loaded from disk.")
        except Exception as e:
            if isinstance(e, DatabaseCorruptError):
                raise
            log.error(f"Failed to load database from disk: {e}")
            # Check if it's a plain sqlite file (migration path)
            try:
                temp_conn = sqlite3.connect(self.filepath)
                temp_conn.execute("SELECT count(*) FROM folders")
                temp_conn.close()
                log.info("Detected plain SQLite database. Migrating to encrypted format.")
                self.conn.close()
                self.conn = sqlite3.connect(self.filepath) # Load plain
                data = self.conn.serialize()
                self.conn.close()
                self.conn = sqlite3.connect(":memory:", check_same_thread=False)
                self.conn.deserialize(data)
                self.save_to_disk() # Encrypt and save
                log.info("Migration successful.")
            except Exception:
                raise DatabaseCorruptError(f"The database file is corrupt or invalid: {e}")

    def save_to_disk(self):
        """Serializes and encrypts the in-memory database to disk."""
        if not self.password:
            log.warning("No password set, skipping encrypted save.")
            return False

        try:
            self._create_backup()
            data = self.conn.serialize()

            # To ensure performance, we reuse the salt and cache the key.
            # Constant re-derivation with 600k iterations would freeze the UI.
            existing_salt = None
            if os.path.exists(self.filepath):
                with open(self.filepath, "rb") as f:
                    existing_salt = f.read(16)

            salt = existing_salt if existing_salt and len(existing_salt) == 16 else os.urandom(16)
            key = self._derive_key(salt)

            f_obj = Fernet(key)
            encrypted_data = f_obj.encrypt(data)

            with open(self.filepath, "wb") as f:
                f.write(salt)
                f.write(encrypted_data)

            audit_log("Database Saved", "In-memory database encrypted and saved to disk.")
            return True
        except Exception as e:
            log.error(f"Failed to save database to disk: {e}")
            return False

    def _create_tables(self):
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

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                note_id UNINDEXED,
                title,
                body,
                content='notes',
                content_rowid='note_id'
            )
        """)

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

    def load(self):
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

    _backup_done_this_session = False

    def _create_backup(self, force=False):
        if not force and StorageManager._backup_done_this_session:
            return True

        if os.path.exists(self.filepath):
            try:
                os.makedirs(os.path.dirname(self.backup_path), exist_ok=True)
                shutil.copy2(self.filepath, self.backup_path)
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
            self.save_to_disk()
            return True
        except Exception as e:
            log.error(f"Failed to update note body: {e}")
            return False

    def update_note_title(self, note_id, title):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE notes SET title = ? WHERE note_id = ?", (title, note_id))
            self.conn.commit()
            self.save_to_disk()
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
            self.save_to_disk()
            return new_id
        except Exception as e:
            log.error(f"Failed to create note: {e}")
            return None

    def delete_notes(self, note_ids):
        if not note_ids:
            return True
        try:
            cursor = self.conn.cursor()
            placeholders = ",".join(["?"] * len(note_ids))
            cursor.execute(f"DELETE FROM notes WHERE note_id IN ({placeholders})", note_ids)
            self.conn.commit()
            self.save_to_disk()
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
            self.save_to_disk()
            return new_id
        except Exception as e:
            log.error(f"Failed to create folder: {e}")
            return None

    def rename_folder(self, folder_id, name):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE folders SET name = ? WHERE folder_id = ?", (name, folder_id))
            self.conn.commit()
            self.save_to_disk()
            return True
        except Exception as e:
            log.error(f"Failed to rename folder: {e}")
            return False

    def delete_folder(self, folder_id):
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
            self.conn.commit()
            self.save_to_disk()
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
            self.save_to_disk()
            return True
        except Exception as e:
            log.error(f"Failed to reorder notes: {e}")
            self.conn.rollback()
            return False

    def get_note_body(self, note_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT body FROM notes WHERE note_id = ?", (note_id,))
        result = cursor.fetchone()
        return result[0] if result else ""

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
        except sqlite3.OperationalError:
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
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['folders'] = {int(k): v for k, v in data['folders'].items()}
                data['notes'] = {int(k): v for k, v in data['notes'].items()}

                # Manual insertion for import
                cursor = self.conn.cursor()
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
                self.save_to_disk()
                os.rename(json_path, f"{json_path}.imported")
                log.info("Successfully imported data from JSON.")
            except Exception as e:
                log.error(f"Failed to import JSON: {e}")

    def restore_from_backup(self):
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                self._load_from_disk()
                return True
            except Exception as e:
                log.error(f"Failed to restore from backup: {e}")
                return False
        return False
