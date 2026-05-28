import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class EncryptionManager:
    def __init__(self, password: str, salt: bytes = None):
        """
        Initializes the encryption manager with a password and an optional salt.
        If salt is not provided, a new one is generated.
        """
        if salt is None:
            salt = os.urandom(16)
        self.salt = salt

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        self.fernet = Fernet(key)

    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypts the data and prepends the salt for later reconstruction.
        """
        encrypted_data = self.fernet.encrypt(data)
        return self.salt + encrypted_data

    @staticmethod
    def decrypt(encrypted_data_with_salt: bytes, password: str) -> bytes:
        """
        Decrypts data where the first 16 bytes are the salt.
        """
        if len(encrypted_data_with_salt) < 16:
            raise ValueError("Data too short to contain salt.")

        salt = encrypted_data_with_salt[:16]
        encrypted_data = encrypted_data_with_salt[16:]

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_data)
