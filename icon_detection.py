import io


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
    size = round(28 * scale)
    x, y = tab_x, round(tab_y + 20 * scale)
    if x + size > width or y + size > height:
        return None
    output = io.BytesIO()
    image.crop((x, y, x + size, y + size)).save(output, format="PNG")
    return output.getvalue()
