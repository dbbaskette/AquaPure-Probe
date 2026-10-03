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
        self.assertTrue({"switch.pool_pump", "switch.spa_pump", "switch.pool_heater", "climate.pool"}.issubset(entities))
        for card in self.sections[1]["cards"]:
            if card.get("entity") in {"switch.pool_pump", "switch.spa_pump", "switch.pool_heater"}:
                self.assertNotIn("features", card)
                self.assertEqual(card["tap_action"], {"action": "toggle"})

    def test_pool_and_spa_lights_have_matching_top_switches(self):
        lights = next(c for c in self.sections[1]["cards"] if c["type"] == "entities")
        self.assertFalse(lights["show_header_toggle"])
        self.assertEqual([e["entity"] for e in lights["entities"]], ["light.pool_light", "switch.spa_light"])
        self.assertEqual([e["name"] for e in lights["entities"]], ["Pool lights", "Spa lights"])
        self.assertFalse(any(c.get("entity") == "switch.spa_light" for c in self.sections[3]["cards"]))


if __name__ == "__main__":
    unittest.main()
