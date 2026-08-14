import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.modules.updates import ModulePackageManager, ModuleUpdateError


class ModulePackageManagerTests(unittest.TestCase):
    def test_update_verifies_and_activates_files(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ModulePackageManager(Path(temp))
            content = b"value = 42\n"
            digest = hashlib.sha256(content).hexdigest()
            manager._request = lambda url: content
            manager.update("example", {"version": "1.2.0", "files": [{"path": "adapter.py", "url": "memory:", "sha256": digest}]})
            self.assertEqual(manager.active_file("example", "adapter.py").read_bytes(), content)

    def test_bad_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ModulePackageManager(Path(temp))
            manager._request = lambda url: b"not the expected file"
            with self.assertRaises(ModuleUpdateError):
                manager.update("example", {"version": "1.0.0", "files": [{"path": "adapter.py", "url": "memory:", "sha256": "0" * 64}]})

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ModulePackageManager(Path(temp))
            with self.assertRaises(ModuleUpdateError):
                manager.update("example", {"version": "1.0.0", "files": [{"path": "../outside.py", "url": "memory:"}]})


if __name__ == "__main__":
    unittest.main()
