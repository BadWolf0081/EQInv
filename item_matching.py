import re
from difflib import SequenceMatcher


REMOVAL_INSTRUCTIONS = re.compile(
    r"\b(?:you\s+must\s*use\b|"
    r"this\s+augment\s+can\s+(?:only\s+)?(?:safely\s+)?be\s+removed\b)",
    re.IGNORECASE,
)


def item_name_text(text):
    instructions = REMOVAL_INSTRUCTIONS.search(text)
    return text[:instructions.start()] if instructions else text


def normalize_name(text):
    return " ".join(re.findall(r"[^\W_]+", text.casefold(), re.UNICODE))


def suggest_item_names(text, items):
    lines = [normalize_name(line[:160]) for line in item_name_text(text).splitlines()[:10]]
    lines = [line.split()[:20] for line in lines if line]
    matches = []
    for item in items:
        name = normalize_name(item["name"])
        words = name.split()
        if len(name) < 6 or not words:
            continue
        best = 0.0
        for line in lines:
            for count in range(max(1, len(words) - 1), min(len(line), len(words) + 1) + 1):
                for start in range(len(line) - count + 1):
                    candidate = " ".join(line[start:start + count])
                    if abs(len(candidate) - len(name)) > max(2, len(name) // 5):
                        continue
                    score = SequenceMatcher(None, name, candidate, autojunk=False).ratio()
                    best = max(best, score)
        if best >= 0.85:
            matches.append((best, item))
    matches.sort(key=lambda result: (-result[0], result[1]["name"].casefold(), result[1]["id"]))
    return [item for _, item in matches[:3]]
