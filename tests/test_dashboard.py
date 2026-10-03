"""Regression checks for missing readings and stale salt disclosure."""

import json
from pathlib import Path
import unittest


class DashboardTests(unittest.TestCase):
    def test_gauges_have_complementary_fallbacks(self):
        config = json.loads(
            (Path(__file__).parents[1] / "examples/pool-dashboard.json").read_text()
        )
        sections = config["views"][0]["sections"]
        cards = [card for section in sections for card in section["cards"]]
        gauges = [(i, c) for i, c in enumerate(cards) if c["type"] == "gauge"]
        self.assertEqual(len(gauges), 8)
        for i, gauge in gauges:
            with self.subTest(entity=gauge["entity"]):
                condition = gauge["visibility"][0]
                self.assertEqual(condition["condition"], "numeric_state")
                self.assertEqual(condition["entity"], gauge["entity"])
                self.assertLess(condition["above"], min(0, gauge["min"]))
                self.assertGreater(condition["below"], gauge["max"])
                fallback = cards[i + 1]
                self.assertIn("Reading unavailable", fallback["content"])
                self.assertEqual(fallback["grid_options"], gauge["grid_options"])
                self.assertEqual(fallback["visibility"], [
                    {"condition": "not", "conditions": [condition]}
                ])
        salt = next(g for _, g in gauges if "salt_level" in g["entity"])
        self.assertEqual(salt["name"], "Salt · last reported")
        note = next(c["content"] for c in cards if c["type"] == "markdown" and "last_successful_reading" in c["content"])
        self.assertIn("'stale'", note)
        self.assertIn("'last_successful_reading'", note)
        self.assertIn("last known reading", note)

    def test_daily_graphs_pair_with_gauges_and_camera_is_live(self):
        config = json.loads(
            (Path(__file__).parents[1] / "examples/pool-dashboard.json").read_text()
        )
        sections = config["views"][0]["sections"]
        for section in sections[:4]:
            gauges = [c for c in section["cards"] if c["type"] == "gauge"]
            graphs = [c for c in section["cards"] if c["type"] == "history-graph"]
            self.assertEqual(len(gauges), 2)
            self.assertEqual(len(graphs), 2)
            self.assertEqual([c["entity"] for c in gauges], [c["entities"][0]["entity"] for c in graphs])
            for graph in graphs:
                self.assertEqual(graph["hours_to_show"], 24)
                self.assertEqual(graph["grid_options"]["columns"], 6)
        camera = next(c for c in sections[4]["cards"] if c["type"] == "picture-entity")
        self.assertEqual(camera["entity"], "camera.backyard_live_view")
        self.assertEqual(camera["camera_view"], "live")
        self.assertEqual(camera["tap_action"]["action"], "more-info")


if __name__ == "__main__":
    unittest.main()
