import unittest

from base_stats import calculate_base


class BaseStatsTests(unittest.TestCase):
    def test_subtracts_only_complete_numeric_additive_values(self):
        observed = {"hp": 1000, "mana": 900, "heroic_int": 30, "size": "SMALL", "ac": 100}
        augments = [{"hp": 200, "mana": 0, "heroic_int": "5", "ac": 10},
                    {"hp": 50, "mana": "", "heroic_int": 3, "ac": 5}]
        self.assertEqual(calculate_base(observed, augments),
                         {"ac": 85, "hp": 750, "mana": None, "heroic_int": 22})

    def test_unknown_augment_or_absent_stat_never_becomes_zero(self):
        self.assertEqual(calculate_base({"hp": 500}, [None]), {"hp": None})
        self.assertEqual(calculate_base({"hp": 500}, [{"mana": 0}]), {"hp": None})
        self.assertEqual(calculate_base({"hp": 500}, []), {"hp": 500})


if __name__ == "__main__":
    unittest.main()
