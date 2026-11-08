"""File-backed keyring for tests: the real macOS Keychain is never touched. File path: env FAKEKR_FILE."""
import json, os
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

class FileKR(KeyringBackend):
    priority = 100
    def _load(self):
        try: return json.load(open(os.environ["FAKEKR_FILE"]))
        except (OSError, ValueError): return {}
    def _save(self, d): json.dump(d, open(os.environ["FAKEKR_FILE"], "w"))
    def get_password(self, s, u): return self._load().get(f"{s}|{u}")
    def set_password(self, s, u, p):
        d = self._load(); d[f"{s}|{u}"] = p; self._save(d)
    def delete_password(self, s, u):
        d = self._load()
        if f"{s}|{u}" not in d: raise PasswordDeleteError("not found")
        del d[f"{s}|{u}"]; self._save(d)
