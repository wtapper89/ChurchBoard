from __future__ import annotations

import math
import unittest

from app.modules.behringer import db_to_x32_fader, osc_message, parse_osc, strip_paths, x32_fader_to_db


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

    def test_osc_messages_round_trip(self):
        self.assertEqual(parse_osc(osc_message("/ch/01/mix/on", 1)), [("/ch/01/mix/on", 1)])
        address, value = parse_osc(osc_message("/ch/01/mix/fader", .75))[0]
        self.assertEqual(address, "/ch/01/mix/fader")
        self.assertAlmostEqual(value, .75)


if __name__ == "__main__":
    unittest.main()
