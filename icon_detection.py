import io
from collections import Counter

from PIL import Image


def isolate_icon(image):
    """Remove the common dark blue window texture and center the visible artwork."""
    rgb = image.convert("RGB")
    raw = rgb.tobytes()
    colors = list(zip(raw[0::3], raw[1::3], raw[2::3]))
    bins = Counter((r // 8, g // 8, b // 8) for r, g, b in colors
                   if b > r + 5 and b > g + 5 and max(r, g, b) < 120)
    if not bins:
        return None
    dominant, count = bins.most_common(1)[0]
    if count < max(4, len(colors) // 50):
        return None
    center = tuple(value * 8 + 4 for value in dominant)
    backgrounds = [
        tuple(value * 8 + 4 for value in color)
        for color, frequency in bins.items()
        if frequency >= max(2, len(colors) // 500)
        and sum((color[i] * 8 + 4 - center[i]) ** 2 for i in range(3)) <= 32 ** 2
    ]
    rgba = rgb.convert("RGBA")
    values = []
    for r, g, b in colors:
        distance = min(sum((channel - sample[i]) ** 2 for i, channel in enumerate((r, g, b)))
                       for sample in backgrounds) ** 0.5
        alpha = min(255, max(0, round((distance - 10) * 255 / 15)))
        values.append((r, g, b, alpha))
    rgba.putdata(values)
    bounds = rgba.getchannel("A").point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None:
        return None
    artwork = rgba.crop(bounds)
    if artwork.width < 2 or artwork.height < 2:
        return None
    side = max(artwork.size) + max(2, round(max(artwork.size) * 0.08))
    result = Image.new("RGBA", (side, side))
    result.paste(artwork, ((side - artwork.width) // 2, (side - artwork.height) // 2))
    return result


def automatic_icon(image):
    """Crop an icon from a recognizable, complete item-window screenshot."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 100 or height < 75:
        return None
    pixels = rgb.load()
    search_width = min(width, 250)
    tab = None
    for y in range(min(height, 100)):
        run = 0
        start = 0
        for x in range(search_width):
            r, g, b = pixels[x, y]
            if b > r + 12 and b > 135 and g > 100:
                if not run:
                    start = x
                run += 1
                if run >= 40 and start < 80:
                    tab = (start, y)
                    break
            else:
                run = 0
        if tab:
            break
    if tab is None:
        return None
    tab_x, tab_y = tab
    title_y = None
    for y in range(tab_y):
        bright = 0
        for x in range(5, min(width, 100)):
            color = pixels[x, y]
            if min(color) > 125 and max(color) - min(color) < 85:
                bright += 1
        if bright >= 45:
            title_y = y
            break
    if title_y is None:
        return None
    scale = (tab_y - title_y) / 12
    if not 0.75 <= scale <= 2.5:
        return None
    if scale < 1:
        scale = 1
    # The first border row can start partway around the rounded tab corner.
    for y in range(tab_y + 1, min(tab_y + 3, height)):
        run = 0
        start = 0
        for x in range(search_width):
            r, g, b = pixels[x, y]
            if b > r + 12 and b > 135 and g > 100:
                if not run:
                    start = x
                run += 1
                if run >= 40 and start < tab_x:
                    tab_x = start
                    break
            else:
                run = 0
    crop_width, crop_height = round(30 * scale), round(36 * scale)
    x, y = tab_x, round(tab_y + 17 * scale)
    if x + crop_width > width or y + crop_height > height:
        return None
    icon = isolate_icon(image.crop((x, y, x + crop_width, y + crop_height)))
    if icon is None:
        return None
    output = io.BytesIO()
    icon.save(output, format="PNG")
    return output.getvalue()
