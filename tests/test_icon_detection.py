import io
import unittest

from PIL import Image, ImageDraw

from icon_detection import automatic_icon


def item_window(scale=1, margin=0):
    image = Image.new("RGB", (240 * scale + margin, 180 * scale + margin), (20, 25, 45))
    draw = ImageDraw.Draw(image)
    draw.line((margin + 5, margin, margin + 120 * scale, margin), fill=(190, 185, 170))
    tab_y = margin + 12 * scale
    tab_x = margin + 10 * scale
    draw.line((tab_x, tab_y, tab_x + 100 * scale, tab_y), fill=(160, 180, 220))
    x, y = tab_x, tab_y + 20 * scale
    draw.rectangle((x, y, x + 28 * scale - 1, y + 28 * scale - 1), fill=(240, 20, 20))
    return image


class IconDetectionTests(unittest.TestCase):
    def test_detects_icon_at_multiple_scales_and_window_offsets(self):
        for scale, margin in ((1, 0), (1, 6), (2, 0), (2, 7)):
            with self.subTest(scale=scale, margin=margin):
                result = automatic_icon(item_window(scale, margin))
                self.assertIsNotNone(result)
                icon = Image.open(io.BytesIO(result))
                self.assertEqual(icon.size, (28 * scale, 28 * scale))
                self.assertEqual(icon.getpixel((0, 0)), (240, 20, 20))
                self.assertEqual(icon.getpixel((icon.width - 1, icon.height - 1)), (240, 20, 20))

    def test_unrecognized_or_incomplete_images_are_not_cropped(self):
        self.assertIsNone(automatic_icon(Image.new("RGB", (240, 180), (20, 25, 45))))
        self.assertIsNone(automatic_icon(Image.new("RGB", (10, 10))))
        self.assertIsNone(automatic_icon(item_window().crop((0, 0, 240, 50))))


if __name__ == "__main__":
    unittest.main()
