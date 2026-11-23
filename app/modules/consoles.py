"""A&H MIDI/TCP and Yamaha RCP adapters.

Protocol maps adapted from ProDeck (MIT), Copyright (c) 2026 Zach Green.
See THIRD_PARTY_NOTICES.md and licenses/PRODECK.txt.
"""
from __future__ import annotations

import asyncio
import shlex
from typing import Any

from app.modules.behringer import db_to_x32_fader

HEADER = bytes.fromhex('f0 00 00 1a 50 10 01 00')
# kind: offset, first note, count (Avantis / dLive)
NOTE_MAP = {'channel': (0, 0, 64, 128), 'bus': (2, 0, 40, 62),
            'aux': (2, 0x40, 20, 31), 'main': (4, 0x30, 3, 6),
            'dca': (4, 0x36, 16, 24)}
SQ_MAP = {'channel': (48, 0, 0x2000), 'bus': (12, 0x45, 0x2781),
          'aux': (12, 0x45, 0x2781), 'main': (1, 0x44, 0x2780),
          'dca': (8, 0x100, 0x27a0)}
# Published SQ linear taper table, retained at every breakpoint.
SQ_TAPER = [(-89.0, 4630), (-85.0, 5105), (-75.0, 6292), (-70.0, 6885), (-35.0, 11041), (-34.0, 11159), (-32.0, 11397), (-23.0, 12465), (-22.0, 12584), (-20.0, 12822), (-18.0, 13059), (-16.0, 13296), (-15.0, 13415), (-6.0, 14484), (-4.0, 14721), (-3.0, 14840), (-1.0, 15077), (1.0, 15315), (2.0, 15433), (3.0, 15552)]


def interpolate(value, pairs):
    if value <= pairs[0][0]:
        return pairs[0][1]
    for (a, x), (b, y) in zip(pairs, pairs[1:]):
        if value <= b:
            return x + (value - a) / (b - a) * (y - x)
    return pairs[-1][1]


def address(model, base, strip):
    kind, number = strip.get('kind', 'channel'), int(strip.get('number') or 1)
    if kind == 'send':
        raise ValueError('Personal channel sends are currently supported only on X32/M32 and WING')
    if model == 'sq':
        count, mute, level = SQ_MAP.get(kind, (0, 0, 0))
        if not 1 <= number <= count:
            raise ValueError('Channel is outside this console’s supported range')
        return base, mute + number - 1, level + number - 1
    off, first, avantis, dlive = NOTE_MAP.get(kind, (0, 0, 0, 0))
    if not 1 <= number <= (dlive if model == 'dlive' else avantis):
        raise ValueError('Channel is outside this console’s supported range')
    return base + off, first + number - 1, 0x17


def nrpn(channel, msb, lsb, coarse, fine=None):
    result = bytes([0xb0 | channel, 0x63, msb, 0xb0 | channel, 0x62, lsb,
                    0xb0 | channel, 0x06, coarse])
    return result + (bytes([0xb0 | channel, 0x26, fine]) if fine is not None else b'')


