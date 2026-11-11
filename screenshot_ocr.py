import io
import json
import re
import subprocess
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from distiller import valid_distiller_class
from socket_types import socket_number


MAX_PIXELS = 20_000_000
STAT_PATTERN = re.compile(
    r"\b(MANA\s+REGEN(?:ERATION)?|HP\s+REGEN(?:ERATION)?|"
    r"END(?:UR(?:ANCE)?)?\s+REGEN(?:ERATION)?|"
    r"HEAL\s+AMOUNT|SPELL\s+(?:DMG|DAMAGE)|CLAIRVOYANCE|ATTACK|TRIBUTE|PURITY|"
    r"REQ(?:UIRED)?\s+LEVEL|REC(?:OMMENDED)?\s+LEVEL|"
    r"STRENGTH|STAMINA|AGILITY|DEXTERITY|WISDOM|INTELLIGENCE|CHARISMA|"
    r"MAGIC|FIRE|COLD|DISEASE|POISON|CORRUPT(?:ION)?|"
    r"AC|HP|MANA|END(?:UR(?:ANCE)?)?|STR|STA|AGI|DEX|WIS|INT|CHA)"
    r"(?:[ \t]*:[ \t]*|[ \t]+)"
    r"([+-]?\d[\d,]*(?:[ \t]*\+[ \t]*\d[\d,]*)?)",
    re.IGNORECASE,
)
WEIGHT_PATTERN = re.compile(r"\bWeight[ \t]*:[ \t]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
TYPE_PATTERN = re.compile(
    r"\b(?:Augmentation\s+types?|This\s+Augmentation\s+fits\s+in\s+slot\s+types?)"
    r"\s*:[ \t]*([0-9]+(?:[ \t]*\([^()]{0,100}\))?"
    r"(?:(?:[ \t]*[,/|][ \t\r\n]*|[ \t]+)[0-9]+"
    r"(?:[ \t]*\([^()]{0,100}\))?)*)", re.IGNORECASE,
)
SKILL_PATTERN = re.compile(
    r"\bSkill\s+Mod[ \t]*:[ \t]*(.*?)(?=[\r\n]|\s+This\s+Augmentation\b|$)",
    re.IGNORECASE,
)
SIZE_PATTERN = re.compile(r"\bSize[ \t]*:[ \t]*([A-Za-z]+)\b", re.IGNORECASE)
DISTILLER_PATTERN = re.compile(
    r"\bsolvent\s+Class\s+([A-Za-z0-9]+)\s+Augmentation\s+Distiller\b", re.IGNORECASE,
)
PERFECTED_ONLY_PATTERN = re.compile(
    r"\bmust\s*use\s+(?:a\s+)?(?:solvent\s+)?(?:a\s+)?Perfected\s+Augmentation\s+Distiller\b",
    re.IGNORECASE,
)
SOCKET_PATTERN = re.compile(
    r"(?:\bSlot[ \t]*([0-9]+)|(?<!\w)#[ \t]*([0-9]+)[ \t]+Slot)"
    r"[ \t]*,?[ \t]*type[ \t]+([0-9]+)\b", re.IGNORECASE,
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
    "end": "endurance", "endur": "endurance", "mana regeneration": "mana_regen", "mana regen": "mana_regen",
    "hp regeneration": "hp_regen", "hp regen": "hp_regen",
    "end regeneration": "endurance_regen", "end regen": "endurance_regen",
    "endur regeneration": "endurance_regen", "endur regen": "endurance_regen",
    "endurance regeneration": "endurance_regen", "endurance regen": "endurance_regen",
    "heal amount": "heal_amount", "spell dmg": "spell_damage", "spell damage": "spell_damage",
    "req level": "required_level", "required level": "required_level",
    "rec level": "recommended_level", "recommended level": "recommended_level",
    "strength": "str", "stamina": "sta", "agility": "agi", "dexterity": "dex",
    "wisdom": "wis", "intelligence": "int", "charisma": "cha", "corrupt": "corruption",
}
HEROIC_STATS = {"str", "sta", "agi", "dex", "wis", "int", "cha",
                "magic", "fire", "cold", "disease", "poison", "corruption"}


def extract_candidates(text):
    stats = {}
    for match in STAT_PATTERN.finditer(text):
        label = " ".join(match.group(1).lower().split())
        key = STAT_NAMES.get(label, label)
        value = re.sub(r"[,\s]", "", match.group(2))
        parts = re.fullmatch(r"([+-]?\d+)\+(\d+)", value)
        if key in HEROIC_STATS and parts:
            stats[key] = int(parts.group(1))
            stats[f"heroic_{key}"] = int(parts.group(2))
        elif re.fullmatch(r"[+-]?\d+", value):
            stats[key] = int(value)
            if key in HEROIC_STATS:
                stats.pop(f"heroic_{key}", None)
        else:
            stats[key] = value
    weight = WEIGHT_PATTERN.search(text)
    if weight:
        stats["weight"] = weight.group(1)
    skill = SKILL_PATTERN.search(text)
    if skill:
        stats["skill_mod"] = skill.group(1).strip()
    size = SIZE_PATTERN.search(text)
    if size:
        stats["size"] = size.group(1).upper()
    distiller = DISTILLER_PATTERN.search(text)
    if distiller:
        stats["distiller_class"] = distiller.group(1).upper()
    elif PERFECTED_ONLY_PATTERN.search(text):
        stats["distiller_class"] = "Perfected only"
    sockets = {}
    for match in SOCKET_PATTERN.finditer(text):
        number = int(match.group(1) or match.group(2))
        value = int(match.group(3))
        if 1 <= number <= 255 and 1 <= value <= 255:
            sockets.setdefault(number, set()).add(value)
    for number, values in sockets.items():
        if len(values) == 1:
            stats[f"socket_{number}_type"] = values.pop()
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
    types = sorted({int(token) for token in re.findall(r"\([^()]*\)|[0-9]+", type_match.group(1))
                    if token[0].isdigit()}) if type_match else []
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
        if socket_number(key) is not None and value != "" and (
                not isinstance(value, int) or not 1 <= value <= 255):
            raise ValueError(f"Stat {key} must be an integer from 1 to 255 or blank.")
        if key == "distiller_class" and not valid_distiller_class(value):
            raise ValueError("distiller_class must be a Roman numeral from I to XXX, "
                             '"Perfected only", or blank. Check the screenshot; do not guess an OCR misread.')
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
