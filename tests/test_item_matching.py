import unittest

from item_matching import item_name_text, suggest_item_names


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

    def test_removal_instructions_do_not_supply_item_name_matches(self):
        items = [{"id": 1, "index": 0, "name": "Topaz of Evocation"},
                 {"id": 2, "index": 1, "name": "Perfected Augmentation Distiller"}]
        for text in (
            "Topaz of Evocation Description Topaz of Evocation "
            "You must use a solvent Class XII Augmentation Distiller or higher, "
            "or use a Perfected Augmentation Distiller, to remove this augment safely.",
            "Topaz of Evocati0n\nDescription\nThis augment can only safely be removed "
            "with the Perfected Augmentation Distiller.",
            "Topaz of Evocation Description You mustuse a solvent Class XXI "
            "Augmentation Distiller or higher, or use a Perfected Augmentation Distiller.",
        ):
            with self.subTest(text=text):
                self.assertNotIn("Perfected Augmentation Distiller", item_name_text(text))
                self.assertEqual([item["id"] for item in suggest_item_names(text, items)], [1])

    def test_distiller_can_still_be_matched_as_the_item(self):
        name = "Perfected Augmentation Distiller"
        text = f"{name}\nDescription\n{name}\nThis augment can only safely be removed with the {name}."
        items = [{"id": 2, "index": 0, "name": name}]
        self.assertIn(name, item_name_text(text))
        self.assertEqual(suggest_item_names(text, items), items)
