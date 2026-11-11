import unittest

from item_matching import suggest_item_names


class ItemMatchingTests(unittest.TestCase):
    def test_possible_ocr_match_and_close_competitors(self):
        items = [
            {"id": 1, "index": 0, "name": "Tribute to the Fallen"},
            {"id": 2, "index": 1, "name": "Tribute to the Fallen King"},
            {"id": 3, "index": 2, "name": "Green Pulse"},
        ]
        result = suggest_item_names("Tribute to the Fali en\nDescription\n", items)
        self.assertEqual(result[0]["id"], 1)
        self.assertNotIn(3, [item["id"] for item in result])

    def test_no_guess_from_description_or_very_short_names(self):
        items = [{"id": 1, "index": 0, "name": "Or"},
                 {"id": 2, "index": 1, "name": "Green Pulse"}]
        self.assertEqual(suggest_item_names("Description\nUnknown window", items), [])

    def test_tied_names_remain_distinct_suggestions(self):
        items = [{"id": 1, "index": 0, "name": "Tribute to the Fallen"},
                 {"id": 2, "index": 1, "name": "Tribute to the Fallen"}]
        self.assertEqual([x["id"] for x in suggest_item_names("Tribute to the Fallen", items)], [1, 2])
