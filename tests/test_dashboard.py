"""Regression checks for the compact dashboard configuration."""
import json
from pathlib import Path
import unittest


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).parents[1] / "examples/pool-dashboard.json").read_text())
        self.sections = self.config["views"][0]["sections"]

    def test_readings_are_one_headerless_compact_grid(self):
        cards = self.sections[2]["cards"]
        self.assertFalse(any(c["type"] == "heading" for c in cards))
        self.assertEqual(cards[0]["type"], "custom:pool-readings-card")
        readings = cards[0]["readings"]
        self.assertEqual(len(readings), 8)
        self.assertEqual(len({r["entity"] for r in readings}), 8)
        for r in readings:
            self.assertLess(r["min"], r["max"])
            if r.get("segments"):
                stops = [s["from"] for s in r["segments"]]
                self.assertEqual(stops, sorted(stops))
                self.assertEqual(stops[0], r["min"])
                self.assertLess(stops[-1], r["max"])

    def test_salt_staleness_stays_with_readings(self):
        note = self.sections[2]["cards"][1]["content"]
        self.assertIn("'stale'", note)
        self.assertIn("'last_successful_reading'", note)
        self.assertIn("last known reading", note)

    def test_camera_is_beside_quick_controls(self):
        self.assertEqual(self.config["views"][0]["max_columns"], 2)
        self.assertEqual(self.sections[0].get("column_span", 1), 1)
        self.assertEqual(self.sections[1].get("column_span", 1), 1)
        camera = next(c for c in self.sections[0]["cards"] if c["type"] == "picture-entity")
        self.assertEqual(camera["entity"], "camera.backyard_live_view")
        self.assertEqual(camera["camera_view"], "live")
        self.assertEqual(camera["tap_action"]["action"], "more-info")
        self.assertEqual(camera["aspect_ratio"], "21:9")
        entities = {c.get("entity") for c in self.sections[1]["cards"]}
        self.assertTrue({"climate.pool", "climate.spa"}.issubset(entities))

    def test_pool_and_spa_lights_have_matching_top_switches(self):
        switches = [c for c in self.sections[1]["cards"] if c["type"] == "entities"]
        lights = switches[2:4]
        self.assertEqual(len(lights), 2)
        self.assertTrue(all(not card["show_header_toggle"] for card in lights))
        self.assertTrue(all(card["grid_options"]["columns"] == 6 for card in lights))
        self.assertEqual([card["entities"][0]["entity"] for card in lights], ["light.pool_light", "switch.spa_light"])
        self.assertEqual([card["entities"][0]["name"] for card in lights], ["Pool", "Spa"])
        self.assertFalse(any(c.get("entity") == "switch.spa_light" for c in self.sections[3]["cards"]))

    def test_quick_controls_use_consistent_native_switches(self):
        switches = [c for c in self.sections[1]["cards"] if c["type"] == "entities"]
        self.assertEqual(len(switches), 6)
        self.assertTrue(all(not card["show_header_toggle"] for card in switches))
        self.assertTrue(all(card["grid_options"]["columns"] == 6 for card in switches))
        self.assertEqual(
            [card["entities"][0]["entity"] for card in switches],
            [
                "switch.pool_pump",
                "switch.spa_pump",
                "light.pool_light",
                "switch.spa_light",
                "switch.pool_heater",
                "switch.spa_heater",
            ],
        )
        self.assertEqual([card["entities"][0]["name"] for card in switches[:2]], ["Pool", "Spa"])

    def test_heater_switches_and_targets_are_half_width(self):
        cards = self.sections[1]["cards"]
        switch_cards = [c for c in cards if c["type"] == "entities"]
        pool_heater = next(c for c in switch_cards if c["entities"][0]["entity"] == "switch.pool_heater")
        spa_heater = next(c for c in switch_cards if c["entities"][0]["entity"] == "switch.spa_heater")
        pool_target = next(c for c in cards if c.get("entity") == "climate.pool")
        spa_target = next(c for c in cards if c.get("entity") == "climate.spa")
        self.assertEqual(pool_heater["grid_options"]["columns"], 6)
        self.assertEqual(spa_heater["grid_options"]["columns"], 6)
        self.assertFalse(pool_heater["show_header_toggle"])
        self.assertFalse(spa_heater["show_header_toggle"])
        self.assertEqual(pool_target["grid_options"]["columns"], 6)
        self.assertEqual(spa_target["grid_options"]["columns"], 6)
        self.assertEqual(pool_target["features"], [{"type": "target-temperature"}])
        self.assertEqual(spa_target["features"], [{"type": "target-temperature"}])
        self.assertFalse(any(c.get("entity") == "switch.spa_heater" for c in self.sections[3]["cards"]))

    def test_more_controls_exclude_unconfirmed_solar_heat(self):
        entities = {c.get("entity") for c in self.sections[3]["cards"]}
        self.assertIn("switch.low_speed", entities)
        self.assertNotIn("switch.solar_heater", entities)


if __name__ == "__main__":
    unittest.main()
