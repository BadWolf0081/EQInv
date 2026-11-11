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
    for row in range(y - 3 * scale, y + 33 * scale):
        for col in range(x, x + 30 * scale):
            image.putpixel((col, row), (40, 45, 65) if (col + row) % 2 else (48, 50, 70))
    draw.rectangle((x + 5 * scale, y + 4 * scale, x + 20 * scale - 1, y + 23 * scale - 1),
                   fill=(240, 20, 20))
    return image


class IconDetectionTests(unittest.TestCase):
    def test_detects_icon_at_multiple_scales_and_window_offsets(self):
        for scale, margin in ((1, 0), (1, 6), (2, 0), (2, 7)):
            with self.subTest(scale=scale, margin=margin):
                result = automatic_icon(item_window(scale, margin))
                self.assertIsNotNone(result)
                icon = Image.open(io.BytesIO(result))
                self.assertEqual(icon.mode, "RGBA")
                self.assertEqual(icon.width, icon.height)
                self.assertEqual(icon.getpixel((0, 0))[3], 0)
                self.assertEqual(icon.getpixel((icon.width // 2, icon.height // 2)), (240, 20, 20, 255))
                bbox = icon.getchannel("A").getbbox()
                self.assertLessEqual(abs(bbox[0] - (icon.width - bbox[2])), 1)
                self.assertLessEqual(abs(bbox[1] - (icon.height - bbox[3])), 1)

    def test_solid_background_does_not_create_icon(self):
        image = item_window()
        ImageDraw.Draw(image).rectangle((10, 29, 39, 64), fill=(40, 45, 65))
        self.assertIsNone(automatic_icon(image))

    def test_artwork_is_centered_when_position_varies(self):
        for left, top in ((11, 30), (22, 38), (14, 45)):
            with self.subTest(left=left, top=top):
                image = item_window()
                draw = ImageDraw.Draw(image)
                draw.rectangle((10, 29, 39, 64), fill=(40, 45, 65))
                draw.rectangle((left, top, left + 6, top + 8), fill=(240, 20, 20))
                icon = Image.open(io.BytesIO(automatic_icon(image)))
                bounds = icon.getchannel("A").getbbox()
                self.assertEqual((bounds[2] - bounds[0], bounds[3] - bounds[1]), (7, 9))
                self.assertLessEqual(abs(bounds[0] - (icon.width - bounds[2])), 1)
                self.assertLessEqual(abs(bounds[1] - (icon.height - bounds[3])), 1)

    def test_unrecognized_or_incomplete_images_are_not_cropped(self):
        self.assertIsNone(automatic_icon(Image.new("RGB", (240, 180), (20, 25, 45))))
        self.assertIsNone(automatic_icon(Image.new("RGB", (10, 10))))
        self.assertIsNone(automatic_icon(item_window().crop((0, 0, 240, 50))))


if __name__ == "__main__":
    unittest.main()
