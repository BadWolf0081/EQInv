import unittest

from augment_preview import augment_summary


class AugmentPreviewTests(unittest.TestCase):
    def test_hp_and_mana_take_priority_including_missing_or_zero(self):
        self.assertEqual(augment_summary({"stats": {"hp": 123, "heroic_int": 50}}),
                         {"hp": 123, "mana": None, "heroic": [], "heroic_value": None})
        self.assertEqual(augment_summary({"stats": {"hp": "0", "mana": 3}}),
                         {"hp": 0, "mana": 3, "heroic": [], "heroic_value": None})

    def test_maximum_positive_heroic_and_ties(self):
        result = augment_summary({"stats": {"hp": 0, "mana": 0, "heroic_str": "14",
                                            "heroic_int": 14, "heroic_fire": 3, "heroic_sta": -5}})
        self.assertEqual(result["heroic"], ["STR", "INT"])
        self.assertEqual(result["heroic_value"], 14)

    def test_unknown_invalid_and_no_increase_are_not_zero(self):
        self.assertEqual(augment_summary(None),
                         {"hp": None, "mana": None, "heroic": [], "heroic_value": None})
        result = augment_summary({"stats": {"hp": True, "mana": "not known", "heroic_wis": -1}})
        self.assertIsNone(result["hp"])
        self.assertIsNone(result["mana"])
        self.assertIsNone(result["heroic_value"])


if __name__ == "__main__":
    unittest.main()
