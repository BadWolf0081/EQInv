import io
import unittest
from unittest.mock import patch

from PIL import Image
from screenshot_ocr import extract_candidates, recognize_screenshot, validate_review


class ScreenshotTests(unittest.TestCase):
    def test_extract_stats_and_types_without_inventing_values(self):
        stats, types = extract_candidates(
            "Augmentation type: 7 8\nAC: 113\nSTR: +22+16 HP: +1,600 MANA: +1600 ENDUR: +1600"
        )
        self.assertEqual(types, [7, 8])
        self.assertEqual(stats, {"ac": 113, "str": "+22+16", "hp": 1600, "mana": 1600, "endurance": 1600})
        self.assertEqual(extract_candidates("Slot 1, Type 8\nAC: unclear"), ({}, []))

    def test_review_rejects_bad_values(self):
        for stats, types, raw in [('[]', '7', 'x'), ('{"ac":"42"}', '7', 'x'),
                                  ('{"ac":42}', '256', 'x'), ('{}', '', 'x'),
                                  ('{"ac":42}', '7', '')]:
            with self.subTest(stats=stats, types=types, raw=raw), self.assertRaises(ValueError):
                validate_review(stats, types, raw)
        stats, types = validate_review('{"ac":0,"str":"+3+4"}', '8|7|8', 'confirmed text')
        self.assertEqual(stats["ac"], 0)
        self.assertEqual(stats["ocr_text"], "confirmed text")
        self.assertEqual(types, [7, 8])

    def test_invalid_images_and_missing_ocr_are_explicit(self):
        with self.assertRaises(ValueError):
            recognize_screenshot(b"not an image")
        image = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, format="PNG")
        with patch("screenshot_ocr.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                recognize_screenshot(image.getvalue())
