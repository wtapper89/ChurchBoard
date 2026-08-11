from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.certificates import _update_settings


class CertificateTests(unittest.TestCase):
    def test_https_settings_are_merged_without_losing_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_file = root / "churchboard.json"
            data_file.write_text(json.dumps({"settings": {"timezone": "America/New_York", "server": {"port": 8040}}}))
            certificate = root / "churchboard.crt"
            private_key = root / "churchboard.key"
            _update_settings(data_file, certificate, private_key)
            saved = json.loads(data_file.read_text())
            self.assertEqual(saved["settings"]["timezone"], "America/New_York")
            self.assertEqual(saved["settings"]["server"]["port"], 8040)
            self.assertTrue(saved["settings"]["server"]["https_enabled"])
            self.assertEqual(saved["settings"]["server"]["ssl_certfile"], str(certificate))
            self.assertEqual(saved["settings"]["server"]["ssl_keyfile"], str(private_key))


if __name__ == "__main__":
    unittest.main()
