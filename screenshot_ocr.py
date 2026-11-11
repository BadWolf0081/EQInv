import io
import json
import re
import subprocess
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PIXELS = 20_000_000
STAT_PATTERN = re.compile(
    r"\b(AC|HP|MANA|ENDUR(?:ANCE)?|STR|STA|AGI|DEX|WIS|INT|CHA|"
    r"MANA\s+REGEN(?:ERATION)?|HP\s+REGEN(?:ERATION)?|ENDURANCE\s+REGEN(?:ERATION)?|"
    r"HEAL\s+AMOUNT|SPELL\s+DMG|SPELL\s+DAMAGE|CLAIRVOYANCE|ATTACK|TRIBUTE|REQ(?:UIRED)?\s+LEVEL)"
    r"(?:[ \t]*:[ \t]*|[ \t]+)"
    r"([+-]?\d[\d,]*(?:[ \t]*\+[ \t]*\d[\d,]*)?)",
    re.IGNORECASE,
)
TYPE_PATTERN = re.compile(
    r"\b(?:Augmentation\s+types?|This\s+Augmentation\s+fits\s+in\s+slot\s+types?)"
    r"\s*:[ \t]*([0-9][0-9 \t,/|]*)", re.IGNORECASE,
)
SKILL_PATTERN = re.compile(
    r"\bSkill\s+Mod[ \t]*:[ \t]*(.*?)(?=[\r\n]|\s+This\s+Augmentation\b|$)",
    re.IGNORECASE,
)
SIZE_PATTERN = re.compile(r"\bSize[ \t]*:[ \t]*([A-Za-z]+)\b", re.IGNORECASE)
DISTILLER_PATTERN = re.compile(
    r"\bsolvent\s+Class\s+([IVXLCDM]+)\s+Augmentation\s+Distiller\b", re.IGNORECASE,
)
FLAGS_PATTERN = re.compile(
    r"\b((?:Lore|No Trade|No Drop|Augmentation|Prestige|Attuneable|Heirloom)"
    r"(?:[ \t]*,[ \t]*(?:Lore|No Trade|No Drop|Augmentation|Prestige|Attuneable|Heirloom))+)\b",
    re.IGNORECASE,
)
SLOT_NAMES = {"ear", "head", "face", "neck", "shoulders", "arms", "back", "wrist", "range",
              "hands", "primary", "secondary", "finger", "fingers", "chest", "legs", "feet",
              "waist", "charm", "ammo", "power", "source"}
STAT_NAMES = {
    "endur": "endurance", "mana regeneration": "mana_regen", "mana regen": "mana_regen",
    "hp regeneration": "hp_regen", "hp regen": "hp_regen",
    "endurance regeneration": "endurance_regen", "endurance regen": "endurance_regen",
    "heal amount": "heal_amount", "spell dmg": "spell_damage", "spell damage": "spell_damage",
    "req level": "required_level", "required level": "required_level",
}


def extract_candidates(text):
    stats = {}
    for match in STAT_PATTERN.finditer(text):
        label = " ".join(match.group(1).lower().split())
        key = STAT_NAMES.get(label, label)
        value = match.group(2).replace(",", "").replace(" ", "")
        if re.fullmatch(r"[+-]?\d+", value):
            stats[key] = int(value)
        else:
            stats[key] = value
    skill = SKILL_PATTERN.search(text)
    if skill:
        stats["skill_mod"] = skill.group(1).strip()
    size = SIZE_PATTERN.search(text)
    if size:
        stats["size"] = size.group(1).upper()
    distiller = DISTILLER_PATTERN.search(text)
    if distiller:
        stats["distiller_class"] = distiller.group(1).upper()
    flags = FLAGS_PATTERN.search(text)
    if flags:
        stats["item_flags"] = flags.group(1).strip()
        if size and size.start() > flags.end():
            slot_text = text[flags.end():size.start()]
            words = slot_text.split()
            slots = [word for word in words if word.lower() in SLOT_NAMES]
            if slots and all(word.lower() in SLOT_NAMES or len(word) == 1 for word in words):
                stats["equip_slots"] = " ".join(slots)
    type_match = TYPE_PATTERN.search(text)
    types = sorted(set(map(int, re.findall(r"\d+", type_match.group(1))))) if type_match else []
    return stats, types


def load_screenshot(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in ("PNG", "JPEG"):
                    raise ValueError("Use a PNG or JPEG screenshot.")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("Screenshot exceeds the 20 megapixel limit.")
                original.load()
                return original.convert("RGB"), original.format.lower()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
        raise ValueError("Invalid or oversized screenshot; use a PNG or JPEG image.") from exc


def recognize_screenshot(data):
    original, image_format = load_screenshot(data)
    image = ImageOps.autocontrast(original.convert("L"))
    if original.width * original.height * 4 <= MAX_PIXELS:
        image = image.resize((original.width * 2, original.height * 2))
    output = io.BytesIO()
    image.save(output, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6"],
            input=output.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Tesseract is not installed or not on the server PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Screenshot OCR timed out.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Tesseract failed: {detail or 'unknown error'}")
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("No text was recognized. Crop the item window and try a clearer screenshot.")
    return text, image_format


def validate_review(stats_text, types_text, raw_text):
    try:
        stats = json.loads(stats_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Stats must be a valid JSON object.") from exc
    if not isinstance(stats, dict) or not all(isinstance(k, str) and k.strip() for k in stats):
        raise ValueError("Stats must be a JSON object with nonempty field names.")
    for key, value in stats.items():
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError(f"Stat {key} must be a string or integer.")
        if key in ("ac", "hp", "mana", "endurance") and value != "" and not isinstance(value, int):
            raise ValueError(f"Stat {key} must be an integer or blank.")
    types = []
    if types_text.strip():
        for value in re.split(r"[\s,|/]+", types_text.strip()):
            if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 255:
                raise ValueError("Augment types must be numbers from 1 to 255.")
            types.append(int(value))
    if not raw_text.strip():
        raise ValueError("The reviewed OCR text must not be empty.")
    if not stats and not types:
        raise ValueError("Enter at least one stat or augment type before saving.")
    stats["ocr_text"] = raw_text.strip()
    return stats, sorted(set(types))
