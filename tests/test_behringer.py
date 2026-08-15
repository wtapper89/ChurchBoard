from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from app.modules.behringer import BehringerClient, _osc_scalar, _wing_osc_value, db_to_x32_fader, osc_message, parse_osc, strip_name_path, strip_paths, x32_fader_to_db


class BehringerModuleTests(unittest.TestCase):
    def test_x32_segmented_fader_curve_round_trips(self):
        for db in (-60, -30, -10, 0, 10):
            self.assertAlmostEqual(x32_fader_to_db(db_to_x32_fader(db)), db, places=4)
        self.assertTrue(math.isinf(x32_fader_to_db(0)))

    def test_x32_paths_cover_channel_send_dca_and_mains(self):
        self.assertEqual(strip_paths("x32", {"kind": "channel", "number": 2}), ("/ch/02/mix/fader", "/ch/02/mix/on", True))
        self.assertEqual(strip_paths("x32", {"kind": "send", "number": 3, "target_bus": 7}), ("/ch/03/mix/07/level", "/ch/03/mix/07/on", True))
        self.assertEqual(strip_paths("x32", {"kind": "dca", "number": 4}), ("/dca/4/fader", "/dca/4/on", True))
        self.assertEqual(strip_paths("x32", {"kind": "main", "number": 1}), ("/main/st/mix/fader", "/main/st/mix/on", True))

    def test_wing_paths_use_native_mute_semantics(self):
        self.assertEqual(strip_paths("wing", {"kind": "channel", "number": 12}), ("/ch/12/fdr", "/ch/12/mute", False))
        self.assertEqual(strip_paths("wing", {"kind": "send", "number": 12, "target_bus": 2}), ("/ch/12/send/2/lvl", "/ch/12/send/2/on", True))

    def test_console_name_paths_follow_the_controlled_source(self):
        self.assertEqual(strip_name_path("x32", {"kind": "send", "number": 3, "target_bus": 7}), "/ch/03/config/name")
        self.assertEqual(strip_name_path("wing", {"kind": "channel", "number": 12}), "/ch/12/name")

    def test_osc_messages_round_trip(self):
        self.assertEqual(parse_osc(osc_message("/ch/01/mix/on", 1)), [("/ch/01/mix/on", 1)])
        address, value = parse_osc(osc_message("/ch/01/mix/fader", .75))[0]
        self.assertEqual(address, "/ch/01/mix/fader")
        self.assertAlmostEqual(value, .75)

    def test_status_accepts_one_element_argument_arrays_from_console(self):
        client = BehringerClient({"enabled": True, "model": "wing", "host": "192.0.2.10", "port": 2223})
        strips = [{"id": "main", "label": "Main", "kind": "main", "number": 1}]
        with patch.object(client, "_exchange", return_value={"/main/1/fdr": ["-5.0", 0.625, -5.0], "/main/1/mute": ["1", 1.0, 1]}):
            result = __import__("asyncio").run(client.status(strips))
        self.assertTrue(result["connected"])
        self.assertEqual(result["strips"][0]["db"], -5.0)
        self.assertTrue(result["strips"][0]["muted"])

    def test_status_includes_live_console_channel_name(self):
        client = BehringerClient({"enabled": True, "model": "x32", "host": "192.0.2.10", "port": 10023})
        strips = [{"id": "vocal", "label": "Configured", "kind": "channel", "number": 2}]
        replies = {"/ch/02/mix/fader": .75, "/ch/02/mix/on": 1, "/ch/02/config/name": "Lead Vox"}
        with patch.object(client, "_exchange", return_value=replies):
            result = __import__("asyncio").run(client.status(strips))
        self.assertEqual(result["strips"][0]["console_label"], "Lead Vox")

    def test_osc_scalar_unwraps_nested_argument_arrays(self):
        self.assertEqual(_osc_scalar([[0.5]]), 0.5)

    def test_wing_value_uses_actual_final_osc_argument(self):
        self.assertEqual(_wing_osc_value(["-12.0", 0.45, -12.0]), -12.0)
        self.assertEqual(_wing_osc_value(["0", 0.0, 0]), 0)

    def test_console_catalog_reads_wing_channel_and_bus_names(self):
        client = BehringerClient({"enabled": True, "model": "wing", "host": "192.0.2.10", "port": 2223})
        with patch.object(client, "_exchange", return_value={"/ch/1/name": "Lead Vox", "/bus/3/name": ["Vox IEM"]}):
            result = __import__("asyncio").run(client.catalog())
        self.assertTrue(result["connected"])
        self.assertEqual(result["channels"][0], {"number": 1, "name": "Lead Vox"})
        self.assertEqual(result["buses"][2], {"number": 3, "name": "Vox IEM"})


if __name__ == "__main__":
    unittest.main()
