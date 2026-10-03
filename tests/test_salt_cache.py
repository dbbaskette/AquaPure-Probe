"""Salt cache tests without requiring a running Home Assistant instance."""

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "salt_cache",
    Path(__file__).parents[1] / "custom_components/aquapure_probe/salt_cache.py",
)
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)
T1 = "2026-10-03T04:58:15+00:00"
T2 = "2026-10-03T05:28:31+00:00"
READING = {"serial": "test-pool", "system_name": "Test", "salt_ppm": 3200}


class SaltCacheTests(unittest.TestCase):
    def test_numeric_validation(self):
        for value in (None, "unknown", "unavailable", "nan", "inf", -1, True, {}):
            with self.subTest(value=value):
                self.assertIsNone(cache.numeric_salt(value))
        self.assertEqual(cache.numeric_salt("3200"), 3200)
        self.assertEqual(cache.numeric_salt(0), 0)

    def test_fresh_then_missing_retains_value_and_time(self):
        fresh, saved = cache.retain_salt(READING, None, T1)
        self.assertFalse(fresh["salt_stale"])
        for value in (None, "unknown", "unavailable"):
            stale, unchanged = cache.retain_salt({**READING, "salt_ppm": value}, saved, T2)
            self.assertEqual(stale["salt_ppm"], 3200)
            self.assertTrue(stale["salt_stale"])
            self.assertEqual(stale["salt_last_success"], T1)
            self.assertEqual(unchanged, saved)

    def test_same_fresh_value_advances_confirmation_time(self):
        _, saved = cache.retain_salt(READING, None, T1)
        fresh, saved = cache.retain_salt(READING, saved, T2)
        self.assertFalse(fresh["salt_stale"])
        self.assertEqual(saved["salt_last_success"], T2)

    def test_restore_and_full_poll_failure(self):
        _, saved = cache.retain_salt(READING, None, T1)
        restored = cache.valid_cache(saved)
        stale, _ = cache.retain_salt({"serial": "test-pool", "probe_available": False}, restored, T2)
        self.assertEqual(stale["salt_ppm"], 3200)
        self.assertTrue(stale["salt_stale"])
        self.assertFalse(stale["probe_available"])
        self.assertNotIn("pool_output", stale)

    def test_never_transfer_between_pools(self):
        _, saved = cache.retain_salt(READING, None, T1)
        result, saved = cache.retain_salt({"serial": "another-pool"}, saved, T2)
        self.assertIsNone(saved)
        self.assertIsNone(result["salt_ppm"])

    def test_no_history_does_not_invent_value(self):
        result, saved = cache.retain_salt({"serial": "test-pool"}, None, T1)
        self.assertIsNone(saved)
        self.assertIsNone(result["salt_ppm"])
        self.assertIsNone(result["salt_last_success"])

    def test_corrupt_storage_is_ignored(self):
        for value in (None, [], {}, {**READING, "salt_last_success": "bad"},
                      {**READING, "salt_last_success": "2026-10-03T04:58:15"}):
            self.assertIsNone(cache.valid_cache(value))


if __name__ == "__main__":
    unittest.main()
