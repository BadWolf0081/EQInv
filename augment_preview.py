import re


HEROIC_STATS = (
    ("heroic_str", "STR"), ("heroic_sta", "STA"), ("heroic_agi", "AGI"),
    ("heroic_dex", "DEX"), ("heroic_wis", "WIS"), ("heroic_int", "INT"),
    ("heroic_cha", "CHA"), ("heroic_magic", "Magic"), ("heroic_fire", "Fire"),
    ("heroic_cold", "Cold"), ("heroic_disease", "Disease"),
    ("heroic_poison", "Poison"), ("heroic_corruption", "Corruption"),
)


def numeric_stat(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        return int(value)
    return None


def augment_summary(catalog, slot_type=None):
    stats = catalog["stats"] if catalog else {}
    types = catalog["types"] if catalog else []
    purity_type = slot_type in (13, 14) or (slot_type is None and types and set(types) <= {13, 14})
    hp = numeric_stat(stats.get("hp"))
    mana = numeric_stat(stats.get("mana"))
    heroics = [(label, value) for key, label in HEROIC_STATS
               for value in [numeric_stat(stats.get(key))] if value is not None and value > 0]
    largest = max((value for _, value in heroics), default=None)
    return {"hp": hp, "mana": mana, "slot_type": slot_type, "purity_type": purity_type,
            "skill_mod": stats.get("skill_mod", ""), "purity": numeric_stat(stats.get("purity")),
            "heroic": [label for label, value in heroics if value == largest],
            "heroic_value": largest}
