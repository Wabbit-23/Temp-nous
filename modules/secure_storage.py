# modules/secure_storage.py

from cryptography.fernet import Fernet
from pathlib import Path
import base64
import hashlib
import json

def _derive_key(password: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())

def get_vault_path():
    return Path(__file__).parent.parent / "data" / "secure_data.vault"

def save_secure_data(data: dict, password: str):
    key = _derive_key(password)
    fernet = Fernet(key)
    path = get_vault_path()
    encrypted = fernet.encrypt(json.dumps(data).encode())
    path.write_bytes(encrypted)

def load_secure_data(password: str) -> dict:
    key = _derive_key(password)
    fernet = Fernet(key)
    path = get_vault_path()
    if not path.exists():
        return {}
    try:
        decrypted = fernet.decrypt(path.read_bytes())
        return json.loads(decrypted.decode())
    except Exception as e:
        raise ValueError("Incorrect password or corrupt vault.") from e

def delete_vault():
    get_vault_path().unlink(missing_ok=True)
