import sqlite3
import json
import os
import shutil
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, InvalidToken
from utils.helpers import DB_FILE_PATH, BACKUP_LOCATION, JSON_IMPORT_PATH, log
from utils.logger import audit_log

# ---------------- Encryption handling ----------------------------------

class EncryptionManager:
    """Manages PBKDF2 key derivation and Fernet encryption."""
    def __init__(self, password="PieceNoteDefaultPassword"):
        # SOC 2 note: In a production environment, the password and salt
        # should be uniquely generated for each user and stored securely.
        self.salt = b'piece_note_fixed_salt_v1'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        self.fernet = Fernet(key)

    def encrypt(self, data):
        return self.fernet.encrypt(data)

    def decrypt(self, encrypted_data):
        return self.fernet.decrypt(encrypted_data)

# ---------------- Storage handling ----------------------------------

class DatabaseCorruptError(Exception):
    """Custom exception for when the database is unreadable."""
    pass

class StorageManager:
    def __init__(self, filepath=DB_FILE_PATH):
        self.filepath = filepath
        self.backup_path = os.path.join(BACKUP_LOCATION, f"{os.path.basename(filepath)}.bak")
        self.encryption = EncryptionManager()

        # In-memory database for runtime performance and security
        self.mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.mem_conn.execute("PRAGMA foreign_keys = ON")
        self.mem_conn.execute("PRAGMA synchronous = NORMAL")
        self.mem_conn.execute("PRAGMA mmap_size = 30000000000")

        if os.path.exists(self.filepath):
            self._initialize_from_disk()
        else:
            self._create_tables()
            self._save_to_disk()

        self._import_from_json_if_needed()

    def _initialize_from_disk(self):
        """Attempts to load encrypted data, or migrate plain SQLite if found."""
        try:
            with open(self.filepath, "rb") as f:
                header = f.read(16)
                f.seek(0)
                data = f.read()

            if header.startswith(b"SQLite format 3"):
                log.info("Detected plain SQLite database. Migrating to encrypted format...")
                self._migrate_plain_db(data)
            else:
                self._load_encrypted_data(data)
        except Exception as e:
            log.error(f"Failed to initialize database: {e}")
            raise DatabaseCorruptError(f"Database initialization failed: {e}")

    def _migrate_plain_db(self, plain_data):
        """Loads plain data and immediately saves it encrypted."""
        try:
            self.mem_conn.deserialize(plain_data)
            # Ensure tables exist (especially if migrating from a very old version)
            self._create_tables()
            self._save_to_disk()
            audit_log("Database Migration", "Successfully migrated plain SQLite to encrypted format.")
        except Exception as e:
            log.error(f"Migration failed: {e}")
            raise DatabaseCorruptError("Could not migrate plain database.")

    def _load_encrypted_data(self, encrypted_data):
        """Decrypts and loads data into memory."""
        try:
            decrypted_data = self.encryption.decrypt(encrypted_data)
            self.mem_conn.deserialize(decrypted_data)
            audit_log("Database Load", "Decrypted and loaded database into memory.")
        except InvalidToken:
            log.error("Invalid encryption key or corrupted data.")
            raise DatabaseCorruptError("Could not decrypt database. Incorrect password or corruption.")
        except Exception as e:
            log.error(f"Decryption/Load error: {e}")
            raise DatabaseCorruptError(f"Load error: {e}")

    def _get_connection(self):
        return self.mem_conn

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

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                note_id UNINDEXED,
                title,
                body,
                content='notes',
                content_rowid='note_id'
            )
        """)

        # Triggers for FTS
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

    def _save_to_disk(self):
        """Serializes and encrypts the in-memory database to disk."""
        try:
            # SOC 2 Performance Note: For extremely large databases,
            # incremental encryption or a different storage engine may be required.
            data = self.mem_conn.serialize()
            encrypted_data = self.encryption.encrypt(data)

            dir_name = os.path.dirname(self.filepath)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            with open(self.filepath, "wb") as f:
                f.write(encrypted_data)
            audit_log("Database Save", f"Encrypted and persisted to {self.filepath}")
        except Exception as e:
            log.error(f"Failed to save database: {e}")

    def load(self):
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
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE notes SET body = ? WHERE note_id = ?", (body, note_id))
            conn.commit()
            self._save_to_disk()
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
            self._save_to_disk()
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
            self._save_to_disk()
            return new_id
        except Exception as e:
            log.error(f"Failed to create note: {e}")
            return None

    def delete_notes(self, note_ids):
        if not note_ids:
            return True
        self._create_backup(force=True)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(note_ids))
            cursor.execute(f"DELETE FROM notes WHERE note_id IN ({placeholders})", note_ids)
            conn.commit()
            self._save_to_disk()
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
            self._save_to_disk()
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
            self._save_to_disk()
            return True
        except Exception as e:
            log.error(f"Failed to rename folder: {e}")
            return False

    def delete_folder(self, folder_id):
        self._create_backup(force=True)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
            conn.commit()
            self._save_to_disk()
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
            self._save_to_disk()
            return True
        except Exception as e:
            log.error(f"Failed to reorder notes: {e}")
            conn.rollback()
            return False

    def get_note_body(self, note_id):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT body FROM notes WHERE note_id = ?", (note_id,))
        result = cursor.fetchone()
        return result[0] if result else ""

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
        except sqlite3.OperationalError:
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

    def restore_from_backup(self):
        if os.path.exists(self.backup_path):
            try:
                shutil.copy2(self.backup_path, self.filepath)
                return True
            except IOError:
                return False
        return False

    def _import_from_json_if_needed(self):
        json_path = JSON_IMPORT_PATH
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['folders'] = {int(k): v for k, v in data['folders'].items()}
                data['notes'] = {int(k): v for k, v in data['notes'].items()}

                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                cursor.execute("DELETE FROM notes")
                cursor.execute("DELETE FROM folders")
                for fid, fdata in data.get("folders", {}).items():
                    cursor.execute("INSERT INTO folders (folder_id, name) VALUES (?, ?)", (fid, fdata["name"]))
                    for i, nid in enumerate(fdata.get("notes", [])):
                        ndata = data["notes"].get(nid)
                        if ndata:
                            cursor.execute(
                                "INSERT INTO notes (note_id, title, body, folder_id, sort_order) VALUES (?, ?, ?, ?, ?)",
                                (nid, ndata["title"], ndata.get("body", ""), fid, i)
                            )
                conn.commit()
                self._save_to_disk()
                os.rename(json_path, f"{json_path}.imported")
            except Exception as e:
                log.error(f"JSON Import failed: {e}")
