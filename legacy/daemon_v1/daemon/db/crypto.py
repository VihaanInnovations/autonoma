from cryptography.fernet import Fernet
from pathlib import Path
import os

KEY_FILE = Path(__file__).parent.parent.parent / "secret.key"

def load_key():
    """Load or create the encryption key."""
    if not KEY_FILE.exists():
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)
        return key
    else:
        with open(KEY_FILE, "rb") as key_file:
            return key_file.read()

# Initialize Cipher Suite
_key = load_key()
_cipher_suite = Fernet(_key)

def encrypt(data: str) -> str:
    """Encrypt a string."""
    if not data: return ""
    return _cipher_suite.encrypt(data.encode('utf-8')).decode('utf-8')

def decrypt(data: str) -> str:
    """Decrypt a string."""
    if not data: return ""
    try:
        return _cipher_suite.decrypt(data.encode('utf-8')).decode('utf-8')
    except Exception:
        return "[Encrypted Data]"  # Fail safe
