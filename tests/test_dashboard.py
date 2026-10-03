"""Regression checks for missing readings and stale salt disclosure."""

import json
from pathlib import Path
import unittest


class DashboardTests(unittest.TestCase):
    def test_gauges_have_complementary_fallbacks(self):
        config = json.loads(
            (Path(__file__).parents[1] / "examples/pool-dashboard.json").read_text()
        )
        cards = config["views"][0]["sections"][0]["cards"]
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
        self.assertEqual(gauges[0][1]["name"], "Salt · last reported")
        note = next(c["content"] for c in cards if c["type"] == "markdown" and "visibility" not in c)
        self.assertIn("'stale'", note)
        self.assertIn("'last_successful_reading'", note)
        self.assertIn("last known reading", note)


if __name__ == "__main__":
    unittest.main()