class ConsoleClient:
    def __init__(self, settings):
        self.settings = settings
        self.model = settings['model']
        self.host = str(settings.get('host') or '').strip()
        self.port = int(settings.get('port') or (49280 if self.model == 'yamaha' else 51325))
        self.base = int(settings.get('midi_channel') or 1) - 1
        if not 0 <= self.base < (16 if self.model == 'sq' else 12):
            raise ValueError('Invalid base MIDI channel')
        self.reader = self.writer = None
        self.lock = asyncio.Lock()
        self.values = {}
        self.selectors = {}
        self.buffer = bytearray()
        self.running = None
        self.pending = []
        self.sysex = None

    @property
    def configured(self):
        return bool(self.settings.get('enabled') and self.host)

    def close(self):
        if self.writer:
            self.writer.close()
        self.reader = self.writer = None
        self.values.clear()
        self.buffer.clear()
        self.selectors.clear()
        self.running, self.pending, self.sysex = None, [], None

    async def connect(self):
        if self.writer is None or self.writer.is_closing():
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 2)

    def feed(self, data):
        for byte in data:
            if byte >= 0xf8:  # realtime may interrupt any MIDI message
                continue
            if byte == 0xf0:
                self.sysex, self.running, self.pending = bytearray([byte]), None, []
                continue
            if self.sysex is not None:
                self.sysex.append(byte)
                if byte == 0xf7:
                    msg = bytes(self.sysex)
                    if msg.startswith(HEADER) and len(msg) >= 12 and msg[9] == 2:
                        self.values.setdefault((msg[8], msg[10]), {})['console_label'] = msg[11:-1].decode('ascii', 'replace').rstrip('\0 ')
                    self.sysex = None
                elif len(self.sysex) > 1024:
                    self.sysex = None
                continue
            if byte & 0x80:
                self.running, self.pending = byte, []
                continue
            if self.running is None:
                continue
            self.pending.append(byte)
            length = 1 if self.running & 0xf0 in (0xc0, 0xd0) else 2
            if len(self.pending) < length:
                continue
            status, args = self.running, self.pending
            self.pending = []
            channel, kind = status & 15, status & 0xf0
            if kind == 0x90 and self.model != 'sq' and args[1]:
                self.values.setdefault((channel, args[0]), {})['muted'] = args[1] >= 64
            elif kind == 0xb0:
                cc, value = args
                selected = self.selectors.setdefault(channel, {})
                selected[cc] = value
                if 0x63 not in selected or 0x62 not in selected:
                    continue
                if self.model == 'sq' and cc == 0x26 and channel == self.base and 6 in selected:
                    parameter = selected[0x63] * 128 + selected[0x62]
                    raw = selected[6] * 128 + value
                    for count, mute, level in SQ_MAP.values():
                        if mute <= parameter < mute + count:
                            self.values.setdefault((channel, parameter), {})['muted'] = raw != 0
                        if level <= parameter < level + count:
                            db = interpolate(raw, [(v, d) for d, v in SQ_TAPER]) if raw else -100
                            self.values.setdefault((channel, parameter), {})['db'] = db
                elif self.model != 'sq' and cc == 6 and selected[0x62] == 0x17:
                    self.values.setdefault((channel, selected[0x63]), {})['db'] = value / 127 * 64 - 54 if value else -100

    async def exchange(self, outgoing):
        try:
            await self.connect()
            if self.model == "yamaha":
                # RCP desks can drop a burst of hundreds of catalog reads.
                for line in outgoing.splitlines(keepends=True):
                    self.writer.write(line)
                    await self.writer.drain()
                    await asyncio.sleep(.004)
            else:
                self.writer.write(outgoing)
                await self.writer.drain()
            deadline = asyncio.get_running_loop().time() + .18
            while asyncio.get_running_loop().time() < deadline:
                try:
                    data = await asyncio.wait_for(self.reader.read(16384), .04)
                except asyncio.TimeoutError:
                    break
                if not data:
                    raise ConnectionError('Console disconnected')
                if self.model == 'yamaha':
                    self.buffer.extend(data)
                    while b'\n' in self.buffer:
                        line, _, rest = self.buffer.partition(b'\n')
                        self.buffer = bytearray(rest)
                        self.feed_rcp(line.decode('utf-8', 'replace'))
                else:
                    self.feed(data)
        except Exception:
            self.close()
            raise

    def feed_rcp(self, line):
        try:
            parts = shlex.split(line)
            if len(parts) < 6 or parts[0] not in ('OK', 'NOTIFY') or parts[1] not in ('get', 'set'):
                return
            path, x, y, value = parts[2:6]
            row = self.values.setdefault((path.rsplit('/', 2)[0] if '/Label/' in path or '/Fader/' in path else path, int(x)), {})
            if path.endswith('/Label/Name'):
                row['console_label'] = value
            elif path.endswith('/Fader/On'):
                row['muted'] = value == '0'
            elif path.endswith('/Fader/Level'):
                row['db'] = -100 if int(value) == -32768 else int(value) / 100
        except (ValueError, IndexError):
            return

    def rcp_address(self, strip):
        kind = strip.get('kind', 'channel')
        number = int(strip.get('number') or 1)
        root = {'channel': 'InCh', 'bus': 'Mix', 'aux': 'Mix', 'dca': 'DCA', 'main': 'St'}.get(kind)
        if not root or number < 1 or number > {'channel':72,'bus':24,'aux':24,'dca':16,'main':1}[kind]:
            raise ValueError('Unsupported Yamaha strip')
        return f'MIXER:Current/{root}', number - 1

    async def status(self, strips):
        if not self.configured:
            return {'connected': False, 'strips': []}
        rows, outgoing = [], bytearray()
        for strip in strips:
            try:
                if self.model == 'yamaha':
                    root, index = self.rcp_address(strip)
                    for prop in ('Label/Name', 'Fader/On', 'Fader/Level'):
                        outgoing.extend(f'get {root}/{prop} {index} 0\n'.encode())
                    key, level_key = (root, index), (root, index)
                else:
                    channel, mute, level = address(self.model, self.base, strip)
                    key, level_key = (channel, mute), (channel, level if self.model == 'sq' else mute)
                    if self.model == 'sq':
                        for parameter in (mute, level):
                            outgoing.extend(bytes([0xb0|channel, 0x63, parameter >> 7, 0xb0|channel, 0x62, parameter & 127, 0xb0|channel, 0x60, 127]))
                    else:
                        outgoing.extend(HEADER + bytes([channel, 1, mute, 0xf7]))
                        if self.model == 'dlive':
                            outgoing.extend(HEADER + bytes([channel, 5, 9, mute, 0xf7]))
                            outgoing.extend(HEADER + bytes([channel, 5, 11, 0x17, mute, 0xf7]))
                rows.append((strip, key, level_key, None))
            except ValueError as exc:
                rows.append((strip, None, None, str(exc)))
        async with self.lock:
            await self.exchange(bytes(outgoing))
            result = []
            for strip, key, level_key, error in rows:
                reading = {**self.values.get(key, {}), **{k:v for k,v in self.values.get(level_key, {}).items() if k == 'db'}}
                db = reading.get('db')
                result.append({**strip, **reading, 'db':db, 'muted':reading.get('muted'),
                               'position':db_to_x32_fader(db) if db is not None else 0,
                               'online':bool(reading), 'read_only':self.model == 'yamaha', 'error':error})
            return {'connected':True, 'model':self.model, 'host':self.host, 'read_only':self.model == 'yamaha', 'strips':result}

    async def control(self, strip, level_db=None, muted=None):
        if self.model == 'yamaha':
            raise ValueError('Yamaha CL/QL/TF monitoring is read only')
        if not self.configured:
            raise ValueError('Console is not configured')
        channel, mute, level = address(self.model, self.base, strip)
        outgoing = b''
        if muted is not None:
            outgoing += (nrpn(channel, mute >> 7, mute & 127, 0, int(muted)) if self.model == 'sq'
                         else bytes([0x90|channel, mute, 127 if muted else 63, 0x90|channel, mute, 0]))
        if level_db is not None:
            if self.model == 'sq':
                value = 0 if level_db <= -89 else round(interpolate(level_db, SQ_TAPER))
                outgoing += nrpn(channel, level >> 7, level & 127, value >> 7, value & 127)
            else:
                value = 0 if level_db <= -90 else max(1, min(127, round((level_db + 54) / 64 * 127)))
                outgoing += nrpn(channel, mute, 0x17, value)
        async with self.lock:
            await self.exchange(outgoing)

    async def catalog(self):
        channels = 48 if self.model == 'sq' else 128 if self.model == 'dlive' else 64
        if self.model == 'yamaha':
            channels = 72
        strips = [{'id':f'ch-{n}', 'kind':'channel', 'number':n} for n in range(1, channels + 1)]
        result = await self.status(strips)
        return {**result, 'channels':[{'number':s['number'], 'name':s.get('console_label') or f"CH {s['number']}"} for s in result['strips']], 'buses':[]}
