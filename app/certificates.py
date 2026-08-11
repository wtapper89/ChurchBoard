from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import tempfile
from pathlib import Path

from app.config import DATA_DIR


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"Command failed: {command[0]}")


def _local_names_and_addresses() -> tuple[list[str], list[str]]:
    hostname = socket.gethostname().split(".")[0].strip() or "churchboard"
    names = {"localhost", hostname, f"{hostname}.local", "churchboard.local"}
    addresses = {"127.0.0.1"}
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if address and not address.startswith("169.254."):
                addresses.add(address)
    except OSError:
        pass
    for interface in ("en0", "en1"):
        result = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", interface], capture_output=True, text=True, check=False
        )
        address = result.stdout.strip()
        if address:
            addresses.add(address)
    return sorted(names), sorted(addresses)


def _update_settings(data_file: Path, certificate: Path, private_key: Path) -> None:
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    settings = data.setdefault("settings", {})
    server = settings.setdefault("server", {})
    server.update({
        "https_enabled": True,
        "ssl_certfile": str(certificate),
        "ssl_keyfile": str(private_key),
    })
    data_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = data_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, data_file)


def install_macos_https(data_file: Path | None = None) -> dict:
    if os.uname().sysname != "Darwin":
        raise RuntimeError("The guided HTTPS installer is currently available on macOS only")
    openssl = Path("/usr/bin/openssl")
    security = Path("/usr/bin/security")
    if not openssl.exists() or not security.exists():
        raise RuntimeError("The required macOS certificate tools could not be found")

    target = DATA_DIR / "https"
    target.mkdir(parents=True, exist_ok=True)
    ca_key = target / "churchboard-local-ca.key"
    ca_cert = target / "churchboard-local-ca.crt"
    server_key = target / "churchboard.key"
    server_csr = target / "churchboard.csr"
    server_cert = target / "churchboard.crt"
    names, addresses = _local_names_and_addresses()

    with tempfile.TemporaryDirectory(prefix="churchboard-https-") as temporary:
        extension = Path(temporary) / "extensions.cnf"
        sans = [*(f"DNS:{name}" for name in names), *(f"IP:{address}" for address in addresses)]
        extension.write_text(
            "basicConstraints=CA:FALSE\n"
            "keyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName={','.join(sans)}\n",
            encoding="utf-8",
        )
        if not ca_key.exists() or not ca_cert.exists():
            _run([str(openssl), "req", "-x509", "-newkey", "rsa:4096", "-sha256", "-nodes",
                  "-days", "3650", "-subj", "/CN=ChurchBoard Local CA", "-keyout", str(ca_key),
                  "-out", str(ca_cert)])
        _run([str(openssl), "req", "-new", "-newkey", "rsa:2048", "-sha256", "-nodes",
              "-subj", "/CN=churchboard.local", "-keyout", str(server_key), "-out", str(server_csr)])
        _run([str(openssl), "x509", "-req", "-sha256", "-days", "825", "-in", str(server_csr),
              "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-extfile", str(extension),
              "-out", str(server_cert)])

    os.chmod(ca_key, 0o600)
    os.chmod(server_key, 0o600)
    server_csr.unlink(missing_ok=True)
    trust_command = " ".join(shlex.quote(part) for part in [
        str(security), "add-trusted-cert", "-d", "-r", "trustRoot",
        "-k", "/Library/Keychains/System.keychain", str(ca_cert),
    ])
    escaped = trust_command.replace("\\", "\\\\").replace('"', '\\"')
    _run(["/usr/bin/osascript", "-e", f'do shell script "{escaped}" with administrator privileges'])
    _update_settings(data_file or DATA_DIR / "churchboard.json", server_cert, server_key)
    return {"certificate": str(server_cert), "private_key": str(server_key), "ca_certificate": str(ca_cert),
            "names": names, "addresses": addresses}
