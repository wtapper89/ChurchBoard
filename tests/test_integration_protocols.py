from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.modules.behringer import BehringerClient
from app.modules.consoles import ConsoleClient, HEADER, address, nrpn
from app.modules.sennheiser_g4 import parse_g4_response
from app.modules.sennheiser import SennheiserClient


class ProtocolTests(unittest.TestCase):
    def test_g4_meters_are_not_ew_dx_json(self):
        receiver = {'host':'192.0.2.1', 'channel_configs':[{'id':'red','name':'Red'}]}
        row = parse_g4_response('Name Vocal 1\rFrequency 1 1 548100\rRF 67 1 1\rAF 37 42 3\rBat 70\rMsg TX_Mute\rConfig 3\r', receiver)
        self.assertEqual((row['id'],row['name'],row['battery_percent'],row['rf'],row['audio']), ('red','Red',70,67,37))
        self.assertTrue(row['muted'])
        self.assertTrue(row['online'])
        row = parse_g4_response('RF 0 1 0\rAF 0 0 5\rBat ?\rMsg RF_Mute\rConfig 4\r', receiver)
        self.assertFalse(row['online'])
        self.assertFalse(row['battery_available'])

    def test_g4_config_keeps_model_and_default_port(self):
        client = SennheiserClient({'mics':[{'host':'192.0.2.1','model':'ew-g4','channel':1}]})
        receiver = client._configured_receivers()[0]
        self.assertEqual(receiver['model'], 'ew-g4')
        self.assertEqual(receiver['port'], 53212)

    def test_console_factory_and_dlive_map(self):
        self.assertIsInstance(BehringerClient({'model':'sq'}), ConsoleClient)
        self.assertEqual(address('avantis',0,{'kind':'channel','number':64}), (0,63,23))
        self.assertEqual(address('dlive',11,{'kind':'dca','number':24}), (15,77,23))
        with self.assertRaises(ValueError):
            address('sq',0,{'kind':'send','number':1})

    def test_fragmented_midi_running_status_and_realtime(self):
        client = ConsoleClient({'model':'avantis'})
        packet = HEADER + bytes([0,2,0]) + b'Pastor' + b'\xf7'
        packet += bytes([0x90,0,0x7f,0,0,0xf8]) + nrpn(0,0,0x17,64)
        for byte in packet:
            client.feed(bytes([byte]))
        self.assertEqual(client.values[(0,0)]['console_label'], 'Pastor')
        self.assertTrue(client.values[(0,0)]['muted'])
        self.assertAlmostEqual(client.values[(0,0)]['db'],64/127*64-54)

    def test_sq_fader_and_mute_on_matching_channel(self):
        client = ConsoleClient({'model':'sq','midi_channel':3})
        client.feed(nrpn(2,0,0,0,1))
        client.feed(nrpn(2,0x40,0,0x76,0x5c))
        self.assertTrue(client.values[(2,0)]['muted'])
        self.assertEqual(client.values[(2,0x2000)]['db'],0)
        client.feed(nrpn(3,0,0,0,0))
        self.assertNotIn((3,0),client.values)

    def test_yamaha_names_levels_and_on_inversion(self):
        client = ConsoleClient({'model':'yamaha'})
        for line in ('OK get MIXER:Current/InCh/Label/Name 0 0 "Pastor Mic"',
                     'NOTIFY set MIXER:Current/InCh/Fader/On 0 0 0',
                     'OK get MIXER:Current/InCh/Fader/Level 0 0 -1000'):
            client.feed_rcp(line)
        self.assertEqual(client.values[('MIXER:Current/InCh',0)], {'console_label':'Pastor Mic','muted':True,'db':-10})


class AsyncProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_yamaha_rejects_writes_before_connecting(self):
        client = ConsoleClient({'model':'yamaha','enabled':True,'host':'192.0.2.1'})
        client.connect = AsyncMock()
        with self.assertRaisesRegex(ValueError,'read only'):
            await client.control({'kind':'channel','number':1}, 0, False)
        client.connect.assert_not_called()

    async def test_live_crosses_headers_once_in_both_directions(self):
        from app.modules.runtime import RuntimeService
        from app.store import ConfigStore
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory)/'state.json'))
            items = [{'id':'h1','title':'Pre-Service','item_type':'header','length':0},
                     {'id':'a','title':'Announcements','item_type':'item','length':60},
                     {'id':'h2','title':'Service','item_type':'header','length':0},
                     {'id':'b','title':'Song','item_type':'song','length':60},
                     {'id':'c','title':'Message','item_type':'item','length':60}]
            state = {'service':{'id':'p','items':items},'timing':{},
                     'propresenter':{'connected':True,'title':'Song','presentation_uuid':'song'}}
            class Live:
                configured = True
                def __init__(self): self.current, self.actions = 'a', []
                async def live_status(self, service, create=False):
                    return {'id':'live','has_control':True,'current_item_id':self.current}
                async def live_action(self,service,live,action):
                    self.actions.append(action)
                    ids = ['a','b','c']
                    direction = 1 if action == 'go_to_next_item' else -1
                    self.current = ids[max(0,min(2,ids.index(self.current)+direction))]
                    return await self.live_status(service)
            client = Live()
            settings = {'stable_seconds':0,'songs_only':False,'allow_previous':True}
            for clock in (10,10.1,11,12):
                await runtime._sync_propresenter_live(state,client,settings,clock)
            self.assertEqual(client.current,'b')
            self.assertEqual(client.actions,['go_to_next_item'])
            state['propresenter'].update(title='Announcements',presentation_uuid='announcements')
            for clock in (13,13.1,14,15):
                await runtime._sync_propresenter_live(state,client,settings,clock)
            self.assertEqual(client.current,'a')
            self.assertEqual(client.actions,['go_to_next_item','go_to_previous_item'])

class NetworkProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_sq_tcp_poll_and_control_share_connection(self):
        received, writers = [], []
        async def desk(reader, writer):
            writers.append(writer)
            try:
                while data := await reader.read(4096):
                    received.append(data)
                    writer.write(nrpn(0, 0, 0, 0, 0) + nrpn(0, 0x40, 0, 0x76, 0x5c))
                    await writer.drain()
            finally:
                writer.close()
        server = await asyncio.start_server(desk, '127.0.0.1', 0)
        client = ConsoleClient({'model':'sq','enabled':True,'host':'127.0.0.1','port':server.sockets[0].getsockname()[1]})
        strip = {'id':'ch1','kind':'channel','number':1}
        try:
            status = await client.status([strip])
            self.assertEqual(status['strips'][0]['db'], 0)
            await client.control(strip, muted=True)
            self.assertEqual(len(writers), 1)
            self.assertIn(nrpn(0,0,0,0,1), b''.join(received))
        finally:
            client.close()
            server.close()
            await server.wait_closed()
            for writer in writers:
                writer.close()
                await writer.wait_closed()

    async def test_g4_udp_one_shot_collects_multiple_packets(self):
        from app.modules.sennheiser_g4 import query_g4
        class Receiver(asyncio.DatagramProtocol):
            def connection_made(self, transport): self.transport = transport
            def datagram_received(self, data, peer):
                replies = {b'Name\r':b'Name Vocal\r', b'Frequency\r':b'Frequency 1 1 548100\r',
                           b'FirmwareRevision\r':b'FirmwareRevision 1.7.0\r',
                           b'Push 0 100 1\r':b'RF 50 1 1\rAF 40 65 0\rBat 70\rMsg OK\rConfig 1\r'}
                self.transport.sendto(replies[data], peer)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(Receiver, local_addr=('127.0.0.1',0))
        try:
            row = await query_g4({'host':'127.0.0.1','port':transport.get_extra_info('sockname')[1]})
            self.assertTrue(row['online'])
            self.assertEqual(row['battery_percent'],70)
            self.assertEqual(row['firmware'],'1.7.0')
        finally:
            transport.close()

    async def test_propresenter_optional_timeout_keeps_slides_online(self):
        import httpx
        from app.modules.propresenter import ProPresenterClient
        async def respond(request):
            path = request.url.path
            if path == '/v1/macros':
                raise httpx.ReadTimeout('optional endpoint timed out')
            payload = {'current':{'text':'Live lyric'}} if path == '/v1/status/slide' else {}
            return httpx.Response(200,json=payload)
        client = ProPresenterClient({'enabled':True,'host':'127.0.0.1'})
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            status = await client.status()
            self.assertTrue(status['connected'])
            self.assertEqual(status['current']['text'],'Live lyric')
        finally:
            await client.close()

    async def test_focused_playlist_cannot_override_live_plan_index(self):
        import httpx
        from app.modules.propresenter import ProPresenterClient
        async def respond(request):
            path = request.url.path
            payload = {}
            if path == '/v1/status/slide':
                payload = {'current':{'text':'Message'}}
            elif path == '/v1/presentation/active':
                payload = {'presentation':{'id':{'uuid':'PRES','name':'Message'}}}
            elif path in ('/v1/playlist/active','/v1/playlist/focused'):
                active = path.endswith('/active')
                payload = {'presentation':{'playlist':{'uuid':'LIVE' if active else 'BROWSING'},
                           'item':{'name':'Message','index':5 if active else 8},
                           'playlist_item':{'is_pco':True}}}
            elif path == '/v1/playlist/BROWSING':
                payload = {'items':[{'type':'presentation','name':'Message','index':8,'is_pco':True,
                           'presentation_info':{'presentation_uuid':'PRES'}}]}
            return httpx.Response(200,json=payload)
        client = ProPresenterClient({'enabled':True,'host':'127.0.0.1'})
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            status = await client.status()
            self.assertEqual(status['service_item_index'],5)
            self.assertFalse(status.get('service_item_index_is_absolute',False))
        finally:
            await client.close()

    async def test_library_playback_shows_active_slides_without_playlist(self):
        import httpx
        from app.modules.propresenter import ProPresenterClient
        presentation = {'id':{'uuid':'LIBRARY-PRES','name':'Library Song'},
                        'groups':[{'name':'Verse','slides':[{'text':'First lyric'},{'text':'Second lyric'}]}]}
        async def respond(request):
            payload = {
                '/v1/playlist/active':{'presentation':{'playlist':None,'item':None,'playlist_item':None},'announcements':{'playlist':None,'item':None,'playlist_item':None}},
                '/v1/playlist/focused':{'playlist':None,'item':None,'playlist_item':{'id':{'uuid':'ROW','name':'Library Song','index':0},'type':'presentation','presentation_info':{'presentation_uuid':'LIBRARY-PRES'}}},
                '/v1/presentation/active':{'presentation':presentation},
                '/v1/presentation/LIBRARY-PRES':presentation,
                '/v1/status/slide':{'current':{'text':'First lyric'}},
                '/v1/presentation/slide_index':0,
            }.get(request.url.path,{})
            return httpx.Response(200,json=payload)
        client = ProPresenterClient({'enabled':True,'host':'127.0.0.1'})
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            status = await client.status()
            cards = status['playlist_presentations']
            self.assertEqual(len(cards),1)
            self.assertEqual(cards[0]['title'],'Library Song')
            self.assertEqual(len(cards[0]['slides']),2)
            self.assertIn('/thumbnail/LIBRARY-PRES/',cards[0]['slides'][0]['image_url'])
            self.assertTrue(cards[0]['slides'][0]['active'])
        finally:
            await client.close()

    def test_null_playlist_destination_is_not_a_presentation(self):
        from app.modules.propresenter import ProPresenterClient
        self.assertEqual(ProPresenterClient._playlist_presentations({'presentation':None,'announcements':None},{}),[])


class PlanningCenterTitleMatchTests(unittest.TestCase):
    def test_live_title_beats_linked_index_when_punctuation_differs(self):
        from app.modules.runtime import RuntimeService

        items = [{"id": "1", "title": "Welcome"}, {"id": "2", "title": "Here Again"}]
        presentation = {"title": "Here Again!", "service_item_is_pco": True,
                        "service_item_index": 0, "service_item_index_is_absolute": True}
        self.assertEqual(RuntimeService._match_propresenter_item(presentation, items, "1", {})["id"], "2")

    def test_unique_gap_between_matching_playlist_neighbors(self):
        from app.modules.runtime import RuntimeService

        items = [{"id": "1", "title": "Welcome"}, {"id": "header", "item_type": "header"},
                 {"id": "2", "title": "Message"}, {"id": "3", "title": "Closing Song"}]
        presentation = {"title": "John 1", "playlist_presentations": [
            {"title": "Welcome!"}, {"title": "John 1", "active": True}, {"title": "Closing Song"},
        ]}
        self.assertEqual(RuntimeService._match_propresenter_item(presentation, items, "1", {})["id"], "2")
        presentation.pop("playlist_presentations")
        self.assertEqual(RuntimeService._match_propresenter_item(presentation, items, "1", {})["id"], "1")
