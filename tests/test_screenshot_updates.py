import unittest

from screenshot_updates import stat_count, update_decision


class ScreenshotUpdateTests(unittest.TestCase):
    def test_count_excludes_metadata_and_includes_zero(self):
        self.assertEqual(stat_count({"ac": 0, "hp": "", "mana": 10, "ocr_text": "text",
                                     "socket_1_type": 7, "equip_slots": "Ear", "skill_mod": "Specialize"}), 3)

    def test_more_stats_replaces_complete_record(self):
        decision, stats, types = update_decision({"ac": 12, "hp": ""}, [7], {"mana": 20, "hp": 1}, [8])
        self.assertEqual((decision, stats, types), ("replace", {"mana": 20, "hp": 1}, [8]))

    def test_equal_stats_requires_confirmation(self):
        decision, stats, types = update_decision({"ac": 12}, [7], {"ac": 12}, [7])
        self.assertEqual((decision, stats, types), ("confirm_replace", {"ac": 12}, [7]))

    def test_fewer_preserves_omitted_and_prompts_only_on_conflict(self):
        old = {"ac": 12, "hp": 30, "mana": 50}
        decision, merged, types = update_decision(old, [7], {"ac": 13, "ocr_text": "new"}, [])
        self.assertEqual(decision, "confirm_merge")
        self.assertEqual(merged, {"ac": 13, "hp": 30, "mana": 50, "ocr_text": "new"})
        self.assertEqual(types, [7])
        decision, merged, types = update_decision(old, [7], {"ac": 12}, [])
        self.assertEqual((decision, merged, types), ("merge", old, [7]))


if __name__ == "__main__":
    unittest.main()
