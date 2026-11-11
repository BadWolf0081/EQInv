from augment_preview import numeric_stat


ADDITIVE_STATS = (
    "ac", "hp", "mana", "endurance", "str", "sta", "agi", "dex", "wis", "int", "cha",
    "heroic_str", "heroic_sta", "heroic_agi", "heroic_dex", "heroic_wis", "heroic_int", "heroic_cha",
    "magic", "fire", "cold", "disease", "poison", "corruption", "heroic_magic", "heroic_fire",
    "heroic_cold", "heroic_disease", "heroic_poison", "heroic_corruption", "attack",
    "hp_regen", "mana_regen", "endurance_regen", "heal_amount", "spell_damage", "clairvoyance",
)


def calculate_base(observed, augments):
    results = {}
    for key in ADDITIVE_STATS:
        total = numeric_stat(observed.get(key))
        if total is None:
            continue
        values = [numeric_stat(aug.get(key)) if aug is not None else None for aug in augments]
        results[key] = None if any(value is None for value in values) else total - sum(values)
    return results
