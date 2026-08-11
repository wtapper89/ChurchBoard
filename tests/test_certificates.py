from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.certificates import _trust_macos_certificate, _update_settings


class CertificateTests(unittest.TestCase):
    def test_certificate_trust_uses_current_user_not_system_keychain(self):
        certificate = Path("/tmp/churchboard-local-ca.crt")
        with patch("app.certificates._run") as run:
            _trust_macos_certificate(certificate)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["/usr/bin/security", "add-trusted-cert", "-r", "trustRoot"])
        self.assertNotIn("-d", command)
        self.assertNotIn("/Library/Keychains/System.keychain", command)

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
