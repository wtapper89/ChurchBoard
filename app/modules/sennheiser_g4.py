"""EW 300–500 G4 Media Control Protocol (Sennheiser TI 1254 v1.0)."""
from __future__ import annotations

import asyncio
import re
import socket
from typing import Any


def parse_g4_response(text: str, receiver: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for line in re.split(r'[\r\n;]+', text):
        key, _, value = line.strip().partition(' ')
        if key:
            fields[key.casefold()] = value.strip()
    if not {'rf', 'af', 'bat', 'config'} <= fields.keys():
        raise ValueError('Incomplete EW G4 meter response')
    rf, af = fields['rf'].split(), fields['af'].split()
    if not rf or not af:
        raise ValueError('Invalid EW G4 meter response')
    battery = fields['bat']
    online = len(rf) >= 3 and rf[2] == '1'
    warnings = [s.replace('_', ' ') for s in fields.get('msg', '').split() if s != 'OK']
    mic = (receiver.get('channel_configs') or [{}])[0]
    muted = bool(int(af[2]) & 1) if len(af) >= 3 else fields.get('mute') == '1'
    if not online:
        warnings.append('Transmitter off')
    return {
        'id': str(mic.get('id') or receiver.get('id') or receiver.get('host')),
        'receiver': receiver.get('name') or receiver.get('host'), 'channel': 1,
        'name': mic.get('name') or fields.get('name') or 'EW G4',
        'battery_percent': max(0, min(100, int(battery))) if battery != '?' else 0,
        'battery_available': battery != '?', 'rf': max(0, min(100, int(rf[0]))),
        'audio': max(0, min(100, int(af[0]))), 'muted': muted,
        'online': online, 'receiver_online': True,
        'frequency': f"{int(fields['frequency'].split()[-1]) / 1000:.3f} MHz" if fields.get('frequency') else '',
        'model': 'Sennheiser EW 300–500 G4', 'firmware': fields.get('firmwarerevision', ''),
        'default_photo': mic.get('default_photo') or '', 'errors': warnings,
    }


async def query_g4(receiver: dict[str, Any]) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, (str(receiver['host']), int(receiver.get('port') or 53212)))
        # One-shot configuration + cyclic update; no receiver settings change.
        for command in (b'Name\r', b'Frequency\r', b'FirmwareRevision\r', b'Push 0 100 1\r'):
            await loop.sock_sendall(sock, command)
        chunks = []
        deadline = loop.time() + 1.5
        while loop.time() < deadline:
            try:
                packet = await asyncio.wait_for(loop.sock_recv(sock, 1500), deadline - loop.time())
            except asyncio.TimeoutError:
                break
            chunks.append(packet.decode('ascii', 'replace'))
            text = '\r'.join(chunks)
            if all(re.search(r'(?:^|[\r\n;])' + key + r' ', text, re.I) for key in ('Name', 'Frequency', 'FirmwareRevision', 'RF', 'AF', 'Bat', 'Config')):
                return parse_g4_response(text, receiver)
        return parse_g4_response('\r'.join(chunks), receiver)
    finally:
        sock.close()
